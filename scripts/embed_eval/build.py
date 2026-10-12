"""
Build the eval corpus and the generated (exact / near-verbatim) queries.

Reads ``data/chunks/`` (regenerate it first: ``scripts.chunk`` then
``scripts.link_translations``, since Scripture targets need
``translation_group_id``) and ``data/normalized/_works.jsonl``. Writes:

- ``data/eval/corpus.jsonl``  — one chunk per line (id, work, language, text, group, role)
- ``data/eval/queries.jsonl`` — one ``Query`` per line
- ``data/eval/build.json``    — parameters and counts

Targets of the authored queries in ``data/eval_authored/`` are always kept in
the corpus, so rebuilding never orphans them.

The output is deterministic for a given seed and input. It reads the chunk
files twice (metadata first, then texts of the selected chunks only) to keep
memory use low.

Usage::

    python -m scripts.embed_eval.build [--seed 0] [--scripture-per-lang 100] ...
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from tqdm import tqdm

from scripts.embed_eval.queries import DEFAULT_AUTHORED, make_queries
from scripts.embed_eval.select import ChunkMeta, select

log = logging.getLogger(__name__)

DEFAULT_CHUNKS = Path("data/chunks")
DEFAULT_WORKS = Path("data/normalized/_works.jsonl")
DEFAULT_OUT = Path("data/eval")


def load_works(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line)["work"] for line in f if line.strip()]


def _chunk_files(chunks_dir: Path) -> list[Path]:
    files = sorted(chunks_dir.rglob("*.json"))
    if not files:
        raise FileNotFoundError(
            f"No chunk files under {chunks_dir}. Run scripts.chunk and scripts.link_translations."
        )
    return files


def _iter_chunks(files: list[Path], desc: str) -> Iterator[dict]:
    for path in tqdm(files, desc=desc, unit="file"):
        yield from json.loads(path.read_text(encoding="utf-8"))


def build(
    chunks_dir: Path,
    works_path: Path,
    out_dir: Path,
    *,
    seed: int = 0,
    scripture_per_lang: int = 100,
    unique_per_lang: int = 100,
    distractors_per_lang: int = 2000,
    authored_dir: Path = DEFAULT_AUTHORED,
) -> dict:
    works = load_works(works_path)
    genre = {w["work_id"]: w["genre"] for w in works}
    files = _chunk_files(chunks_dir)

    metas: list[ChunkMeta] = []
    unknown: Counter[str] = Counter()
    for c in _iter_chunks(files, "metadata"):
        if c["work_id"] not in genre:
            unknown[c["work_id"]] += 1
            continue
        metas.append(ChunkMeta(
            chunk_id=c["chunk_id"], work_id=c["work_id"], language=c["language"],
            genre=genre[c["work_id"]], chunk_index=c["chunk_index"], n_chars=len(c["text"]),
            translation_group_id=c.get("translation_group_id"),
            out_of_period=c.get("out_of_period", False),
        ))
    if unknown:
        log.warning("Skipped chunks of %d works missing from %s (stale data/chunks?)",
                    len(unknown), works_path)

    required = frozenset(
        json.loads(line)["target_chunk_id"]
        for path in sorted(authored_dir.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )
    sel = select(
        metas, works, seed=seed, scripture_per_lang=scripture_per_lang,
        unique_per_lang=unique_per_lang, distractors_per_lang=distractors_per_lang,
        required=required,
    )
    del metas

    corpus = [
        {
            "chunk_id": c["chunk_id"], "work_id": c["work_id"], "language": c["language"],
            "text": c["text"], "translation_group_id": c.get("translation_group_id"),
            "role": sel.roles[c["chunk_id"]],
        }
        for c in _iter_chunks(files, "texts")
        if c["chunk_id"] in sel.corpus_ids
    ]
    corpus.sort(key=lambda c: c["chunk_id"])
    text_of = {c["chunk_id"]: c["text"] for c in corpus}

    targets = [(t.chunk_id, t.language, t.origin, text_of[t.chunk_id]) for t in sel.targets]
    queries = make_queries(targets, corpus, seed=seed)

    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "corpus.jsonl", corpus)
    _write_jsonl(out_dir / "queries.jsonl", [q.to_json() for q in queries])
    stats = {
        "params": {
            "seed": seed, "scripture_per_lang": scripture_per_lang,
            "unique_per_lang": unique_per_lang, "distractors_per_lang": distractors_per_lang,
        },
        "corpus_by_language": dict(sorted(Counter(c["language"] for c in corpus).items())),
        "corpus_by_role": dict(sorted(Counter(c["role"] for c in corpus).items())),
        "targets": dict(sorted(Counter(f"{t.language}/{t.origin}" for t in sel.targets).items())),
        "queries": dict(sorted(Counter(
            f"{q.mode}/{q.target_lang}/{q.origin}" for q in queries).items())),
    }
    (out_dir / "build.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    return stats


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--chunks-dir", type=Path, default=DEFAULT_CHUNKS)
    p.add_argument("--works", type=Path, default=DEFAULT_WORKS)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--scripture-per-lang", type=int, default=100)
    p.add_argument("--unique-per-lang", type=int, default=100)
    p.add_argument("--distractors-per-lang", type=int, default=2000)
    p.add_argument("--authored", type=Path, default=DEFAULT_AUTHORED,
                   help="authored query files whose targets must stay in the corpus")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = build(
        args.chunks_dir, args.works, args.out_dir, seed=args.seed,
        scripture_per_lang=args.scripture_per_lang, unique_per_lang=args.unique_per_lang,
        distractors_per_lang=args.distractors_per_lang, authored_dir=args.authored,
    )
    log.info("Wrote %s\n%s", args.out_dir, json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
