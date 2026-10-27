"""Derived verses anchored on the original (#292): patristica.anchoring and its
use by scripts.normalize."""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from patristica import anchoring
from patristica.anchoring import (
    PARAGRAPHS,
    SEGMENTS,
    Anchor,
    AnchoringError,
    align_lengths,
    load_enrolment,
    project,
)
from patristica.models import Chunk
from patristica.versify import split_text, versify_chunks
from scripts import normalize as nz
from scripts import status

NORMALIZED = Path(__file__).resolve().parents[1] / "data" / "normalized"

# ---------------------------------------------------------------- a parallel text

_LAT = ("verbum dominus gratia caritas fides spes populus ecclesia sermo lex "
        "vita mors caelum terra aqua lux").split()
_ENG = ("word lord grace love faith hope people church speech law "
        "life death heaven earth water light").split()


def _parallel(n: int, seed: int = 1, free: bool = False) -> tuple[list[str], list[str]]:
    """*n* Latin sentences and their 'English' translations, each tagged with its
    number (``s7`` / ``t7``) so a test can tell which sentence went where. The
    English is ~1.3× longer, with jitter; a *free* translation also reorders
    them and runs most of them together into longer sentences."""
    rng = random.Random(seed)
    lat, eng = [], []
    for k in range(n):
        size = rng.choice([4, 6, 9, 14, 22, 30])
        lw = [rng.choice(_LAT) for _ in range(size)]
        ew = [_ENG[_LAT.index(w)] for w in lw]
        ew += [rng.choice(_ENG) for _ in range(round(size * rng.uniform(0.15, 0.45)))]
        mark = "?" if k % 7 == 3 else "."
        lat.append(f"s{k} " + " ".join(lw) + mark)
        eng.append(f"t{k} " + " ".join(ew) + mark)
    if free:
        rng.shuffle(eng)
        eng = [e if i % 3 == 2 else e.rstrip(".?") + ";" for i, e in enumerate(eng)]
    return lat, eng


def _tags(text: str, prefix: str) -> list[int]:
    return [int(m) for m in re.findall(rf"\b{prefix}(\d+)\b", text)]


def _anchor_paragraphs(lat: list[str], para_size: int = 12) -> list[list[str]]:
    paras = [" ".join(lat[i:i + para_size]) for i in range(0, len(lat), para_size)]
    return [split_text(p, "lat") for p in paras]


# ------------------------------------------------------------------- enrolment


def test_committed_enrolment_table_is_valid() -> None:
    sources = load_enrolment()
    assert all(reason for reason in sources.values())


def test_enrolment_table_needs_a_reason_and_no_duplicates(tmp_path: Path) -> None:
    path = tmp_path / "anchored.csv"
    path.write_text("source_id,reason\nchu-x,\n", encoding="utf-8")
    with pytest.raises(AnchoringError, match="no reason"):
        load_enrolment(path)
    path.write_text("source_id,reason\nchu-x,new\nchu-x,again\n", encoding="utf-8")
    with pytest.raises(AnchoringError, match="twice"):
        load_enrolment(path)


def test_committed_anchored_works_are_current() -> None:
    """A work of an enrolled source was cut on its anchor's current cuts (#130)."""
    stale = status.anchor_stale_works(NORMALIZED)
    assert not stale, f"anchors changed (re-run scripts.normalize): {stale[:10]}"


# --------------------------------------------------------------- length aligner


def test_identical_lengths_align_one_to_one_with_margins() -> None:
    lengths = [30.0, 80.0, 12.0, 55.0, 40.0, 70.0, 25.0]
    result = align_lengths(lengths, lengths, SEGMENTS)
    assert {i: j for i, (j, _) in result.boundary.items()} == {i: i for i in range(1, 7)}
    assert all(margin > 0 for _, margin in result.boundary.values())


def test_an_inserted_item_is_skipped() -> None:
    a = [30.0, 80.0, 12.0, 55.0, 40.0, 70.0]
    b = [30.0, 80.0, 60.0, 12.0, 55.0, 40.0, 70.0]  # 60 has no counterpart
    result = align_lengths(a, b, PARAGRAPHS)
    assert result.boundary[2][0] in (2, 3)
    assert result.boundary[3][0] == 4
    assert result.boundary[5][0] == 6


# ------------------------------------------------------------------ projection


