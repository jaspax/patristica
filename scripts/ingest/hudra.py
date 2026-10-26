"""
Ingestor for Syriac liturgical books from hudra.day.

Source: hudra.day — a Firestore-backed collaborative transcription platform
        for East Syriac (Assyrian/Chaldean) liturgical manuscripts.
API:    Firestore REST API (public read, no auth required for books/pages collections)
Language: syc  Tradition: syriac  Genre: liturgical  License: used-with-permission

Works ingested
--------------
1. hudra-ace-1960: The Hudra of the Assyrian Church of the East, Vol. I
   (Thoma Darmo ed., printed Thrissur 1960). Only pages with transcribed text
   are included — the digitization is in progress; pages without text are skipped.

2. taksa-draze-2003: Taksa d'Raze Editio Typica (2003), Congregation for the
   Oriental Churches. The Order of the Mysteries (East Syriac Eucharistic Liturgy)
   with the First Hallowing (Anaphora of Ss. Adai and Mari).

Canonical ref format
--------------------
  EastSyrLit.Hudra.{page_num:03d}   — Hudra page paragraphs, sequential within page
  EastSyrLit.Taksa.{page_num:03d}   — Taksa d'Raze page paragraphs

Licence
-------
hudra.day's own terms grant personal viewing only (#32), but its maintainer
(Hendo Academy) gave Patristica explicit permission to include these
transcriptions in the library and search (2026-10-24, #262): non-commercial
use, with attribution, for Patristica only. The works carry the licence id
``used-with-permission`` and credit hudra.day in their edition line;
DATA_LICENSE.md records the grant.

The content is read through the Firestore REST API (the web app's public API
key). There is no cache, so this ingestor cannot run offline (#215).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from patristica.models import Work

log = logging.getLogger(__name__)

SOURCE_ID = "hudra"

_API_KEY = "AIzaSyCgS9iRPMpwhCqTzI6JkrW9AIeJ_RzIpFU"
_FIRESTORE_BASE = (
    "https://firestore.googleapis.com/v1/projects/hudra-d80ee"
    "/databases/(default)/documents"
)

_BOOKS = [
    {
        "slug": "hudra-of-the-assyrian-church-of-the-east-volume-i",
        "work_slug": "hudra-ace-1960",
        "ref_prefix": "EastSyrLit.Hudra",
    },
    {
        "slug": "taksa-draze-edition-typica-2003",
        "work_slug": "taksa-draze-2003",
        "ref_prefix": "EastSyrLit.Taksa",
    },
]


# ---------------------------------------------------------------------------
# Firestore helpers
# ---------------------------------------------------------------------------

def _fs_value(fv: dict) -> object:
    """Convert a Firestore typed-value dict to a plain Python object."""
    if "stringValue" in fv:
        return fv["stringValue"]
    if "integerValue" in fv:
        return int(fv["integerValue"])
    if "booleanValue" in fv:
        return fv["booleanValue"]
    if "nullValue" in fv:
        return None
    if "arrayValue" in fv:
        return [_fs_value(v) for v in fv["arrayValue"].get("values", [])]
    if "mapValue" in fv:
        return {k: _fs_value(v) for k, v in fv["mapValue"]["fields"].items()}
    if "timestampValue" in fv:
        return fv["timestampValue"]
    if "doubleValue" in fv:
        return fv["doubleValue"]
    return fv


_ATTEMPTS = 3


def _fetch_doc(client: httpx.Client, path: str) -> dict | None:
    """GET a single Firestore document; return its fields dict, or None once
    every attempt failed (transport errors, 429 and 5xx are retried)."""
    url = f"{_FIRESTORE_BASE}/{path}?key={_API_KEY}"
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            resp = client.get(url)
        except httpx.TransportError as e:
            log.warning("Firestore %s: %s (attempt %d/%d)", path, e, attempt, _ATTEMPTS)
        else:
            if resp.status_code == 200:
                raw = resp.json()
                return {k: _fs_value(v) for k, v in raw.get("fields", {}).items()}
            log.warning("Firestore %s: HTTP %s (attempt %d/%d)",
                        path, resp.status_code, attempt, _ATTEMPTS)
            if resp.status_code != 429 and resp.status_code < 500:
                return None
        if attempt < _ATTEMPTS:
            time.sleep(2 ** attempt)
    return None


# ---------------------------------------------------------------------------
# ProseMirror / TipTap text extractor
# ---------------------------------------------------------------------------

def _extract_text(node: object) -> str:
    """Recursively extract plain text from a ProseMirror/TipTap document node."""
    if not isinstance(node, dict):
        return ""
    node_type = node.get("type")
    if node_type == "text":
        return node.get("text", "")
    children = [_extract_text(c) for c in node.get("content", [])]
    children = [c for c in children if c.strip()]
    if node_type == "paragraph":
        return " ".join(children)
    return "\n".join(children)


# ---------------------------------------------------------------------------
# Per-book ingestion
# ---------------------------------------------------------------------------

def _ingest_book(
    client: httpx.Client,
    book_conf: dict,
    out_dir: Path,
    force: bool,
) -> Work | None:
    slug = book_conf["slug"]
    work_slug = book_conf["work_slug"]
    ref_prefix = book_conf["ref_prefix"]
    out_path = out_dir / f"{work_slug}.json"

    if out_path.exists() and not force:
        log.info("Skipping %s (already exists)", out_path)
        data = json.loads(out_path.read_text(encoding="utf-8"))
        return Work(**data["work"])

    log.info("Fetching book metadata: %s", slug)
    book = _fetch_doc(client, f"books/{slug}")
    if book is None:
        raise RuntimeError(f"Could not fetch book document: {slug}")

    title = book.get("title", slug)
    author = book.get("author") or None
    page_list = book.get("pages", [])

    log.info("%s: %d pages listed", slug, len(page_list))

    paragraphs: list[dict[str, str]] = []
    pages_with_text = 0
    pages_skipped = 0
    pages_failed = 0

    for page_entry in page_list:
        page_id = page_entry.get("pageId")
        page_num = page_entry.get("pageNumber", 0)

        if not page_id:
            continue

        time.sleep(0.05)  # gentle rate limiting
        page_doc = _fetch_doc(client, f"pages/{page_id}")
        if page_doc is None:
            # A page that failed is missing from the work: no ingest stamp (#130).
            log.error("%s: page %s (%s) could not be fetched; left out", slug, page_num, page_id)
            pages_failed += 1
            continue

        pm_doc = page_doc.get("currentTextJson", {})
        text = _extract_text(pm_doc).strip()

        if not text:
            pages_skipped += 1
            continue

        ref = f"{ref_prefix}.{int(page_num):03d}"
        paragraphs.append({"ref": ref, "text": text})
        pages_with_text += 1
        log.debug("Page %s: %d chars", page_num, len(text))

    log.info(
        "%s: %d/%d pages have text, %d skipped (not yet transcribed), %d failed",
        slug, pages_with_text, len(page_list), pages_skipped, pages_failed,
    )

    # Build Work metadata
    if slug == "hudra-of-the-assyrian-church-of-the-east-volume-i":
        work = Work(
            work_id=f"hudra/{work_slug}",
            source_id=SOURCE_ID,
            author=author,
            title=title,
            date_composed=None,
            date_range=(600, 1000),
            date_confidence="uncertain",
            genre="liturgical",
            language="syc",
            tradition="syriac",
            license="used-with-permission",
            provenance_url=f"https://hudra.day/books/{slug}",
            edition=(
                f"Thoma Darmo (ed.), Thrissur: Mar Narsai Press, 1960; "
                f"transcription on hudra.day (Hendo Academy), used with permission. "
                f"Partial: {pages_with_text}/{len(page_list)} pages transcribed."
            ),
            translation_of=None,
        )
    else:
        work = Work(
            work_id=f"hudra/{work_slug}",
            source_id=SOURCE_ID,
            author=author,
            title=title,
            date_composed=None,
            date_range=(200, 700),
            date_confidence="uncertain",
            genre="liturgical",
            language="syc",
            tradition="syriac",
            license="used-with-permission",
            provenance_url=f"https://hudra.day/books/{slug}",
            edition=(
                f"Congregation for the Oriental Churches, Editio Typica (2003); "
                f"transcription on hudra.day (Hendo Academy), used with permission. "
                f"{pages_with_text}/{len(page_list)} pages transcribed."
            ),
            translation_of=None,
        )

    out_path.write_text(
        json.dumps(
            {"work": work.model_dump(), "paragraphs": paragraphs},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info("Wrote %s (%d paragraphs)", out_path, len(paragraphs))
    return work


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)

    works: list[Work] = []
    with httpx.Client(follow_redirects=True, timeout=20) as client:
        for book_conf in _BOOKS:
            try:
                work = _ingest_book(client, book_conf, out_dir, force)
                if work:
                    works.append(work)
            except Exception as e:
                log.error("Failed to ingest %s: %s", book_conf["slug"], e)

    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
