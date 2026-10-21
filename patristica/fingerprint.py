"""Fingerprints of pipeline code and data, for detecting stale outputs (#130).

A pipeline step's output is stale when the code that produced it, or its
input, has changed since.  This module computes the hashes that make that
checkable without re-running the step:

- ``code_hash(entry)``: the step's code.  It covers every module the entry
  module imports, directly or indirectly, from this repository
  (``patristica``, ``scripts``), plus any declared data files.  Each module is
  hashed from its syntax tree with docstrings dropped, so comments,
  docstrings, blank lines and formatting don't count; any change that could
  alter behaviour does.  The tree is serialized here, not with ``ast.dump``,
  and fields that are empty or ``None`` are left out, so the hash stays the
  same across Python versions (new versions add optional fields).
- ``value_hash(value)`` and ``sha16(data)``: data and content.

Some modules hold *per-key registries*, dicts with one entry per source such
as ``SOURCE_SCHEMES``.  Adding a source adds an entry; if the whole module
counted, every other source would turn stale too.  A step excludes such a
registry from its code hash (``exclude``) and hashes each source's entries
separately with ``value_hash``.  A registry excluded this way must be a single
top-level assignment.

Imports are found statically (``import`` statements anywhere in a module,
including inside functions); ``importlib`` calls are not followed.
``import_chain(entry, module)`` shows why a module is part of a step's code.  All hashes
are the first 16 hex digits of a SHA-256, like ``translations.text_sha``.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections import deque
from collections.abc import Collection, Iterable, Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_PACKAGES = ("patristica", "scripts")

#: Modules that never count as a step's code: the fingerprinting itself.
IGNORED_MODULES = frozenset({"patristica.fingerprint"})


class FingerprintError(ValueError):
    """A step's fingerprint specification doesn't match the code."""


def sha16(data: bytes | str) -> str:
    """First 16 hex digits of the SHA-256 of *data* (str is UTF-8 encoded)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def _canonical_value(value: object) -> object:
    if isinstance(value, Mapping):
        items = [(k if isinstance(k, str) else repr(k), _canonical_value(v))
                 for k, v in value.items()]
        return {"__map__": sorted(items)}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return {"__set__": sorted(repr(v) for v in value)}
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return repr(value)


def value_hash(value: object) -> str:
    """Hash of a plain data value (dicts, lists, tuples, sets, scalars).

    Dict order doesn't matter; non-string keys and other objects count by
    ``repr``.
    """
    return sha16(json.dumps(_canonical_value(value), ensure_ascii=False, sort_keys=True))


