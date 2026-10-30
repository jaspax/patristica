"""The anchor step (#304) end to end on a small synthetic corpus, with a fake
embedder: no API calls.

The fake embedder knows a "concept" per word: ``lat17`` and ``eng17`` mean the
same, so a text's vector is the normalized sum of its concepts' random
vectors, and a translation's sentence has the vector of the Latin it renders.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from patristica import anchor_refine, anchor_store, anchoring  # noqa: E402
from patristica import embeddings as emb  # noqa: E402
from patristica import translations as tr  # noqa: E402
from patristica.alignment import Bead  # noqa: E402
from scripts import anchor  # noqa: E402
from scripts import normalize as nz  # noqa: E402

DIMS = anchor.DIMS


def concept_vec(c: int) -> np.ndarray:
    return np.random.default_rng(c).standard_normal(DIMS)


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        out = []
        for t in texts:
            v = np.zeros(DIMS)
            for c in re.findall(r"(?:lat|eng)(\d+)", t):
                v += concept_vec(int(c))
            if not v.any():
                v = concept_vec(10_000 + len(t))
            out.append(v / np.linalg.norm(v))
        return np.array(out, dtype=np.float32)

    @property
    def sent(self) -> int:
        return sum(len(c) for c in self.calls)


# The original's sentences, each a list of concepts. Sentence ends where the
# Latin has them; the English joins two of them into one sentence (with a
# semicolon) and splits another one in two, so its provisional cut by size can't
# match the original's units.
SENTENCES = [list(range(i * 7, i * 7 + 7)) for i in range(16)]


def latin(sents: list[list[int]]) -> str:
    return " ".join(" ".join(f"lat{c}" for c in s) + "." for s in sents)


def english(sents: list[list[int]]) -> str:
    out = []
    for i, s in enumerate(sents):
        words = [f"eng{c}" for c in s]
        if i % 5 == 1:
            out.append(" ".join(words[:3]) + ". " + " ".join(words[3:]) + ".")
        elif i % 5 == 3:
            out.append(" ".join(words) + ";")
        else:
            out.append(" ".join(words) + ".")
    return " ".join(out)


#: An editor's heading at the start of the English, marked as editorial (#236).
HEADING = "Edhead the editor's heading."


def write_work(raw: Path, rel: str, language: str, paragraphs: list[str],
               translation_of: str | None = None, license: str = "public_domain",
               heading: bool = False) -> None:
    source_id, name = rel.split("/")[0], Path(rel).stem
    work = {"work_id": f"{source_id}/{name}", "source_id": source_id, "title": "T",
            "genre": "patristic", "language": language, "license": license}
    if translation_of:
        work["translation_of"] = translation_of
    units = [{"ref": f"P.{i}", "text": t} for i, t in enumerate(paragraphs, 1)]
    if heading:
        units[0] = {"ref": "P.1", "text": HEADING + " " + paragraphs[0],
                    "editorial": [[0, len(HEADING), "heading"]]}
    path = raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"work": work, "paragraphs": units}), encoding="utf-8")


def embed_work(norm: Path, store: Path, rel: str, fake: FakeEmbedder) -> None:
    chunks = json.loads((norm / rel).read_text(encoding="utf-8"))
    run = anchor.run_spec()
    keep = [c for c in chunks if anchor.wants_vector(c["text"])]
    vecs = fake([c["text"] for c in keep])
    emb.save(store, emb.WorkEmbeddings(
        chunks[0]["work_id"], rel, {run.key: run},
        [emb.Row(c["chunk_id"], emb.KIND_TEXT, anchor.text_sha(c["text"]), run.key)
         for c in keep], vecs.astype(np.float16)))


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setattr(anchoring, "enrolled_sources", lambda: {"tr": "test"})
    d = {k: tmp_path / k for k in ("raw", "normalized", "anchors", "embeddings", "scratch")}
    write_work(d["raw"], "orig/w.json", "lat",
               [latin(SENTENCES[:8]), latin(SENTENCES[8:])])
    write_work(d["raw"], "tr/w.json", "eng",
               [english(SENTENCES[:8]), english(SENTENCES[8:])], translation_of="orig/w")
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"])
    return d


def run(d: dict[str, Path], fake: FakeEmbedder | None, **kw) -> dict[str, list[str]]:
    return anchor.run(d["normalized"], d["raw"], d["anchors"], d["embeddings"], d["scratch"],
                      embed=fake, **kw)


def units(d: dict[str, Path], rel: str) -> list[dict]:
    return json.loads((d["normalized"] / rel).read_text(encoding="utf-8"))


def concepts(text: str) -> tuple[int, ...]:
    return tuple(int(c) for c in re.findall(r"(?:lat|eng)(\d+)", text))


def test_the_original_needs_current_vectors(corpus) -> None:
    states = {s.candidate.work_id: s.status for s in anchor.check_works(
        corpus["normalized"], corpus["anchors"])}
    assert states == {"tr/w": anchor.MISSING}
    done = run(corpus, FakeEmbedder())
    assert done["refused"] == ["tr/w"] and done["cut"] == []
    assert not (corpus["anchors"] / "tr/w.json").exists()


def test_without_an_embedder_nothing_is_sent(corpus) -> None:
    embed_work(corpus["normalized"], corpus["embeddings"], "orig/w.json", FakeEmbedder())
    p = anchor.plan(corpus["normalized"], corpus["anchors"])
    est = anchor.estimate(p, corpus["normalized"], corpus["embeddings"], corpus["scratch"])
    assert est.works == 1 and est.first_tokens > 0 and est.rounds_tokens > 0
    with pytest.raises(anchor_refine.NeedsVectors):
        run(corpus, None)


def test_anchor_cuts_the_translation_on_the_original(corpus) -> None:
    d = corpus
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    fake = FakeEmbedder()
    done = run(d, fake)
    assert done["cut"] == ["tr/w"]
    cut = anchor_store.load(d["anchors"], "tr/w.json")
    assert cut is not None and cut.anchor == "orig/w"
    assert cut.method == anchoring.params_hash()
    # Each original unit has a translation unit with exactly its concepts.
    orig = {concepts(c["text"]) for c in units(d, "orig/w.json")}
    trans = [concepts(c["text"]) for c in units(d, "tr/w.json")]
    assert sum(t in orig for t in trans) >= len(orig) - 1
    # The step re-normalized the work, and normalize agrees.
    assert nz.read_work_fingerprints(d["normalized"])["tr/w.json"]["anchor"] == {
        "cuts": cut.sha}
    before = (d["normalized"] / "tr/w.json").read_bytes()
    assert nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"]) == 0
    assert (d["normalized"] / "tr/w.json").read_bytes() == before
    # Every final unit has its production vector: embed has nothing to send.
    shard = emb.load(d["embeddings"], "tr/w.json")
    have = {r.chunk_id for r in shard.rows if r.kind == emb.KIND_TEXT}
    assert have == {c["chunk_id"] for c in units(d, "tr/w.json")}
    assert all(shard.runs[r.run].script == "scripts.anchor" for r in shard.rows)
    # Current now; a second run sends nothing and changes nothing.
    assert [s.status for s in anchor.check_works(d["normalized"], d["anchors"])] == [
        anchor.CURRENT]
    again = FakeEmbedder()
    assert run(d, again)["cut"] == []
    assert again.calls == []
    # The scratch store makes a re-cut free and gives the same cut.
    sent = fake.sent
    assert run(d, again, recut=["tr/w"])["cut"] == ["tr/w"]
    assert again.sent < sent / 4
    assert anchor_store.load(d["anchors"], "tr/w.json").paragraphs == cut.paragraphs


def test_a_changed_original_freezes_the_cut_until_recut(corpus) -> None:
    d = corpus
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    run(d, FakeEmbedder())
    write_work(d["raw"], "orig/w.json", "lat",
               [latin(SENTENCES[:9]), latin(SENTENCES[9:])])
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"],
                     accept_raw_change=True)
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.ANCHOR_CUTS
    p = anchor.plan(d["normalized"], d["anchors"])
    assert p.todo == [] and [s.status for s in p.frozen] == [anchor.ANCHOR_CUTS]
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    assert run(d, FakeEmbedder())["cut"] == []
    assert run(d, FakeEmbedder(), recut=["all"])["cut"] == ["tr/w"]
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.CURRENT


def test_changed_words_and_stale_output_fail(corpus) -> None:
    d = corpus
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    run(d, FakeEmbedder())
    cut = anchor_store.load(d["anchors"], "tr/w.json")
    # A cut file normalize hasn't applied yet.
    ref = next(iter(cut.paragraphs))
    rec = cut.paragraphs[ref]
    moved = (0, *(s + 1 for s in rec.starts[1:])) if len(rec.starts) > 1 else rec.starts
    cut.paragraphs[ref] = anchor_store.ParagraphCut(rec.words, moved)
    anchor_store.save(d["anchors"], "tr/w.json", cut)
    if moved != rec.starts:
        [state] = anchor.check_works(d["normalized"], d["anchors"])
        assert state.status == anchor.OUTPUT
    # The translation's text changed: re-cut by a plain run.
    write_work(d["raw"], "tr/w.json", "eng",
               [english(SENTENCES[:8]) + " eng999.", english(SENTENCES[8:])],
               translation_of="orig/w")
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"],
                     accept_raw_change=True)
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.WORDS
    assert run(d, FakeEmbedder())["cut"] == ["tr/w"]


def test_orphan_cut_files_are_reported(corpus) -> None:
    anchor_store.save(corpus["anchors"], "tr/gone.json", anchor_store.CutFile(
        "tr/gone", "orig/w", "m", "c", "w", "", {}))
    states = anchor.check_works(corpus["normalized"], corpus["anchors"])
    assert {s.status for s in states} == {anchor.MISSING, anchor.ORPHAN}


# ---------------------------------------------------------------- the DP


def test_refine_matches_original_units_on_a_close_translation() -> None:
    fake = FakeEmbedder()
    lat = [latin(SENTENCES[i:i + 2]) for i in range(0, 16, 2)]
    eng_par = english(SENTENCES)
    orig_vecs = fake(lat)
    orig = anchor_refine.Units("o", "lat", [f"P.1.s{i}" for i in range(1, 9)], lat, orig_vecs)
    today_texts = anchoring.cut_at(eng_par, list(range(0, len(anchoring.words(eng_par)), 30)))
    today = anchor_refine.Units("t", "eng", [f"P.1.s{i}" for i in range(1, len(today_texts) + 1)],
                                today_texts, np.zeros((len(today_texts), DIMS), np.float32))
    cache = anchor_refine.VectorCache(None, "t", "t.json", fake, anchor.run_spec(),
                                      lambda t: len(t.split()))
    result = anchor_refine.refine(orig, today, cache)
    got = [concepts(t) for t in result.texts()]
    want = [concepts(t) for t in lat]
    assert got == want
    assert result.history[-1]["new_units"] == 0


# ------------------------------------------------------- review fixes (#319)


def other_model_run() -> emb.EmbeddingRun:
    return anchor.run_spec().model_copy(update={"model": "voyage/voyage-3"})


def test_unpublishable_works_and_originals_are_not_anchored(corpus) -> None:
    d = corpus
    write_work(d["raw"], "tr/w.json", "eng", [english(SENTENCES[:8]), english(SENTENCES[8:])],
               translation_of="orig/w", license="unknown")
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"], accept_raw_change=True)
    assert anchor.check_works(d["normalized"], d["anchors"]) == []
    write_work(d["raw"], "tr/w.json", "eng", [english(SENTENCES[:8]), english(SENTENCES[8:])],
               translation_of="orig/w")
    write_work(d["raw"], "orig/w.json", "lat", [latin(SENTENCES[:8]), latin(SENTENCES[8:])],
               license="unknown")
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"], accept_raw_change=True)
    assert anchor.check_works(d["normalized"], d["anchors"]) == []


def test_original_vectors_of_another_model_count_as_missing(corpus) -> None:
    d = corpus
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    shard = emb.load(d["embeddings"], "orig/w.json")
    old = other_model_run()
    shard.runs = {old.key: old}
    shard.rows = [emb.Row(r.chunk_id, r.kind, r.sha, old.key) for r in shard.rows]
    emb.save(d["embeddings"], shard)
    assert run(d, FakeEmbedder())["refused"] == ["tr/w"]


def test_translation_rows_of_another_model_are_replaced(corpus) -> None:
    d = corpus
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    embed_work(d["normalized"], d["embeddings"], "tr/w.json", FakeEmbedder())
    shard = emb.load(d["embeddings"], "tr/w.json")
    old = other_model_run()
    shard.runs = {old.key: old}
    shard.rows = [emb.Row(r.chunk_id, r.kind, r.sha, old.key) for r in shard.rows]
    emb.save(d["embeddings"], shard)
    assert run(d, FakeEmbedder())["cut"] == ["tr/w"]
    shard = emb.load(d["embeddings"], "tr/w.json")
    assert all(shard.runs[r.run].same_space(anchor.run_spec()) for r in shard.rows)
    assert len(shard.rows) == len(units(d, "tr/w.json"))


def test_editorial_material_is_never_embedded(corpus) -> None:
    d = corpus
    write_work(d["raw"], "tr/w.json", "eng", [english(SENTENCES[:8]), english(SENTENCES[8:])],
               translation_of="orig/w", heading=True)
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"], accept_raw_change=True)
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    fake = FakeEmbedder()
    assert run(d, fake)["cut"] == ["tr/w"]
    sent = [t for call in fake.calls for t in call]
    assert sent and not any("Edhead" in t or "heading." in t for t in sent)
    first = units(d, "tr/w.json")[0]
    assert first["text"].startswith("Edhead") and first.get("editorial")
    shard = emb.load(d["embeddings"], "tr/w.json")
    assert {r.chunk_id for r in shard.rows} == {
        c["chunk_id"] for c in units(d, "tr/w.json") if anchor.wants_vector(
            anchor.source_text(c))}


def test_a_failure_after_the_cut_is_saved_rolls_it_back(corpus, monkeypatch) -> None:
    d = corpus
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    before = (d["normalized"] / "tr/w.json").read_bytes()

    def boom(*args, **kw):
        raise RuntimeError("the final embed failed")

    monkeypatch.setattr(anchor, "write_vectors", boom)
    with pytest.raises(RuntimeError):
        run(d, FakeEmbedder())
    assert not (d["anchors"] / "tr/w.json").exists()
    assert (d["normalized"] / "tr/w.json").read_bytes() == before
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.MISSING
    monkeypatch.undo()
    monkeypatch.setattr(anchoring, "enrolled_sources", lambda: {"tr": "test"})
    fake = FakeEmbedder()
    assert run(d, fake)["cut"] == ["tr/w"]
    assert fake.calls == []  # resumed from the scratch store


def test_each_work_is_capped_at_its_estimate(corpus, monkeypatch) -> None:
    d = corpus
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    p = anchor.plan(d["normalized"], d["anchors"])
    est = anchor.estimate(p, d["normalized"], d["embeddings"], d["scratch"])
    fake = FakeEmbedder()
    run(d, fake)
    from patristica.versify import count_tokens
    assert sum(count_tokens(t) for c in fake.calls for t in c) <= est.tokens
    # A work that would send more than its bound stops, uncut.
    monkeypatch.setattr(anchor, "work_bound", lambda cache, today: (10, 0))
    d2 = {**d, "scratch": d["scratch"].parent / "scratch2"}
    (d["embeddings"] / "tr" / "w.npz").unlink()  # nothing cached: it must embed
    cut = (d["anchors"] / "tr" / "w.json").read_bytes()
    with pytest.raises(anchor_refine.NeedsVectors):
        run(d2, FakeEmbedder(), recut=["tr/w"])
    assert (d["anchors"] / "tr" / "w.json").read_bytes() == cut


def test_cut_files_hold_no_timings(corpus) -> None:
    embed_work(corpus["normalized"], corpus["embeddings"], "orig/w.json", FakeEmbedder())
    run(corpus, FakeEmbedder())
    cut = anchor_store.load(corpus["anchors"], "tr/w.json")
    assert "seconds" not in cut.stats


# --------------------------------------------- partial translations (#394)


def bead(i: int, j: int, conf: float = 0.9) -> Bead:
    return Bead(i, i + 1, j, j + 1, 0.8, 0.3, conf)


def test_a_whole_translation_covers_the_whole_original() -> None:
    beads = [bead(i, i + 2) for i in range(95)]  # units 2–96 of 100
    assert anchor_refine.covered_span(beads, 100, 100, 6) == (0, 100)
    assert anchor_refine.covered_span([], 100, 100, 6) == (0, 100)


def test_a_partial_translation_covers_a_span() -> None:
    # Units 300–379 of 1000 render the translation's 80 units.
    beads = [bead(i, 300 + i) for i in range(80)]
    assert anchor_refine.covered_span(beads, 1000, 80, 6) == (294, 386)
    # A stray match at the end (a similar passage far on) is set aside.
    stray = [*beads, bead(80, 700), bead(81, 900)]
    assert anchor_refine.covered_span(stray, 1000, 82, 6) == (294, 386)
    # Only an uncovered end is cut off: a translation of the beginning.
    head = [bead(i, i) for i in range(80)]
    assert anchor_refine.covered_span(head, 1000, 80, 6) == (0, 86)


def test_a_thin_alignment_leaves_the_whole_original() -> None:
    # Weak vectors: a tenth of the translation's units in the confident chain.
    beads = [bead(i * 10, 300 + i) for i in range(8)]
    assert anchor_refine.covered_span(beads, 1000, 80, 6) == (0, 1000)
    # Too few beads, even if they are the whole translation.
    assert anchor_refine.covered_span([bead(0, 500), bead(1, 501)], 1000, 2, 6) == (0, 1000)
    # Unconfident beads don't count.
    weak = [bead(i, 300 + i, conf=0.3) for i in range(80)]
    assert anchor_refine.covered_span(weak, 1000, 80, 6) == (0, 1000)


def partial_pair(untranslated: int) -> tuple:
    """An original of 8 units the translation renders, then *untranslated*
    units it doesn't; the translation's provisional cut is every 30 words."""
    fake = FakeEmbedder()
    lat = [latin(SENTENCES[i:i + 2]) for i in range(0, 16, 2)]
    lat += [latin([list(range(500 + 7 * k, 507 + 7 * k))]) for k in range(untranslated)]
    orig = anchor_refine.Units("o", "lat", [f"P.1.s{i}" for i in range(1, len(lat) + 1)], lat,
                               fake(lat))
    eng_par = english(SENTENCES)
    today_texts = anchoring.cut_at(eng_par, list(range(0, len(anchoring.words(eng_par)), 30)))
    today = anchor_refine.Units("t", "eng", [f"P.1.s{i}" for i in range(1, len(today_texts) + 1)],
                                today_texts, np.zeros((len(today_texts), DIMS), np.float32))
    cache = anchor_refine.VectorCache(None, "t", "t.json", fake, anchor.run_spec(),
                                      lambda t: len(t.split()))
    return orig, today, cache, lat


def test_refine_restricts_a_partial_translation_to_its_span() -> None:
    orig, today, cache, lat = partial_pair(40)
    result = anchor_refine.refine(orig, today, cache)
    band = anchoring.RefineParams().band
    assert result.span == (0, 8 + band)
    assert all(k1 <= 8 for k0, k1, _, _ in result.beads)
    assert [concepts(t) for t in result.texts()] == [concepts(t) for t in lat[:8]]
    stats = result.stats(len(lat))
    assert stats["span"] == [0, 8 + band]
    assert stats["one_one"] == round(8 / (8 + band), 4)  # of the span, not of all 48 units


def test_refine_of_a_whole_translation_is_unchanged() -> None:
    """No span, and the stats keep their keys: cut files of whole translations
    are made exactly as before #394."""
    orig, today, cache, lat = partial_pair(0)
    result = anchor_refine.refine(orig, today, cache)
    assert result.span is None
    assert "span" not in result.stats(len(lat))
    orig, today, cache, lat = partial_pair(0)
    plain = anchor_refine.refine(orig, today, cache, restrict=False)
    assert plain.beads == result.beads and plain.starts() == result.starts()
    assert plain.stats(len(lat)) == result.stats(len(lat))


