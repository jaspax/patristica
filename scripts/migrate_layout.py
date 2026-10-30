"""
Move data from the genre-first layout to the source-first layout (#102).

Until #102, every ``source_id`` carried a genre prefix (``scripture/oshb``,
``patristic/first1k``, ``liturgical/hudra``, ``councils/ecumenical``), and
``data/raw`` and ``data/normalized`` were organized ``{genre}/{source}/…``.
Now a ``source_id`` is the bare collection slug (``oshb``, ``first1k``), data
lives under ``data/{raw,normalized}/{source_id}/…``, and every work id is
``{source_id}/{local id}``.  Genre is only ``Work.genre``.

Two subcommands, both idempotent (a second run changes nothing) and both with
``--dry-run``:

``raw``
    For an existing local checkout: moves ``data/raw/{genre}/{source}`` to
    ``data/raw/{source_id}`` and rewrites the ids in each raw work record
    (``work_id``, ``source_id``, ``translation_of``), so that ``normalize``
    reproduces the tracked files without re-ingesting::

        uv run python -m scripts.migrate_layout raw --dry-run
        uv run python -m scripts.migrate_layout raw

``eval``
    For an existing local ``data/eval`` (gitignored scratch of the embedding
    eval): rewrites the old ids in every ``*.jsonl`` file there (corpus,
    queries, reviews, translation caches), so the eval set need not be
    re-sampled.  Embedding caches are keyed by text and need nothing::

        uv run python -m scripts.migrate_layout eval

``tracked``
    The one-off migration of the tracked data, already applied in the #102
    PR: ``git mv`` of the ``data/normalized`` (and ``data/translations``)
    source directories, and id rewrites in the normalized files,
    ``_works.jsonl``, ``data/eval_authored/*.jsonl`` and
    ``data/translations/``.  Kept so that branches made before #102 can
    migrate data they add.

The mapping is ``SOURCE_IDS`` (old → new source id) plus ``new_work_id``.
Apart from dropping the genre, two ids change: Patrologia Latina's folder and
work ids ``oglt_pl`` become ``oglt-pl`` (its source id was already
``patristic/oglt-pl``), and the council work ids ``councils/{council}`` become
``ecumenical/{council}`` (``{source_id}/{local id}``).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

GENRE_PREFIXES = ("scripture", "patristic", "liturgical", "councils")

# Old source id → new source id.  Includes the three CCEL volume caches, which
# have raw data but no normalized works.
SOURCE_IDS: dict[str, str] = {
    # scripture
    "scripture/armenian": "armenian",
    "scripture/asv": "asv",
    "scripture/clementine": "clementine",
    "scripture/coptic-nt": "coptic-nt",
    "scripture/gez": "gez",
    "scripture/kjv": "kjv",
    "scripture/lxx-rahlfs": "lxx-rahlfs",
    "scripture/oshb": "oshb",
    "scripture/pta-lxx": "pta-lxx",
    "scripture/pta-peshitta": "pta-peshitta",
    "scripture/sblgnt": "sblgnt",
    "scripture/web": "web",
    "scripture/wulfila": "wulfila",
    # patristic
    "patristic/anf-works": "anf-works",
    "patristic/apostolic-constitutions": "apostolic-constitutions",
    "patristic/ccel-anf": "ccel-anf",
    "patristic/ccel-npnf1": "ccel-npnf1",
    "patristic/ccel-npnf2": "ccel-npnf2",
    "patristic/coptic-scriptorium": "coptic-scriptorium",
    "patristic/didache": "didache",
    "patristic/first1k": "first1k",
    "patristic/npnf-works": "npnf-works",
    "patristic/oglt-pl": "oglt-pl",
    "patristic/ogpg": "ogpg",
    "patristic/perseus": "perseus",
    "patristic/pta": "pta",
    "patristic/syriac-documents": "syriac-documents",
    # liturgical
    "liturgical/adai-mari": "adai-mari",
    "liturgical/armenian-liturgy": "armenian-liturgy",
    "liturgical/cantus": "cantus",
    "liturgical/coptic-scriptorium": "coptic-scriptorium",  # before #52
    "liturgical/cursus": "cursus",
    "liturgical/gallican": "gallican",
    "liturgical/gez-anaphoras": "gez-anaphoras",
    "liturgical/goarch-basil": "goarch-basil",
    "liturgical/goarch-chrysostom": "goarch-chrysostom",
    "liturgical/hudra": "hudra",
    "liturgical/mark-liturgy": "mark-liturgy",
    "liturgical/mozarabic": "mozarabic",
    "liturgical/serapion": "serapion",
    "liturgical/syriac-james": "syriac-james",
    "liturgical/typikon": "typikon",
    # councils
    "councils/ecumenical": "ecumenical",
}

# Sources added after #102: they were never in the old layout, so nothing maps to them.
NEW_SOURCES: frozenset[str] = frozenset({
    "coptic-scriptorium-eng", "csel", "dsc", "first1k-eng", "ocp", "perseus-eng", "pta-eng",
    "wikisource-apocrypha", "wikisource-canons",
})
# Church Slavonic (#29), all source-first from the start.
NEW_SOURCES |= {"ccmh", "ccmh-assemanianus", "ccmh-marianus", "ccmh-savvina", "ccmh-zographensis",
                "ccmh-supr", "demetrius-psalter", "torot"}
# Machine translations (#422).
NEW_SOURCES |= {"mt-eng"}
# Christian Arabic (#83): OpenITI (#480).
NEW_SOURCES |= {"openiti"}

# Old directory (relative to data/raw or data/normalized) → new directory.
# Every source id is its own directory, except Patrologia Latina's, which was
# ``patristic/oglt_pl``.  When two old directories map to one new directory,
# the first one listed wins and the other is left in place with a warning.
SOURCE_DIRS: dict[str, str] = {
    **{old: new for old, new in SOURCE_IDS.items() if old != "patristic/oglt-pl"},
    "patristic/oglt_pl": "oglt-pl",
}

_WORK_ID_PREFIXES = {"councils": "ecumenical", "oglt_pl": "oglt-pl"}


def new_source_id(source_id: str) -> str:
    """The source-first id for *source_id* (unchanged if already migrated)."""
    return SOURCE_IDS.get(source_id, source_id)


def new_work_id(work_id: str) -> str:
    """The ``{source_id}/{local id}`` form of *work_id*.

    ``scripture/kjv/gen`` → ``kjv/gen``; ``councils/nicaea1`` →
    ``ecumenical/nicaea1``; ``oglt_pl/augustinus/…`` → ``oglt-pl/augustinus/…``.
    Ids without a genre prefix (``first1k/…``, ``ogpg/…``) are unchanged.
    """
    head, sep, rest = work_id.partition("/")
    if not sep:
        return work_id
    if head in _WORK_ID_PREFIXES:
        return f"{_WORK_ID_PREFIXES[head]}/{rest}"
    if head in GENRE_PREFIXES:
        return rest
    return work_id


def new_chunk_id(chunk_id: str) -> str:
    """``{work_id}#{ref}`` with the work id migrated; the ref is unchanged."""
    work_id, sep, ref = chunk_id.partition("#")
    return new_work_id(work_id) + sep + ref


