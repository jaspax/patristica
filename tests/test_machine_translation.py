"""Machine translations (#422, #423): eligibility (patristica.machine_translation),
the translator (scripts.machine_translate) and the tracked mt-eng raw files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import machine_translation as mt
from patristica.translations import text_sha
from scripts import machine_translate as mtr
from scripts.translate import BulkItem, BulkTranslation

REPO = Path(__file__).resolve().parent.parent


def work(work_id: str, language: str = "lat", translation_of: str | None = None,
         source_id: str | None = None, genre: str = "patristic",
         license: str = "public_domain") -> dict:
    return {"work_id": work_id, "source_id": source_id or work_id.split("/")[0],
            "language": language, "translation_of": translation_of, "genre": genre,
            "license": license, "title": work_id, "author": "Augustinus",
            "author_ids": ["augustine-of-hippo"], "tradition": "latin",
            "date_composed": 400, "date_range": None, "date_confidence": "approximate",
            "edition": "Ed.", "provenance_url": "https://example.org"}


def entries(*works: dict) -> list[dict]:
    return [{"path": f"{w['work_id']}.json", "work": w} for w in works]


def ids(cands: list[mt.Candidate]) -> list[str]:
    return [c.work_id for c in cands]


# --- eligibility ----------------------------------------------------------------


def test_candidates_are_originals_without_english():
    es = entries(
        work("csel/a"),                                          # alone: a candidate
        work("csel/b"), work("npnf/b", "eng", "csel/b"),         # has English
        work("pta/c", "grc"), work("pta/c-lat", "lat", "pta/c"),  # Latin from Greek: the Greek
        work("arm/d", "hye", translation_of="lost/d"),           # original lost: the Armenian
        work("csel/e", genre="scripture"),                       # Scripture: never
        work("csel/f", license="unknown"),                       # unpublishable
        work("kjv/g", "eng"),                                    # English itself
    )
    assert ids(mt.candidates(es, exceptions={})) == ["arm/d", "csel/a", "pta/c"]


def test_an_existing_machine_translation_counts_as_english():
    es = entries(work("csel/a"), work("mt-eng/csel/a", "eng", "csel/a"))
    assert mt.candidates(es, exceptions={}) == []
    assert mt.is_machine_translation(es[1]["work"])


def test_a_listed_divergent_version_is_a_candidate_even_beside_english():
    es = entries(work("pta/c", "grc"), work("npnf/c", "eng", "pta/c"),
                 work("syr/c", "syc", "pta/c"))
    assert mt.candidates(es, exceptions={}) == []
    (cand,) = mt.candidates(es, exceptions={"syr/c": "the Syriac differs"})
    assert (cand.work_id, cand.exception) == ("syr/c", "the Syriac differs")
    # ...until English made from it exists.
    es += entries(work("mt-eng/syr/c", "eng", "syr/c"))
    assert mt.candidates(es, exceptions={"syr/c": "the Syriac differs"}) == []


def test_of_two_editions_the_preferred_one_is_translated(monkeypatch):
    # Two Greek editions of one work, joined by a shared TLG id.
    a = {**work("ogpg/x", "grc"), "external_ids": ["TLG:tlg2042.tlg001"]}
    b = {**work("first1k/x", "grc"), "external_ids": ["TLG:tlg2042.tlg001"]}
    assert ids(mt.candidates(entries(a, b), exceptions={})) == ["first1k/x"]
    assert mt.edition_rank("pta") < mt.edition_rank("newsource") < mt.edition_rank("ogpg")


def test_redundant_machine_translations():
    works = {w["work_id"]: w for w in (
        work("csel/a"), work("mt-eng/csel/a", "eng", "csel/a"),        # alone: kept
        work("csel/b"), work("mt-eng/csel/b", "eng", "csel/b"),
        work("npnf/b", "eng", "csel/b"),                               # published: redundant
        work("pta/c", "grc"), work("npnf/c", "eng", "pta/c"),
        work("syr/c", "syc", "pta/c"), work("mt-eng/syr/c", "eng", "syr/c"),  # divergent: kept
    )}
    assert mt.redundant(works, exceptions={"syr/c": "differs"}) == {"mt-eng/csel/b"}


def test_exceptions_file_is_valid(tmp_path: Path):
    mt.load_exceptions()  # the tracked file
    bad = tmp_path / "x.csv"
    for body in ("work_id,reason\ncsel/a,\n",                       # no reason
                 "work_id,reason\ncsel/b,x\ncsel/a,y\n",            # out of order
                 "work_id,reason\ncsel/a,x\ncsel/a,y\n",            # twice
                 "work,reason\ncsel/a,x\n"):                        # wrong columns
        bad.write_text(body, encoding="utf-8")
        with pytest.raises(mt.ExceptionsError):
            mt.load_exceptions(bad)


def test_blocked_file_is_valid(tmp_path: Path):
    mt.load_blocked()  # the tracked file
    good = tmp_path / "ok.csv"
    good.write_text('work_id,issue,reason\ncsel/a,316,OCR garbled\nogpg/b,#81,"lacunae, '
                    'columns run together"\n', encoding="utf-8")
    assert mt.load_blocked(good) == {
        "csel/a": mt.Blocked(316, "OCR garbled"),
        "ogpg/b": mt.Blocked(81, "lacunae, columns run together")}
    bad = tmp_path / "x.csv"
    for body in ("work_id,issue,reason\ncsel/a,0,x\n",       # not an issue
                 "work_id,issue,reason\ncsel/a,abc,x\n",
                 "work_id,issue,reason\ncsel/a,12,\n",       # no reason
                 "work_id,issue,reason\ncsel/b,1,x\ncsel/a,2,y\n",  # out of order
                 "work_id,reason\ncsel/a,x\n"):              # wrong columns
        bad.write_text(body, encoding="utf-8")
        with pytest.raises(mt.ExceptionsError):
            mt.load_blocked(bad)


def test_tracked_curation_rows_name_works_of_the_corpus():
    """Every row of mt_exceptions.csv and mt_blocked.csv names a work in _works.jsonl."""
    rows = [*mt.load_exceptions(), *mt.load_blocked()]
    if not rows:
        pytest.skip("no rows yet")
    works = {json.loads(line)["work"]["work_id"]: True
             for line in (REPO / "data/normalized/_works.jsonl").read_text().splitlines() if line}
    assert mt.unknown_works(rows, works) == []


def test_blocked_works_are_not_candidates():
    es = entries(work("csel/a"), work("csel/b"))
    blocked = {"csel/a": mt.Blocked(316, "OCR")}
    assert ids(mt.candidates(es, exceptions={}, blocked=blocked)) == ["csel/b"]
    assert mt.unknown_works(["csel/a", "csel/zzz"], {w["work"]["work_id"]: 1 for w in es}) \
        == ["csel/zzz"]


def test_candidates_list_their_other_versions_and_review_lists_derived_ones():
    es = entries(work("pta/c", "grc"), work("syr/c", "syc", "pta/c"),
                 work("arm/c", "hye", "syr/c"),                     # chained: still derived
                 {**work("ogpg/c", "grc"), "external_ids": ["TLG:x"]},
                 {**work("first1k/c", "grc"), "external_ids": ["TLG:x"]},
                 work("csel/d"), work("csel/d-arm", "hye", "csel/d"),
                 work("npnf/d", "eng", "csel/d"))                   # has English: not reviewed
    # pta/c and the two TLG editions are not linked; pta/c's group is its versions.
    cands = {c.work_id: c for c in mt.candidates(es, exceptions={}, blocked={})}
    assert [(v.work_id, v.kind, v.translation_of) for v in cands["pta/c"].versions] == [
        ("arm/c", "derived", "syr/c"), ("syr/c", "derived", "pta/c")]
    assert [(v.work_id, v.kind) for v in cands["first1k/c"].versions] == [("ogpg/c", "edition")]
    review = mt.versions_to_review(es, exceptions={})
    assert [v.work_id for v in review] == ["arm/c", "syr/c"]
    assert [v.work_id for v in mt.versions_to_review(es, exceptions={"syr/c": "x"})] == ["arm/c"]


def test_version_info_counts_source_characters(tmp_path: Path):
    norm = tmp_path / "n"
    (norm / "syr").mkdir(parents=True)
    (norm / "syr/c.json").write_text(json.dumps(
        [chunk("A.1.s1", "abc", work_id="syr/c"), chunk("A.1.s2", "de", work_id="syr/c")]))
    v = mt.Version("syr/c", "syr/c.json", "syc", "syr", "pta/c", "derived")
    assert mtr._version_info(norm, v) == {"work_id": "syr/c", "language": "syc",
                                          "source_id": "syr", "translation_of": "pta/c",
                                          "kind": "derived", "chars": 6}


# --- units and requests ---------------------------------------------------------


def chunk(ref: str, text: str, editorial: list | None = None, work_id: str = "csel/a") -> dict:
    c = {"chunk_id": f"{work_id}#{ref}", "work_id": work_id, "canonical_ref": ref,
         "language": "lat", "text": text}
    if editorial:
        c["editorial"] = editorial
    return c


def test_units_join_derived_verses_and_keep_editorial_headings():
    chunks = [
        chunk("A", "DE TRINITATE", [[0, 12, "title"]]),        # all editorial: translated, marked
        chunk("A.1.s1", "Prima pars."), chunk("A.1.s2", "Secunda [1] pars.", [[8, 11, "note"]]),
        chunk("A.2", "   "),                                     # blank: nothing to translate
        chunk("A.3", "Tertia."),
    ]
    units = mtr.units_of(chunks)
    assert [(u.ref, u.text, u.editorial) for u in units] == [
        ("A", "DE TRINITATE", "title"),
        ("A.1", "Prima pars. Secunda pars.", None),   # the note is not sent
        ("A.3", "Tertia.", None)]
    assert units[1].sha == text_sha("Prima pars. Secunda pars.")


def unit(ref: str, size: int) -> mtr.Unit:
    return mtr.Unit(ref, "x" * size, text_sha(ref))


def test_requests_follow_sections_and_split_long_ones_with_context():
    units = [unit("W.1.1", 300), unit("W.1.2", 300), unit("W.2.1", 300),   # sections 1, 2
             unit("W.3.1", 600), unit("W.3.2", 600), unit("W.3.3", 600)]    # section 3: too long
    reqs = mtr.make_requests(units, max_chars=1000)
    assert [[u.ref for u in r.units] for r in reqs] == [
        ["W.1.1", "W.1.2", "W.2.1"], ["W.3.1"], ["W.3.2"], ["W.3.3"]]
    assert [[u.ref for u in r.context] for r in reqs] == [[], [], ["W.3.1"], ["W.3.1", "W.3.2"]]
    text = mtr.request_text(reqs[2])
    assert text.startswith("Context, already translated (do not translate):")
    assert "[1]\n" + "x" * 600 in text and "[2]" not in text
    # A work under the limit is one request.
    assert len(mtr.make_requests(units)) == 1


def test_check_response():
    req = mtr.Request([mtr.Unit("A.1", "a" * 400, "s"), mtr.Unit("A.2", "b" * 400, "t")])
    assert mtr.check_response(req, {1: "x" * 500, 2: "y" * 500}, "lat") is None
    assert "missing [2]" in mtr.check_response(req, {1: "x" * 500}, "lat")
    assert "empty" in mtr.check_response(req, {1: "x" * 500, 2: " "}, "lat")
    assert "ratio" in mtr.check_response(req, {1: "x" * 100, 2: "y" * 100}, "lat")
    assert "shorter" in mtr.check_response(req, {1: "x" * 900, 2: "y" * 50}, "lat")


# --- translating a work ---------------------------------------------------------


class FakeClients:
    """Translates each numbered paragraph as 'EN <its text>'; can fail the first calls."""

    def __init__(self, fail: int = 0, served: str = "claude-opus-5-5") -> None:
        self.calls: list[str] = []
        self.fail = fail
        self.served = served

    def call(self, name, system, user, schema, effort=None):
        self.calls.append(user)
        if len(self.calls) <= self.fail:
            raise RuntimeError("boom")
        body = user.split("Translate:\n\n")[-1]
        items = []
        for block in body.split("\n\n["):
            n, text = block.lstrip("[").split("]\n", 1)
            items.append(BulkItem(n=int(n), translation=f"EN {text}"))
        return BulkTranslation(items=items), {"model": name, "input": 1, "output": 1,
                                              "served_by": self.served}


def corpus(tmp_path: Path, chunks: list[dict], raw_units_key: str = "paragraphs",
           genre: str = "patristic") -> tuple[Path, Path]:
    norm, raw = tmp_path / "normalized", tmp_path / "raw"
    w = work("csel/a", genre=genre)
    (norm / "csel").mkdir(parents=True)
    (norm / "_works.jsonl").write_text(json.dumps({"path": "csel/a.json", "work": w}) + "\n",
                                       encoding="utf-8")
    (norm / "csel/a.json").write_text(json.dumps(chunks), encoding="utf-8")
    (raw / "csel").mkdir(parents=True)
    raw_units = [{"ref": c["canonical_ref"], "text": c["text"]} for c in chunks]
    (raw / "csel/a.json").write_text(json.dumps({"work": w, raw_units_key: raw_units}),
                                     encoding="utf-8")
    return norm, raw


CHUNKS = [chunk("A", "DE TRINITATE", [[0, 12, "title"]]), chunk("A.1.s1", "Prima pars."),
          chunk("A.1.s2", "Secunda pars."), chunk("A.2", "Tertia pars.")]


def test_translate_work_writes_the_raw_file(tmp_path: Path):
    norm, raw = corpus(tmp_path, CHUNKS)
    fake = FakeClients()
    out = mtr.translate_work("csel/a", norm, raw, tmp_path / "out", tmp_path / "partial",
                             workers=1, clients=fake)
    assert out == tmp_path / "out/mt-eng/csel/a.json"
    rec = json.loads(out.read_text(encoding="utf-8"))
    w = rec["work"]
    assert (w["work_id"], w["source_id"], w["language"], w["translation_of"]) == (
        "mt-eng/csel/a", "mt-eng", "eng", "csel/a")
    assert w["author"] == "Augustinus" and w["license"] == "public_domain"
    assert w["edition"].startswith("Machine translation (claude-opus-5-5, Patristica, ")
    assert "author_ids" not in w and "external_ids" not in w
    assert [(u["ref"], u["text"]) for u in rec["paragraphs"]] == [
        ("A", "EN DE TRINITATE"), ("A.1", "EN Prima pars. Secunda pars."),
        ("A.2", "EN Tertia pars.")]
    assert rec["paragraphs"][0]["editorial"] == [[0, 15, "title"]]
    assert rec["machine_translation"]["original"] == "csel/a"
    assert rec["machine_translation"]["prompt_version"] == mtr.PROMPT_VERSION
    assert len(fake.calls) == 1
    with pytest.raises(mtr.MachineTranslateError, match="exists"):
        mtr.translate_work("csel/a", norm, raw, tmp_path / "out", tmp_path / "partial",
                           clients=fake)


def test_a_work_ingested_as_verses_keeps_verses(tmp_path: Path):
    norm, raw = corpus(tmp_path, [chunk("A.1", "Unus."), chunk("A.2", "Duo.")],
                       raw_units_key="verses")
    out = mtr.translate_work("csel/a", norm, raw, tmp_path / "out", tmp_path / "p",
                             clients=FakeClients())
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert "verses" in rec and "paragraphs" not in rec


def test_failed_requests_are_retried_once_then_kept_for_resuming(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mtr, "DOC_MAX_CHARS", 15)  # one request per paragraph
    norm, raw = corpus(tmp_path, CHUNKS)
    out_dir, partial = tmp_path / "out", tmp_path / "partial"
    # The first request fails twice (both its attempts); the others succeed.
    with pytest.raises(mtr.MachineTranslateError, match="1 requests failed"):
        mtr.translate_work("csel/a", norm, raw, out_dir, partial, workers=1,
                           clients=FakeClients(fail=2))
    assert not (out_dir / "mt-eng/csel/a.json").exists()     # all or nothing
    assert (partial / "mt-eng/csel/a.json").exists()
    again = FakeClients()
    mtr.translate_work("csel/a", norm, raw, out_dir, partial, workers=1, clients=again)
    assert len(again.calls) == 1                                # only the failed one
    assert not (partial / "mt-eng/csel/a.json").exists()


def test_stale_and_update_retranslate_only_what_changed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(mtr, "DOC_MAX_CHARS", 15)
    norm, raw = corpus(tmp_path, CHUNKS)
    out_dir = tmp_path / "out"
    mtr.translate_work("csel/a", norm, raw, out_dir, tmp_path / "p", clients=FakeClients())
    assert mtr.stale(norm, out_dir) == []
    changed = [*CHUNKS[:3], chunk("A.2", "Tertia pars mutata.")]
    (norm / "csel/a.json").write_text(json.dumps(changed), encoding="utf-8")
    ((work_id, why),) = mtr.stale(norm, out_dir)
    assert work_id == "mt-eng/csel/a" and why.startswith("1 paragraphs new or changed")
    fake = FakeClients()
    mtr.translate_work("csel/a", norm, raw, out_dir, tmp_path / "p", update=True, clients=fake)
    assert len(fake.calls) == 1 and "Tertia pars mutata." in fake.calls[0]
    assert mtr.stale(norm, out_dir) == []


def test_english_and_unknown_languages_are_refused(tmp_path: Path):
    norm, raw = corpus(tmp_path, CHUNKS)
    with pytest.raises(mtr.MachineTranslateError, match="not in"):
        mtr.translate_work("csel/zzz", norm, raw, tmp_path / "o", tmp_path / "p",
                           clients=FakeClients())


def test_document_languages_are_not_enrolled_for_search_translation():
    from scripts.embed_eval.translate import LANGUAGE_NAMES

    assert {"grc", "lat"} <= set(mtr.DOCUMENT_LANGUAGES)
    assert "grc" not in LANGUAGE_NAMES and "lat" not in LANGUAGE_NAMES


# --- the tracked machine translations --------------------------------------------


def test_tracked_machine_translations_name_an_original_in_the_corpus():
    """Every data/raw/mt-eng file (plain git) translates a work in _works.jsonl."""
    mt_dir = REPO / "data/raw/mt-eng"
    files = sorted(mt_dir.rglob("*.json")) if mt_dir.is_dir() else []
    if not files:
        pytest.skip("no machine translations yet")
    works = {json.loads(line)["work"]["work_id"]: json.loads(line)["path"]
             for line in (REPO / "data/normalized/_works.jsonl").read_text().splitlines() if line}
    for path in files:
        rec = json.loads(path.read_text(encoding="utf-8"))
        original = rec["machine_translation"]["original"]
        assert original in works, f"{path}: original {original} not in the corpus"
        assert rec["work"]["translation_of"] == original
        assert rec["work"]["work_id"] == f"mt-eng/{original}"
        assert path.relative_to(mt_dir).as_posix() == works[original]


def test_machine_translation_raw_files_are_plain_git():
    attrs = (REPO / ".gitattributes").read_text(encoding="utf-8")
    assert "data/raw/mt-eng/** !filter !diff !merge !text" in attrs
    rows = (REPO / "patristica/data/anchored_sources.csv").read_text(encoding="utf-8")
    assert "\nmt-eng,," in rows   # derived verses cut on the original (#304)


# --- export and search context ----------------------------------------------------


def test_export_marks_machine_translations_only():
    from patristica.models import Work
    from scripts.export_library import index_row

    human = index_row(Work(**work("npnf/b", "eng", "csel/b")), "works/x.json", 3)
    machine = index_row(Work(**work("mt-eng/csel/b", "eng", "csel/b", source_id="mt-eng")),
                        "works/y.json", 3)
    assert "machine_translation" not in human
    assert machine["machine_translation"] is True


def test_search_context_ranks_machine_translations_after_published_ones():
    pytest.importorskip("fastapi")
    from api import context as ctx

    def u(work_id: str, source_id: str, translation_of: str | None = None) -> ctx.EnglishUnit:
        return ctx.EnglishUnit(work_id, 4, "R.4", f"{work_id} text", source_id, "Ed.",
                               translation_of)

    hit = {"chunk_id": "w#R.1", "work_id": "w", "work": {"genre": "patristic"}}
    mt_unit = u("mt-eng/w", "mt-eng", translation_of="w")
    both = {"w#R.1": [mt_unit, u("z/npnf", "npnf", translation_of="other")]}
    version = ctx.english_version(hit, None, None, both)
    assert (version["work_id"], version["machine"]) == ("z/npnf", False)
    # Alone, the machine translation is the English context, marked as machine and
    # linked to its passage like a published version (the web app links it, #424).
    version = ctx.english_version(hit, None, None, {"w#R.1": [mt_unit]})
    assert version["machine"] is True
    assert (version["work_id"], version["canonical_ref"]) == ("mt-eng/w", "R.4")
    assert version["source_label"] == "Patristica machine translations (English)"


# --- the search database ----------------------------------------------------------


def _add_machine_translation(norm: Path, store: Path) -> str:
    """Add an MT of the fixture's Syriac hymns, with a vector in its shard (as anchor writes)."""
    import numpy as np

    from patristica import embeddings as emb
    from tests import index_fixture as fx

    work_id, path = "mt-eng/pta/hymns", "mt-eng/pta/hymns.json"
    w = {"work_id": work_id, "source_id": "mt-eng", "title": "Hymns on Faith",
         "author": "Ephrem", "author_ids": ["ephrem-the-syrian"], "genre": "patristic",
         "language": "eng", "license": "cc-by-sa-4.0", "date_composed": 360,
         "date_range": [350, 373], "date_confidence": "approximate", "tradition": "syriac",
         "edition": "Machine translation", "provenance_url": None, "translation_of": "pta/hymns"}
    text = "Our faith is truly glorious, says the machine."
    cid = f"{work_id}#Hymn.1.1"
    chunks = [{"chunk_id": cid, "work_id": work_id, "canonical_ref": "Hymn.1.1",
               "language": "eng", "text": text, "chunk_index": 0, "context_before": None,
               "context_after": None, "date_composed": 360, "date_range": [350, 373],
               "date_confidence": "approximate", "out_of_period": False,
               "translation_group_id": None}]
    (norm / path).parent.mkdir(parents=True, exist_ok=True)
    (norm / path).write_text(json.dumps(chunks), encoding="utf-8")
    with (norm / "_works.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"path": path, "work": w}) + "\n")
    emb.save(store, emb.WorkEmbeddings(
        work_id, path, {fx.RUN.key: fx.RUN},
        [emb.Row(cid, emb.KIND_TEXT, text_sha(text), fx.RUN.key)],
        np.asarray([fx.direction(40)], dtype=np.float16)))
    return cid


def test_machine_translations_are_loaded_but_never_searched(pg_url: str, tmp_path: Path):
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("fastapi")
    from api import keyword as api_kw
    from api.search import Filters
    from scripts import build_index
    from tests import index_fixture as fx

    norm, trans, store = fx.write_corpus(tmp_path)
    cid = _add_machine_translation(norm, store)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        # Its chunk is there for the reader and the search context, its vector is not.
        assert conn.execute("SELECT text FROM chunks WHERE chunk_id = %s",
                            (cid,)).fetchone()[0].startswith("Our faith")
        assert conn.execute("SELECT count(*) FROM chunk_vectors WHERE work_id = %s",
                            ("mt-eng/pta/hymns",)).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0] == 5
        # Keyword search skips it; the same phrase still finds published English.
        where, params = Filters().sql()
        rows, _ = api_kw.phrase_search(conn, ["faith is truly glorious"], where, params, 20)
        assert rows == []
        rows, _ = api_kw.phrase_search(conn, ["In the beginning"], where, params, 20)
        assert [r[0] for r in rows] == ["kjv/gen#Gen.1.1"]


