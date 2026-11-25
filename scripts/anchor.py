"""
Anchor derived verses on the original (#304, #638).

The paid step between ``scripts.normalize`` and ``scripts.translate``
(``docs/anchored-derived-verses.md``). Which works are anchored, and on what,
is a rule (``patristica.anchor_rule``), not a list: a translation on (the
preferred edition of) its ``translation_of``, another edition of a text on the
preferred edition of its language in its version group (a critical text
before OCR'd Migne). For each such work without a current cut file it finds
the cut of its derived verses that pairs each of the anchor's derived verses
with a run of whole sentence/clause segments: from Voyage vectors for a
translation (``patristica.anchor_refine``), by projecting through the two
texts' word alignment for an edition (``patristica.edition_projection``). If
the anchored cut has no more 1:1 rows with the anchor than the provisional one,
the work keeps its provisional cut (also on a tie), and the cut file records that
(``stats.kept``), so each decision is made once. Then it:

1. writes the tracked cut file ``data/anchors/{normalized path}`` (word
   positions only, ``patristica.anchor_store``);
2. re-normalizes the work from ``data/raw`` with it (``scripts.normalize``'s
   own code path, so a later normalize writes the same bytes);
3. for a translation, writes the final units' text vectors into
   ``data/embeddings`` (ordinary ``KIND_TEXT`` rows with the production run
   record), so ``scripts.embed`` has nothing left to send for them; an
   edition's new units are embedded by ``scripts.embed``.

Segment and candidate vectors are kept in ``data/anchor_vectors/`` (gitignored
scratch, regenerable): a re-run hits it for free.

**Which works.** A cut file is *missing* (never cut) or its translation's
words changed (a re-ingest or text fix): such works are cut. A cut file whose
inputs changed otherwise (the original's cuts, the anchor itself, the method
version or parameters) is **frozen** (owner, 2026-10-28): derived refs are
reader URLs and translation keys, so it is only reported (``scripts.status``)
until ``--recut WORK`` (or ``--recut all``) re-cuts it. A change to this code
re-cuts nothing; bump ``anchoring.ANCHOR_VERSION`` deliberately.

**Requirements.** The original's units need current text vectors (run
``scripts.embed --work {original}`` first, as ``scripts.align`` requires); the
step refuses a work otherwise. An original in a language
``scripts.translate`` translates (Syriac, Coptic, Armenian, Ge'ez, Church
Slavonic) is anchored on its English machine translation's vectors (#392,
:func:`original_vectors`), so translate and embed it first; a unit without
one falls back to its text vector (logged). A translation of only part of its
original is refined on the span it covers (#394,
``anchor_refine.covered_span``). normalize's code must be current, and the
work's raw file present. Works are cut originals first (an English translation
of a Slavonic translation waits for the Slavonic cut).

**Paid.** Requests are sent only with ``--pay`` (Voyage). Without it a run
that needs vectors stops with the estimate (``--dry-run`` prints it per work:
the first embed exactly, the refinement rounds as an upper bound). Agents run
``--pay`` only with the owner's permission, asked first, every time.

Usage::

    uv run --extra embed python -m scripts.anchor --dry-run
    uv run --extra embed python -m scripts.anchor --pay [--max-cost USD] [--work PREFIX]
    uv run --extra embed python -m scripts.anchor --pay --recut WORK_ID
    uv run python -m scripts.anchor --check     # stale or missing cut files (no vectors)
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import json
import logging
import sys
import time
from collections.abc import Callable, Collection, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from patristica import anchor_rule, anchor_store, anchoring, console, fingerprint
from patristica import embeddings as emb
from patristica import translations as tr
from patristica.corpus import EXCLUDED_LICENSES, load_works
from patristica.editorial import source_text, spans_of
from patristica.stat_cache import StatCache, cache_dir, file_stamps
from patristica.translations import text_sha

if TYPE_CHECKING:
    from patristica.anchor_refine import Units, VectorCache

log = logging.getLogger(__name__)

NORMALIZED = Path("data/normalized")
RAW = Path("data/raw")
ANCHORS = anchor_store.DEFAULT_DIR
EMBEDDINGS = emb.DEFAULT_DIR
SCRATCH = Path("data/anchor_vectors")
TRANSLATIONS = tr.DEFAULT_DIR

MODEL = "voyage-4-large"
DIMS = 1024
INPUT_TYPE = "document"
PRICE_PER_MTOK = 0.12  # as scripts.embed (list price, cl100k estimate)
#: Upper bound of what the refinement rounds send, × the translation's text
#: tokens. A round embeds only the pieces it chose that aren't cached, and a
#: round's pieces don't overlap, so each exploring round sends at most the
#: text once, and the final units at most once more. (Measured: 0.7× for
#: NPNF's Tractates, 1.7× for a free Armenian version, 2.1× for a re-cut of
#: a CCMH homily; a measured factor of 2.0 stopped that re-cut, #472.)
ROUNDS_FACTOR = anchoring.RefineParams().max_rounds + 1

#: States of an anchorable work (``check_works``).
CURRENT = "current"
MISSING = "missing"  # no cut file: cut it
WORDS = "words"  # the translation's words changed: cut it again
OUTPUT = "output"  # the normalized output doesn't match the cut file: run normalize
UNNORMALIZED = "unnormalized"  # anchored, but normalize hasn't fingerprinted it: run normalize
ORPHAN = "orphan"  # a cut file for a work that isn't anchored
ANCHOR = "anchor"  # translation_of changed (frozen)
ANCHOR_CUTS = "anchor_cuts"  # the original's cuts changed (frozen)
METHOD = "method"  # ANCHOR_VERSION or the parameters changed (frozen)
MODEL_CHANGED = "model"  # the original's vectors are of another model (reported only)

#: Fail ``tests/test_anchor_fingerprint.py`` and ``scripts.status``.
FAILING = frozenset({MISSING, WORDS, OUTPUT, UNNORMALIZED, ORPHAN})
#: Reported, re-cut only with ``--recut``.
FROZEN = frozenset({ANCHOR, ANCHOR_CUTS, METHOD})
#: Cut by a plain run.
TO_CUT = frozenset({MISSING, WORDS})


class AnchorError(RuntimeError):
    """The step can't run as asked (stale normalize, no raw data, …)."""