def module_path(name: str, root: Path = REPO_ROOT) -> Path | None:
    """The source file of module *name* under *root*, or None."""
    base = root.joinpath(*name.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


def _is_local(name: str) -> bool:
    return name.split(".")[0] in LOCAL_PACKAGES


def _imported_names(tree: ast.Module, name: str, is_package: bool) -> set[str]:
    """Candidate module names imported by *tree* (module *name*).

    ``from a import b`` yields both ``a`` and ``a.b``, since *b* may be a
    submodule; names that aren't modules are dropped by the caller.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = name if is_package else name.rpartition(".")[0]
                parts = package.split(".")
                if node.level - 1 >= len(parts):
                    raise FingerprintError(f"{name}: relative import beyond top-level package")
                package = ".".join(parts[: len(parts) - (node.level - 1)])
                base = f"{package}.{node.module}" if node.module else package
            else:
                base = node.module or ""
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def _walk(entries: str | Iterable[str], root: Path,
          ignore: Collection[str] = ()) -> dict[str, str | None]:
    """Breadth-first walk of the import graph: ``{module: importer}``.

    The importer of an entry is None; following importers back from any
    module gives a shortest import chain to it.
    """
    if isinstance(entries, str):
        entries = [entries]
    pending: deque[tuple[str, str | None]] = deque()
    for entry in entries:
        if module_path(entry, root) is None:
            raise FingerprintError(f"No module {entry!r} under {root}")
        pending.append((entry, None))
    seen: dict[str, str | None] = {}
    while pending:
        name, importer = pending.popleft()
        if name in seen or name in IGNORED_MODULES or name in ignore or not _is_local(name):
            continue
        path = module_path(name, root)
        if path is None:  # an imported attribute, not a module
            continue
        seen[name] = importer
        parts = name.split(".")
        pending.extend((".".join(parts[:i]), name) for i in range(1, len(parts)))
        tree = ast.parse(path.read_bytes(), filename=str(path))
        pending.extend(
            (imported, name)
            for imported in sorted(_imported_names(tree, name, path.name == "__init__.py"))
        )
    return seen


def module_closure(entries: str | Iterable[str], root: Path = REPO_ROOT,
                   ignore: Collection[str] = ()) -> list[str]:
    """Sorted names of the repository modules that *entries* import.

    Includes the entries themselves and the packages (``__init__``) of every
    module, since importing a module runs its packages' ``__init__`` too.
    Modules in *ignore* (and what only they import) are left out.
    """
    return sorted(_walk(entries, root, ignore))


def import_chain(
    entries: str | Iterable[str], module: str, root: Path = REPO_ROOT
) -> list[str] | None:
    """A shortest import chain from *entries* to *module*, or None if it isn't
    in their closure — to explain why a module counts as a step's code.
    """
    importers = _walk(entries, root)
    if module not in importers:
        return None
    chain = [module]
    while (importer := importers[chain[-1]]) is not None:
        chain.append(importer)
    return chain[::-1]


def _strip_docstrings(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                del body[0]


def _strip_assignments(tree: ast.Module, names: Collection[str], module: str) -> None:
    found: set[str] = set()

    def assigns(stmt: ast.stmt) -> set[str]:
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
        else:
            return set()
        return {t.id for t in targets if isinstance(t, ast.Name)} & set(names)

    kept = []
    for stmt in tree.body:
        hit = assigns(stmt)
        found |= hit
        if not hit:
            kept.append(stmt)
    tree.body = kept
    missing = set(names) - found
    if missing:
        raise FingerprintError(f"{module}: no top-level assignment to {sorted(missing)}")


def _canonical_ast(node: object) -> object:
    if isinstance(node, ast.AST):
        fields = {}
        for field in node._fields:
            value = getattr(node, field, None)
            if value is None or (isinstance(value, list) and not value):
                continue
            fields[field] = _canonical_ast(value)
        return [type(node).__name__, fields]
    if isinstance(node, list):
        return [_canonical_ast(v) for v in node]
    return repr(node)


def module_hash(name: str, exclude: Collection[str] = (), root: Path = REPO_ROOT) -> str:
    """Hash of module *name*'s code, ignoring docstrings, comments and layout.

    Top-level assignments to the names in *exclude* (per-key registries) are
    left out; each must exist.
    """
    path = module_path(name, root)
    if path is None:
        raise FingerprintError(f"No module {name!r} under {root}")
    tree = ast.parse(path.read_bytes(), filename=str(path))
    _strip_docstrings(tree)
    if exclude:
        _strip_assignments(tree, exclude, name)
    return sha16(json.dumps(_canonical_ast(tree), ensure_ascii=False))


def code_hash(
    entries: str | Iterable[str],
    *,
    exclude: Mapping[str, Collection[str]] | None = None,
    data_files: Iterable[Path] = (),
    ignore: Collection[str] = (),
    root: Path = REPO_ROOT,
) -> str:
    """Hash of a pipeline step's code: the import closure of *entries*.

    *exclude* maps module names to per-key registries left out of their module
    hash (see the module docstring); every module named must be in the
    closure.  *data_files* are files the code reads (relative to *root* or
    absolute under it), hashed by content. Modules in *ignore* are left out of
    the closure (shared runners that aren't the step's code).
    """
    exclude = exclude or {}
    modules = module_closure(entries, root, ignore)
    unknown = set(exclude) - set(modules)
    if unknown:
        raise FingerprintError(
            f"Excluded registries in modules outside the closure: {sorted(unknown)}"
        )
    lines = [f"{m} {module_hash(m, exclude.get(m, ()), root)}" for m in modules]
    for data_file in data_files:
        path = data_file if data_file.is_absolute() else root / data_file
        rel = path.resolve().relative_to(root.resolve()).as_posix()
        lines.append(f"{rel} {sha16(path.read_bytes())}")
    return sha16("\n".join(sorted(lines)))
