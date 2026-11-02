"""Anchored derived verses (#304): enrolment, cut files and normalize applying
them. No vectors and no numpy; the refinement is ``tests/test_anchor.py``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import anchor_store, anchoring
from patristica.models import Chunk
from patristica.versify import split_text
from scripts import normalize as nz

# ---------------------------------------------------------------- enrolment


ROOT = Path(__file__).resolve().parents[1]
NORMALIZED = ROOT / "data" / "normalized"


def test_enrolment_table() -> None:
    """PTA is enrolled only for its Slavonic (#335) and ReA only for its Old High
    German (#567, its Latin sides have no original in the corpus); every other row
    enrols a whole source."""
    table = anchoring.load_enrolment()
    assert {key for key in table if key[0] == "pta"} == {("pta", "chu")}
    assert {key for key in table if key[1] is not None} == {("pta", "chu"), ("rea", "goh")}


def test_no_published_pta_work_is_enrolled() -> None:
    """Enrolling PTA's Slavonic re-cuts no other PTA work (#335, #200): of
    PTA's works in the manifest, only the Slavonic one is enrolled, and every
    other PTA work's fingerprint has no anchor record (it is cut as before)."""
    manifest = NORMALIZED / "_works.jsonl"
    entries = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    enrolled = sorted(e["work"]["work_id"] for e in entries
                      if e["work"]["source_id"] == "pta" and anchoring.is_enrolled(
                          e["work"]["source_id"], e["work"]["language"]))
    assert enrolled == ["pta/pta0001/pta028/pta-chu1"]
    fps = nz.read_work_fingerprints(NORMALIZED)
    anchored = sorted(path for path, fp in fps.items()
                      if path.startswith("pta/") and "anchor" in fp)
    assert anchored == ["pta/pta0001/pta028/pta0001.pta028.pta-chu1.json"]


def test_enrolment_by_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "e.csv"
    path.write_text("source_id,language,reason\nall,,x\npta,chu,y\npta,hye,z\n",
                    encoding="utf-8")
    table = anchoring.load_enrolment(path)
    assert table == {("all", None): "x", ("pta", "chu"): "y", ("pta", "hye"): "z"}
    monkeypatch.setattr(anchoring, "load_enrolment", lambda: table)
    for f in (anchoring.enrolled_sources, anchoring.enrolled_languages):
        monkeypatch.setattr(anchoring, f.__name__, f.__wrapped__)
    assert anchoring.is_enrolled("all") and anchoring.is_enrolled("all", "eng")
    assert anchoring.is_enrolled("pta", "chu") and anchoring.is_enrolled("pta", "hye")
    assert not anchoring.is_enrolled("pta") and not anchoring.is_enrolled("pta", "eng")
    assert anchoring.enrols_by_language("pta") and not anchoring.enrols_by_language("all")
    assert not anchoring.enrols_by_language("other")


def test_the_language_column_is_optional(tmp_path: Path) -> None:
    path = tmp_path / "e.csv"
    path.write_text("source_id,reason\ntorot,x\n", encoding="utf-8")
    assert anchoring.load_enrolment(path) == {("torot", None): "x"}


def test_enrolled_sources_are_known_sources() -> None:
    """Every enrolled source is a real source (it has a label), with a reason."""
    from patristica.sources import SOURCE_LABELS

    enrolled = anchoring.load_enrolment()
    assert ("ccmh-supr", None) in enrolled  # the first Slavonic source enrolled (#333)
    assert {source for source, _ in enrolled} <= set(SOURCE_LABELS)
    assert all(reason.strip() for reason in enrolled.values())


@pytest.mark.parametrize("body, message", [
    ("source_id,reason\ntorot,\n", "no reason"),
    ("source_id,reason\ntorot,x\ntorot,y\n", "twice"),
    ("source_id,reason\na/b,x\n", "bad source_id"),
    ("source_id,language,reason\npta,chu,x\npta,chu,y\n", "twice"),
    ("source_id,language,reason\npta,xx,x\n", "unknown language"),
    ("source_id,language,reason\npta,,x\npta,chu,y\n", "both"),
    ("source_id,language,reason\npta,chu,x\npta,,y\n", "both"),
])
def test_enrolment_errors(tmp_path: Path, body: str, message: str) -> None:
    path = tmp_path / "e.csv"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(anchoring.AnchoringError, match=message):
        anchoring.load_enrolment(path)


def test_anchor_order_puts_anchors_first_and_finds_cycles() -> None:
    order = anchoring.anchor_order({"eng/x": "chu/x", "chu/x": "grc/x", "other": None})
    assert order.index("chu/x") < order.index("eng/x")
    with pytest.raises(anchoring.AnchoringError, match="cycle"):
        anchoring.anchor_order({"a": "b", "b": "a"})


def test_params_hash_changes_with_the_parameters() -> None:
    p = anchoring.RefineParams()
    assert anchoring.params_hash(p) == anchoring.params_hash(anchoring.RefineParams())
    assert anchoring.params_hash(p) != anchoring.params_hash(
        anchoring.RefineParams(max_rounds=4))


# --------------------------------------------------------------- paragraphs

TEXT = "In the beginning was the Word. And the Word was with God; and God was the Word."


def test_cut_at_returns_stripped_slices() -> None:
    ws = anchoring.words(TEXT)
    start = next(i for i, w in enumerate(ws) if w.strip() == "And")
    assert anchoring.cut_at(TEXT, [0, start]) == [
        "In the beginning was the Word.", "And the Word was with God; and God was the Word."]
    assert anchoring.cut_at(TEXT, [0]) == [TEXT]


def test_paragraphs_rebuild_words_and_starts_from_units() -> None:
    units = split_text(TEXT * 4, "eng")
    assert len(units) > 1
    chunks = [{"canonical_ref": f"P.1.s{i}", "text": u} for i, u in enumerate(units, 1)]
    chunks.append({"canonical_ref": "P.2", "text": "Short."})
    paras = anchoring.paragraphs(chunks)
    assert [p.ref for p in paras] == ["P.1", "P.2"]
    assert [w.strip() for w in paras[0].words] == [w.strip()
                                                   for w in anchoring.words(TEXT * 4)]
    assert anchoring.cut_at(TEXT * 4, list(paras[0].starts)) == units
    assert paras[1].starts == (0,)


def test_words_hash_ignores_whitespace() -> None:
    a = anchoring.words("one  two\nthree")
    b = anchoring.words("one two three")
    assert anchoring.words_hash(a) == anchoring.words_hash(b)


def cut_file(paragraphs: dict[str, tuple[str, tuple[int, ...]]]) -> anchor_store.CutFile:
    return anchor_store.CutFile(
        work_id="tr/w", anchor="orig/w", method=anchoring.params_hash(), anchor_cuts="x",
        words="y", model="voyage/voyage-4-large",
        paragraphs={ref: anchor_store.ParagraphCut(anchoring.words_hash(anchoring.words(t)), st)
                    for ref, (t, st) in paragraphs.items()},
        stats={"rounds": 2})


def test_units_of_applies_only_matching_paragraphs() -> None:
    chunks = [Chunk(chunk_id=f"tr/w#P.{i}", work_id="tr/w", canonical_ref=f"P.{i}",
                    chunk_index=i, language="eng", text=TEXT) for i in (1, 2, 3)]
    second = anchoring.words(TEXT).index(" And")
    cut = cut_file({"P.1": (TEXT, (0, second)), "P.2": ("Other words.", (0, 1))})
    assert anchoring.units_of(chunks, cut) == {
        "tr/w#P.1": ["In the beginning was the Word.",
                     "And the Word was with God; and God was the Word."]}


def test_cut_file_roundtrip(tmp_path: Path) -> None:
    cut = cut_file({"P.1": (TEXT, (0, 6)), "P.2": ("Short.", (0,))})
    assert anchor_store.save(tmp_path, "tr/w.json", cut)
    assert not anchor_store.save(tmp_path, "tr/w.json", cut)
    loaded = anchor_store.load(tmp_path, "tr/w.json")
    assert loaded == cut and loaded.sha == cut.sha
    json.loads((tmp_path / "tr/w.json").read_text())  # valid JSON
    assert [p for p, _ in anchor_store.iter_store(tmp_path)] == ["tr/w.json"]
    empty = cut_file({})
    assert anchor_store.CutFile.from_dict(json.loads(empty.dumps())) == empty


# --------------------------------------------------- normalize applies cuts

LONG = " ".join(f"Sentence number {i} says a few more words here." for i in range(12))


def write_work(raw: Path, rel: str, language: str, text: str, genre: str = "patristic",
               translation_of: str | None = None, verses: bool = False) -> None:
    source_id, name = rel.split("/")[0], Path(rel).stem
    path = raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    work = {"work_id": f"{source_id}/{name}", "source_id": source_id, "title": "T",
            "genre": genre, "language": language, "license": "public_domain"}
    if translation_of:
        work["translation_of"] = translation_of
    path.write_text(json.dumps({
        "work": work, ("verses" if verses else "paragraphs"): [
            {"ref": "P.1", "text": text}, {"ref": "P.2", "text": "A short one."}],
    }), encoding="utf-8")


@pytest.fixture
def enrolled(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    table = {"tr": "test"}
    monkeypatch.setattr(anchoring, "enrolled_sources", lambda: table)
    return table


@pytest.fixture
def corpus(tmp_path: Path, enrolled: dict[str, str]) -> tuple[Path, Path, Path]:
    raw, norm, anchors = tmp_path / "raw", tmp_path / "normalized", tmp_path / "anchors"
    write_work(raw, "orig/w.json", "lat", LONG)
    write_work(raw, "tr/w.json", "eng", LONG, translation_of="orig/w")
    write_work(raw, "tr/v.json", "eng", LONG, verses=True)
    return raw, norm, anchors


def refs(norm: Path, rel: str) -> list[str]:
    return [c["canonical_ref"] for c in json.loads((norm / rel).read_text(encoding="utf-8"))]


def test_enrolled_work_without_a_cut_file_gets_the_provisional_cut(corpus) -> None:
    raw, norm, anchors = corpus
    nz.normalize_all(raw, norm, anchors_dir=anchors)
    fps = nz.read_work_fingerprints(norm)
    assert fps["tr/w.json"]["anchor"] == {"cuts": None}
    assert fps["tr/v.json"]["anchor"] is None  # verses: never anchored
    assert "anchor" not in fps["orig/w.json"]
    n = len(split_text(LONG, "eng"))
    assert refs(norm, "tr/w.json") == [f"P.1.s{i}" for i in range(1, n + 1)] + ["P.2"]


def test_a_cut_file_rebuilds_exactly_its_work(corpus, monkeypatch) -> None:
    raw, norm, anchors = corpus
    nz.normalize_all(raw, norm, anchors_dir=anchors)
    built: list[str] = []
    original = nz._normalize_record

    def record(raw_record, raw_path, output_dir, *args):
        built.append(nz._output_rel(raw_path).as_posix())
        return original(raw_record, raw_path, output_dir, *args)

    monkeypatch.setattr(nz, "_normalize_record", record)
    nz.normalize_all(raw, norm, anchors_dir=anchors)
    assert built == []
    ws = anchoring.words(LONG)
    cut = cut_file({"P.1": (LONG, (0, 9, 27)), "P.2": ("A short one.", (0, 1))})
    anchor_store.save(anchors, "tr/w.json", cut)
    nz.normalize_all(raw, norm, anchors_dir=anchors)
    assert built == ["tr/w.json"]
    chunks = json.loads((norm / "tr/w.json").read_text(encoding="utf-8"))
    assert [c["canonical_ref"] for c in chunks] == ["P.1.s1", "P.1.s2", "P.1.s3",
                                                    "P.2.s1", "P.2.s2"]
    assert chunks[1]["text"] == "".join(ws[9:27]).strip()
    assert chunks[4]["text"] == "short one."
    assert nz.read_work_fingerprints(norm)["tr/w.json"]["anchor"] == {"cuts": cut.sha}
    built.clear()
    nz.normalize_all(raw, norm, anchors_dir=anchors)
    assert built == []
    # The cut file applies to the paragraphs whose words it still matches.
    write_work(raw, "tr/w.json", "eng", LONG + " An added sentence.", translation_of="orig/w")
    nz.normalize_all(raw, norm, anchors_dir=anchors, accept_raw_change=True)
    assert refs(norm, "tr/w.json")[-2:] == ["P.2.s1", "P.2.s2"]
    assert refs(norm, "tr/w.json")[:-2] == [
        f"P.1.s{i}" for i in range(1, len(split_text(LONG + " An added sentence.", "eng")) + 1)]


def test_a_language_row_enrols_only_that_language(tmp_path: Path, monkeypatch) -> None:
    """A source enrolled by language (#335): its works in other languages keep
    their cut and record no anchor, the enrolled language's works are anchored."""
    monkeypatch.setattr(anchoring, "enrolled_sources", lambda: {})
    monkeypatch.setattr(anchoring, "enrolled_languages", lambda: {("tr", "chu"): "test"})
    raw, norm, anchors = tmp_path / "raw", tmp_path / "normalized", tmp_path / "anchors"
    write_work(raw, "orig/w.json", "lat", LONG)
    write_work(raw, "tr/w.json", "eng", LONG, translation_of="orig/w")
    write_work(raw, "tr/c.json", "chu", LONG, translation_of="orig/w")
    nz.normalize_all(raw, norm, anchors_dir=anchors)
    fps = nz.read_work_fingerprints(norm)
    assert "anchor" not in fps["tr/w.json"] and "anchor" not in fps["orig/w.json"]
    assert fps["tr/c.json"]["anchor"] == {"cuts": None}
    before = refs(norm, "tr/w.json")
    # A cut file beside a work that isn't enrolled is ignored.
    anchor_store.save(anchors, "tr/w.json",
                      cut_file({"P.1": (LONG, (0, 9)), "P.2": ("A short one.", (0,))}))
    nz.normalize_all(raw, norm, anchors_dir=anchors)
    assert refs(norm, "tr/w.json") == before
    assert "anchor" not in nz.read_work_fingerprints(norm)["tr/w.json"]


def test_enrolling_a_source_rebuilds_its_works(corpus, enrolled, monkeypatch) -> None:
    raw, norm, anchors = corpus
    enrolled.clear()
    nz.normalize_all(raw, norm, anchors_dir=anchors)
    assert "anchor" not in nz.read_work_fingerprints(norm)["tr/w.json"]
    enrolled["tr"] = "test"
    nz.normalize_all(raw, norm, anchors_dir=anchors)
    assert nz.read_work_fingerprints(norm)["tr/w.json"]["anchor"] == {"cuts": None}


def test_only_never_prunes_other_works(corpus) -> None:
    """A partial rebuild (scripts.anchor) leaves works whose raw file is absent."""
    raw, norm, anchors = corpus
    nz.normalize_all(raw, norm, anchors_dir=anchors)
    (raw / "tr/v.json").unlink()
    nz.normalize_all(raw / "tr", norm, anchors_dir=anchors, only={"tr/w.json"})
    assert (norm / "tr/v.json").exists()
    assert "tr/v.json" in nz.read_works_manifest(norm)


def test_only_limits_the_run(corpus) -> None:
    raw, norm, anchors = corpus
    nz.normalize_all(raw / "tr", norm, anchors_dir=anchors, only={"tr/w.json"})
    assert sorted(nz.read_work_fingerprints(norm)) == ["tr/w.json"]