@dataclass
class Candidate:
    """A work the anchoring rule anchors (#638), with its anchor."""

    path: str
    work_id: str
    language: str
    anchor: str
    anchor_path: str
    #: The original's language; it decides the vectors it is anchored on
    #: (:func:`original_vectors`). Empty: read from the original's units.
    anchor_language: str = ""
    #: ``vectors``: a translation refined on its original's vectors
    #: (``patristica.anchor_refine``); ``text``: another edition in the same
    #: language, cut where the anchor cuts by projecting through the two texts
    #: (``patristica.edition_projection``, #200), with no vectors.
    method: str = "vectors"


@dataclass
class State:
    candidate: Candidate | None  # None for an orphan cut file
    status: str
    detail: str = ""


# ---------------------------------------------------------------------------
# Which works are anchored, and are their cut files current (no vectors)
# ---------------------------------------------------------------------------


def _model() -> str:
    return f"voyage/{MODEL}"


def candidates(norm: Path, anchors_dir: Path = ANCHORS) -> tuple[list[Candidate], list[str]]:
    """(anchorable works, works normalize hasn't fingerprinted since #638).

    The works :func:`anchor_rule` anchors, when normalize cut them as prose
    (their fingerprint's ``anchor`` record isn't null). Works whose licence
    keeps them out of the index (``corpus.EXCLUDED_LICENSES``), and works whose
    anchor's does, aren't anchored: neither is embedded (``scripts.embed``), so
    their text is never sent and they keep the size cut. An anchor in the
    work's own language is another edition, cut by text projection.
    """
    from scripts import normalize as nz

    entries = load_works(norm)
    by_id = {e["work"]["work_id"]: e for e in entries}
    fps = nz.read_work_fingerprints(norm)
    recorded = anchor_rule.recorded_anchors(anchors_dir)
    rule = anchor_rule.anchors({w: e["work"] for w, e in by_id.items()}, recorded)
    out: list[Candidate] = []
    unbuilt: list[str] = []
    for e in entries:
        work, path = e["work"], e["path"]
        target = rule.get(work["work_id"])
        if target is None:
            continue
        fp = fps.get(path)
        if fp is None or "anchor" not in fp:
            unbuilt.append(path)
            continue
        if fp["anchor"] is None:
            continue  # a standard versification: never anchored
        orig = by_id[target]["work"]
        if work.get("license") in EXCLUDED_LICENSES or orig.get("license") in EXCLUDED_LICENSES:
            continue
        method = "text" if anchoring.same_language(work["language"], orig["language"]) else (
            "vectors")
        out.append(Candidate(path, work["work_id"], work["language"], target,
                             by_id[target]["path"], orig["language"], method))
    return out, unbuilt


def _chunks(norm: Path, path: str) -> list[dict]:
    return json.loads((norm / path).read_text(encoding="utf-8"))


def paragraph_words(paras: list[anchoring.Paragraph]) -> str:
    """The ``words`` input of a cut: every paragraph's ref and words."""
    from patristica import fingerprint

    return fingerprint.value_hash([[p.ref, p.words_hash] for p in paras])


def check_work(c: Candidate, norm: Path, anchors_dir: Path,
               params: anchoring.RefineParams = anchoring.RefineParams()) -> State:
    """The state of one anchorable work's cut file."""
    cut = anchor_store.load(anchors_dir, c.path)
    if cut is None:
        return State(c, MISSING, "no cut file")
    paras = anchoring.paragraphs(_chunks(norm, c.path))
    if cut.words != paragraph_words(paras):
        changed = [p.ref for p in paras
                   if p.ref not in cut.paragraphs or cut.paragraphs[p.ref].words != p.words_hash]
        return State(c, WORDS, f"{len(changed)} paragraphs changed"
                     + (f", e.g. {changed[0]}" if changed else ""))
    for p in paras:
        rec = cut.paragraphs.get(p.ref)
        if rec is None or rec.words != p.words_hash or rec.starts != p.starts:
            return State(c, OUTPUT, f"{p.ref} isn't cut as its cut file says: re-run "
                                    "scripts.normalize")
    if cut.anchor != c.anchor:
        return State(c, ANCHOR, f"cut on {cut.anchor}, translation_of is now {c.anchor}")
    if cut.method != method_hash(c, params):
        return State(c, METHOD, "cut with another ANCHOR_VERSION or parameters")
    if cut.anchor_cuts != anchoring.chunks_cuts_hash(_chunks(norm, c.anchor_path)):
        return State(c, ANCHOR_CUTS, f"the cuts of {c.anchor} changed since")
    if cut.model and cut.model != _model():
        return State(c, MODEL_CHANGED, f"cut on {cut.model} vectors")
    return State(c, CURRENT)


