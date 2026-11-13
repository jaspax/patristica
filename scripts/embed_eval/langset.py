"""
A one-language eval set for a new language, built straight from ``data/normalized``.

``scripts.embed_eval.build`` samples the 2026-10 eval corpus from
``data/chunks`` across every language, and its embedding cache is per text, so
extending it means embedding a corpus whose chunk ids predate the source-first
layout (#102). Every number in ``docs/embedding-eval.md`` is filtered to the
target's language, so a new language needs only its own chunks: this builds
the same kind of set for one language with ``select.select`` (about 100
Scripture targets with every same-language witness of their verse, about 100
language-unique targets with ±2 neighbours, 2,000 random distractors) and
``queries.make_queries`` (exact and near-verbatim spans), from the text
``scripts.embed`` embeds (``editorial.source_text``). Scripture verses are
grouped by their org-versification ref, as ``scripts.link_translations`` does.

For Church Slavonic it adds a ``modern`` query per exact span: the span in
modern Russian orthography (``spelling.modern``), scored at R@1 like near.

The Scripture targets' verse groups also get their English verses (WEB, KJV,
ASV; role ``reference``), so the translation-quality eval and the query review
have a published reference, as in #84 and #87. They are outside the
language-filtered scores.

``--subset-dir`` writes the set's chunks in the language as a normalized tree
(``_works.jsonl`` plus one file per work), so ``scripts.translate --input-dir``
translates exactly the eval chunks into an eval store.

Works in ``WITNESS_GROUPS`` are two editions of one non-Scripture text: their
units are grouped by canonical ref like Scripture witnesses, so a query on one
is answered by the other, both are in the corpus, and only one is a target.

Languages in ``EDITION_LANGUAGES`` have editions of one text cut at different
places, so refs don't pair them: their units are grouped by the passage
alignment (``data/alignments``, #199's word alignment of same-language
editions). A query on a unit of one edition is then answered by the units of
the other edition in its alignment group (Literary Chinese, #663: the
Wikisource and Taishō editions of four Jingjiao texts).

``--all-units`` puts every unit of the language that ``scripts.embed`` embeds
into the corpus, short ones too, for a language whose whole corpus is smaller
than the distractor sample (Literary Chinese: about 600 units), so the set is
the search space a user filtering by the language has.

``--min-target-chars`` keeps short units (Old Irish glosses) out of the unique
targets; they stay in the corpus as neighbours and distractors.

``--fold`` also writes ``{out}-fold``: the same set with every corpus text and
every query in the language passed through ``fold()``, to measure embedding an
orthographically normalized form (#336). Authored English queries are the
same in both.

Usage::

    python -m scripts.embed_eval.langset chu [--out-dir data/eval/chu] [--fold]
        [--subset-dir data/eval/chu/normalized]
    python -m scripts.embed_eval.run --eval-dir data/eval/chu --retriever bm25 \\
        --retriever dense:voyage/voyage-4-large
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from patristica import alignment_store, editorial
from patristica.embeddings import MIN_CHARS
from patristica.textfold import fold
from patristica.versification import to_org_ref
from scripts.embed_eval.queries import DEFAULT_AUTHORED, Query, make_queries
from scripts.embed_eval.select import MIN_CHARS as MIN_TARGET_CHARS
from scripts.embed_eval.select import ChunkMeta, select

log = logging.getLogger(__name__)

DEFAULT_NORMALIZED = Path("data/normalized")
REFERENCE_SOURCES: tuple[str, ...] = ("web", "kjv", "asv")
CORPUS_KEYS = ("chunk_id", "work_id", "language", "text", "translation_group_id")

# Editions of one non-Scripture text with the same canonical refs (work id →
# group name): the Félire Óengusso from CELT (Stokes's normalized text) and
# from Gloss Corpus (a diplomatic text), one quatrain per day (#552).
WITNESS_GROUPS: dict[str, str] = {
    "celt/felire-oengusso": "felire",
    "glosscorpus/felire": "felire",
}

# Languages whose same-language editions are grouped by their passage
# alignment (``edition_groups``), with the prefix of the group ids.
EDITION_LANGUAGES: frozenset[str] = frozenset({"lzh"})
EDITION_PREFIX = "edition:"


def edition_groups(chunks: list[dict],
                   alignments_dir: Path = alignment_store.DEFAULT_DIR) -> dict[str, str]:
    """chunk id → group id for the *chunks* (of one language) that an alignment
    pairs with a unit of another edition among them (confident spans only).

    A member whose chunk ids changed since it was aligned is left out, since its
    spans count other units.
    """
    by_work: dict[str, list[str]] = {}
    for c in chunks:
        by_work.setdefault(c["work_id"], []).append(c["chunk_id"])
    out: dict[str, str] = {}
    for _, a in alignment_store.iter_store(
            alignments_dir, lambda ids: sum(i in by_work for i in ids) >= 2):
        members = {w: m for w, m in a.members.items() if w in by_work
                   and m.ids == alignment_store.ids_sha(by_work[w])}
        for g, spans in a.groups_of().items():
            spans = {w: s for w, s in spans.items() if w in members}
            if len(spans) < 2:
                continue
            for w, (start, end) in spans.items():
                for cid in by_work[w][start:end]:
                    out[cid] = f"{EDITION_PREFIX}{a.group}:{g}"
    return out


def group_id(work: dict, ref: str) -> str | None:
    """A unit's ``translation_group_id``: Scripture by org verse, witnesses by ref."""
    if work["genre"] == "scripture":
        return to_org_ref(work["source_id"], ref)
    if name := WITNESS_GROUPS.get(work["work_id"]):
        return f"{name}:{ref}"
    return None