def test_an_offline_cache_sends_nothing_and_raises_nothing() -> None:
    orig, today, _, lat = partial_pair(0)
    cache = anchor_refine.VectorCache(None, "t", "t.json", None, anchor.run_spec(),
                                      lambda t: len(t.split()), offline=True)
    cache.seed(anchor.text_sha(today.texts[0]), FakeEmbedder()([today.texts[0]])[0],
               anchor.run_spec())
    assert cache.ensure(today.texts) == 0 and cache.sent_tokens == 0
    with pytest.raises(anchor_refine.NeedsVectors):
        anchor_refine.VectorCache(None, "t", "t.json", None, anchor.run_spec(),
                                  lambda t: 1).ensure(today.texts)


# ------------------------------- machine-translation vectors of originals (#392)


def coptic(sents: list[list[int]]) -> str:
    """A Coptic original the fake embedder can't read: its own vectors are noise."""
    return " ".join(" ".join(f"ⲕ{c}ⲁ" for c in s) + "." for s in sents)


@pytest.fixture
def coptic_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setattr(anchoring, "enrolled_sources", lambda: {"tr": "test"})
    d = {k: tmp_path / k for k in ("raw", "normalized", "anchors", "embeddings", "scratch",
                                   "translations")}
    write_work(d["raw"], "orig/c.json", "cop", [coptic(SENTENCES[:8]), coptic(SENTENCES[8:])])
    write_work(d["raw"], "tr/w.json", "eng",
               [english(SENTENCES[:8]), english(SENTENCES[8:])], translation_of="orig/c")
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"])
    chunks = units(d, "orig/c.json")
    prov = tr.Provenance(model="m", prompt_version="1", date="2026-10-29", script="test")
    work = tr.WorkTranslations(work_id="orig/c", source_path="orig/c.json",
                               source_language="cop", provenance={prov.key: prov})
    # Every unit but the last has its English machine translation.
    for c in chunks[:-1]:
        eng = " ".join(f"eng{n}" for n in re.findall(r"ⲕ(\d+)ⲁ", c["text"])) + "."
        work.translations.append(tr.ChunkTranslation(
            chunk_id=c["chunk_id"], source_sha256=anchor.text_sha(c["text"]),
            provenance=prov.key, group_size=1, text=eng))
    tr.save(d["translations"], work, chunks)
    fake = FakeEmbedder()
    embed_work(d["normalized"], d["embeddings"], "orig/c.json", fake)
    shard = emb.load(d["embeddings"], "orig/c.json")
    run_key = next(iter(shard.runs))
    rows, vecs = list(shard.rows), list(shard.vecs)
    for t in work.translations:
        rows.append(emb.Row(t.chunk_id, emb.KIND_TRANSLATION, anchor.text_sha(t.text), run_key))
        vecs.append(fake([t.text])[0].astype(np.float16))
    emb.save(d["embeddings"], emb.WorkEmbeddings(shard.work_id, shard.source_path, shard.runs,
                                                 rows, np.stack(vecs)))
    return d


