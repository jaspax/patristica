"""Tests for Migne's notes in OGPG paragraphs, marked editorial (#450)."""

from __future__ import annotations

from scripts.ingest import _ogpg_notes as notes
from scripts.ingest import ogpg

BODY = ("ἵνα, ὅταν ἐνθένδε ἀπαλλαγῶμεν, δέξωνται ἡμᾶς εἰς τὰς αἰωνίους σκηνὰς, "
        "ἐν αὐτῷ Χριστῷ (46) τῷ Κυρίῳ ἡμῶν, ᾧ ἡ δόξα (47) εἰς τοὺς αἰῶνας. Ἀμήν.")
PLAIN = ("Ἀγαπητοί, μιμησώμεθα τὴν τοῦ Θεοῦ φιλανθρωπίαν, καὶ τοῖς δεομένοις τὰ "
         "ἡμέτερα μεταδῶμεν, ἵνα καὶ αὐτοὶ τῆς ἐκεῖθεν χάριτος τύχωμεν. ") * 3
NOTES = ("(58) Καὶ θαυμάσιον. Deest καί in Reg. a. Deinde in schol. θαυμαστόν. "
         "(40) Τοὺς πτωχοὺς κοινωνούς, etc. Reg. a, κοινόν. Jes., πτωχοὺς ἔργον.")


def test_notes_ending_a_paragraph_are_marked():
    text = f"{BODY} {NOTES}"
    k = text.index("(58)")
    assert notes.note_spans(text) == [[k, len(text), "note"]]


def test_note_references_in_the_text_are_not_notes():
    # (46) and (47) refer to notes; the block starts at the first note with a siglum.
    assert notes.note_spans(BODY) == []
    text = f"{BODY} {NOTES}"
    assert notes.note_spans(text)[0][0] > text.index("Ἀμήν")


def test_a_paragraph_of_notes_is_marked_whole():
    assert notes.note_spans(NOTES) == [[0, len(NOTES), "note"]]


def test_body_text_after_the_notes_is_not_marked():
    # The notes don't run to the end: a long stretch of text follows them.
    text = f"{NOTES} {PLAIN}"
    assert notes.note_spans(text) == []


def test_body_text_with_a_late_siglum_is_not_a_note():
    text = f"(16) {PLAIN} Reg. 2, κατάβασις."
    assert notes.note_spans(text) == []


def test_reference_followed_by_comma_is_no_note_number():
    text = "(86), ὥστε τῷ μὲν ἐγγὺς ὄντι Reg. 1 ἀγαπῶν, κατήγορος ἑαυτοῦ γίνεται."
    assert notes.note_spans(text) == []


def test_split_volume_writes_the_spans():
    extract = {"repo": "Vol.-35", "pipeline": {"primary_scan": "hvd.x_ocr"},
               "page_heads": [("010", [1]), ("011", [3])],
               "paragraphs": [{"stem": "010", "title": None, "text": f"{BODY} {NOTES}"},
                              {"stem": "011", "title": None, "text": BODY}]}
    [(_, _, units)] = ogpg.split_volume("Vol.-35", extract, [])
    assert units[0]["editorial"] == [[len(BODY) + 1, len(BODY) + 1 + len(NOTES), "note"]]
    assert "editorial" not in units[1]
