"""GOA DCS liturgies: rubrics marked as editorial spans of kind "rubric" (#500)."""

from __future__ import annotations

from patristica import editorial
from scripts.ingest._goarch_common import parse_dcs_liturgy

_HTML = """
<html><body><table id="biTable">
<tr><td class="leftCell">
<p class="mixed"><span class="smaller"><span class="kvp">ΕΝΑΡΞΙΣ, ΕΙΡΗΝΙΚΑ</span></span></p>
<p class="actor"><span class="kvp">ΙΕΡΕΥΣ</span>
</p>
<p class="dialog"><span class="kvp">Εὐλογημένη ἡ βασιλεία.</span></p>
<p class="actor"><span class="kvp">ΧΟΡΟΣ</span> <span class="smaller"><span class="kvp">(μεθʼ ἑκάστην δέησιν)</span></span></p>
<p class="actor"><span class="kvp">ΧΟΡΟΣ·</span> <span class="dialogafteractor"><span class="kvp">Σοί, Κύριε.</span></span></p>
<p class="inaudible"><span class="boldred"><span class="kvp">ΙΕΡΕΥΣ</span>
</span> <span class="smallred"><span class="kvp">(χαμηλοφώνως)</span></span></p>
<p class="mixed"><span class="designation"><span class="kvp">Ἀντίφωνον Αʹ</span></span></p>
<p class="mixed"><span class="rubric"><span class="kvp">(Δείτε τά μεταβλητά.)</span></span></p>
<p class="hymn"><span class="kvp">Ἀλληλούϊα.</span> <span class="red"><span class="kvp">(3)</span></span></p>
<p class="dialog"><span class="kvp">Μνήσθητι, Κύριε,</span> <span class="red"><span class="kvp">τοῦ Ἀρχιεπισκόπου ἡμῶν
(δεῖνος).</span></span></p>
<p class="rubric"><span class="kvp">Ὁ Ἱερεὺς αἴρει.</span></p>
</td></tr>
</table></body></html>
"""


def _marked(record: dict) -> list[str]:
    return [record["text"][s:e] for s, e, _ in record.get("editorial", [])]


def test_rubric_spans() -> None:
    paras = parse_dcs_liturgy(_HTML, service_abbrev="Basil")
    by_ref = {p["ref"].rsplit(".", 1)[1]: p for p in paras}
    # Section heading: no marks.
    assert by_ref["0000"]["text"] == "ΕΝΑΡΞΙΣ, ΕΙΡΗΝΙΚΑ"
    assert "editorial" not in by_ref["0000"]
    # Speaker label, whole.
    assert _marked(by_ref["0001"]) == ["ΙΕΡΕΥΣ"]
    # Spoken text: no marks.
    assert "editorial" not in by_ref["0002"]
    # Label and stage direction: one span.
    assert _marked(by_ref["0003"]) == ["ΧΟΡΟΣ (μεθʼ ἑκάστην δέησιν)"]
    # Label with the words spoken after it: only the label.
    assert by_ref["0004"]["text"] == "ΧΟΡΟΣ· Σοί, Κύριε."
    assert _marked(by_ref["0004"]) == ["ΧΟΡΟΣ·"]
    # Red speaker and direction inside an inaudible prayer.
    assert _marked(by_ref["0005"]) == ["ΙΕΡΕΥΣ (χαμηλοφώνως)"]
    # Red label line.
    assert _marked(by_ref["0006"]) == ["Ἀντίφωνον Αʹ"]
    # "(Δείτε τά μεταβλητά.)" in a mixed paragraph is skipped, as before.
    assert by_ref["0007"]["text"] == "Ἀλληλούϊα. (3)"
    assert _marked(by_ref["0007"]) == ["(3)"]
    # Plain red: only the parenthesised placeholder; the commemoration is spoken.
    assert by_ref["0008"]["text"] == "Μνήσθητι, Κύριε, τοῦ Ἀρχιεπισκόπου ἡμῶν (δεῖνος)."
    assert _marked(by_ref["0008"]) == ["(δεῖνος)"]
    assert len(paras) == 9


def test_spans_are_valid_and_text_unchanged() -> None:
    for p in parse_dcs_liturgy(_HTML, service_abbrev="Basil"):
        spans = editorial.check(p["text"], p.get("editorial", []), p["ref"])
        assert all(kind == "rubric" for _, _, kind in spans)
        assert p["text"] == " ".join(p["text"].split())


def test_wholly_rubric_unit_has_no_source_text() -> None:
    paras = parse_dcs_liturgy(_HTML, service_abbrev="Basil")
    label = next(p for p in paras if p["text"] == "ΙΕΡΕΥΣ")
    assert editorial.source_text(label) == ""
    spoken = next(p for p in paras if p["text"].startswith("ΧΟΡΟΣ·"))
    assert editorial.source_text(spoken) == "Σοί, Κύριε."