def coptic_concepts(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"ⲕ(\d+)ⲁ", text))


def test_a_rare_language_original_is_anchored_on_its_machine_translation(
        coptic_corpus, caplog) -> None:
    d = coptic_corpus
    [c] = anchor.candidates(d["normalized"])[0]
    assert c.anchor_language == "cop"
    assert anchor.original_vectors("cop") == emb.KIND_TRANSLATION
    assert anchor.original_vectors("grc") == emb.KIND_TEXT
    orig, missing, _ = anchor.load_original(c, d["normalized"], d["embeddings"],
                                            d["translations"])
    text, _, _ = anchor.load_original(c, d["normalized"], d["embeddings"], d["translations"],
                                      vectors=emb.KIND_TEXT)
    assert missing == 0
    # The machine translation's vectors, but the last unit's text vector (it has none).
    assert not np.allclose(orig.vecs[0], text.vecs[0])
    assert np.allclose(orig.vecs[-1], text.vecs[-1])
    assert "no current machine-translation vector" in caplog.text
    assert run(d, FakeEmbedder(), trans_dir=d["translations"])["cut"] == ["tr/w"]
    cut = anchor_store.load(d["anchors"], "tr/w.json")
    assert cut.method == anchor.method_hash(c) != anchoring.params_hash()
    # Cut on those vectors, the English units render the Coptic units.
    want = {coptic_concepts(ch["text"]) for ch in units(d, "orig/c.json")}
    got = [concepts(ch["text"]) for ch in units(d, "tr/w.json")]
    assert sum(g in want for g in got) >= len(want) - 2
    assert [s.status for s in anchor.check_works(d["normalized"], d["anchors"])] == [
        anchor.CURRENT]


