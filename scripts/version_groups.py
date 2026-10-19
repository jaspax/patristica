"""
Report the work-level version groups (#178, ``patristica.versions``).

Prints, for Scripture-book groups and for all other groups separately, how many
groups hold each language pair and how many works of those languages they
hold, then per language how many works are in a multi-member group.

Usage::

    python -m scripts.version_groups [--input-dir data/normalized] [--members]
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from patristica.versions import VersionGroups, derive_version_groups, language_pair_counts


def _split(groups: VersionGroups, scripture: bool) -> VersionGroups:
    members = {g: m for g, m in groups.members.items() if g.startswith("book:") == scripture}
    return VersionGroups({w: g for g, m in members.items() for w in m}, members)


def report(input_dir: Path, show_members: bool = False) -> str:
    works = [json.loads(line)["work"]
             for line in (input_dir / "_works.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    language_of = {w["work_id"]: w["language"] for w in works}
    groups = derive_version_groups({w["work_id"]: w.get("translation_of") for w in works})
    out: list[str] = []
    for title, scripture in (("Scripture books", True), ("Other works", False)):
        part = _split(groups, scripture)
        out += [f"## {title}: {len(part.members)} groups, {len(part.group_of)} works", "",
                "| languages | groups | works |", "|---|---:|---:|"]
        out += [f"| {a}–{b} | {g} | {n} |"
                for a, b, g, n in language_pair_counts(part, language_of)]
        out.append("")
    total = Counter(language_of.values())
    linked = Counter(language_of[w] for w in groups.group_of)
    out += ["## Works in a multi-member group, per language", "",
            "| language | in a group | works |", "|---|---:|---:|"]
    out += [f"| {lang} | {linked[lang]} | {total[lang]} |" for lang in sorted(total)]
    if groups.dangling:
        out += ["", f"Ignored links to unknown works: {list(groups.dangling)}"]
    if show_members:
        out += ["", "## Groups", ""]
        out += [f"- `{gid}`: " + ", ".join(f"`{w}`" for w in mem)
                for gid, mem in groups.members.items() if not gid.startswith("book:")]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Report work-level version groups.")
    parser.add_argument("--input-dir", default="data/normalized")
    parser.add_argument("--members", action="store_true",
                        help="also list the members of every non-Scripture group")
    args = parser.parse_args()
    print(report(Path(args.input_dir), args.members), end="")


if __name__ == "__main__":
    main()
