"""
Upload the static library export to DigitalOcean Spaces for the deployed web app.

Syncs ``data/library/`` (built by ``scripts.export_library``) to the Spaces
bucket created by ``infra/tofu`` (#131), through its S3-compatible API. The web
app reads it through the bucket's CDN endpoint (tofu output ``library_url``):

- Works whose licence is not cleared for publication (``unknown``; see
  DATA_LICENSE.md) are left out, and the uploaded ``index.json`` is filtered
  to match. ``authors.json`` (the author index, #82) is CC0 metadata and is
  uploaded whole.
- Every object is stored gzip-compressed (``Content-Encoding: gzip``). Work
  files and the index are public-read; the bucket listing and the manifest
  stay private. CORS is part of the bucket's tofu config.
- Changes are detected from content, not from the stored bytes: the bucket
  holds a manifest (``_manifest.json``: key → SHA-256 of the *uncompressed*
  content), and a file is uploaded only when its hash differs or the object is
  missing. Gzip output varies between Python and zlib versions (even the
  header's OS byte), so comparing compressed bytes or ETags would re-upload
  everything whenever the uploading machine changes. The manifest is written
  last, after all uploads and deletes succeed, so an interrupted run is simply
  retried.
- Objects in the bucket that are no longer part of the export are deleted
  (disable with ``--no-delete``).

Credentials come from the environment, or from ``.env`` / ``web/.env``:
``LIBRARY_ACCESS_KEY_ID``, ``LIBRARY_SECRET_ACCESS_KEY``, ``LIBRARY_BUCKET``, and
optionally ``LIBRARY_REGION`` (default ``nyc3``). The key is the bucket-scoped
one from ``infra/tofu.sh output -raw library_access_key`` / ``library_secret_key``.

Usage::

    uv run --extra deploy python -m scripts.upload_library [--dry-run] [--no-delete]
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from tqdm import tqdm

log = logging.getLogger(__name__)

#: Licences that may not be published (see DATA_LICENSE.md).
EXCLUDED_LICENSES = frozenset({"unknown"})

ENV_FILES = (Path(".env"), Path("web/.env"))
REQUIRED_ENV = ("LIBRARY_ACCESS_KEY_ID", "LIBRARY_SECRET_ACCESS_KEY", "LIBRARY_BUCKET")
DEFAULT_REGION = "nyc3"

INDEX_KEY = "index.json"
AUTHORS_KEY = "authors.json"
MANIFEST_KEY = "_manifest.json"
CACHE_INDEX = "public, max-age=300"
CACHE_WORK = "public, max-age=3600"


class UploadError(Exception):
    """Raised for missing configuration or input."""


def load_env_files(paths: tuple[Path, ...] = ENV_FILES) -> None:
    """Read ``KEY=VALUE`` lines into ``os.environ`` without overriding existing values."""
    for path in paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def public_index(index: dict[str, Any]) -> dict[str, Any]:
    """Return *index* without works whose licence is excluded from publication."""
    works = [w for w in index["works"] if w["license"] not in EXCLUDED_LICENSES]
    used = {w["source_id"] for w in works}
    return {
        **index,
        "sources": {k: v for k, v in index["sources"].items() if k in used},
        "works": works,
    }


def compress(data: bytes) -> bytes:
    """Gzip *data* for storage with ``Content-Encoding: gzip``."""
    return gzip.compress(data, compresslevel=9, mtime=0)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def plan_sync(
    local: dict[str, str], manifest: dict[str, str], present: set[str]
) -> tuple[list[str], list[str]]:
    """Return ``(keys to upload, keys to delete)``.

    *local* and *manifest* map key → SHA-256 of the uncompressed content (what
    we have, and what the bucket last received); *present* is the set of keys
    actually in the bucket. A key is uploaded when its hash changed or the
    object is missing; objects not in *local* are deleted (except the manifest).
    """
    upload = sorted(k for k, h in local.items() if manifest.get(k) != h or k not in present)
    delete = sorted(k for k in present if k not in local and k != MANIFEST_KEY)
    return upload, delete


UPLOAD_THREADS = 16


def spaces_endpoint(region: str) -> str:
    """S3 API endpoint of DigitalOcean Spaces in *region*."""
    return f"https://{region}.digitaloceanspaces.com"


def _client() -> Any:
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise UploadError(
            f"Missing Spaces settings: {', '.join(missing)} (set them in .env or web/.env)"
        )
    import boto3  # optional dependency: `uv sync --extra deploy`
    from botocore.config import Config

    region = os.environ.get("LIBRARY_REGION") or DEFAULT_REGION
    return boto3.client(
        "s3",
        endpoint_url=spaces_endpoint(region),
        aws_access_key_id=os.environ["LIBRARY_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["LIBRARY_SECRET_ACCESS_KEY"],
        region_name=region,
        config=Config(max_pool_connections=UPLOAD_THREADS),
    )


def remote_keys(client: Any, bucket: str) -> set[str]:
    """Every object key in *bucket*."""
    keys: set[str] = set()
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        keys.update(obj["Key"] for obj in page.get("Contents", []))
    return keys


def read_manifest(client: Any, bucket: str) -> dict[str, str]:
    """The bucket's manifest (key → content SHA-256), or ``{}`` if there is none yet."""
    from botocore.exceptions import ClientError

    try:
        body = client.get_object(Bucket=bucket, Key=MANIFEST_KEY)["Body"].read()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
            log.info("No manifest in the bucket yet; every file counts as changed")
            return {}
        raise
    return dict(json.loads(gzip.decompress(body)))


