"""Passage alignments, stored in ``data/alignments/`` (#179).

One tracked JSON file per version group (``patristica.versions``): the group
``book:gen`` is ``data/alignments/book/gen.json``, any other group
``data/alignments/{group id}.json``. ``scripts.align`` writes them
(``patristica.alignment`` holds the method); this module reads and writes the
format and needs no numpy, so the loaders can use it anywhere.

A file holds the alignment groups of one version group. Groups are numbered
``0 … groups − 1`` in the order of the *pivot* version. For each member it
stores, per unit of the work's normalized file (in order), which group the
unit belongs to, and per group the confidence of the member's span in it:

``spans``
    One token per unit: ``.`` the unit is in no group, ``+`` the next group
    (the last group this member used, plus one), ``+N`` / ``-N`` that group
    plus or minus *N*, ``=`` the same group as the unit before. A member's
    units in one group are contiguous, so ``=`` only continues a run.
    Scripture's 1:1 verses are ``+++…``: one byte per unit.
``conf``
    One digit per group the member has, in the order the groups first appear
    in ``spans``: the confidence 0.0–0.9 (rounded down; 9 also stands for
    1.0). The pivot's confidence in a group is the best of the other
    members'.

``ids`` (per member) is ``ids_sha`` of the work's chunk ids, so a loader can
tell whether the spans still count the units it has. ``inputs`` (per member
and for the file) is a hash of everything the
alignment depends on: the units, the vectors used for them and the reference
keys, and for the file the method, its parameters and the members; a file
whose hash still matches is not aligned again. ``run`` records the method,
parameters, model and date of the run that wrote the file.

Groups whose confidence is below ``MIN_CONFIDENCE`` are *flagged*: they stay
in the file, so a reader can see the stretch is uncertain, but
``Alignment.groups`` leaves them out unless asked.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DIR = Path("data/alignments")
FORMAT = 1
#: A member's span in a group counts only at this confidence (tenths).
MIN_CONFIDENCE = 5

_TOKEN = re.compile(r"\.|=|[+-]\d*")


class AlignmentFormatError(ValueError):
    """An alignment file is malformed."""


def ids_sha(chunk_ids: list[str]) -> str:
    """Hash of a work's chunk ids in order: a member's spans hold while it is unchanged."""
    return hashlib.sha256("\n".join(chunk_ids).encode("utf-8")).hexdigest()[:16]


def encode_spans(group_of: list[int]) -> str:
    """Encode a member's unit → group list (−1: no group) as tokens."""
    out: list[str] = []
    last = -1
    prev = -1
    for g in group_of:
        if g < 0:
            out.append(".")
        elif g == prev:
            out.append("=")
        else:
            d = g - last
            out.append("+" if d == 1 else f"+{d}" if d > 0 else f"-{-d}")
            last = g
        prev = g
    return "".join(out)


def decode_spans(spans: str) -> list[int]:
    """Inverse of ``encode_spans``."""
    out: list[int] = []
    last = -1
    prev = -1
    pos = 0
    for m in _TOKEN.finditer(spans):
        if m.start() != pos:
            raise AlignmentFormatError(f"bad token at {pos}: {spans[pos:pos + 10]!r}")
        pos = m.end()
        tok = m.group()
        if tok == ".":
            g = -1
        elif tok == "=":
            if prev < 0:
                raise AlignmentFormatError(f"'=' at {m.start()} continues no group")
            g = prev
        else:
            d = int(tok[1:] or 1)
            g = last + d if tok[0] == "+" else last - d
            if g < 0:
                raise AlignmentFormatError(f"group {g} < 0 at {m.start()}")
            last = g
        out.append(g)
        prev = g
    if pos != len(spans):
        raise AlignmentFormatError(f"bad token at {pos}: {spans[pos:pos + 10]!r}")
    return out


def group_order(group_of: list[int]) -> list[int]:
    """The groups of a member in the order they first appear."""
    seen: dict[int, None] = {}
    for g in group_of:
        if g >= 0:
            seen.setdefault(g, None)
    return list(seen)


@dataclass
class Member:
    work_id: str
    units: int
    inputs: str
    group_of: list[int]  # per unit: group, or −1
    conf: dict[int, int]  # group → confidence in tenths (0–9)
    ids: str = ""  # ids_sha of the work's chunk ids: the units the spans count

    def spans(self) -> dict[int, tuple[int, int]]:
        """group → [first, last + 1) units of this member."""
        out: dict[int, tuple[int, int]] = {}
        for u, g in enumerate(self.group_of):
            if g >= 0:
                out[g] = (out[g][0] if g in out else u, u + 1)
        return out