@functools.cache
def _check_head() -> str:
    """What decides a :func:`check_work` verdict besides its files and candidate."""
    return fingerprint.code_hash("scripts.anchor")


def check_cache(norm: Path) -> StatCache:
    """:func:`check_works`' cache of current works (#782), beside *norm*."""
    return StatCache(cache_dir(norm) / "anchor_check.json", _check_head())


def check_works(norm: Path = NORMALIZED, anchors_dir: Path = ANCHORS,
                use_cache: bool = True) -> list[State]:
    """Every anchorable work's state, plus works normalize hasn't fingerprinted
    and cut files of works that aren't anchored (orphans). Needs no vectors.

    A work found current is remembered (``data/cache/anchor_check.json``)
    while its normalized file, its anchor's and its cut file keep their stat
    and its anchor, method and model are the same, so a no-op check reads
    only the changed works (#782)."""
    cands, unbuilt = candidates(norm, anchors_dir)
    states = [State(None, UNNORMALIZED, p) for p in unbuilt]
    cache = check_cache(norm) if use_cache else None
    for c in cands:
        stamps = file_stamps([norm / c.path, norm / c.anchor_path,
                              anchor_store.cut_path(anchors_dir, c.path)])
        tag = [c.anchor, c.anchor_path, c.anchor_language, c.method, method_hash(c), _model()]
        if cache is not None and cache.get(c.work_id, stamps, tag) == CURRENT:
            states.append(State(c, CURRENT))
            continue
        s = check_work(c, norm, anchors_dir)
        if cache is not None:
            if s.status == CURRENT:
                cache.put(c.work_id, stamps, CURRENT, tag)
            else:
                cache.forget(c.work_id)
        states.append(s)
    if cache is not None:
        cache.save()
    known = {c.path for c in cands}
    for path in _cut_paths(anchors_dir):
        if path not in known:
            states.append(State(None, ORPHAN, path))
    return states


def _cut_paths(anchors_dir: Path) -> list[str]:
    """Every cut file's normalized path (``anchor_store.iter_store`` without parsing them)."""
    if not anchors_dir.is_dir():
        return []
    return [p.relative_to(anchors_dir).as_posix() for p in sorted(anchors_dir.rglob("*.json"))
            if not p.name.startswith("_")]


def describe(s: State) -> str:
    where = s.candidate.work_id if s.candidate is not None else s.detail
    return f"{where}: {s.status}" + (f" ({s.detail})" if s.candidate and s.detail else "")


# ---------------------------------------------------------------------------
# Loading units and vectors
# ---------------------------------------------------------------------------


def wants_vector(text: str) -> bool:
    return len(text.strip()) >= emb.MIN_CHARS


def original_vectors(anchor_language: str) -> int:
    """The vectors an original in *anchor_language* is anchored on (#392): its
    English machine translation's (``KIND_TRANSLATION``) for a language
    ``scripts.translate`` translates (``translations.TRANSLATED_LANGUAGES``:
    Syriac, Coptic, Armenian, Ge'ez, Church Slavonic), whose own vectors
    match English badly, else its own text (``KIND_TEXT``). This
    is what ``scripts.align`` uses for such a member too."""
    return emb.KIND_TRANSLATION if anchor_language in tr.TRANSLATED_LANGUAGES else emb.KIND_TEXT


def method_hash(c: Candidate, params: anchoring.RefineParams = anchoring.RefineParams()) -> str:
    """The ``method`` a cut file of *c* records: ``anchoring.params_hash`` for an
    original anchored on its own text vectors, so the cut files made before
    #392 stay current; with the vector kind added for an original anchored on
    its machine translations (a different method: cut files made on such an
    original's text vectors are frozen until ``--recut``).

    Kept here, not in ``patristica.anchoring``, which is normalize's code: a
    change there would change normalize's code hash and rebuild the corpus."""
    if c.method == "text":
        from patristica.edition_projection import method_hash as projection_hash

        return projection_hash()
    if original_vectors(c.anchor_language) == emb.KIND_TEXT:
        return anchoring.params_hash(params)
    return fingerprint.value_hash({"version": anchoring.ANCHOR_VERSION, "params": asdict(params),
                                   "original_vectors": "translation"})