def _manifest(normalized_dir: Path) -> list[dict]:
    """The ``_works.jsonl`` records (``{"path", "work"}``)."""
    with (normalized_dir / "_works.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _chunks(normalized_dir: Path, rec: dict) -> list[dict]:
    w = rec["work"]
    return [{
        "chunk_id": c["chunk_id"], "work_id": c["work_id"], "language": c["language"],
        "text": editorial.source_text(c), "chunk_index": c["chunk_index"],
        "out_of_period": c.get("out_of_period", False),
        "translation_group_id": group_id(w, c["canonical_ref"]),
        "raw": c,
    } for c in json.loads((normalized_dir / rec["path"]).read_text(encoding="utf-8"))]


def load_language(normalized_dir: Path, lang: str,
                  alignments_dir: Path = alignment_store.DEFAULT_DIR
                  ) -> tuple[list[dict], list[dict]]:
    """``(manifest records, chunks)``: every work, and the chunks of the works in *lang*.

    Chunks carry the embedded text and, for Scripture, their verse's org ref as
    ``translation_group_id`` (in ``EDITION_LANGUAGES``, their edition group);
    ``raw`` is the normalized chunk.
    """
    recs = _manifest(normalized_dir)
    chunks = [c for r in recs if r["work"]["language"] == lang
              for c in _chunks(normalized_dir, r)]
    if lang in EDITION_LANGUAGES:
        groups = edition_groups(chunks, alignments_dir)
        for c in chunks:
            c["translation_group_id"] = c["translation_group_id"] or groups.get(c["chunk_id"])
    return recs, chunks


def english_references(normalized_dir: Path, groups: set[str]) -> list[dict]:
    """The verses of the English Bibles (``REFERENCE_SOURCES``) in the verse *groups*."""
    books = {g.split(".")[0] for g in groups}
    out = []
    for r in _manifest(normalized_dir):
        w = r["work"]
        if w["source_id"] not in REFERENCE_SOURCES or w["genre"] != "scripture":
            continue
        if Path(r["path"]).stem not in books:
            continue
        out += [c for c in _chunks(normalized_dir, r)
                if c["translation_group_id"] in groups and c["text"].strip()]
    return out


def authored_targets(authored_dir: Path) -> frozenset[str]:
    return frozenset(
        json.loads(line)["target_chunk_id"]
        for path in sorted(authored_dir.glob("*.jsonl"))
        for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    )


def modern_queries(queries: list[Query]) -> list[Query]:
    """A ``modern`` query per exact Church Slavonic query: the span in modern spelling."""
    from scripts.embed_eval.spelling import modern

    out = []
    for q in queries:
        if q.mode == "exact" and q.target_lang == "chu":
            out.append(Query(f"modern:{q.target_chunk_id}", "modern", modern(q.text),
                             q.query_lang, q.target_lang, q.origin, q.target_chunk_id,
                             q.relevant_ids))
    return out


def write_subset(out_dir: Path, recs: list[dict], chunks: list[dict], ids: set[str]) -> int:
    """Write the chunks in *ids* as a normalized tree under *out_dir*; returns the count."""
    by_work: dict[str, list[dict]] = {}
    for c in chunks:
        if c["chunk_id"] in ids:
            by_work.setdefault(c["work_id"], []).append(c["raw"])
    lines = []
    for r in recs:
        kept = by_work.get(r["work"]["work_id"])
        if not kept:
            continue
        path = out_dir / r["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(kept, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        lines.append(json.dumps(r, ensure_ascii=False))
    (out_dir / "_works.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sum(len(v) for v in by_work.values())


def build(normalized_dir: Path, lang: str, out_dir: Path, *, seed: int = 0,
          scripture_per_lang: int = 100, unique_per_lang: int = 100,
          distractors_per_lang: int = 2000, authored_dir: Path = DEFAULT_AUTHORED,
          folded: bool = False, subset_dir: Path | None = None,
          min_target_chars: int = MIN_TARGET_CHARS, all_units: bool = False,
          alignments_dir: Path = alignment_store.DEFAULT_DIR) -> dict:
    recs, chunks = load_language(normalized_dir, lang, alignments_dir)
    works = [r["work"] for r in recs]
    genre = {w["work_id"]: w["genre"] for w in works}
    metas = [ChunkMeta(c["chunk_id"], c["work_id"], c["language"], genre[c["work_id"]],
                       c["chunk_index"], len(c["text"]), c["translation_group_id"],
                       c["out_of_period"]) for c in chunks]
    sel = select(metas, works, seed=seed, target_langs=(lang,),
                 scripture_per_lang=scripture_per_lang, unique_per_lang=unique_per_lang,
                 distractors_per_lang=distractors_per_lang,
                 required=authored_targets(authored_dir), min_target_chars=min_target_chars)
    if all_units:
        for c in chunks:
            sel.add(c["chunk_id"], "distractor")
    # A unique target's other witnesses answer its queries too.
    by_group: dict[str, list[str]] = {}
    for c in chunks:
        if c["translation_group_id"] and (c["work_id"] in WITNESS_GROUPS
                                          or c["translation_group_id"].startswith(EDITION_PREFIX)):
            by_group.setdefault(c["translation_group_id"], []).append(c["chunk_id"])
    group_of = {c["chunk_id"]: c["translation_group_id"] for c in chunks}
    for t in sel.targets:
        for cid in by_group.get(group_of[t.chunk_id] or "", []):
            sel.add(cid, "parallel")
    # Neighbours aren't size-filtered: drop the units scripts.embed doesn't embed
    # (wholly editorial headings are empty in source_text, and the API refuses "").
    corpus = [{k: c[k] for k in CORPUS_KEYS} | {"role": sel.roles[c["chunk_id"]]}
              for c in chunks if c["chunk_id"] in sel.corpus_ids
              and len(c["text"].strip()) >= MIN_CHARS]
    wanted = {t.chunk_id for t in sel.targets} | authored_targets(authored_dir)
    groups = {c["translation_group_id"] for c in corpus
              if c["translation_group_id"] and c["chunk_id"] in wanted}
    refs = [{k: c[k] for k in CORPUS_KEYS} | {"role": "reference"}
            for c in english_references(normalized_dir, groups)]
    corpus = sorted(corpus + refs, key=lambda c: c["chunk_id"])
    text_of = {c["chunk_id"]: c["text"] for c in corpus}
    targets = [(t.chunk_id, t.language, t.origin, text_of[t.chunk_id]) for t in sel.targets]
    queries = make_queries(targets, corpus, seed=seed)
    if lang == "chu":
        queries += modern_queries(queries)

    stats = {
        "lang": lang, "seed": seed, "source": str(normalized_dir),
        "corpus_by_role": dict(sorted(Counter(c["role"] for c in corpus).items())),
        "corpus_by_source": dict(sorted(Counter(c["work_id"].split("/")[0]
                                                for c in corpus).items())),
        "targets": dict(sorted(Counter(f"{t.language}/{t.origin}"
                                       for t in sel.targets).items())),
        "queries": dict(sorted(Counter(f"{q.mode}/{q.origin}" for q in queries).items())),
        "targets_list": [{"chunk_id": t.chunk_id, "origin": t.origin} for t in sel.targets],
    }
    _write(out_dir, corpus, queries, stats)
    if subset_dir is not None:
        stats["subset_chunks"] = write_subset(
            subset_dir, recs, chunks, {c["chunk_id"] for c in corpus if c["role"] != "reference"})
    if folded:
        fc = [{**c, "text": fold(c["text"])} if c["language"] == lang else c for c in corpus]
        fq = [Query(q.query_id, q.mode, fold(q.text) if q.query_lang == lang else q.text,
                    q.query_lang, q.target_lang, q.origin, q.target_chunk_id, q.relevant_ids)
              for q in queries]
        _write(out_dir.with_name(out_dir.name + "-fold"), fc, fq, {**stats, "folded": True})
    return stats


def _write(out_dir: Path, corpus: list[dict], queries: list[Query], stats: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "corpus.jsonl").open("w", encoding="utf-8") as f:
        for row in corpus:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out_dir / "queries.jsonl").open("w", encoding="utf-8") as f:
        for q in queries:
            f.write(json.dumps(q.to_json(), ensure_ascii=False) + "\n")
    (out_dir / "build.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False) + "\n",
                                        encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("lang")
    p.add_argument("--normalized-dir", type=Path, default=DEFAULT_NORMALIZED)
    p.add_argument("--out-dir", type=Path, help="default: data/eval/{lang}")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--scripture-per-lang", type=int, default=100)
    p.add_argument("--unique-per-lang", type=int, default=100)
    p.add_argument("--distractors-per-lang", type=int, default=2000)
    p.add_argument("--min-target-chars", type=int, default=MIN_TARGET_CHARS,
                   help="shortest unique target (default %(default)s)")
    p.add_argument("--all-units", action="store_true",
                   help="every unit of LANG that scripts.embed embeds is in the corpus")
    p.add_argument("--authored", type=Path, default=DEFAULT_AUTHORED)
    p.add_argument("--fold", action="store_true", help="also write the fold()-ed set")
    p.add_argument("--subset-dir", type=Path,
                   help="also write the set's chunks in LANG as a normalized tree")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = build(args.normalized_dir, args.lang, args.out_dir or Path("data/eval") / args.lang,
                  seed=args.seed, scripture_per_lang=args.scripture_per_lang,
                  unique_per_lang=args.unique_per_lang,
                  distractors_per_lang=args.distractors_per_lang,
                  authored_dir=args.authored, folded=args.fold, subset_dir=args.subset_dir,
                  min_target_chars=args.min_target_chars, all_units=args.all_units)
    log.info("%s", json.dumps({k: v for k, v in stats.items() if k != "targets_list"},
                              indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
