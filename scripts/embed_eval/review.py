"""
Review the drafted paraphrase/topical queries (#87) without a human pass.

1. ``review``: an independent model (GPT-6.1 Sol; the queries were drafted by
   Claude) checks every target's queries against the original passage, plus
   a published English translation for Scripture. A paraphrase gets an
   accuracy score (misreadings and additions; partial coverage is fine); a
   topical query gets a relevance score and a specificity label. Each gets a
   corrected version when it falls short. Results are cached in
   ``data/eval/review/reviews.jsonl``; reruns resume.
2. ``overlap``: for Scripture paraphrases, measures how much wording they
   share with the corpus's English Bibles (KJV/ASV/WEB). High overlap would
   make the cross-lingual test too easy.
3. ``variants``: writes three query sets under ``data/eval/review/variants/``:
   ``all`` (as drafted), ``passing`` (only queries that pass review and the
   overlap check) and ``corrected`` (failing queries replaced by the
   reviewer's corrections).
4. ``compare``: after ``run`` has scored each variant (``--authored`` /
   ``--results-dir``), shows whether the conclusions change.
5. ``apply``: writes the outcome into the tracked query file (corrections,
   with the draft kept, and a review status per query).

Usage::

    python -m scripts.embed_eval.review review
    python -m scripts.embed_eval.review overlap
    python -m scripts.embed_eval.review variants
    python -m scripts.embed_eval.review compare
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from scripts.embed_eval.translate import LANGUAGE_NAMES, Clients, cost
from scripts.migrate_layout import new_chunk_id, new_work_id

log = logging.getLogger(__name__)

REVIEWER = "sol"
MODELS_REVIEWER = "gpt-6.1-sol"
DEFAULT_DIR = Path("data/eval")
DEFAULT_AUTHORED = Path("data/eval_authored")
VARIANTS = ("all", "passing", "corrected")

MIN_ACCURACY = 4
MIN_RELEVANCE = 4
MAX_OVERLAP = 0.6  # share of a paraphrase's content-word bigrams found in an English Bible

LANGUAGES = {**LANGUAGE_NAMES, "grc": "Greek", "lat": "Latin", "hbo": "Biblical Hebrew"}

REVIEW_SYSTEM = """\
You review queries written for a search evaluation over early Christian and \
Jewish texts. Each target passage, in {language}, has two English queries:

- a paraphrase: a loose English rendering of the passage, meant to retrieve it;
- a topical query: a topic a user might search for, which the passage should be \
a reasonable answer to.

Check them against the original (a published English translation is included \
for Scripture; the original governs where they differ).

Paraphrase: a paraphrase query may cover only part of a long passage, as a \
user's search would. Rate two things separately:
- accuracy 1-5: is what the paraphrase does say right? (5 = nothing misread \
or added; 3 = one clause misread or something added that is not in the \
passage; 1 = mostly wrong). Leaving parts of the passage out does not lower \
accuracy.
- coverage: "most", "main point" or "minor part" of the passage.
List concrete misreadings or additions only.

Topical query: rate relevance 1-5 (5 = the passage is clearly about this \
topic; 1 = unrelated). Rate specificity: "narrow" if the query practically \
names or quotes this passage (e.g. a named event plus its characters), \
"medium" if it names a recognisable theme, "broad" if many passages would \
match. List concrete problems.