def new_path(rel: str) -> str:
    """A path relative to data/normalized (or data/raw), moved to its source dir."""
    parts = rel.split("/")
    for n in (2, 1):
        old = "/".join(parts[:n])
        if old in SOURCE_DIRS:
            return "/".join([SOURCE_DIRS[old], *parts[n:]])
    return rel


def migrate_work(work: dict[str, Any]) -> dict[str, Any]:
    """A copy of a ``Work`` dict with its id fields migrated."""
    out = dict(work)
    if out.get("work_id"):
        out["work_id"] = new_work_id(out["work_id"])
    if out.get("source_id"):
        out["source_id"] = new_source_id(out["source_id"])
    if out.get("translation_of"):
        out["translation_of"] = new_work_id(out["translation_of"])
    return out


def migrate_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    """A copy of a normalized ``Chunk`` dict with its ids migrated."""
    out = dict(chunk)
    out["chunk_id"] = new_chunk_id(out["chunk_id"])
    out["work_id"] = new_work_id(out["work_id"])
    return out


def migrate_query(row: dict[str, Any]) -> dict[str, Any]:
    """An authored eval query (``data/eval_authored``) with its ids migrated."""
    out = dict(row)
    if "target_chunk_id" in out:
        out["target_chunk_id"] = new_chunk_id(out["target_chunk_id"])
    if "query_id" in out:
        mode, sep, chunk_id = out["query_id"].partition(":")
        if sep:
            out["query_id"] = f"{mode}:{new_chunk_id(chunk_id)}"
    return out


