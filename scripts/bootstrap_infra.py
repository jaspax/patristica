"""
One-time bootstrap for the OpenTofu state bucket (#117).

OpenTofu keeps its state in a private DigitalOcean Spaces bucket, which has
to exist before ``tofu init``. With only ``DIGITALOCEAN_TOKEN`` in
``infra/.env``, this script:

1. creates a full-access Spaces key ``patristica-tofu`` through the DO API and
   appends ``SPACES_ACCESS_KEY_ID`` / ``SPACES_SECRET_ACCESS_KEY`` to
   ``infra/.env`` (OpenTofu uses it for the state backend and to manage the
   other buckets), unless the file already has a key;
2. creates the state bucket (``SPACES_STATE_BUCKET``, default
   ``patristica-tfstate``) with versioning on, unless it already exists.

Idempotent: re-running changes nothing. Secrets are never logged.

Usage::

    uv run --extra deploy python -m scripts.bootstrap_infra
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

ENV_FILE = Path("infra/.env")
DO_API = "https://api.digitalocean.com/v2"
REGION = "nyc3"
DEFAULT_STATE_BUCKET = "patristica-tfstate"
KEY_NAME = "patristica-tofu"


class BootstrapError(Exception):
    """Raised for missing configuration or a failed API call."""


def read_env(path: Path) -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines (comments and blanks ignored)."""
    if not path.exists():
        raise BootstrapError(
            f"{path} not found; copy infra/.env.example and set DIGITALOCEAN_TOKEN"
        )
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip("\"'")
    return env


def append_env(path: Path, values: dict[str, str]) -> None:
    """Append ``KEY=VALUE`` lines to the env file."""
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    text += "".join(f"{k}={v}\n" for k, v in values.items())
    path.write_text(text, encoding="utf-8")


def create_spaces_key(token: str, client: httpx.Client | None = None) -> tuple[str, str]:
    """Create a full-access Spaces key; return (access key id, secret)."""
    client = client or httpx.Client(timeout=30)
    resp = client.post(
        f"{DO_API}/spaces/keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": KEY_NAME, "grants": [{"bucket": "", "permission": "fullaccess"}]},
    )
    if resp.status_code >= 400:
        raise BootstrapError(f"creating Spaces key failed: HTTP {resp.status_code} {resp.text}")
    key = resp.json()["key"]
    return key["access_key"], key["secret_key"]


def spaces_client(access_key: str, secret_key: str) -> Any:
    import boto3

    return boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url=f"https://{REGION}.digitaloceanspaces.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def ensure_bucket(s3: Any, bucket: str, attempts: int = 10, delay: float = 3.0) -> bool:
    """Create the bucket with versioning unless it exists. Return True if created.

    A new key can take a few seconds to work, so access errors are retried.
    """
    from botocore.exceptions import ClientError

    for attempt in range(attempts):
        try:
            existing = {b["Name"] for b in s3.list_buckets().get("Buckets", [])}
            created = bucket not in existing
            if created:
                s3.create_bucket(Bucket=bucket)
            s3.put_bucket_versioning(
                Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
            )
            return created
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code == "BucketAlreadyExists":
                raise BootstrapError(
                    f"bucket name {bucket!r} is taken by another account; "
                    "set SPACES_STATE_BUCKET in infra/.env to another name"
                ) from exc
            if code not in ("InvalidAccessKeyId", "AccessDenied", "SignatureDoesNotMatch") or (
                attempt == attempts - 1
            ):
                raise
            time.sleep(delay)
    raise AssertionError("unreachable")


def bootstrap(env_file: Path = ENV_FILE, client: httpx.Client | None = None) -> None:
    env = read_env(env_file)
    token = env.get("DIGITALOCEAN_TOKEN")
    if not token:
        raise BootstrapError(f"DIGITALOCEAN_TOKEN is not set in {env_file}")

    access, secret = env.get("SPACES_ACCESS_KEY_ID"), env.get("SPACES_SECRET_ACCESS_KEY")
    if access and secret:
        log.info("Spaces key already in %s", env_file)
    else:
        access, secret = create_spaces_key(token, client)
        append_env(env_file, {"SPACES_ACCESS_KEY_ID": access, "SPACES_SECRET_ACCESS_KEY": secret})
        log.info("created Spaces key %s and saved it to %s", KEY_NAME, env_file)

    bucket = env.get("SPACES_STATE_BUCKET") or DEFAULT_STATE_BUCKET
    if ensure_bucket(spaces_client(access, secret), bucket):
        log.info("created state bucket %s (%s)", bucket, REGION)
    else:
        log.info("state bucket %s already exists", bucket)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env-file", type=Path, default=ENV_FILE)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    bootstrap(args.env_file)


if __name__ == "__main__":
    main()
