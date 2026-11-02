"""
Check every OGPG work's boundaries in the raw data: does it start and end cleanly?

The OGPG ingestor (``scripts/ingest/ogpg.py``) cuts Migne volumes into works by
column ranges; a work whose first unit starts mid-sentence, or whose last unit
breaks off or ends in Migne's critical apparatus, has lost text at a boundary
(or the OCR lost it; #531, #453, #165).  This lists such works and counts them,
so a change to the ingestor can be measured before and after::

    uv run python -m scripts.ogpg_boundaries [--raw-dir data/raw/ogpg] [--list]

Heuristics, per work (the remainder works ``{vol}/other`` are left out):

* **starts mid-sentence**: the first letter of the first unit is lower case
  (Greek or Latin), i.e. not a heading, a capital or a numbered section;
* **ends mid-sentence**: the last unit doesn't end with sentence punctuation
  (``. · ; ! :`` or a closing bracket or quote after one);
* **ends in apparatus**: the last unit's end has a manuscript or edition siglum
  (``Colb.``, ``Reg.``, ``Savil.``, ``ed.`` …) or a bracketed note number.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from patristica.console import setup_logging

log = logging.getLogger(__name__)

_END_OK = re.compile(r"(?:[.·;!:;]|Ἀμήν|ἀμήν)[\s’'\"»)\]]*$")
_APPARATUS = re.compile(
    r"\b(?:Colb|Culb|Coisl|Reg|Regg|Savil|Morel|Edit|edit|ed|codd?|om|Jes|Vat|Bas)\.\s*"
    r"|\(\d{1,3}\)\s*\S+\s*$")
_TAIL = 120


@dataclass
class Boundary:
    work: str
    start_mid: bool
    end_mid: bool
    end_apparatus: bool
    first: str
    last: str


def first_letter(text: str) -> str | None:
    for c in text:
        if c.isalpha():
            return c
    return None


def check_work(path: Path, root: Path) -> Boundary | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    paras = data.get("paragraphs") or []
    if not paras:
        return None
    first, last = paras[0]["text"].strip(), paras[-1]["text"].strip()
    letter = first_letter(first)
    tail = last[-_TAIL:]
    return Boundary(
        work=f"ogpg/{path.relative_to(root).with_suffix('').as_posix()}",
        start_mid=bool(letter) and letter.islower(),
        end_mid=not _END_OK.search(last),
        end_apparatus=bool(_APPARATUS.search(tail)),
        first=first[:80],
        last=last[-80:],
    )


def check(root: Path) -> list[Boundary]:
    """Boundaries of every OGPG work under ``root`` (``data/raw/ogpg``)."""
    out: list[Boundary] = []
    for path in sorted(root.rglob("*.json")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("_") or path.stem == "other":
            continue
        b = check_work(path, root)
        if b is not None:
            out.append(b)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/ogpg"))
    parser.add_argument("--list", action="store_true", help="list the flagged works")
    args = parser.parse_args()
    setup_logging()
    found = check(args.raw_dir)
    start = [b for b in found if b.start_mid]
    end = [b for b in found if b.end_mid or b.end_apparatus]
    if args.list:
        for b in found:
            flags = [n for n, f in (("start", b.start_mid), ("end", b.end_mid),
                                    ("apparatus", b.end_apparatus)) if f]
            if flags:
                print(f"{b.work}\t{','.join(flags)}\t{b.first!r}\t{b.last!r}")
    log.info("OGPG boundaries: %d works; %d start mid-sentence, %d end mid-sentence "
             "or in apparatus (%d both)", len(found), len(start), len(end),
             len({b.work for b in start} & {b.work for b in end}))


if __name__ == "__main__":
    main()