def load_original(c: Candidate, norm: Path, store_dir: Path, trans_dir: Path = TRANSLATIONS,
                  vectors: int | None = None) -> tuple[Units, int, set[str]]:
    """The original's units with their current vectors, the number of units
    that should have one but don't, and the vectors' models. A row of another
    model, size or input type counts as missing: it can't be compared with the
    vectors this step makes.

    An original in a translated language (:func:`original_vectors`, #392)
    gets its English machine translation's vector where it has a current one
    (the translation was made from the unit's current text, and the vector
    from that translation), else its text vector: such units are logged. Only
    a missing *text* vector counts as missing (``scripts.embed`` makes the
    translation vectors after ``scripts.translate``). *vectors* overrides the
    kind (``scripts.anchor_eval`` compares them)."""
    import numpy as np

    from patristica.anchor_refine import Units, normalize_rows

    chunks = _chunks(norm, c.anchor_path)
    shard = emb.load(store_dir, c.anchor_path)
    index = shard.by_key() if shard is not None else {}
    kind = vectors if vectors is not None else original_vectors(
        c.anchor_language or (chunks[0]["language"] if chunks else ""))
    rows: dict[str, tr.ChunkTranslation] = {}
    if kind == emb.KIND_TRANSLATION:
        trans = tr.load(trans_dir, c.anchor_path)
        rows = trans.by_chunk() if trans is not None else {}
    vecs = np.zeros((len(chunks), DIMS), dtype=np.float32)
    missing = 0
    fallback: list[str] = []
    models: set[str] = set()
    spec = run_spec()

    def current(k: int | None, sha: str) -> bool:
        return (k is not None and shard.rows[k].sha == sha
                and shard.runs[shard.rows[k].run].same_space(spec))

    for u, ch in enumerate(chunks):
        text = source_text(ch)
        sha = text_sha(text)
        k = index.get((ch["chunk_id"], emb.KIND_TEXT))
        if not current(k, sha):
            k = None
            if wants_vector(text):
                missing += 1
        if kind == emb.KIND_TRANSLATION and wants_vector(text):
            t = rows.get(ch["chunk_id"])
            kt = index.get((ch["chunk_id"], emb.KIND_TRANSLATION))
            if t is not None and t.source_sha256 == sha and current(kt, text_sha(t.text)):
                k = kt
            else:
                fallback.append(ch["canonical_ref"])
        if k is not None:
            vecs[u] = shard.vecs[k]
            models.add(shard.runs[shard.rows[k].run].model)
    if fallback:
        log.warning("%s: %d of %d units of the original %s have no current machine-translation "
                    "vector and are anchored on their text vector (e.g. %s): run "
                    "scripts.translate and scripts.embed for it", c.work_id, len(fallback),
                    len(chunks), c.anchor, ", ".join(fallback[:3]))
    return (Units(c.anchor, chunks[0]["language"] if chunks else "",
                  [ch["canonical_ref"] for ch in chunks], [ch["text"] for ch in chunks],
                  normalize_rows(vecs)), missing, models)


def load_translation(c: Candidate, norm: Path, store_dir: Path, cache: VectorCache) -> Units:
    """The translation's current (provisional) units; their stored text vectors
    seed *cache*. Its ``vecs`` are left empty: ``refine`` fills them."""
    import numpy as np

    from patristica.anchor_refine import Units

    chunks = _chunks(norm, c.path)
    shard = emb.load(store_dir, c.path)
    if shard is not None and shard.vecs is not None:
        for row, v in zip(shard.rows, shard.vecs):
            if row.kind == emb.KIND_TEXT:
                cache.seed(row.sha, v, shard.runs[row.run])
    return Units(c.work_id, c.language, [ch["canonical_ref"] for ch in chunks],
                 [ch["text"] for ch in chunks], np.zeros((len(chunks), DIMS), dtype=np.float32),
                 [spans_of(ch) for ch in chunks])


def run_spec() -> emb.EmbeddingRun:
    return emb.EmbeddingRun(model=_model(), dims=DIMS, input_type=INPUT_TYPE,
                            date=time.strftime("%Y-%m-%d"), script=__name__)


def make_cache(c: Candidate, scratch: Path | None,
               embed: Callable[[list[str]], object] | None,
               budget_tokens: int | None = None, offline: bool = False) -> VectorCache:
    from patristica.anchor_refine import VectorCache
    from patristica.versify import count_tokens

    return VectorCache(scratch, c.work_id, c.path, embed, run_spec(), count_tokens,
                       budget_tokens, offline)


# ---------------------------------------------------------------------------
# Writing the results
# ---------------------------------------------------------------------------


def write_vectors(c: Candidate, norm: Path, store_dir: Path, cache: VectorCache) -> int:
    """Put the final units' text vectors into the work's ``data/embeddings`` shard.

    Rows still valid are kept (translation vectors too: ``scripts.embed``
    checks them), every unit with a vector in *cache* gets it; returns the
    units still without a text vector (``scripts.embed`` sends them).
    """
    import numpy as np

    chunks = _chunks(norm, c.path)
    shard = emb.load(store_dir, c.path)
    index = shard.by_key() if shard is not None else {}
    rows: list[emb.Row] = []
    vecs: list[np.ndarray] = []
    runs: dict[str, emb.EmbeddingRun] = dict(shard.runs) if shard is not None else {}
    left = 0
    spec = run_spec()
    for ch in chunks:
        cid = ch["chunk_id"]
        text = source_text(ch)
        if wants_vector(text):
            sha = text_sha(text)
            k = index.get((cid, emb.KIND_TEXT))
            if (k is not None and shard.rows[k].sha == sha
                    and shard.runs[shard.rows[k].run].same_space(spec)):
                rows.append(shard.rows[k])
                vecs.append(shard.vecs[k])
            elif sha in cache.raw:
                run = cache.runs[sha]
                runs[run.key] = run
                rows.append(emb.Row(cid, emb.KIND_TEXT, sha, run.key))
                vecs.append(cache.raw[sha])
            else:
                left += 1
        k = index.get((cid, emb.KIND_TRANSLATION))
        if k is not None:
            rows.append(shard.rows[k])
            vecs.append(shard.vecs[k])
    work = emb.WorkEmbeddings(c.work_id, c.path, runs, rows,
                              np.stack(vecs).astype(np.float16) if vecs else None)
    emb.save(store_dir, work, shard)
    return left