def test_a_cut_made_on_text_vectors_of_a_rare_original_is_frozen(coptic_corpus) -> None:
    """A cut file made before #392 on a Coptic original's own vectors is
    reported (frozen) and re-cut only with --recut."""
    d = coptic_corpus
    run(d, FakeEmbedder(), trans_dir=d["translations"])
    cut = anchor_store.load(d["anchors"], "tr/w.json")
    cut.method = anchoring.params_hash()
    anchor_store.save(d["anchors"], "tr/w.json", cut)
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.METHOD
    assert run(d, FakeEmbedder(), trans_dir=d["translations"])["cut"] == []
    assert run(d, FakeEmbedder(), trans_dir=d["translations"],
               recut=["tr/w"])["cut"] == ["tr/w"]


def test_text_vector_originals_keep_the_method_of_existing_cut_files() -> None:
    """Greek and Latin originals: the method hash is the one every cut file
    before #392/#394 records, so none of them goes stale. (A Slavonic
    *translation* is anchored on its Greek original: the original's language
    decides.)"""
    assert anchor.original_vectors("chu") == emb.KIND_TRANSLATION  # #336
    for language in ("grc", "lat", ""):
        c = anchor.Candidate("tr/w.json", "tr/w", "eng", "orig/w", "orig/w.json", language)
        assert anchor.method_hash(c) == anchoring.params_hash() == "e26e66e4678bcee0"


def test_a_provisional_cut_inside_a_clause_keeps_the_commas_around_it() -> None:
    # De pythonissa: the provisional cut fell after '"Seek,'; the comma before
    # it must stay a candidate, or the word can't move to the next verse.
    text = ('He who said to his disciples, "Seek, and you will find," will surely '
            'also give the power to find to those who, out of love of learning, '
            'search as the Lord commanded and seek out the hidden mysteries.')
    atoms = anchor_refine._atoms(text)
    seek = next(i for i, a in enumerate(atoms) if "Seek" in a)
    para = anchor_refine.Paragraph("p.1", atoms, [0, seek + 1])
    ends = [s.a1 for s in anchor_refine.segments_of([para], "eng")]
    assert seek in ends and seek + 1 in ends


def test_the_rounds_cap_is_a_bound_not_a_measurement() -> None:
    # Each exploring round, and the final units, send the text at most once
    # (#472: a measured 2× stopped a re-cut).
    assert anchor.ROUNDS_FACTOR >= anchoring.RefineParams().max_rounds + 1