def test_candidate_rows_filter_sort_and_limit(tmp_path: Path):
    """The nightly agent filters with the tool itself, never with shell text tools (#432)."""
    norm = tmp_path / "normalized"
    works = [work("csel/small"), work("csel/big"), work("pta/mid", "grc"),
             work("cantus/hymn", genre="liturgical"), work("csel/mid")]
    sizes = {"csel/small": 10, "csel/big": 500, "pta/mid": 100, "cantus/hymn": 50,
             "csel/mid": 100}
    lines = []
    for w in works:
        path = f"{w['work_id']}.json"
        (norm / path).parent.mkdir(parents=True, exist_ok=True)
        (norm / path).write_text(json.dumps([chunk("A.1", "x" * sizes[w["work_id"]])]),
                                 encoding="utf-8")
        lines.append(json.dumps({"path": path, "work": w}))
    (norm / "_works.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def rows(**kw) -> list[str]:
        return [r["work_id"] for r in mtr.candidate_rows(norm, **kw)]

    assert rows(min_chars=50, max_chars=100, exclude_sources=["cantus"], sort="chars") == [
        "csel/mid", "pta/mid"]
    assert rows(langs=["grc"]) == ["pta/mid"]
    assert rows(genres=["liturgical"]) == ["cantus/hymn"]
    assert rows(works=["csel/big"])[0] == "csel/big"
    assert rows(sort="chars", limit=2) == ["csel/small", "cantus/hymn"]
    (r,) = mtr.candidate_rows(norm, works=["csel/big"])
    assert r["chars"] == 500 and r["requests"] == 1 and r["versions"] == []


def test_candidates_skip_works_with_an_mt_raw_file(tmp_path: Path):
    """A merged MT is in data/raw/mt-eng before the pipeline normalizes it (#444)."""
    norm, raw = tmp_path / "normalized", tmp_path / "raw"
    for w in ("csel/a", "csel/b"):
        (norm / w).parent.mkdir(parents=True, exist_ok=True)
        (norm / f"{w}.json").write_text(json.dumps([chunk("A.1", "Lorem ipsum.")]),
                                        encoding="utf-8")
    (norm / "_works.jsonl").write_text("".join(
        json.dumps({"path": f"{w}.json", "work": work(w)}) + "\n"
        for w in ("csel/a", "csel/b")), encoding="utf-8")
    (raw / "mt-eng/csel").mkdir(parents=True)
    (raw / "mt-eng/csel/a.json").write_text("{}", encoding="utf-8")
    assert [r["work_id"] for r in mtr.candidate_rows(norm, output_dir=raw)] == ["csel/b"]
    assert len(mtr.candidate_rows(norm)) == 2
