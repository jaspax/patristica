"""Tests for scripts/bootstrap_infra.py (no network; DO API and Spaces are mocked)."""

import json
from pathlib import Path

import httpx
import pytest

from scripts import bootstrap_infra as bi


def _env(tmp_path: Path, text: str) -> Path:
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def _do_api(calls: list[dict]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"url": str(request.url), "body": json.loads(request.content)})
        return httpx.Response(201, json={"key": {"access_key": "AK", "secret_key": "SK"}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_read_env_ignores_comments_and_quotes(tmp_path: Path) -> None:
    path = _env(tmp_path, "# c\n\nDIGITALOCEAN_TOKEN='tok'\nEMPTY=\n")
    assert bi.read_env(path) == {"DIGITALOCEAN_TOKEN": "tok", "EMPTY": ""}


def test_read_env_missing_file(tmp_path: Path) -> None:
    with pytest.raises(bi.BootstrapError, match="not found"):
        bi.read_env(tmp_path / "nope")


def test_bootstrap_creates_key_and_bucket(tmp_path: Path, mocker) -> None:
    path = _env(tmp_path, "DIGITALOCEAN_TOKEN=tok")  # no trailing newline
    s3 = mocker.MagicMock()
    s3.list_buckets.return_value = {"Buckets": []}
    mocker.patch.object(bi, "spaces_client", return_value=s3)
    calls: list[dict] = []

    bi.bootstrap(path, client=_do_api(calls))

    assert calls == [{
        "url": "https://api.digitalocean.com/v2/spaces/keys",
        "body": {"name": "patristica-tofu", "grants": [{"bucket": "", "permission": "fullaccess"}]},
    }]
    assert bi.read_env(path) == {
        "DIGITALOCEAN_TOKEN": "tok", "SPACES_ACCESS_KEY_ID": "AK", "SPACES_SECRET_ACCESS_KEY": "SK",
    }
    bi.spaces_client.assert_called_once_with("AK", "SK")
    s3.create_bucket.assert_called_once_with(Bucket="patristica-tfstate")
    s3.put_bucket_versioning.assert_called_once()


def test_bootstrap_is_idempotent(tmp_path: Path, mocker) -> None:
    text = "DIGITALOCEAN_TOKEN=tok\nSPACES_ACCESS_KEY_ID=AK\nSPACES_SECRET_ACCESS_KEY=SK\n"
    text += "SPACES_STATE_BUCKET=my-state\n"
    path = _env(tmp_path, text)
    s3 = mocker.MagicMock()
    s3.list_buckets.return_value = {"Buckets": [{"Name": "my-state"}]}
    mocker.patch.object(bi, "spaces_client", return_value=s3)
    calls: list[dict] = []

    bi.bootstrap(path, client=_do_api(calls))

    assert calls == []
    assert path.read_text(encoding="utf-8") == text
    s3.create_bucket.assert_not_called()


def test_bootstrap_requires_token(tmp_path: Path) -> None:
    with pytest.raises(bi.BootstrapError, match="DIGITALOCEAN_TOKEN"):
        bi.bootstrap(_env(tmp_path, "OTHER=1\n"))


def test_create_spaces_key_reports_api_errors() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="no")))
    with pytest.raises(bi.BootstrapError, match="HTTP 403"):
        bi.create_spaces_key("tok", client)


def test_ensure_bucket_name_taken(mocker) -> None:
    botocore = pytest.importorskip("botocore.exceptions")
    s3 = mocker.MagicMock()
    s3.list_buckets.return_value = {"Buckets": []}
    s3.create_bucket.side_effect = botocore.ClientError(
        {"Error": {"Code": "BucketAlreadyExists"}}, "CreateBucket"
    )
    with pytest.raises(bi.BootstrapError, match="taken"):
        bi.ensure_bucket(s3, "patristica-tfstate")


def test_ensure_bucket_retries_new_key(mocker) -> None:
    botocore = pytest.importorskip("botocore.exceptions")
    s3 = mocker.MagicMock()
    s3.list_buckets.side_effect = [
        botocore.ClientError({"Error": {"Code": "InvalidAccessKeyId"}}, "ListBuckets"),
        {"Buckets": [{"Name": "b"}]},
    ]
    assert bi.ensure_bucket(s3, "b", delay=0) is False
