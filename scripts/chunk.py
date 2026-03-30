"""
Add context overlap to normalized Chunk records → embedding-ready chunks.

For each work's chunks, fills in ``context_before`` and ``context_after``
using trailing/leading text from adjacent chunks (≈50 tokens each).

Scripture chunks (individual verses) use the preceding/following verse text
as context.  Patristic prose chunks use a 50-token overlap from neighbouring
paragraphs (implemented in M3+).

Reads from ``data/normalized/`` and writes to ``data/chunks/``.

Usage::

    python -m scripts.chunk [--input-dir data/normalized] [--output-dir data/chunks] [--force]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import tiktoken
from tqdm import tqdm

from patristica.models import Chunk

log = logging.getLogger(__name__)

CONTEXT_TOKENS = 50  # target overlap size in tokens

_enc = tiktoken.get_encoding("cl100k_base")


def _truncate_to_tokens(text: str, max_tokens: int, from_end: bool = False) -> str:
    """Return at most *max_tokens* tokens from *text*.

    If *from_end* is True, return the trailing tokens (for ``context_before``).
    """
    tokens = _enc.encode(text)
    if from_end:
        tokens = tokens[-max_tokens:]
    else:
        tokens = tokens[:max_tokens]
    return _enc.decode(tokens)


def add_context(chunks: list[Chunk]) -> list[Chunk]:
    """Return new Chunk objects with ``context_before`` and ``context_after`` filled in."""
    updated: list[Chunk] = []
    for i, chunk in enumerate(chunks):
        before = None
        after = None

        if i > 0:
            prev_text = chunks[i - 1].text
            before = _truncate_to_tokens(prev_text, CONTEXT_TOKENS, from_end=True)

        if i < len(chunks) - 1:
            next_text = chunks[i + 1].text
            after = _truncate_to_tokens(next_text, CONTEXT_TOKENS, from_end=False)

        updated.append(chunk.model_copy(update={
            "context_before": before,
            "context_after": after,
        }))

    return updated


def chunk_file(
    norm_path: Path,
    output_dir: Path,
    force: bool = False,
) -> int:
    """Add context to all chunks in *norm_path* and write to *output_dir*.

    Returns the number of chunks written (0 if skipped).
    """
    # Mirror path structure
    rel_parts = norm_path.parts
    try:
        norm_idx = next(i for i, p in enumerate(rel_parts) if p == "normalized")
        sub_parts = rel_parts[norm_idx + 1:]
    except StopIteration:
        sub_parts = (norm_path.name,)

    out_path = output_dir.joinpath(*sub_parts)

    if out_path.exists() and not force:
        log.debug("Skipping %s (already chunked)", out_path)
        return 0

    with norm_path.open(encoding="utf-8") as f:
        try:
            raw_chunks = json.load(f)
        except json.JSONDecodeError as exc:
            log.warning("Skipping %s: JSON error: %s", norm_path, exc)
            return 0

    if not isinstance(raw_chunks, list) or not raw_chunks:
        return 0

    chunks = [Chunk(**c) for c in raw_chunks]
    chunks_with_ctx = add_context(chunks)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = [c.model_dump() for c in chunks_with_ctx]
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.debug("Chunked %d records → %s", len(data), out_path)
    return len(data)


def chunk_all(
    input_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> int:
    """Walk *input_dir* and apply context overlap to every normalized file."""
    json_files = list(input_dir.rglob("*.json"))
    if not json_files:
        log.warning("No normalized JSON files found under %s", input_dir)
        return 0

    log.info("Adding context overlap to %d normalized files…", len(json_files))
    total = 0
    for path in tqdm(json_files, desc="chunk"):
        total += chunk_file(path, output_dir, force=force)

    log.info("Chunking complete: %d total records written", total)
    return total


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Add context overlap to normalized chunks.")
    parser.add_argument("--input-dir", default="data/normalized")
    parser.add_argument("--output-dir", default="data/chunks")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    chunk_all(
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        force=args.force,
    )


if __name__ == "__main__":
    main()
