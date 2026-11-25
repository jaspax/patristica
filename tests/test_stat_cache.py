"""Tests for patristica.stat_cache and the no-op fast paths built on it (#782)."""

from __future__ import annotations

import enum
import json
from pathlib import Path

import pytest

from patristica import fingerprint, stat_cache
from patristica.stat_cache import StatCache, file_stamps


@pytest.fixture
def no_racy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache files written a moment ago (tests write their files just before)."""
    monkeypatch.setattr(stat_cache, "RACY_SECONDS", 0.0)


def test_a_value_is_kept_while_the_files_and_head_match(tmp_path: Path, no_racy) -> None:
    f, missing = tmp_path / "a.json", tmp_path / "none.json"
    f.write_text("1")
    cache = StatCache(tmp_path / "cache.json", "head")
    stamps = file_stamps([f, missing])
    assert stamps[1] is None
    cache.put("w", stamps, {"n": 3}, tag=["x"])
    cache.save()

    again = StatCache(tmp_path / "cache.json", "head")
    assert again.get("w", file_stamps([f, missing]), ["x"]) == {"n": 3}
    assert again.get("w", file_stamps([f, missing]), ["y"]) is None       # other tag
    assert StatCache(tmp_path / "cache.json", "other").get(
        "w", file_stamps([f, missing]), ["x"]) is None                     # other head
    f.write_text("2")
    assert again.get("w", file_stamps([f, missing]), ["x"]) is None       # rewritten
    f.write_text("1")
    missing.write_text("")
    assert again.get("w", file_stamps([f, missing]), ["x"]) is None       # created


def test_a_file_changed_just_now_is_not_cached(tmp_path: Path) -> None:
    f = tmp_path / "a.json"
    f.write_text("1")
    cache = StatCache(tmp_path / "cache.json", "head")
    cache.put("w", file_stamps([f]), 1)
    assert cache.get("w", file_stamps([f])) is None
    cache.save()
    assert not (tmp_path / "cache.json").exists()


def test_no_path_caches_nothing_and_a_broken_file_starts_afresh(tmp_path: Path,
                                                                 no_racy) -> None:
    f = tmp_path / "a.json"
    f.write_text("1")
    cache = StatCache(None, "head")
    cache.put("w", file_stamps([f]), 1)
    assert cache.get("w", file_stamps([f])) is None
    (tmp_path / "cache.json").write_text("{not json")
    assert StatCache(tmp_path / "cache.json", "head").entries == {}


class Kind(enum.IntEnum):
    TEXT = 0


class Word(str):
    pass


@pytest.mark.parametrize("value", [
    ["a", "b", " c"],
    ("a", 1, [None, True, 1.5, ["x", ("y",)]]),
    [["Gen.1.1", "In the beginning"], ["Gen.1.2", "And the earth"]],
    {"b": [1, {"c": {3, 1}}], 2: "x"},
    [Word("w"), Kind.TEXT],
])
def test_value_hash_is_unchanged_by_the_fast_path(value: object) -> None:
    def slow(v: object) -> object:  # the canonical form before #782
        if isinstance(v, dict):
            return {"__map__": sorted((k if isinstance(k, str) else repr(k), slow(x))
                                      for k, x in v.items())}
        if isinstance(v, (list, tuple)):
            return [slow(x) for x in v]
        if isinstance(v, (set, frozenset)):
            return {"__set__": sorted(repr(x) for x in v)}
        if v is None or isinstance(v, (bool, int, float, str)):
            return v
        return repr(v)

    expected = fingerprint.sha16(json.dumps(slow(value), ensure_ascii=False, sort_keys=True))
    assert fingerprint.value_hash(value) == expected


def test_module_hashes_follow_the_source_not_a_stale_cache(tmp_path: Path) -> None:
    pkg = tmp_path / "patristica"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    mod = pkg / "m.py"
    mod.write_text("X = 1\n")
    first = fingerprint.code_hash("patristica.m", root=tmp_path)
    assert fingerprint.code_hash("patristica.m", root=tmp_path) == first
    mod.write_text("X = 2\n")  # same size, likely the same mtime tick
    assert fingerprint.code_hash("patristica.m", root=tmp_path) != first


def test_embed_reuses_a_clean_work_until_a_file_changes(tmp_path: Path, no_racy,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("numpy")
    from scripts import embed
    from tests.test_embed import FakeEmbedder, run, write_corpus

    write_corpus(tmp_path, {"kjv/gen": ("eng", [("Gen.1.1", "In the beginning God created."),
                                                ("Gen.1.2", "And the earth was void.")])})
    run(tmp_path, FakeEmbedder())
    first = run(tmp_path, FakeEmbedder())   # finds it clean: cached
    assert first.to_embed == 0 and (tmp_path / "cache" / "embed_plan.json").exists()

    real_read = embed.read_rows
    monkeypatch.setattr(embed, "read_rows", lambda p: pytest.fail("read a cached work"))
    again = run(tmp_path, FakeEmbedder())
    assert (again.works, again.units, again.vectors, again.reused, again.to_embed,
            again.written) == (first.works, first.units, first.vectors, first.reused, 0, 0)

    monkeypatch.setattr(embed, "read_rows", real_read)
    write_corpus(tmp_path, {"kjv/gen": ("eng", [("Gen.1.1", "In the beginning God made.")])})
    fake = FakeEmbedder()
    stats = run(tmp_path, fake)
    assert fake.sent == ["In the beginning God made."] and stats.written == 1


def test_anchor_check_reuses_a_current_work_until_a_file_changes(
        tmp_path: Path, no_racy, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("numpy")
    from scripts import anchor
    from scripts import normalize as nz
    from tests.test_anchor import (SENTENCES, FakeEmbedder, embed_work, english, latin,
                                   write_work)

    d = {k: tmp_path / k for k in ("raw", "normalized", "anchors", "embeddings", "scratch")}
    write_work(d["raw"], "orig/w.json", "lat", [latin(SENTENCES[:8]), latin(SENTENCES[8:])])
    write_work(d["raw"], "tr/w.json", "eng", [english(SENTENCES[:8]), english(SENTENCES[8:])],
               translation_of="orig/w")
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"])
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    anchor.run(d["normalized"], d["raw"], d["anchors"], d["embeddings"], d["scratch"],
               embed=FakeEmbedder())
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.CURRENT

    real = anchor.check_work
    monkeypatch.setattr(anchor, "check_work", lambda *a, **k: pytest.fail("checked again"))
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.CURRENT

    monkeypatch.setattr(anchor, "check_work", real)
    write_work(d["raw"], "tr/w.json", "eng",
               [english(SENTENCES[:8]) + " eng999.", english(SENTENCES[8:])],
               translation_of="orig/w")
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"],
                     accept_raw_change=True)
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.WORDS


def test_translate_plan_skips_a_translated_work_until_a_file_changes(
        tmp_path: Path, no_racy, monkeypatch: pytest.MonkeyPatch) -> None:
    from patristica import translations as tr
    from scripts import translate
    from tests.test_translations import PROV, chunk, write_corpus

    store = tmp_path / "translations"
    norm = write_corpus(tmp_path, {"a": ("public_domain", [chunk("1", "ܫܠܡܐ")])})
    a = tr.WorkTranslations(work_id="a", source_path="src/a.json", source_language="syc")
    a.put(tr.ChunkTranslation(chunk_id="a#1", source_sha256=tr.text_sha("ܫܠܡܐ"),
                              provenance=PROV.key, group_size=1, text="peace"), PROV)
    tr.save(store, a, [{"chunk_id": "a#1", "text": "ܫܠܡܐ"}])

    assert translate.plan(norm, store, ["syc"], [], False) == ([], 0)
    monkeypatch.setattr(tr, "load", lambda *a: pytest.fail("read a cached work"))
    assert translate.plan(norm, store, ["syc"], [], False) == ([], 0)

    monkeypatch.undo()
    write_corpus(tmp_path, {"a": ("public_domain", [chunk("1", "ܫܠܡܐ"), chunk("2", "ܐܠܗܐ")])})
    jobs, _ = translate.plan(norm, store, ["syc"], [], False)
    assert [sum(len(g) for g in j.groups) for j in jobs] == [1]