def upload_library(
    library_dir: Path, dry_run: bool = False, delete: bool = True
) -> dict[str, int]:
    """Sync *library_dir* to the library bucket.

    Returns counts of uploaded, deleted and unchanged objects.
    """
    index_path = library_dir / INDEX_KEY
    if not index_path.exists():
        raise UploadError(f"{index_path} not found (run scripts.export_library first)")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    pub = public_index(index)
    excluded = len(index["works"]) - len(pub["works"])
    if excluded:
        log.info("Leaving out %d works with licences not cleared for publication", excluded)

    index_bytes = json.dumps(pub, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    authors_path = library_dir / AUTHORS_KEY
    if not authors_path.exists():
        raise UploadError(f"{authors_path} not found (re-run scripts.export_library)")
    local: dict[str, str] = {
        INDEX_KEY: sha256_hex(index_bytes),
        AUTHORS_KEY: sha256_hex(authors_path.read_bytes()),
    }
    for w in tqdm(pub["works"], desc="hash"):
        path = library_dir / w["file"]
        if not path.exists():
            raise UploadError(f"Work file listed in index.json is missing: {path}")
        local[w["file"]] = sha256_hex(path.read_bytes())

    client = _client()
    bucket = os.environ["LIBRARY_BUCKET"]
    manifest = read_manifest(client, bucket)
    to_upload, to_delete = plan_sync(local, manifest, remote_keys(client, bucket))
    if not delete:
        to_delete = []
    log.info(
        "%d objects to upload, %d to delete, %d unchanged",
        len(to_upload), len(to_delete), len(local) - len(to_upload),
    )
    if dry_run:
        return {"uploaded": 0, "deleted": 0, "unchanged": len(local) - len(to_upload)}

    def put(
        key: str, data: bytes | None = None, cache: str = CACHE_WORK, acl: str = "public-read"
    ) -> None:
        if data is None:
            data = (library_dir / key).read_bytes()
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=compress(data),
            ACL=acl,
            ContentType="application/json; charset=utf-8",
            ContentEncoding="gzip",
            CacheControl=cache,
        )

    # Upload works and authors before the index, so the index never points at a
    # missing file or author.
    works_first = [k for k in to_upload if k not in (INDEX_KEY, AUTHORS_KEY)]
    with ThreadPoolExecutor(max_workers=UPLOAD_THREADS) as pool:
        list(tqdm(pool.map(put, works_first), total=len(works_first), desc="upload"))
    if AUTHORS_KEY in to_upload:
        put(AUTHORS_KEY, None, CACHE_INDEX)
    if INDEX_KEY in to_upload:
        put(INDEX_KEY, index_bytes, CACHE_INDEX)

    for start in range(0, len(to_delete), 1000):
        batch = to_delete[start:start + 1000]
        client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": k} for k in batch]})
    if to_delete:
        log.info("Deleted %d stale objects", len(to_delete))

    # Last: record what the bucket now holds.
    if local != manifest:
        put(MANIFEST_KEY, json.dumps(local, sort_keys=True).encode("utf-8"), "no-store", "private")

    return {
        "uploaded": len(to_upload),
        "deleted": len(to_delete),
        "unchanged": len(local) - len(to_upload),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("botocore").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(
        description="Upload the static library export to DigitalOcean Spaces."
    )
    parser.add_argument("--library-dir", default="data/library")
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would change, upload nothing"
    )
    parser.add_argument(
        "--no-delete", action="store_true", help="keep objects no longer in the export"
    )
    args = parser.parse_args()

    load_env_files()
    counts = upload_library(
        Path(args.library_dir),
        dry_run=args.dry_run,
        delete=not args.no_delete,
    )
    log.info("Done: %s", counts)


if __name__ == "__main__":
    main()
