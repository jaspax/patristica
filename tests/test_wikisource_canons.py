"""Greek Wikisource canons (#22): sections to canons, markup, commentary, pinned pages."""

from __future__ import annotations

import pytest

from scripts.ingest.wikisource_canons import (
    PAGES,
    Page,
    canon_paragraphs,
    greek_numeral,
    parse_page,
)

_PAGE = Page("test", "Κανόνες", 1, "Test", 2, "Test canons", 400, (400, 400),
             skip={3: "an epitome, not a canon"})

_WIKITEXT = """{{Πολυτονικό}}
{{Τίτλος|<u>Κανόνες</u>|<br><small>Συνεκλήθη</small>|325 μ.Χ.|}}

==Κανὼν Α'==

Κανὼν Α'
Εἴ τις ἐν νόσῳ ὑπὸ ἰατρῶν ἐχειρουργήθη (1), οὗτος μενέτω ἐν τῷ κλήρῳ.
'''† Αὐρήλιος ἐπίσκοπος ὑπέγραψα.'''

==Κανὼν [[Εικόνα:Koppa2.png|11px]]'==

Τὴν ἐν Νικαίᾳ πίστιν κρατεῖν.
Ἐ ρ μ η ν ε ί α.
Ὁ παρὼν Κανὼν διορίζει…

==Κανὼν Γ'==

Ἀριστ. Οἱ καταδύσει μιᾷ βαπτιζόμενοι.
</div>
<br>
[[Κατηγορία:Οικουμενικές Σύνοδοι|Α]]
"""


def test_sections_become_canons_with_headings_and_paragraphs() -> None:
    assert parse_page(_PAGE, _WIKITEXT) == [
        {"ref": "Test.Canon.1", "text": "Κανὼν Α'"},
        {"ref": "Test.Canon.1.1",
         "text": "Εἴ τις ἐν νόσῳ ὑπὸ ἰατρῶν ἐχειρουργήθη, οὗτος μενέτω ἐν τῷ κλήρῳ."},
        {"ref": "Test.Canon.1.2", "text": "† Αὐρήλιος ἐπίσκοπος ὑπέγραψα."},
        {"ref": "Test.Canon.2", "text": "Κανὼν Β'"},  # the heading's numeral was an image
        {"ref": "Test.Canon.2.1", "text": "Τὴν ἐν Νικαίᾳ πίστιν κρατεῖν."},  # commentary cut
    ]


def test_canon_count_is_checked() -> None:
    # Without the skip, the epitome would count as a third canon.
    page = Page("test", "Κανόνες", 1, "Test", 2, "Test canons", 400, (400, 400))
    with pytest.raises(ValueError, match="3 canons at revision 1, expected 2"):
        parse_page(page, _WIKITEXT)


def test_commentary_heading_ends_the_canon() -> None:
    assert canon_paragraphs("Κανὼν Β'", "Κείμενον.\nΣ υ μ φ ω ν ί α\nἌλλο.") == ["Κείμενον."]


def test_greek_numerals() -> None:
    assert [greek_numeral(n) for n in (1, 6, 16, 90, 133)] == ["Α'", "ΣΤ'", "ΙΣΤ'", "Ϟ'", "ΡΛΓ'"]


def test_pinned_pages_are_before_the_2012_pedalion_edits() -> None:
    # The Pedalion prolegomena and commentary came in with revisions from 54971 on
    # (20–22 September 2012); every pin is an earlier revision.
    assert all(p.revid < 54971 for p in PAGES)
    assert len({p.slug for p in PAGES}) == len({p.prefix for p in PAGES}) == len(PAGES)