@dataclass
class Alignment:
    group: str  # version group id
    pivot: str
    groups: int
    inputs: str
    run: dict
    members: dict[str, Member] = field(default_factory=dict)

    def groups_of(self, min_confidence: int = MIN_CONFIDENCE
                  ) -> dict[int, dict[str, tuple[int, int]]]:
        """group → {work_id: [start, end) units}, for spans at *min_confidence* or more.

        The pivot's span counts only alongside another member's, and a group
        needs two members.
        """
        out: dict[int, dict[str, tuple[int, int]]] = {}
        for wid, mem in self.members.items():
            if wid == self.pivot:
                continue
            for g, span in mem.spans().items():
                if mem.conf.get(g, 0) >= min_confidence:
                    out.setdefault(g, {})[wid] = span
        pivot = self.members.get(self.pivot)
        if pivot is not None:
            pspans = pivot.spans()
            for g, spans in out.items():
                if g in pspans:
                    spans[self.pivot] = pspans[g]
        return {g: dict(sorted(s.items())) for g, s in sorted(out.items()) if len(s) >= 2}


def path_for(store_dir: Path, group: str) -> Path:
    """The file of *group*: ``book:gen`` → ``{store}/book/gen.json``, another group
    ``{store}/{group}.json``."""
    rel = group.replace(":", "/", 1) if group.startswith("book:") else group
    if ".." in rel.split("/") or rel.startswith("/"):
        raise ValueError(f"unsafe group id {group!r}")
    return store_dir / f"{rel}.json"


def to_json(a: Alignment) -> str:
    """Deterministic JSON for *a*: one member per line."""
    head = {"format": FORMAT, "group": a.group, "pivot": a.pivot, "groups": a.groups,
            "inputs": a.inputs, "run": a.run}
    lines = ["{"]
    for k, v in head.items():
        lines.append(f" {json.dumps(k)}: {json.dumps(v, ensure_ascii=False, sort_keys=True)},")
    lines.append(' "members": [')
    mems = [a.members[w] for w in sorted(a.members)]
    for i, m in enumerate(mems):
        order = group_order(m.group_of)
        conf = "".join(str(min(9, max(0, m.conf.get(g, 0)))) for g in order)
        rec = {"work_id": m.work_id, "units": m.units, "ids": m.ids, "inputs": m.inputs,
               "spans": encode_spans(m.group_of), "conf": conf}
        sep = "," if i < len(mems) - 1 else ""
        lines.append("  " + json.dumps(rec, ensure_ascii=False) + sep)
    lines.append(" ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def from_json(text: str) -> Alignment:
    raw = json.loads(text)
    if raw.get("format") != FORMAT:
        raise AlignmentFormatError(f"unknown format {raw.get('format')!r}")
    a = Alignment(raw["group"], raw["pivot"], raw["groups"], raw["inputs"], raw["run"])
    for rec in raw["members"]:
        group_of = decode_spans(rec["spans"])
        if len(group_of) != rec["units"]:
            raise AlignmentFormatError(
                f"{rec['work_id']}: {len(group_of)} spans for {rec['units']} units")
        order = group_order(group_of)
        if len(rec["conf"]) != len(order):
            raise AlignmentFormatError(
                f"{rec['work_id']}: {len(rec['conf'])} confidences for {len(order)} groups")
        if any(g >= a.groups for g in order):
            raise AlignmentFormatError(f"{rec['work_id']}: group beyond {a.groups}")
        a.members[rec["work_id"]] = Member(rec["work_id"], rec["units"], rec["inputs"],
                                           group_of, {g: int(c) for g, c in
                                                      zip(order, rec["conf"])}, rec["ids"])
    return a


def load(store_dir: Path, group: str) -> Alignment | None:
    path = path_for(store_dir, group)
    if not path.exists():
        return None
    return from_json(path.read_text(encoding="utf-8"))


def save(store_dir: Path, a: Alignment) -> bool:
    """Write *a*; return True if the file changed."""
    path = path_for(store_dir, a.group)
    text = to_json(a)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return True


def iter_store(store_dir: Path = DEFAULT_DIR) -> Iterator[tuple[Path, Alignment]]:
    """Every alignment file in the store, in path order."""
    if not store_dir.exists():
        return
    for path in sorted(store_dir.rglob("*.json")):
        yield path, from_json(path.read_text(encoding="utf-8"))
