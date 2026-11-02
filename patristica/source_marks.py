"""Editorial marks that ``scripts.normalize`` adds for a source whose raw data
can't be re-ingested with them (#236).

A source's ingestor normally writes its editorial spans on the raw units
(``{"ref", "text", "editorial": [[start, end, kind], …]}``). CANTUS can't be
re-ingested offline (its CSVs aren't cached, #215), so its chant metadata is
marked here, from the raw text, when normalize reads it (#163).
"""

from __future__ import annotations

import re

#: The chant metadata CANTUS's ingestor puts before every chant: feast,
#: service, genre, position, Cantus ID and mode, each in brackets
#: (``[Fer. 3 Maj. Hebd.] [L] [A] [5] [CANTUS:002263] [mode:8] Dixerunt…``).
#: The prefix ends at its last ``[CANTUS:…]`` or ``[mode:…]`` token; brackets
#: after that are the chant text's own (CANTUS's reconstructions).
_LEADING_BRACKETS = re.compile(r"^(?:\s*\[[^\]]*\])+")
_ID_OR_MODE = re.compile(r"\[(?:CANTUS|mode):[^\]]*\]")


def cantus_prefix_end(text: str) -> int | None:
    """End of a CANTUS unit's metadata prefix in *text*, or None if it has none."""
    run = _LEADING_BRACKETS.match(text)
    if not run:
        return None
    ends = [m.end() for m in _ID_OR_MODE.finditer(text, 0, run.end())]
    return ends[-1] if ends else None


def mark_units(source_id: str, units: list[dict]) -> list[dict]:
    """*units* with the editorial spans normalize adds for *source_id*."""
    if source_id != "cantus":
        return units
    out: list[dict] = []
    for unit in units:
        end = cantus_prefix_end(unit.get("text", ""))
        if end is None:
            out.append(unit)
            continue
        spans = [[0, end, "metadata"]] + [s for s in unit.get("editorial", []) if s[0] >= end]
        out.append({**unit, "editorial": spans})
    return out
