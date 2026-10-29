"""Tests for scripts.ingest._ebible_usfm: eBible USFM pre-processing (#393)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.ingest._common import parse_usfm
from scripts.ingest._ebible_usfm import _preprocess_usfm

REPO = Path(__file__).resolve().parents[1]
WEB_NORMALIZED = REPO / "data" / "normalized" / "web"


def _verses(tmp_path: Path, body: str) -> dict[str, str]:
    """Pre-process and parse a one-chapter USFM book; "chapter.verse" → text."""
    f = tmp_path / "x.usfm"
    f.write_text(_preprocess_usfm("\\id JHN\n\\c 17\n" + body), encoding="utf-8")
    return {ref.split(".", 1)[1]: text for ref, text in parse_usfm(f)[1]}


@pytest.mark.parametrize(("body", "expected"), [
    # Strong's-tagged words (\w … \w*), the common case: unchanged.
    ('\\v 1 \\w I|strong="G1473"\\w* \\w have|strong="G2192"\\w* spoken.\n',
     "I have spoken."),
    # Nested words of Jesus (\wj \+w … \+w* \wj*): ran together before #393.
    ('\\v 14 \\wj \\+w I|strong="G1473"\\+w* \\+w have|strong="G2532"\\+w* '
     '\\+w given|strong="G1325"\\+w* \\+w them|strong="G3588"\\+w* '
     '\\+w your|strong="G2532"\\+w* \\+w word|strong="G3056"\\+w*.\\wj*\n',
     "I have given them your word."),
    # \wj* directly after a word, then the next words outside it.
    ('\\v 2 \\wj Follow me\\wj* and he followed.\n', "Follow me and he followed."),
    # \wj* after a space keeps that one space (as always).
    ('\\v 3 \\wj Follow me, \\wj* he said.\n', "Follow me, he said."),
    # An end marker before punctuation adds no space.
    ('\\v 4 \\wj \\+w Yes|strong="G3483"\\+w*\\wj*, he said.\n', "Yes, he said."),
    # Book titles (\bk), Selah (\qs), italics in the Clementine Vulgate (\it).
    ('\\v 5 in \\bk \\+w The|strong="H5921"\\+w* \\+w Book|strong="H5612"\\+w*\\bk*, “Vaheb.”\n',
     "in The Book, “Vaheb.”"),
    ("\\v 6 answer them. \\qs Selah.\\qs* They never change.\n",
     "answer them. Selah. They never change."),
    ("\\v 7 \\it Aleph\\it* Beati immaculati in via.\n", "Aleph Beati immaculati in via."),
    # An end marker at the end of a line, before a poetry line.
    ('\\v 8 \\wj \\+w Blessed|strong="G3107"\\+w* \\+w are|strong="G3588"\\+w*\\wj*\n'
     '\\q2 \\wj \\+w they|strong="G2532"\\+w*.\\wj*\n',
     "Blessed are they."),
    # Space before and after an end marker, then the next line: one space.
    ('\\v 9 \\wj \\+w righteousness|strong="G1343"\\+w*, \\wj*  \n'
     '\\q2 \\wj \\+w for|strong="G3754"\\+w* \\+w they|strong="G2532"\\+w*.\\wj*\n',
     "righteousness, for they."),
    # A run of end markers after a space, and a footnote between them.
    ('\\v 10 \\+w rock|strong="G4073"\\+w* \\wj*\\f + \\fr 16:18 \\ft petra.\\f* '
     '\\wj \\+w I|strong="G1473"\\+w* will build\n',
     "rock I will build"),
    # The non-breaking space between nested closing quotes is kept.
    ("\\v 11 said, \\wj ‘Take up your mat.’\\wj* ”\n", "said, ‘Take up your mat.’ ”"),
])
def test_end_markers_keep_word_breaks(tmp_path: Path, body: str, expected: str) -> None:
    verses = _verses(tmp_path, body)
    assert list(verses.values()) == [expected]


def test_verse_lines_survive(tmp_path: Path) -> None:
    """End-marker removal never joins lines, so verse and chapter markers stay put."""
    verses = _verses(tmp_path, "\\v 1 \\wj one\\wj* \n\\v 2 two \\qs Selah\\qs*\n\\c 18\n\\v 1 three\n")
    assert verses == {"17.1": "one", "17.2": "two Selah", "18.1": "three"}


def _is_lfs_pointer(path: Path) -> bool:
    return path.read_bytes()[:40].startswith(b"version https://git-lfs")


def test_normalized_web_has_no_run_together_words() -> None:
    """#393: 1,255 WEB verses had their words run together ("Ihavegiventhem…")."""
    files = sorted(WEB_NORMALIZED.glob("*.json")) if WEB_NORMALIZED.is_dir() else []
    if not files or any(_is_lfs_pointer(f) for f in files):
        pytest.skip("normalized WEB not materialized")
    run = re.compile(r"[a-z]{25,}")
    bad = [c["chunk_id"] for f in files for c in json.loads(f.read_text(encoding="utf-8"))
           if run.search(c["text"])]
    assert bad == [], f"{len(bad)} WEB verses with run-together words, e.g. {bad[:5]}"