def migrate_translation_row(row: dict[str, Any]) -> dict[str, Any]:
    """A row with a ``chunk_id`` (translation stores) with the id migrated."""
    out = dict(row)
    out["chunk_id"] = new_chunk_id(out["chunk_id"])
    return out


def migrate_work_translations(doc: dict[str, Any]) -> dict[str, Any]:
    """A per-work translation file (``data/translations/{path}``, #93)."""
    out = dict(doc)
    if "work_id" in out:
        out["work_id"] = new_work_id(out["work_id"])
    if "source_path" in out:
        out["source_path"] = new_path(out["source_path"])
    if "translations" in out:
        out["translations"] = [migrate_translation_row(t) for t in out["translations"]]
    return out


# ---------------------------------------------------------------------------
# Rewriting files without changing their formatting
# ---------------------------------------------------------------------------


class MigrationError(RuntimeError):
    """A file's formatting could not be reproduced, so it was not rewritten."""


def _jsonl_dumps(row: Any) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def _rewrite_jsonl(
    path: Path,
    migrate: Callable[[dict[str, Any]], dict[str, Any]],
    dumps: Callable[[Any], str],
    sort_key: Callable[[dict[str, Any]], Any] | None,
    dry_run: bool,
) -> bool:
    """Rewrite a JSON-lines file row by row.  Returns True if it changed."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    if [dumps(r) for r in rows] != [line for line in lines if line.strip()]:
        raise MigrationError(f"{path}: rows are not in the expected serialization")
    new_rows = [migrate(r) for r in rows]
    if sort_key is not None:
        new_rows.sort(key=sort_key)
    new_text = "".join(dumps(r) + "\n" for r in new_rows)
    if new_text == text:
        return False
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def _rewrite_json(
    path: Path,
    migrate: Callable[[Any], Any],
    dumps: Callable[[Any], str],
    dry_run: bool,
) -> bool:
    """Rewrite a JSON document.  Returns True if it changed."""
    text = path.read_text(encoding="utf-8")
    doc = json.loads(text)
    if dumps(doc) != text:
        raise MigrationError(f"{path}: not in the expected serialization")
    new_text = dumps(migrate(doc))
    if new_text == text:
        return False
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def _normalized_dumps(doc: Any) -> str:
    """The serialization ``scripts.normalize`` writes."""
    return json.dumps(doc, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Moving source directories
# ---------------------------------------------------------------------------


def _move(src: Path, dst: Path, use_git: bool, dry_run: bool) -> None:
    log.info("%s %s → %s", "Would move" if dry_run else "Moving", src, dst)
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if use_git:
        subprocess.run(["git", "mv", str(src), str(dst)], check=True)
    else:
        shutil.move(str(src), str(dst))


def move_source_dirs(root: Path, use_git: bool = False, dry_run: bool = False) -> int:
    """Move ``root/{genre}/{source}`` directories to ``root/{source_id}``.

    Idempotent: a directory already at its new place is left alone.  If both
    the old and the new directory exist, the old one is left in place and a
    warning is logged (merging is never attempted).  Empty genre directories
    are removed afterwards.  Returns the number of directories moved.
    """
    moved = 0
    claimed: set[str] = set()
    for old, new in SOURCE_DIRS.items():
        src, dst = root / old, root / new
        if not src.is_dir():
            continue
        if new in claimed or dst.exists():
            log.warning("Both %s and %s exist; leaving %s in place", src, dst, src)
            continue
        _move(src, dst, use_git, dry_run)
        claimed.add(new)
        moved += 1
    if not dry_run:
        for genre in GENRE_PREFIXES:
            d = root / genre
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                log.info("Removed empty %s", d)
    leftovers = [p for g in GENRE_PREFIXES for p in sorted((root / g).glob("*")) if (root / g).is_dir()]
    if leftovers and not dry_run:
        log.warning("Not moved (unknown or conflicting): %s", ", ".join(map(str, leftovers)))
    return moved


# ---------------------------------------------------------------------------
# raw: existing local checkouts
# ---------------------------------------------------------------------------

_WORK_FIELD_RE = {
    key: re.compile(rf'("{key}"\s*:\s*)("(?:[^"\\]|\\.)*")')
    for key in ("work_id", "source_id", "translation_of")
}


def rewrite_raw_work(path: Path, dry_run: bool = False) -> bool:
    """Migrate the ids of the ``work`` record in one raw JSON file, in place.

    Only the three id values are replaced, so the rest of the file (and its
    formatting) is untouched.  Returns True if the file changed (or would).
    """
    text = path.read_text(encoding="utf-8")
    try:
        doc = json.loads(text)
    except json.JSONDecodeError:
        log.warning("Skipping %s: not valid JSON", path)
        return False
    work = doc.get("work") if isinstance(doc, dict) else None
    if not isinstance(work, dict):
        return False
    target = migrate_work(work)
    if target == work:
        return False
    new_text = text
    for key, rx in _WORK_FIELD_RE.items():
        if work.get(key) == target.get(key):
            continue
        old_json = json.dumps(work[key], ensure_ascii=False)
        new_json = json.dumps(target[key], ensure_ascii=False)
        new_text, n = rx.subn(
            lambda m: m.group(1) + new_json if json.loads(m.group(2)) == work[key] else m.group(0),
            new_text,
        )
        if n == 0:
            raise MigrationError(f"{path}: {key} {old_json} not found in the text")
    check = json.loads(new_text)
    if check.get("work") != target or {k: v for k, v in check.items() if k != "work"} != {
        k: v for k, v in doc.items() if k != "work"
    }:
        raise MigrationError(f"{path}: rewriting the ids changed more than the work ids")
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")
    return True


def migrate_raw(raw_dir: Path, dry_run: bool = False) -> tuple[int, int]:
    """Move raw source directories and migrate the work records in them.

    Returns ``(directories moved, files rewritten)``.
    """
    moved = move_source_dirs(raw_dir, use_git=False, dry_run=dry_run)
    rewritten = 0
    roots = set(SOURCE_DIRS.values())
    for name in sorted(roots):
        # In a dry run nothing has moved yet: look at the old directories.
        candidates = [raw_dir / name]
        if dry_run:
            candidates += [raw_dir / old for old, new in SOURCE_DIRS.items() if new == name]
        for src_dir in candidates:
            if not src_dir.is_dir():
                continue
            for path in sorted(src_dir.rglob("*.json")):
                if any(p.startswith("_") for p in path.relative_to(src_dir).parts):
                    continue
                if rewrite_raw_work(path, dry_run=dry_run):
                    rewritten += 1
    log.info(
        "%s %d source directories and %d raw work files",
        "Would migrate" if dry_run else "Migrated",
        moved,
        rewritten,
    )
    return moved, rewritten


# ---------------------------------------------------------------------------
# tracked: data/normalized, data/eval_authored, data/translations
# ---------------------------------------------------------------------------


def migrate_tracked(data_dir: Path, use_git: bool = True, dry_run: bool = False) -> dict[str, int]:
    """Migrate the tracked data under *data_dir* (normally ``data/``).

    Returns per-kind counts of rewritten files.
    """
    counts = {"dirs": 0, "normalized": 0, "manifest": 0, "eval_authored": 0, "translations": 0}
    normalized = data_dir / "normalized"
    translations = data_dir / "translations"

    counts["dirs"] += move_source_dirs(normalized, use_git=use_git, dry_run=dry_run)
    if translations.is_dir():
        counts["dirs"] += move_source_dirs(translations, use_git=use_git, dry_run=dry_run)

    norm_root = normalized
    for path in sorted(norm_root.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        if _rewrite_json(
            path, lambda doc: [migrate_chunk(c) for c in doc], _normalized_dumps, dry_run
        ):
            counts["normalized"] += 1

    manifest = normalized / "_works.jsonl"
    if manifest.exists() and _rewrite_jsonl(
        manifest,
        lambda r: {"path": new_path(r["path"]), "work": migrate_work(r["work"])},
        _jsonl_dumps,
        sort_key=lambda r: r["path"],
        dry_run=dry_run,
    ):
        counts["manifest"] += 1

    for path in sorted((data_dir / "eval_authored").glob("*.jsonl")):
        if _rewrite_jsonl(
            path,
            migrate_query,
            lambda r: json.dumps(r, ensure_ascii=False),
            sort_key=None,
            dry_run=dry_run,
        ):
            counts["eval_authored"] += 1

    if translations.is_dir():
        # Model-level stores (scripts.embed_eval.translate): sorted by chunk id.
        for path in sorted(translations.glob("*.jsonl")):
            if _rewrite_jsonl(
                path, migrate_translation_row, _jsonl_dumps, lambda r: r["chunk_id"], dry_run
            ):
                counts["translations"] += 1
        # Per-work stores (#93), mirroring data/normalized.
        for path in sorted(translations.rglob("*.json")):
            if _rewrite_json(
                path, migrate_work_translations, lambda d: _normalized_dumps(d) + "\n", dry_run
            ):
                counts["translations"] += 1

    log.info("%s: %s", "Would rewrite" if dry_run else "Rewrote", counts)
    return counts


# A whole JSON string that is an old id, optionally behind a "mode:" prefix
# (query ids): "scripture/kjv/gen#Gen.1.1", "exact:councils/nicaea1#…".
_OLD_ID_STRING_RE = re.compile(
    r'(?<!\\)"((?:[a-z]+:)?)((?:scripture|patristic|liturgical|councils|oglt_pl)/[^"\\]*)"'
)


def rewrite_ids_in_text(text: str) -> str:
    """Rewrite every JSON string in *text* that is an old work or chunk id."""
    return _OLD_ID_STRING_RE.sub(lambda m: f'"{m.group(1)}{new_chunk_id(m.group(2))}"', text)


def migrate_eval(eval_dir: Path, dry_run: bool = False) -> int:
    """Rewrite old ids in the ``*.jsonl`` files under *eval_dir*.

    Returns the number of files rewritten (or that would be).
    """
    rewritten = 0
    for path in sorted(eval_dir.rglob("*.jsonl")):
        text = path.read_text(encoding="utf-8")
        new_text = rewrite_ids_in_text(text)
        if new_text == text:
            continue
        old_rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        new_rows = [json.loads(line) for line in new_text.splitlines() if line.strip()]
        if len(old_rows) != len(new_rows):
            raise MigrationError(f"{path}: rewriting ids changed the number of rows")
        log.info("%s %s", "Would rewrite" if dry_run else "Rewriting", path)
        if not dry_run:
            path.write_text(new_text, encoding="utf-8")
        rewritten += 1
    return rewritten


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_raw = sub.add_parser("raw", help="move data/raw to the source-first layout")
    p_raw.add_argument("--raw-dir", default="data/raw", type=Path)
    p_raw.add_argument("--dry-run", action="store_true")
    p_ev = sub.add_parser("eval", help="rewrite old ids in data/eval/**/*.jsonl")
    p_ev.add_argument("--eval-dir", default="data/eval", type=Path)
    p_ev.add_argument("--dry-run", action="store_true")
    p_tr = sub.add_parser("tracked", help="migrate tracked data (normalized, eval, translations)")
    p_tr.add_argument("--data-dir", default="data", type=Path)
    p_tr.add_argument("--no-git", action="store_true", help="move with shutil, not git mv")
    p_tr.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.command == "raw":
        if not args.raw_dir.is_dir():
            parser.error(f"{args.raw_dir} is not a directory")
        migrate_raw(args.raw_dir, dry_run=args.dry_run)
    elif args.command == "eval":
        if not args.eval_dir.is_dir():
            parser.error(f"{args.eval_dir} is not a directory")
        n = migrate_eval(args.eval_dir, dry_run=args.dry_run)
        log.info("%s %d files", "Would rewrite" if args.dry_run else "Rewrote", n)
    else:
        migrate_tracked(args.data_dir, use_git=not args.no_git, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
