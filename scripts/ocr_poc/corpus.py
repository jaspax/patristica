"""Load normalized chunks by source and language for the OCR n-gram PoC."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterator
from pathlib import Path

NORMALIZED = Path("data/normalized")

# Encoding variants that are not OCR errors: several apostrophe/koronis code
# points, the Greek ano teleia vs. middle dot, non-breaking space, and Migne's
# curly beta (ϐ, which the OGL OCR emits for word-internal β).
_EQUIV = {
    0x02BC: "’",
    0x1FBD: "’",
    0x1FBF: "’",
    0x2019: "’",
    0x00A0: " ",
    0x0387: "·",
    0x03D0: "β",
}


def norm(text: str) -> str:
    """NFC, unify encoding variants, collapse whitespace."""
    t = unicodedata.normalize("NFC", text).translate(_EQUIV)
    return " ".join(t.split())


def works(source: str | None = None, language: str | None = None) -> Iterator[dict]:
    with open(NORMALIZED / "_works.jsonl", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            w = rec["work"]
            if source and w["source_id"] != source:
                continue
            if language and w["language"] != language:
                continue
            yield rec


def chunks(source: str, language: str) -> Iterator[tuple[str, str]]:
    """Yield (chunk_id, normalized text) for every chunk of a source in a language."""
    for rec in works(source, language):
        for c in json.loads((NORMALIZED / rec["path"]).read_text(encoding="utf-8")):
            yield c["chunk_id"], norm(c["text"])