def test_projection_follows_the_anchor_units() -> None:
    lat, eng = _parallel(120)
    anchor = _anchor_paragraphs(lat)
    paras = [" ".join(eng[i:i + 12]) for i in range(0, len(eng), 12)]
    proj = project(anchor, "lat", paras, "eng")
    units = [u for p in proj.units for u in p]
    anchor_units = [u for p in anchor for u in p]
    assert proj.sentence_agreement > 0.9
    assert len(proj.boundary) > 0.8 * (len(anchor_units) - len(anchor))
    # Every projected unit holds the translations of exactly one anchor unit.
    exact = sum(_tags(t, "t") == _tags(a, "s") for t, a in zip(units, anchor_units))
    assert exact > 0.8 * len(anchor_units)
    assert " ".join(units).split() == " ".join(paras).split()


def test_derived_verses_never_cross_translation_paragraphs() -> None:
    lat, eng = _parallel(60, seed=4)
    anchor = _anchor_paragraphs(lat, para_size=20)
    paras = [" ".join(eng[i:i + 7]) for i in range(0, len(eng), 7)]  # other paragraphing
    proj = project(anchor, "lat", paras, "eng")
    assert len(proj.units) == len(paras)
    for p, units in zip(paras, proj.units):
        assert " ".join(units).split() == p.split()


def test_free_translation_is_cut_as_today() -> None:
    lat, eng = _parallel(120, seed=2, free=True)
    anchor = _anchor_paragraphs(lat)
    paras = [" ".join(eng[i:i + 12]) for i in range(0, len(eng), 12)]
    proj = project(anchor, "lat", paras, "eng")
    assert proj.sentence_agreement < anchoring.MIN_SENTENCE_AGREEMENT
    assert proj.boundary == {}
    assert proj.units == [split_text(p, "eng") for p in paras]


def test_projection_is_deterministic() -> None:
    lat, eng = _parallel(80, seed=3)
    anchor = _anchor_paragraphs(lat)
    paras = [" ".join(eng[i:i + 10]) for i in range(0, len(eng), 10)]
    first = project(anchor, "lat", paras, "eng")
    second = project(anchor, "lat", paras, "eng")
    assert first.units == second.units and first.margin == second.margin


def test_anchor_paragraphs_regroup_derived_verses() -> None:
    anchor = Anchor("w/a", "lat", (("A.1", "x"), ("A.2.s1", "y"), ("A.2.s2", "z"),
                                   ("A.3.s1", "u"), ("A.3.s2", "v"), ("A.4", "w")))
    assert anchor.paragraphs() == [["x"], ["y", "z"], ["u", "v"], ["w"]]
    assert anchor.record() == {"work_id": "w/a", "cuts": anchor.cuts}
    changed = Anchor("w/a", "lat", (*anchor.units[:-1], ("A.4", "w!")))
    assert changed.cuts != anchor.cuts


def test_same_language_anchor_is_left_to_the_199_hook() -> None:
    anchor = Anchor("w/a", "eng", (("A.1", "Some text."),))
    chunk = Chunk(chunk_id="w/b#B.1", work_id="w/b", canonical_ref="B.1", language="eng",
                  text="Some text.", chunk_index=0)
    assert anchoring.anchored_units([chunk], anchor) is None


def test_versify_takes_units_cut_elsewhere() -> None:
    chunk = Chunk(chunk_id="w/b#B.1", work_id="w/b", canonical_ref="B.1", language="eng",
                  text="One two. Three four.", chunk_index=0)
    out = versify_chunks([chunk], units_of={"w/b#B.1": ["One two.", "Three four."]})
    assert [c.canonical_ref for c in out] == ["B.1.s1", "B.1.s2"]
    assert versify_chunks([chunk]) == [chunk]  # too short to split on its own


def test_split_text_target_override() -> None:
    lat, _ = _parallel(40, seed=5)
    text = " ".join(lat)
    assert split_text(text, "lat", target=None) == split_text(text, "lat")
    assert len(split_text(text, "lat", target=400)) < len(split_text(text, "lat"))


# ------------------------------------------------------------------- normalize


def _write_raw(raw: Path, rel: str, work: dict, paragraphs: list[str]) -> None:
    path = raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "work": {"title": "T", "genre": "patristic", "license": "public_domain", **work},
        "paragraphs": [{"ref": f"P.{i + 1}", "text": t} for i, t in enumerate(paragraphs)],
    }), encoding="utf-8")