If accuracy or relevance is below 4, or the topical query is narrow, give a corrected \
query of the same kind; otherwise leave the correction null. Say how well you \
can read the original."""


class ParaphraseReview(BaseModel):
    accuracy: int = Field(ge=1, le=5)
    coverage: Literal["most", "main point", "minor part"]
    problems: list[str]
    corrected: str | None


class TopicalReview(BaseModel):
    relevance: int = Field(ge=1, le=5)
    specificity: Literal["narrow", "medium", "broad"]
    problems: list[str]
    corrected: str | None


class Review(BaseModel):
    paraphrase: ParaphraseReview
    topical: TopicalReview
    can_read_original: Literal["well", "partly", "poorly"]


# --- inputs ---------------------------------------------------------------------

def load_corpus(eval_dir: Path) -> dict[str, dict]:
    """The eval corpus by chunk id, with ids in the current form (#102).

    A local corpus built before #102 (or #69) has genre-prefixed ids; they are
    migrated on load, so it matches the authored queries.
    """
    corpus = {}
    for c in map(json.loads, (eval_dir / "corpus.jsonl").open()):
        c = {**c, "chunk_id": new_chunk_id(c["chunk_id"]), "work_id": new_work_id(c["work_id"])}
        corpus[c["chunk_id"]] = c
    return corpus


def resolve(chunk_id: str, corpus: dict[str, dict]) -> str | None:
    """Map a target id onto the eval corpus (``load_corpus``), migrating old ids."""
    chunk_id = new_chunk_id(chunk_id)
    return chunk_id if chunk_id in corpus else None


def load_drafted(authored_dir: Path) -> list[dict]:
    return [json.loads(line) for path in sorted(authored_dir.glob("*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def targets(authored_dir: Path, corpus: dict[str, dict]) -> list[dict]:
    """One entry per target: its text, language, queries and English references."""
    eng: dict[str, list[dict]] = defaultdict(list)
    for c in corpus.values():
        if c["language"] == "eng" and c.get("translation_group_id"):
            eng[c["translation_group_id"]].append(c)
    by_target: dict[str, dict] = {}
    for q in load_drafted(authored_dir):
        cid = resolve(q["target_chunk_id"], corpus)
        if cid is None:
            log.warning("target %s not in the eval corpus; skipped", q["target_chunk_id"])
            continue
        c = corpus[cid]
        t = by_target.setdefault(q["target_chunk_id"], {
            "target_chunk_id": q["target_chunk_id"], "language": c["language"],
            "origin": q["origin"], "text": c["text"],
            "references": {e["work_id"].split("/")[0]: e["text"]
                           for e in eng.get(c.get("translation_group_id") or "", [])},
        })
        t[q["mode"]] = q["text"]
    return [t for t in by_target.values() if "paraphrase" in t and "topical" in t]


# --- review -------------------------------------------------------------------

def run_review(eval_dir: Path, authored_dir: Path, workers: int) -> None:
    out_dir = eval_dir / "review"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "reviews.jsonl"
    done = {json.loads(line)["target_chunk_id"] for line in path.open()} if path.exists() else set()
    todo = [t for t in targets(authored_dir, load_corpus(eval_dir))
            if t["target_chunk_id"] not in done]
    log.info("reviewing %d targets (%d already done) with %s", len(todo), len(done), REVIEWER)
    clients, lock = Clients(), threading.Lock()

    def one(t: dict) -> None:
        parts = [f"Original ({LANGUAGES[t['language']]}):\n{t['text']}"]
        ref = next((t["references"][k] for k in ("web", "kjv", "asv") if k in t["references"]),
                   None)
        if ref:
            parts.append(f"Published English translation:\n{ref}")
        parts += [f"Paraphrase query:\n{t['paraphrase']}", f"Topical query:\n{t['topical']}"]
        try:
            out, usage = clients.call(
                REVIEWER, REVIEW_SYSTEM.format(language=LANGUAGES[t["language"]]),
                "\n\n".join(parts), Review, effort="high")
        except Exception as e:
            log.error("%s failed: %s", t["target_chunk_id"], e)
            return
        row = {"target_chunk_id": t["target_chunk_id"], "language": t["language"],
               "origin": t["origin"], **out.model_dump(), "usage": usage}
        with lock, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(one, todo))
    summarize(path)


def load_reviews(eval_dir: Path) -> dict[str, dict]:
    path = eval_dir / "review" / "reviews.jsonl"
    return {r["target_chunk_id"]: r for r in map(json.loads, path.open())} if path.exists() else {}


def summarize(path: Path) -> None:
    rows = [json.loads(line) for line in path.open()]
    print(f"{len(rows)} targets reviewed, cost ${cost([r['usage'] for r in rows]):.2f}")
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["language"], r["origin"])].append(r)
    print(f"{'lang':4s} {'origin':9s} {'n':>3s} {'para':>5s} {'p<4':>4s} {'topic':>5s} "
          f"{'t<4':>4s} {'narrow':>6s} {'reads':>5s}")
    for (lang, origin), rs in sorted(groups.items()):
        n = len(rs)
        print(f"{lang:4s} {origin:9s} {n:3d} "
              f"{sum(r['paraphrase']['accuracy'] for r in rs) / n:5.2f} "
              f"{sum(r['paraphrase']['accuracy'] < MIN_ACCURACY for r in rs):4d} "
              f"{sum(r['topical']['relevance'] for r in rs) / n:5.2f} "
              f"{sum(r['topical']['relevance'] < MIN_RELEVANCE for r in rs):4d} "
              f"{sum(r['topical']['specificity'] == 'narrow' for r in rs):6d} "
              f"{sum(r['can_read_original'] == 'well' for r in rs):5d}")


# --- overlap ------------------------------------------------------------------

_STOP = set(
    "a an the and or but of to in on at by for with from into as is are was were be been "
    "being it its this that these those he she they them his her their him i me my we us our "
    "you your shall will not no so then there which who whom what when all also let".split()
)


def _bigrams(text: str) -> set[tuple[str, str]]:
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP]
    return set(zip(words, words[1:], strict=False))


def overlap(paraphrase: str, references: list[str]) -> float:
    """Largest share of the paraphrase's content-word bigrams found in one reference."""
    mine = _bigrams(paraphrase)
    if not mine:
        return 0.0
    return max((len(mine & _bigrams(r)) / len(mine) for r in references), default=0.0)


def run_overlap(eval_dir: Path, authored_dir: Path) -> dict[str, float]:
    scores = {t["target_chunk_id"]: overlap(t["paraphrase"], list(t["references"].values()))
              for t in targets(authored_dir, load_corpus(eval_dir)) if t["references"]}
    vals = sorted(scores.values())
    if vals:
        q = [vals[int(p * (len(vals) - 1))] for p in (0.5, 0.9, 1.0)]
        print(f"{len(vals)} Scripture paraphrases: bigram overlap with an English Bible "
              f"median {q[0]:.2f}, p90 {q[1]:.2f}, max {q[2]:.2f}; "
              f"> {MAX_OVERLAP}: {sum(v > MAX_OVERLAP for v in vals)}")
    return scores


# --- variants and comparison -------------------------------------------------------

def passes(mode: str, review: dict | None, overlap_score: float) -> bool:
    if review is None:
        return False
    if mode == "paraphrase":
        return review["paraphrase"]["accuracy"] >= MIN_ACCURACY and overlap_score <= MAX_OVERLAP
    t = review["topical"]
    return t["relevance"] >= MIN_RELEVANCE and t["specificity"] != "narrow"


def write_variants(eval_dir: Path, authored_dir: Path) -> None:
    corpus = load_corpus(eval_dir)
    reviews = load_reviews(eval_dir)
    overlaps = run_overlap(eval_dir, authored_dir)
    out: dict[str, list[dict]] = {v: [] for v in VARIANTS}
    replaced = 0
    for q in load_drafted(authored_dir):
        cid = resolve(q["target_chunk_id"], corpus)
        if cid is None:
            continue
        q = {**q, "target_chunk_id": cid}
        out["all"].append(q)
        review = reviews.get(q["query_id"].split(":", 1)[1])
        ok = passes(q["mode"], review, overlaps.get(q["query_id"].split(":", 1)[1], 0.0))
        if ok:
            out["passing"].append(q)
            out["corrected"].append(q)
        elif review and review[q["mode"]].get("corrected"):
            out["corrected"].append({**q, "text": review[q["mode"]]["corrected"],
                                     "corrected_by": REVIEWER})
            replaced += 1
    for variant, rows in out.items():
        d = eval_dir / "review" / "variants" / variant
        d.mkdir(parents=True, exist_ok=True)
        with (d / "drafted.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"variants: all {len(out['all'])}, passing {len(out['passing'])}, "
          f"corrected {len(out['corrected'])} ({replaced} replaced)")


def apply_reviews(eval_dir: Path, authored_dir: Path) -> None:
    """Write review outcomes into the tracked query file.

    Queries that fail and have a correction take the corrected text (the draft
    is kept in ``drafted_text``); every query records its ``review`` status:
    ``pass``, ``corrected``, or ``flagged`` (failed without a correction, e.g.
    only the English-Bible overlap check).
    """
    reviews = load_reviews(eval_dir)
    overlaps = run_overlap(eval_dir, authored_dir)
    for path in sorted(authored_dir.glob("*.jsonl")):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        counts: dict[str, int] = defaultdict(int)
        for q in rows:
            target = q["target_chunk_id"]
            review = reviews.get(target)
            if review is None or q.get("review"):
                continue
            if passes(q["mode"], review, overlaps.get(target, 0.0)):
                q["review"] = "pass"
            elif review[q["mode"]].get("corrected"):
                q["drafted_text"], q["text"] = q["text"], review[q["mode"]]["corrected"]
                q["review"] = "corrected"
            else:
                q["review"] = "flagged"
            q["reviewed_by"] = MODELS_REVIEWER
            counts[q["review"]] += 1
        with path.open("w", encoding="utf-8") as f:
            for q in rows:
                f.write(json.dumps(q, ensure_ascii=False) + "\n")
        print(f"{path}: {dict(counts)}")


def compare(eval_dir: Path) -> None:
    """Mean score per retriever and mode for each variant, plus per-language deltas."""
    from scripts.embed_eval.report import THRESHOLDS

    cells: dict[tuple[str, str, str, str], dict[str, float]] = defaultdict(dict)
    for variant in VARIANTS:
        for path in sorted((eval_dir / "review" / "results" / variant).glob("*.json")):
            r = json.loads(path.read_text(encoding="utf-8"))
            for s in r["summaries"]["lang"]:
                if s["mode"] in ("paraphrase", "topical"):
                    key = (r["retriever"], s["mode"], s["lang"], s["origin"])
                    cells[key][variant] = s[THRESHOLDS[s["mode"]]]
    table: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for (ret, mode, _, _), v in cells.items():
        for variant, val in v.items():
            table[(ret, mode)][variant].append(val)
    print(f"{'retriever':45s} {'mode':10s} " + " ".join(f"{v:>9s}" for v in VARIANTS))
    for (ret, mode), v in sorted(table.items()):
        print(f"{ret[:45]:45s} {mode:10s} "
              + " ".join(f"{sum(v[x]) / len(v[x]):9.2f}" if v.get(x) else f"{'–':>9s}"
                         for x in VARIANTS))
    big = [(k, v) for k, v in cells.items()
           if len(v) == 3 and max(v.values()) - min(v.values()) >= 0.2]
    print(f"\ncells moving by ≥ 0.20 between variants: {len(big)}")
    for (ret, mode, lang, origin), v in sorted(big):
        print(f"  {ret[:40]:40s} {mode:10s} {lang}/{origin:9s} "
              + " ".join(f"{x}={v[x]:.2f}" for x in VARIANTS))


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("cmd",
                   choices=("review", "summary", "overlap", "variants", "compare", "apply"))
    p.add_argument("--eval-dir", type=Path, default=DEFAULT_DIR)
    p.add_argument("--authored", type=Path, default=DEFAULT_AUTHORED)
    p.add_argument("--workers", type=int, default=6)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.cmd == "review":
        run_review(args.eval_dir, args.authored, args.workers)
    elif args.cmd == "summary":
        summarize(args.eval_dir / "review" / "reviews.jsonl")
    elif args.cmd == "overlap":
        run_overlap(args.eval_dir, args.authored)
    elif args.cmd == "variants":
        write_variants(args.eval_dir, args.authored)
    elif args.cmd == "apply":
        apply_reviews(args.eval_dir, args.authored)
    else:
        compare(args.eval_dir)


if __name__ == "__main__":
    main()
