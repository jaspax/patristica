"""
Migne's critical notes inside OGPG paragraphs, marked as editorial ``note`` spans (#450, #236).

The OCR runs the notes at the foot of a column into the text above them: the
Maurist notes on Gregory of Nazianzus (PG 35–36), ``(58) Καὶ θαυμάσιον.
Deest καί in Reg. … (40) Τοὺς πτωχοὺς, etc. Reg. …, Jes., …``, and the like
in Montfaucon's Chrysostom (``Colb.``, ``Savil.``, ``Morel.``).  A note is
its number, the lemma and the readings of manuscripts and editions, named by
their sigla.

Only a block that is clearly notes is marked: it starts at a note number
whose note names a siglum (a number in the text, ``ἐν Χριστῷ (46) τῷ Κυρίῳ``,
is a reference to a note, not one), and runs to the end of the paragraph in
notes no longer than ``MAX_NOTE`` characters each.  Its text is kept and
marked, never deleted (CLAUDE.md, "Editorial material"); other OCR residue is
#443.
"""

from __future__ import annotations

import re

# A note number as the OCR reads it: ``(58)``, ``( 58 )``, ``93)``, ``'76)``.
_NUMBER = re.compile(r"(?:(?<=\s)|^)[(']?\s?\d{1,3}\s?\)(?!\s*[,;·])")
# Manuscript and edition sigla, and the Latin words of a note's readings.
_SIGLA = re.compile(
    r"\b(?:Regg?|Or\.\s?\d|Jes|Coisl|Colb|Bas|Billius|Bill|Combef|Vat|Savil|Morel|Cypr|"
    r"codd?|Edit|editi|ed)\.|\b(?:Deest|Desunt|desunt|deest|Billius|Montac)\b")
MAX_NOTE = 260
# The first note names a siglum within this many characters (a short lemma).
LEMMA_SPAN = 90


def note_spans(text: str) -> list[list]:
    """``[[start, end, "note"]]`` for a block of notes ending ``text``, or ``[]``."""
    starts = [m.start() for m in _NUMBER.finditer(text)]
    end = len(text.rstrip())
    for i, k in enumerate(starts):
        bounds = starts[i:] + [end]
        notes = [text[a:b] for a, b in zip(bounds, bounds[1:])]
        if not notes or not _SIGLA.search(notes[0][:LEMMA_SPAN]):
            continue
        if all(len(n) <= MAX_NOTE for n in notes):
            return [[k, end, "note"]]
    return []