def renormalize(c: Candidate, norm: Path, raw: Path, anchors_dir: Path) -> None:
    """Rebuild the work's normalized output with its new cut file."""
    from scripts import normalize as nz

    source = c.path.split("/", 1)[0]
    if not (raw / c.path).exists():
        raise AnchorError(f"{c.work_id}: no raw file {raw / c.path}: scripts.anchor re-normalizes "
                          "the works it cuts, so it needs their data/raw")
    with _quiet_normalize(nz):
        nz.normalize_all(raw / source, norm, anchors_dir=anchors_dir, only={c.path})


@contextlib.contextmanager
def _quiet_normalize(nz: object) -> Iterator[None]:
    """normalize's INFO lines and progress bar, for the one work just cut, are
    detail here: show them only at DEBUG. (normalize's own code is hashed, so
    its output is quieted from outside, #535.)"""
    from functools import partial

    from tqdm import tqdm

    logger = logging.getLogger(nz.__name__)
    level, bar = logger.level, nz.tqdm
    if logging.getLogger().getEffectiveLevel() > logging.DEBUG:
        logger.setLevel(logging.WARNING)
        nz.tqdm = partial(tqdm, disable=True)
    try:
        yield
    finally:
        logger.setLevel(level)
        nz.tqdm = bar


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass
class Plan:
    todo: list[State] = field(default_factory=list)
    frozen: list[State] = field(default_factory=list)
    failing: list[State] = field(default_factory=list)  # not fixable here (normalize, orphans)
    reported: list[State] = field(default_factory=list)  # e.g. a model change


def plan(norm: Path, anchors_dir: Path, recut: Collection[str] = (),
         prefixes: Collection[str] = ()) -> Plan:
    """What a run does: works to cut, frozen ones (``--recut`` adds them to the
    cut; ``all`` for every frozen one) and problems for normalize to fix."""
    out = Plan()
    for s in check_works(norm, anchors_dir):
        c = s.candidate
        if c is not None and prefixes and not any(c.work_id.startswith(p) for p in prefixes):
            continue
        named = c is not None and c.work_id in recut
        if (s.status in TO_CUT or (s.status in FROZEN and (named or "all" in recut))
                or (named and s.status in (CURRENT, MODEL_CHANGED))):
            out.todo.append(s)
        elif s.status in FROZEN:
            out.frozen.append(s)
        elif s.status in FAILING:
            out.failing.append(s)
        elif s.status != CURRENT:
            out.reported.append(s)
    order = {w: i for i, w in enumerate(anchoring.anchor_order(
        {s.candidate.work_id: s.candidate.anchor for s in out.todo if s.candidate}))}
    out.todo.sort(key=lambda s: order[s.candidate.work_id])
    return out


@dataclass
class Estimate:
    works: int = 0
    first_tokens: int = 0  # the first embed (segments, provisional units), exact
    rounds_tokens: int = 0  # the rounds, an upper bound
    refused: list[str] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return self.first_tokens + self.rounds_tokens

    @property
    def cost(self) -> float:
        return self.tokens / 1e6 * PRICE_PER_MTOK


def work_bound(cache: VectorCache, today: Units) -> tuple[int, int]:
    """(the first embed, exact; the rest, a cap) in cl100k tokens for one work.

    ``run`` enforces their sum as the work's budget, so the estimate is a real
    upper bound of what the step sends: a work that would need more stops
    (``NeedsVectors``) and its cut is rolled back.
    """
    from patristica.anchor_refine import first_texts
    from patristica.versify import count_tokens

    first = cache.estimate(first_texts(today, today.language))
    text = sum(count_tokens(t) for t in today.source_texts())
    return first, int(ROUNDS_FACTOR * text)


def estimate(p: Plan, norm: Path = NORMALIZED, store_dir: Path = EMBEDDINGS,
             scratch: Path | None = SCRATCH, verbose: bool = False) -> Estimate:
    """What cutting *p*'s works would send at most (no requests). A work whose
    original lacks vectors is counted when that original is cut earlier in the
    same run (it gets its vectors then), else listed as refused."""
    est = Estimate()
    earlier: set[str] = set()
    for s in p.todo:
        c = s.candidate
        if c.method == "text":  # projected through the texts: no requests
            est.works += 1
            earlier.add(c.work_id)
            continue
        _, missing, _ = load_original(c, norm, store_dir)
        if missing and c.anchor not in earlier:
            est.refused.append(f"{c.work_id} (original {c.anchor}: {missing} units without "
                               "a current vector)")
            continue
        earlier.add(c.work_id)
        cache = make_cache(c, scratch, None)
        today = load_translation(c, norm, store_dir, cache)
        first, rounds = work_bound(cache, today)
        est.works += 1
        est.first_tokens += first
        est.rounds_tokens += rounds
        if verbose:
            log.debug("%s (%s): first embed ~%s tokens, rounds and final units ≤ ~%s",
                     c.work_id, s.status, f"{first:,}", f"{rounds:,}")
    return est


