"""Tests for scripts.describe (#795): everything but the model and Wikipedia calls."""

from __future__ import annotations

from pathlib import Path

from patristica.descriptions import PLACEHOLDER_MODEL, Description
from scripts import describe
from scripts.describe import Subject, match_title, needs, settle


def test_match_title_takes_the_candidate_even_with_a_gloss():
    titles = ["Cyril of Scythopolis", "Scythopolis"]
    assert match_title("Cyril of Scythopolis", titles) == "Cyril of Scythopolis"
    assert match_title("Cyril of Scythopolis (6th-century monk)", titles) == "Cyril of Scythopolis"
    assert match_title("Article title: Scythopolis", titles) == "Scythopolis"
    assert match_title("Cyril of Alexandria", titles) is None


def _subject(key: str, ids: list[str]) -> Subject:
    return Subject(key, ids, key, [], [key])


def test_settle_copies_within_a_group_and_drops_removed_ids():
    have = {
        "a/orig": Description("a/orig", "The work.", None, "claude-sonnet-5-5/p1", ["text:a/orig"]),
        "a/old-mt": Description("a/old-mt", "Lorem.", None, PLACEHOLDER_MODEL),
        "gone/work": Description("gone/work", "Stale."),
    }
    subjects = [_subject("g", ["a/orig", "a/new-eng", "a/old-mt"]), _subject("b/x", ["b/x"])]
    assert settle(subjects, have) == (2, 1)
    assert have["a/new-eng"].text == have["a/old-mt"].text == "The work."
    assert "gone/work" not in have
    assert not needs(subjects[0], have, redo=False)
    assert needs(subjects[1], have, redo=False)
    assert needs(subjects[0], have, redo=True)


def test_prompt_has_facts_excerpt_and_candidates(tmp_path: Path):
    work = tmp_path / "w.json"
    work.write_text('[{"chunk_index": 1, "text": "second"}, {"chunk_index": 0, "text": "first"}]')
    s = Subject("x", ["x"], "Work: X", ["Author: anonymous"], ["X"], [("x", work)])
    s.load_excerpt()
    text = s.prompt([{"title": "X (text)", "description": "a text", "extract": "X is a text."}])
    assert "- Author: anonymous" in text
    assert "first second" in text and s.excerpt_source == "x"
    assert "### Article title: X (text)\nShort description: a text\nX is a text." in text
    assert "(none found)" in Subject("y", ["y"], "Work: Y", [], ["Y"]).prompt([])


def test_unreadable_text_gives_no_excerpt(tmp_path: Path):
    pointer = tmp_path / "w.json"
    pointer.write_text("version https://git-lfs.github.com/spec/v1\n")
    assert describe.read_excerpt(pointer) is None
    assert describe.read_excerpt(tmp_path / "missing.json") is None


def test_dates_and_urls():
    assert describe.year(-400) == "400 BC"
    assert describe.wikipedia_url("Ælfric of Eynsham") == (
        "https://en.wikipedia.org/wiki/%C3%86lfric_of_Eynsham")
    assert describe.wikipedia_url("Origen (theologian)").endswith("/Origen_(theologian)")


def test_text_problem_flags_length_and_source_talk():
    assert describe.text_problem("word " * 90) is None
    assert "101 words" in describe.text_problem("word " * 101)
    assert describe.text_problem("The catalogue dates his activity to 400.") is not None
    assert describe.text_problem("The Panarion is a catalogue of heresies.") is None
    assert describe.text_problem("Its date is uncertain in the catalogue of Gennadius.") is None


def test_mixed_groups_split_a_collection_from_its_parts():
    """#804: "translations" of a collection that are different pieces of it get
    their own descriptions; true versions still share one."""
    ws = [
        {"work_id": "pl/letters", "language": "lat", "title": "Epistolae: prima classis"},
        {"work_id": "en/sel", "language": "eng", "title": "Selected Letters",
         "translation_of": "pl/letters"},
        {"work_id": "en/1-63", "language": "eng", "title": "Letters 1-63",
         "translation_of": "pl/letters"},
        {"work_id": "en/aux", "language": "eng",
         "title": "Sermon Against Auxentius on the Giving Up of the Basilicas",
         "translation_of": "pl/letters"},
    ]
    assert describe.mixed(ws)
    assert describe.clusters(ws) == [["en/1-63", "en/sel"], ["en/aux"], ["pl/letters"]]

    versions = [{"work_id": "grc", "language": "grc", "title": "De Filio (Orat. 29)"},
                {"work_id": "pg", "language": "grc",
                 "title": "Oratio 29: Oratio theologica III (De Filio I)"},
                {"work_id": "eng", "language": "eng", "title": "Third Theological Oration",
                 "translation_of": "grc"}]
    assert not describe.mixed(versions)