@pytest.fixture
def enrolled(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    table: dict[str, str] = {}
    monkeypatch.setattr(anchoring, "enrolled_sources", lambda: table)
    return table


@pytest.fixture
def corpus(tmp_path: Path, enrolled: dict[str, str]) -> tuple[Path, Path]:
    lat, eng = _parallel(90, seed=6)
    raw = tmp_path / "raw"
    _write_raw(raw, "orig/a.json", {"work_id": "orig/a", "source_id": "orig", "language": "lat"},
               [" ".join(lat[i:i + 15]) for i in range(0, len(lat), 15)])
    _write_raw(raw, "trans/a.json", {"work_id": "trans/a", "source_id": "trans",
                                      "language": "eng", "translation_of": "orig/a"},
               [" ".join(eng[i:i + 15]) for i in range(0, len(eng), 15)])
    return raw, tmp_path / "normalized"


def _units(norm: Path, rel: str) -> list[dict]:
    return json.loads((norm / rel).read_text(encoding="utf-8"))


def test_unenrolled_translation_is_cut_on_its_own(corpus) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    assert all("anchor" not in fp for fp in nz.read_work_fingerprints(norm).values())
    own = [u["text"] for u in _units(norm, "trans/a.json")]
    eng = [c["text"] for c in json.loads((raw / "trans/a.json").read_text())["paragraphs"]]
    assert own == [u for p in eng for u in split_text(p, "eng")]


def test_enrolled_translation_is_cut_on_its_anchor(corpus, enrolled) -> None:
    raw, norm = corpus
    enrolled["trans"] = "test"
    nz.normalize_all(raw, norm)
    orig, trans = _units(norm, "orig/a.json"), _units(norm, "trans/a.json")
    exact = sum(_tags(t["text"], "t") == _tags(o["text"], "s") for o, t in zip(orig, trans))
    assert exact > 0.8 * len(orig)
    fps = nz.read_work_fingerprints(norm)
    anchor = Anchor.from_chunks("orig/a", orig)
    assert fps["trans/a.json"]["anchor"] == anchor.record()
    assert "anchor" not in fps["orig/a.json"]
    assert status.anchor_stale_works(norm) == []


def test_a_changed_anchor_resplits_its_translation(corpus, enrolled, monkeypatch) -> None:
    raw, norm = corpus
    enrolled["trans"] = "test"
    nz.normalize_all(raw, norm)
    built: list[str] = []
    original = nz._normalize_record

    def record(raw_record: dict, raw_path: Path, output_dir: Path, **kw: object) -> int | None:
        built.append(nz._output_rel(raw_path).as_posix())
        return original(raw_record, raw_path, output_dir, **kw)

    monkeypatch.setattr(nz, "_normalize_record", record)
    nz.normalize_all(raw, norm)
    assert built == []

    # The anchor's text changes (a re-ingest): its translation is re-split after it.
    path = raw / "orig/a.json"
    rec = json.loads(path.read_text())
    rec["paragraphs"][0]["text"] = rec["paragraphs"][0]["text"].replace("s0 ", "s0 lux ", 1)
    path.write_text(json.dumps(rec))
    nz.normalize_all(raw, norm, accept_raw_change=True)
    assert built == ["orig/a.json", "trans/a.json"]
    assert status.anchor_stale_works(norm) == []


def test_anchor_record_change_is_reported_by_status(corpus, enrolled) -> None:
    raw, norm = corpus
    enrolled["trans"] = "test"
    nz.normalize_all(raw, norm)
    chunks = _units(norm, "orig/a.json")
    chunks[0]["text"] += " lux"
    (norm / "orig/a.json").write_text(json.dumps(chunks), encoding="utf-8")
    assert status.anchor_stale_works(norm) == ["trans/a.json"]


def test_enrolled_work_without_an_anchor_is_cut_as_today(corpus, enrolled) -> None:
    raw, norm = corpus
    enrolled["orig"] = "test"
    nz.normalize_all(raw, norm)
    assert nz.read_work_fingerprints(norm)["orig/a.json"]["anchor"] == anchoring.UNANCHORED
    assert status.anchor_stale_works(norm) == []


def test_anchors_are_normalized_before_the_works_anchored_on_them() -> None:
    works = {
        "x/c.json": {"work_id": "x/c", "translation_of": "x/b"},
        "x/a.json": {"work_id": "x/a"},
        "x/b.json": {"work_id": "x/b", "translation_of": "x/a"},
    }
    assert nz.anchor_order(works) == ["x/a.json", "x/b.json", "x/c.json"]
    works["x/a.json"]["translation_of"] = "x/c"
    with pytest.raises(AnchoringError, match="cycle"):
        nz.anchor_order(works)


def test_anchor_eval_reports_a_pair_without_an_alignment(corpus, capsys) -> None:
    from scripts import anchor_eval

    raw, norm = corpus
    nz.normalize_all(raw, norm)  # not enrolled: the translation is cut on its own
    result = anchor_eval.evaluate("orig/a", "trans/a", norm, norm / "no-alignments", sample=2)
    assert result["languages"] == "lat→eng"
    assert result["projected_share"] > 0.7 and not result["free"]
    assert "agree_exact" not in result  # no passage alignment to check against
    assert capsys.readouterr().out.count("--- P.") == 2
    assert "| `orig/a` → `trans/a` |" in anchor_eval.render([result])
