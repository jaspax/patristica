"""Editorial marks added at normalize: CANTUS metadata (#163), headings and versify (#259)."""

from __future__ import annotations

from patristica.models import Chunk
from patristica.source_marks import cantus_prefix_end, mark_units
from scripts.normalize import _heading_units


def test_cantus_prefix_ends_at_its_id_or_mode() -> None:
    text = "[Fer. 3 Maj. Hebd.] [L] [A] [5] [CANTUS:002263] [mode:8] Dixerunt impii"
    prefix = "[Fer. 3 Maj. Hebd.] [L] [A] [5] [CANTUS:002263] [mode:8]"
    assert text[:cantus_prefix_end(text)] == prefix
    # The chant's own brackets after the mode stay text.
    text = "[X] [A] [CANTUS:a1] [mode:2] [Aspiciens a longe] ecce"
    assert text[cantus_prefix_end(text):] == " [Aspiciens a longe] ecce"
    assert cantus_prefix_end("[X] [A] no id or mode") is None
    assert cantus_prefix_end("Dixerunt [CANTUS:1]") is None


def test_mark_units_only_cantus() -> None:
    units = [{"ref": "a", "text": "[A] [CANTUS:1] Alleluia"}, {"ref": "b", "text": "plain"}]
    assert mark_units("cantus", units)[0]["editorial"] == [[0, 14, "metadata"]]
    assert "editorial" not in mark_units("cantus", units)[1]
    assert mark_units("first1k", units) == units


def _chunk(ref: str, text: str) -> Chunk:
    return Chunk(chunk_id=f"w#{ref}", work_id="w", source_id="first1k", canonical_ref=ref,
                 chunk_index=0, language="grc", text=text, genre="patristic",
                 date_confidence="uncertain")


def test_heading_units() -> None:
    body = " ".join(f"λόγος {i} ἐστὶν ἐν ἀρχῇ καὶ ὁ λόγος ἦν πρὸς τὸν θεόν." for i in range(40))
    head = "ΚΕΦΑΛΑΙΟΝ ΠΡΩΤΟΝ ΠΕΡΙ ΤΟΥ ΛΟΓΟΥ ΚΑΙ ΤΗΣ ΣΟΦΙΑΣ " * 6
    title = _chunk("1", head.strip())
    headed = _chunk("2", f"{head}{body}")
    plain = _chunk("3", body)
    marks = {title.chunk_id: [[0, len(title.text), "heading"]],
             headed.chunk_id: [[0, len(head) - 1, "heading"]]}
    whole, units = _heading_units([title, headed, plain], marks)
    assert whole == {title.chunk_id}
    pieces = units[headed.chunk_id]
    assert pieces[0].startswith(head.strip())
    # The body is cut where it would be without its heading.
    from patristica.versify import split_text
    alone = split_text(body, "grc")
    assert pieces[1:] == alone[1:] and pieces[0].endswith(alone[0])
    assert plain.chunk_id not in units