def pending(norm: Path = NORMALIZED, anchors_dir: Path = ANCHORS,
            store_dir: Path = EMBEDDINGS, scratch: Path | None = SCRATCH) -> tuple[int, float]:
    """(works a plain run would cut, its estimated dollars, an upper bound):
    what ``scripts.pipeline`` gates on ``--pay``."""
    p = plan(norm, anchors_dir)
    if not p.todo:
        return 0, 0.0
    est = estimate(p, norm, store_dir, scratch)
    return len(p.todo), est.cost


def run(norm: Path = NORMALIZED, raw: Path = RAW, anchors_dir: Path = ANCHORS,
        store_dir: Path = EMBEDDINGS, scratch: Path | None = SCRATCH, *,
        embed: Callable[[list[str]], object] | None = None,
        budget_tokens: int | None = None, recut: Collection[str] = (),
        prefixes: Collection[str] = (),
        params: anchoring.RefineParams = anchoring.RefineParams(),
        trans_dir: Path = TRANSLATIONS) -> dict[str, list[str]]:
    """Cut what :func:`plan` lists; ``{"cut", "refused", "frozen", "failing"}``.

    *embed* sends texts to Voyage (None: a work that needs vectors raises
    ``NeedsVectors``). Each work may send at most its :func:`work_bound`, and
    all of them at most *budget_tokens*. A work is complete only once its cut
    file, normalized output and final vectors are all written: a failure after
    the cut file is saved (the final embed, the re-normalize) restores the
    previous cut file and output and re-raises, so a plain re-run resumes it.
    Raises ``AnchorError`` when normalize isn't current.
    """
    from tqdm import tqdm

    from patristica.anchor_refine import refine
    from scripts import normalize as nz

    if nz.read_step_fingerprints(norm).get(nz.STEP, {}).get("code") != nz.normalize_code_hash():
        raise AnchorError("normalize's code changed since data/normalized was built: run "
                          "scripts.normalize first")
    p = plan(norm, anchors_dir, recut, prefixes)
    done: dict[str, list[str]] = {"cut": [], "refused": [],
                                  "frozen": [describe(s) for s in p.frozen],
                                  "failing": [describe(s) for s in p.failing]}
    sent = 0
    bar = tqdm(p.todo, desc="anchor", unit="work", disable=not p.todo)
    for s in bar:
        c = s.candidate
        bar.set_postfix_str(f"{sent:,} tokens sent")
        if c.method == "text":
            cut_by_text(c, norm, raw, anchors_dir)
            done["cut"].append(c.work_id)
            continue
        orig, missing, models = load_original(c, norm, store_dir, trans_dir)
        if missing:
            log.error("%s: refused: its original %s has %d units without a current text "
                      "vector: run scripts.embed --work %s first", c.work_id, c.anchor, missing,
                      c.anchor)
            done["refused"].append(c.work_id)
            continue
        cache = make_cache(c, scratch, embed)
        today = load_translation(c, norm, store_dir, cache)
        first, rest = work_bound(cache, today)
        cache.budget_tokens = first + rest
        if budget_tokens is not None:
            cache.budget_tokens = min(cache.budget_tokens, budget_tokens - sent)
        started = time.monotonic()
        try:
            result = refine(orig, today, cache, params)
        finally:
            sent += cache.sent_tokens
        seconds = time.monotonic() - started
        stats = result.stats(len(orig.texts))  # no timings: the file must be repeatable
        paras = anchoring.paragraphs(_chunks(norm, c.path))
        before_1to1 = one_one_share(orig, _cache_vecs(today.source_texts(), cache))
        after_1to1 = one_one_share(orig, _cache_vecs(result.embed_texts(), cache))
        keep = after_1to1 <= before_1to1  # the anchored cut must win
        stats = {**stats, **decision(before_1to1, after_1to1, keep)}
        starts = [pp.starts for pp in paras] if keep else result.starts()
        cut = anchor_store.CutFile(
            work_id=c.work_id, anchor=c.anchor, method=method_hash(c, params),
            anchor_cuts=anchoring.chunks_cuts_hash(_chunks(norm, c.anchor_path)),
            words=paragraph_words(paras),
            model=sorted(models)[0] if len(models) == 1 else ",".join(sorted(models)),
            paragraphs={pp.ref: anchor_store.ParagraphCut(pp.words_hash, tuple(st))
                        for pp, st in zip(paras, starts)},
            stats=stats)
        if [pp.ref for pp in paras] != [rp.ref for rp in result.paras]:
            raise AnchorError(f"{c.work_id}: paragraphs differ between the refinement and "
                              "the cut file (a bug)")
        previous = anchor_store.load(anchors_dir, c.path)
        before = cache.sent_tokens
        anchor_store.save(anchors_dir, c.path, cut)
        try:
            renormalize(c, norm, raw, anchors_dir)
            # Final units whose exact text the refinement didn't embed
            # (whitespace at an old cut): embed them now, then store all.
            final = [source_text(ch) for ch in _chunks(norm, c.path)]
            cache.ensure([t for t in final if wants_vector(t)])
            left_units = write_vectors(c, norm, store_dir, cache)
        except BaseException:
            sent += cache.sent_tokens - before
            log.error("%s: not completed; restoring its previous cut file and output", c.work_id)
            restore(c, previous, norm, raw, anchors_dir)
            raise
        sent += cache.sent_tokens - before
        log.debug("%s: cut on %s in %.0f s (%s); ~%s tokens sent; %d units left for "
                  "scripts.embed", c.work_id, c.anchor, seconds, json.dumps(stats),
                 f"{cache.sent_tokens:,}", left_units)
        done["cut"].append(c.work_id)
    return done


