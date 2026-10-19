"""Tests for patristica.versions (work-level version groups, #178)."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from patristica.versions import (
    LINKS_PATH,
    RELATIONS,
    VersionLink,
    VersionLinkError,
    cts_work,
    derive_version_groups,
    language_pair_counts,
    load_version_links,
    scripture_book,
)

WORKS_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "normalized" / "_works.jsonl"


def _manifest() -> list[dict]:
    return [json.loads(line) for line in WORKS_MANIFEST.read_text(encoding="utf-8").splitlines()]


def _works() -> dict[str, dict]:
    return {rec["work"]["work_id"]: rec["work"] for rec in _manifest()}


def _write(tmp_path: Path, rows: list[str]) -> Path:
    p = tmp_path / "links.csv"
    p.write_text("work_id,other_work_id,relation,reason\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


class TestKeys:
    def test_scripture_book(self) -> None:
        assert scripture_book("kjv/gen") == "gen"
        assert scripture_book("lxx-rahlfs/pssol") == "pssol"
        assert scripture_book("first1k/tlg1463/tlg001/1st1K-grc1") is None
        assert scripture_book("anf-works/gospel-of-nicodemus") is None

    def test_cts_work(self) -> None:
        assert cts_work("first1k/tlg0555/tlg004/1st1K-grc1") == "tlg0555/tlg004"
        assert cts_work("perseus/tlg0555/tlg004/perseus-grc2") == "tlg0555/tlg004"
        # PTA numbers its own text groups: never the same key as First1K/Perseus.
        assert cts_work("pta/pta0007/pta007/pta-grc1") == "pta:pta0007/pta007"
        assert cts_work("ogpg/vol-001/1-clementis") is None
        assert cts_work("pta/pta0007") is None


class TestLoadLinks:
    def test_reads_rows(self, tmp_path: Path) -> None:
        p = _write(tmp_path, ["a/x,b/y,same_work,because"])
        assert load_version_links(p) == [VersionLink("a/x", "b/y", "same_work", "because")]

    @pytest.mark.parametrize("row, message", [
        ("a/x,a/x,same_work,r", "itself"),
        ("a/x,b/y,sibling,r", "unknown relation"),
        ("a/x,b/y,same_work,", "no reason"),
        (",b/y,same_work,r", "empty"),
    ])
    def test_rejects_bad_rows(self, tmp_path: Path, row: str, message: str) -> None:
        with pytest.raises(VersionLinkError, match=message):
            load_version_links(_write(tmp_path, [row]))

    def test_rejects_duplicate_pair_in_either_order(self, tmp_path: Path) -> None:
        p = _write(tmp_path, ["a/x,b/y,same_work,r", "b/y,a/x,translation_of,r"])
        with pytest.raises(VersionLinkError, match="already linked"):
            load_version_links(p)


class TestDerive:
    def test_translation_star_and_siblings(self) -> None:
        g = derive_version_groups(
            {"first1k/a/b/e1": None, "anf-works/x": "first1k/a/b/e1",
             "npnf-works/y": "first1k/a/b/e1", "ogpg/vol-1/z": None}, links=[])
        assert g.members == {"first1k/a/b/e1": ("anf-works/x", "first1k/a/b/e1", "npnf-works/y")}
        assert g.group("ogpg/vol-1/z") is None

    def test_transitive_through_curated_links(self) -> None:
        g = derive_version_groups(
            {"ogpg/v/a": None, "first1k/t/w/e": None, "anf-works/x": "first1k/t/w/e",
             "oglt-pl/l/m": None},
            links=[VersionLink("ogpg/v/a", "first1k/t/w/e", "different_edition", "r"),
                   VersionLink("oglt-pl/l/m", "ogpg/v/a", "translation_of", "r")])
        # oglt-pl is a translation, so the originals are first1k and ogpg; the smaller wins.
        assert g.members == {
            "first1k/t/w/e": ("anf-works/x", "first1k/t/w/e", "oglt-pl/l/m", "ogpg/v/a")}

    def test_all_translations_falls_back_to_smallest_member(self) -> None:
        g = derive_version_groups(
            {"anf-works/x": None, "npnf-works/y": None},
            links=[VersionLink("npnf-works/y", "anf-works/x", "translation_of", "r"),
                   ])
        assert list(g.members) == ["anf-works/x"]

    def test_scripture_book_across_sources_and_genres(self) -> None:
        g = derive_version_groups(
            {"kjv/gen": None, "oshb/gen": None, "lxx-rahlfs/gen": None, "kjv/exod": None,
             "gez/1en": None, "coptic-nt/1en": None, "first1k/tlg1463/tlg001/1st1K-grc1": None},
            links=[VersionLink("first1k/tlg1463/tlg001/1st1K-grc1", "gez/1en", "same_work", "r")])
        assert g.members == {
            "book:1en": ("coptic-nt/1en", "first1k/tlg1463/tlg001/1st1K-grc1", "gez/1en"),
            "book:gen": ("kjv/gen", "lxx-rahlfs/gen", "oshb/gen"),
        }
        assert g.group("kjv/exod") is None

    def test_cts_editions_group(self) -> None:
        g = derive_version_groups(
            {"first1k/tlg0555/tlg004/1st1K-grc1": None, "perseus/tlg0555/tlg004/perseus-grc2": None,
             "pta/pta0001/pta014/pta-grc1": None, "pta/pta0001/pta014/pta-xcl1": None,
             "pta/tlg0555/tlg004/pta-grc1": None}, links=[])
        assert sorted(g.members.values()) == [
            ("first1k/tlg0555/tlg004/1st1K-grc1", "perseus/tlg0555/tlg004/perseus-grc2"),
            ("pta/pta0001/pta014/pta-grc1", "pta/pta0001/pta014/pta-xcl1"),
        ]

    def test_dangling_links_are_reported_not_applied(self) -> None:
        g = derive_version_groups(
            {"anf-works/x": "first1k/gone", "kjv/gen": None},
            links=[VersionLink("kjv/gen", "oshb/gen", "same_work", "r")])
        assert g.members == {}
        assert g.dangling == (("anf-works/x", "first1k/gone"), ("kjv/gen", "oshb/gen"))

    def test_independent_of_input_order(self) -> None:
        works = {w: t for w, t in (
            ("kjv/gen", None), ("oshb/gen", None), ("ogpg/v/a", None), ("first1k/t/w/e", None),
            ("anf-works/x", "first1k/t/w/e"), ("oglt-pl/l/m", None), ("perseus/t/w/e2", None))}
        links = [VersionLink("ogpg/v/a", "first1k/t/w/e", "different_edition", "r"),
                 VersionLink("oglt-pl/l/m", "ogpg/v/a", "translation_of", "r")]
        expected = derive_version_groups(works, links)
        rng = random.Random(0)
        for _ in range(5):
            items = list(works.items())
            rng.shuffle(items)
            shuffled_links = links[:]
            rng.shuffle(shuffled_links)
            assert derive_version_groups(dict(items), shuffled_links) == expected

    def test_language_pair_counts(self) -> None:
        g = derive_version_groups(
            {"first1k/t/w/e1": None, "first1k/t/w/e2": None, "anf-works/x": "first1k/t/w/e1",
             "kjv/gen": None, "oshb/gen": None}, links=[])
        lang = {"first1k/t/w/e1": "grc", "first1k/t/w/e2": "grc", "anf-works/x": "eng",
                "kjv/gen": "eng", "oshb/gen": "hbo"}
        assert language_pair_counts(g, lang) == [
            ("eng", "grc", 1, 3), ("eng", "hbo", 1, 2), ("grc", "grc", 1, 2)]


class TestTrackedLinks:
    """The curated file against the tracked corpus manifest."""

    def test_file_loads(self) -> None:
        links = load_version_links(LINKS_PATH)
        assert all(link.relation in RELATIONS for link in links)

    def test_every_linked_work_exists(self) -> None:
        works = _works()
        missing = sorted({w for link in load_version_links(LINKS_PATH)
                          for w in (link.work_id, link.other_work_id) if w not in works})
        assert not missing, f"version_links.csv names works not in _works.jsonl: {missing}"

    def test_no_dangling_links(self) -> None:
        works = _works()
        g = derive_version_groups({w: rec.get("translation_of") for w, rec in works.items()})
        assert g.dangling == ()

    def test_curated_links_add_something(self) -> None:
        """A curated link that the derived rules already imply is noise: drop it."""
        works = _works()
        base = derive_version_groups(
            {w: rec.get("translation_of") for w, rec in works.items()}, links=[])
        redundant = [
            (link.work_id, link.other_work_id) for link in load_version_links(LINKS_PATH)
            if base.group(link.work_id) is not None
            and base.group(link.work_id) == base.group(link.other_work_id)
        ]
        assert not redundant, f"links already implied by translation_of/book/CTS: {redundant}"

    def test_translation_of_links_point_at_a_different_language(self) -> None:
        works = _works()
        bad = [(link.work_id, link.other_work_id) for link in load_version_links(LINKS_PATH)
               if link.relation == "translation_of"
               and works[link.work_id]["language"] == works[link.other_work_id]["language"]]
        assert not bad

    def test_different_edition_links_share_a_language(self) -> None:
        works = _works()
        bad = [(link.work_id, link.other_work_id) for link in load_version_links(LINKS_PATH)
               if link.relation == "different_edition"
               and works[link.work_id]["language"] != works[link.other_work_id]["language"]]
        assert not bad

    def test_scripture_book_keys_match_chunk_refs(self) -> None:
        """A Scripture-source work's local id is the book of its refs, lower-cased."""
        root = WORKS_MANIFEST.parent
        wrong = []
        for rec in _manifest():
            wid = rec["work"]["work_id"]
            book = scripture_book(wid)
            if book is None:
                continue
            path = root / rec["path"]
            if not path.exists():
                continue
            chunks = json.loads(path.read_text(encoding="utf-8"))
            books = {c["canonical_ref"].split(".")[0].lower() for c in chunks}
            if books != {book}:
                wrong.append((wid, sorted(books)))
        assert not wrong, f"Scripture works whose refs name another book: {wrong}"

    def test_known_groups(self) -> None:
        works = _works()
        g = derive_version_groups({w: rec.get("translation_of") for w, rec in works.items()})
        gen = g.members["book:gen"]
        for wid in ("kjv/gen", "oshb/gen", "clementine/gen", "lxx-rahlfs/gen", "pta-peshitta/gen"):
            assert wid in gen
        assert g.group("gez/1en") == g.group("coptic-nt/1en") == "book:1en"
        # A translation shares its original's group.
        assert g.group("anf-works/epistle-of-barnabas") == g.group("first1k/tlg1216/tlg001/opp-grc1")

    def test_stable(self) -> None:
        """Two derivations of the tracked corpus agree (no set-order effects)."""
        works = _works()
        a = derive_version_groups({w: rec.get("translation_of") for w, rec in works.items()})
        b = derive_version_groups(
            {w: works[w].get("translation_of") for w in sorted(works, reverse=True)})
        assert a == b
