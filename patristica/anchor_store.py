"""Cut files of anchored derived verses (#304), in ``data/anchors/`` (tracked, plain git).

One file per anchored work at ``data/anchors/{normalized path}``. It records,
per source paragraph of the translation, the word positions
(``patristica.anchoring.words``) where its derived verses start, and what the
cut was computed from. No text and no vectors: ``scripts.normalize`` applies a
current cut file with no API calls, so anyone can rebuild the anchored output
from tracked data. ``scripts.anchor`` writes the files.

A file looks like this (one paragraph per line)::

    {
     "work_id": "torot/supr-…",
     "anchor": "first1k/tlg2062/…",
     "method": "<params_hash>",
     "anchor_cuts": "<cuts_hash of the anchor's refs and texts>",
     "words": "<hash of every paragraph's words>",
     "model": "voyage/voyage-4-large",
     "stats": {"rounds": 4, "beads": 812, "one_one": 0.83, …},
     "paragraphs": {
      "Supr.12": {"words": "<sha16>", "starts": [0, 41, 77, 130]},
      …
     }
    }

``method``, ``anchor``, ``anchor_cuts`` and ``words`` are the inputs of the cut
(the design §6); ``stats`` and ``model`` are informational. No numpy: this is
part of normalize's code.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from patristica import fingerprint

DEFAULT_DIR = Path("data/anchors")


@dataclass(frozen=True)
class ParagraphCut:
    words: str  # words_hash of the paragraph
    starts: tuple[int, ...]


@dataclass
class CutFile:
    work_id: str
    anchor: str
    method: str
    anchor_cuts: str
    words: str
    model: str
    paragraphs: dict[str, ParagraphCut]
    stats: dict = field(default_factory=dict)

    def dumps(self) -> str:
        """The file's content: deterministic, one paragraph per line."""
        head = {"work_id": self.work_id, "anchor": self.anchor, "method": self.method,
                "anchor_cuts": self.anchor_cuts, "words": self.words, "model": self.model,
                "stats": dict(sorted(self.stats.items()))}
        lines = ["{"]
        for k, v in head.items():
            lines.append(f" {json.dumps(k)}: {json.dumps(v, ensure_ascii=False, sort_keys=True)},")
        lines.append(' "paragraphs": {')
        paras = [f"  {json.dumps(ref, ensure_ascii=False)}: "
                 f"{json.dumps({'words': p.words, 'starts': list(p.starts)})}"
                 for ref, p in self.paragraphs.items()]
        lines.append(",\n".join(paras))
        lines.append(" }")
        lines.append("}")
        return "\n".join(line for line in lines if line) + "\n"

    @property
    def sha(self) -> str:
        """Hash of the file's content (what normalize records for the work)."""
        return fingerprint.sha16(self.dumps())

    @classmethod
    def from_dict(cls, d: Mapping) -> CutFile:
        return cls(d["work_id"], d["anchor"], d["method"], d["anchor_cuts"], d["words"],
                   d.get("model", ""),
                   {ref: ParagraphCut(p["words"], tuple(p["starts"]))
                    for ref, p in d["paragraphs"].items()},
                   dict(d.get("stats", {})))


def cut_path(store_dir: Path, source_path: str) -> Path:
    """The cut file of the work at ``data/normalized/{source_path}``."""
    return store_dir / source_path


def load(store_dir: Path, source_path: str) -> CutFile | None:
    path = cut_path(store_dir, source_path)
    if not path.exists():
        return None
    return CutFile.from_dict(json.loads(path.read_text(encoding="utf-8")))


def save(store_dir: Path, source_path: str, cut: CutFile) -> bool:
    """Write *cut*; True if the file changed."""
    path = cut_path(store_dir, source_path)
    content = cut.dumps()
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
    return True


def iter_store(store_dir: Path = DEFAULT_DIR) -> Iterator[tuple[str, CutFile]]:
    """Every cut file as (normalized path, cut file), in path order."""
    if not store_dir.is_dir():
        return
    for path in sorted(store_dir.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        rel = path.relative_to(store_dir).as_posix()
        yield rel, CutFile.from_dict(json.loads(path.read_text(encoding="utf-8")))