def one_one_share(orig: Units, vecs: object) -> float:
    """Share of *orig*'s units in a confident 1:1 bead with a cut whose unit
    vectors are *vecs*: the measure that decides whether a cut wins (#638)."""
    from patristica.alignment import Version, align_pair

    beads = align_pair(Version("original", orig.vecs), Version("cut", vecs))
    one = sum(1 for b in beads if b.i1 - b.i0 == 1 and b.j1 - b.j0 == 1 and b.conf >= 0.5)
    return one / max(len(orig.texts), 1)


def _cache_vecs(texts: list[str], cache: VectorCache) -> object:
    """Normalized vectors of *texts* from *cache* (zero rows where there is none)."""
    import numpy as np

    from patristica.anchor_refine import normalize_rows

    vecs = np.zeros((len(texts), DIMS), dtype=np.float32)
    for u, t in enumerate(texts):
        v = cache.get(t) if wants_vector(t) else None
        if v is not None:
            vecs[u] = v
    return normalize_rows(vecs)


def text_one_one(anchor_units: list[str], units: list[str]) -> float:
    """Share of the anchor edition's units, of those the edition shares, in a
    confident 1:1 bead of #199's text alignment (``scripts.edition_eval``'s
    measure): whether a projected cut wins (#638)."""
    from patristica.text_alignment import align_texts

    r = align_texts(anchor_units, units)
    one = sum(1 for t in r.beads if t.i1 - t.i0 == 1 and t.j1 - t.j0 == 1 and t.conf >= 0.5)
    return one / max(sum(t.i1 - t.i0 for t in r.beads if t.conf >= 0.5), 1)


def decision(before: float, after: float, keep: bool) -> dict[str, object]:
    """What a cut file records of the decision to cut (#638): the 1:1 share of
    the provisional cut and of the anchored one, and ``kept: "provisional"``
    when the anchored cut didn't win and the work keeps its provisional cut."""
    out: dict[str, object] = {"one_one_provisional": round(before, 4),
                              "one_one_anchored": round(after, 4)}
    if keep:
        out["kept"] = "provisional"
    return out


def cut_by_text(c: Candidate, norm: Path, raw: Path, anchors_dir: Path) -> None:
    """Cut an edition where its anchor (another edition, same language) cuts
    (``patristica.edition_projection``, #200), write its cut file and
    re-normalize it. No vectors: its new units are embedded by
    ``scripts.embed``, like any re-normalized work. All or nothing, as in
    :func:`run`."""
    from patristica.edition_projection import project

    paras = anchoring.paragraphs(_chunks(norm, c.path))
    anchor_chunks = _chunks(norm, c.anchor_path)
    anchor_paras = anchoring.paragraphs(anchor_chunks)
    proj = project(anchor_paras, paras)
    starts = [st if st else p.starts for p, st in zip(paras, proj.starts)]
    anchor_units = [u for p in anchor_paras for u in p.units]
    before = text_one_one(anchor_units, [u for p in paras for u in p.units])
    after = text_one_one(anchor_units, [u for p, st in zip(paras, starts)
                                        for u in anchoring.cut_at(" ".join(p.units), st)])
    keep = after <= before  # the projected cut must win
    if keep:
        starts = [p.starts for p in paras]
    cut = anchor_store.CutFile(
        work_id=c.work_id, anchor=c.anchor, method=method_hash(c),
        anchor_cuts=anchoring.chunks_cuts_hash(anchor_chunks),
        words=paragraph_words(paras), model="",
        paragraphs={p.ref: anchor_store.ParagraphCut(p.words_hash, tuple(st))
                    for p, st in zip(paras, starts)},
        stats={**proj.stats, **decision(before, after, keep)})
    previous = anchor_store.load(anchors_dir, c.path)
    anchor_store.save(anchors_dir, c.path, cut)
    try:
        renormalize(c, norm, raw, anchors_dir)
    except BaseException:
        log.error("%s: not completed; restoring its previous cut file and output", c.work_id)
        restore(c, previous, norm, raw, anchors_dir)
        raise
    log.debug("%s: projected from %s (%s)", c.work_id, c.anchor, json.dumps(proj.stats))


def keep_current(c: Candidate, norm: Path, raw: Path, anchors_dir: Path, reason: str) -> None:
    """Record that *c* keeps its current cut: a cut file whose cuts are the
    ones it has now, with ``stats.kept`` (#638). No vectors and no requests;
    the work is re-normalized only so its fingerprint records the cut file
    (its units don't change)."""
    paras = anchoring.paragraphs(_chunks(norm, c.path))
    cut = anchor_store.CutFile(
        work_id=c.work_id, anchor=c.anchor, method=method_hash(c),
        anchor_cuts=anchoring.chunks_cuts_hash(_chunks(norm, c.anchor_path)),
        words=paragraph_words(paras), model="",
        paragraphs={p.ref: anchor_store.ParagraphCut(p.words_hash, p.starts) for p in paras},
        stats={"kept": "provisional", "reason": reason})
    before = _chunks(norm, c.path)
    anchor_store.save(anchors_dir, c.path, cut)
    renormalize(c, norm, raw, anchors_dir)
    if _chunks(norm, c.path) != before:
        raise AnchorError(f"{c.work_id}: keeping its cut changed its units (a bug)")


def restore(c: Candidate, previous: anchor_store.CutFile | None, norm: Path, raw: Path,
            anchors_dir: Path) -> None:
    """Put back the cut file a failed run replaced (none: remove the new one) and
    re-normalize the work with it, so the work is stale again, not half done."""
    if previous is None:
        anchor_store.cut_path(anchors_dir, c.path).unlink(missing_ok=True)
    else:
        anchor_store.save(anchors_dir, c.path, previous)
    try:
        renormalize(c, norm, raw, anchors_dir)
    except Exception:
        log.exception("%s: could not re-normalize after restoring its cut file: run "
                      "scripts.normalize", c.work_id)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--normalized-dir", type=Path, default=NORMALIZED)
    p.add_argument("--raw-dir", type=Path, default=RAW)
    p.add_argument("--anchors-dir", type=Path, default=ANCHORS)
    p.add_argument("--embeddings-dir", type=Path, default=EMBEDDINGS)
    p.add_argument("--scratch-dir", type=Path, default=SCRATCH)
    p.add_argument("--translations-dir", type=Path, default=TRANSLATIONS,
                   help="machine translations of rare-language originals (#392)")
    p.add_argument("--work", action="append", default=[], metavar="PREFIX",
                   help="only works whose id starts with PREFIX (repeatable)")
    p.add_argument("--recut", action="append", default=[], metavar="WORK_ID",
                   help="re-cut this frozen (or current) work; 'all' for every frozen one")
    p.add_argument("--keep", action="append", default=[], metavar="WORK_ID",
                   help="record that this work keeps its current cut (a cut file with "
                        "stats.kept; no requests); repeatable")
    p.add_argument("--keep-reason", default="owner",
                   help="--keep: why, recorded in the cut file")
    p.add_argument("--dry-run", action="store_true", help="report the works and the cost only")
    p.add_argument("--pay", action="store_true", help="send Voyage requests (paid)")
    p.add_argument("--max-cost", type=float, metavar="USD",
                   help="stop before sending more than this (estimated)")
    p.add_argument("--check", action="store_true",
                   help="list stale or missing cut files; exit 1 if any fails (no vectors)")
    args = p.parse_args()
    console.setup_logging()

    if args.check:
        bad = 0
        for s in check_works(args.normalized_dir, args.anchors_dir):
            if s.status != CURRENT:
                print(describe(s))
                bad += s.status in FAILING
        sys.exit(1 if bad else 0)

    if args.keep:
        by_id = {c.work_id: c for c in candidates(args.normalized_dir, args.anchors_dir)[0]}
        unknown = sorted(set(args.keep) - set(by_id))
        if unknown:
            sys.exit(f"--keep: not works the rule anchors: {', '.join(unknown)}")
        for work_id in args.keep:
            keep_current(by_id[work_id], args.normalized_dir, args.raw_dir, args.anchors_dir,
                         args.keep_reason)
        log.info("recorded %d works keeping their current cut", len(args.keep))
        return

    pl = plan(args.normalized_dir, args.anchors_dir, args.recut, args.work)
    for s in pl.frozen:
        log.warning("frozen (re-cut only with --recut %s): %s", s.candidate.work_id, describe(s))
    for s in pl.reported:
        log.warning("%s", describe(s))
    for s in pl.failing:
        log.error("%s: not fixed by this step (scripts.normalize, or remove an orphan "
                  "cut file)", describe(s))
    if args.dry_run:
        est = estimate(pl, args.normalized_dir, args.embeddings_dir, args.scratch_dir,
                       verbose=True)
        for r in est.refused:
            log.error("would refuse %s: run scripts.embed for the original first", r)
        print(f"{len(pl.todo)} works to cut ({est.works} with vectors for their original): "
              f"first embed ~{est.first_tokens:,} tokens, rounds ≤ ~{est.rounds_tokens:,}; "
              f"≤ ~${est.cost:,.2f} at list price"
              + ("" if args.pay else "; nothing is sent without --pay"))
        return
    if not pl.todo:
        log.info("nothing to cut")
        sys.exit(1 if pl.failing else 0)

    from patristica.anchor_refine import NeedsVectors

    embedder = None
    embed = None
    if args.pay:
        from patristica.embedders import VoyageEmbedder

        embedder = VoyageEmbedder(MODEL, DIMS)
        embed = embedder.embed_documents
    budget = None if args.max_cost is None else int(args.max_cost / PRICE_PER_MTOK * 1e6)
    try:
        done = run(args.normalized_dir, args.raw_dir, args.anchors_dir, args.embeddings_dir,
                   args.scratch_dir, embed=embed, budget_tokens=budget, recut=args.recut,
                   prefixes=args.work, trans_dir=args.translations_dir)
    except NeedsVectors as exc:
        log.error("%s", exc)
        sys.exit(1)
    except AnchorError as exc:
        log.error("%s", exc)
        sys.exit(1)
    finally:
        if embedder is not None:
            log.debug("Voyage tokens billed: %s", f"{embedder.tokens_used:,}")
    billed = embedder.tokens_used if embedder is not None else 0
    log.info("cut %d works, refused %d; Voyage tokens billed: %s (~$%.2f)", len(done["cut"]),
             len(done["refused"]), f"{billed:,}", billed / 1e6 * PRICE_PER_MTOK)
    if done["refused"] or done["failing"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
