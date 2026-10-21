"""Tests for patristica.fingerprint (#130)."""

from __future__ import annotations

from pathlib import Path

import pytest

from patristica import fingerprint as fp


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    write(tmp_path, "patristica/__init__.py", "")
    write(tmp_path, "patristica/util.py", '"""Util."""\n\ndef f(x):\n    return x + 1\n')
    write(tmp_path, "patristica/registry.py",
          'LABELS = {\n    "a": "A",\n    "b": "B",\n}\n\ndef label(s):\n    return LABELS[s]\n')
    write(tmp_path, "patristica/unused.py", "X = 1\n")
    write(tmp_path, "scripts/__init__.py", "")
    write(tmp_path, "scripts/ingest/__init__.py", "")
    write(tmp_path, "scripts/ingest/_common.py", "from patristica.util import f\n")
    write(tmp_path, "scripts/ingest/src.py",
          "import json\nfrom . import _common\n\ndef run():\n"
          "    from patristica import registry\n    return registry.label('a')\n")
    write(tmp_path, "scripts/step.py",
          "from patristica.util import f\nimport patristica.registry\n")
    return tmp_path


def test_closure_follows_local_imports_only(repo: Path):
    assert fp.module_closure("scripts.ingest.src", repo) == [
        "patristica", "patristica.registry", "patristica.util",
        "scripts", "scripts.ingest", "scripts.ingest._common", "scripts.ingest.src",
    ]


def test_closure_rejects_unknown_entry(repo: Path):
    with pytest.raises(fp.FingerprintError):
        fp.module_closure("scripts.nope", repo)


def test_comments_docstrings_and_layout_do_not_change_hash(repo: Path):
    before = fp.code_hash("scripts.step", root=repo)
    write(repo, "patristica/util.py",
          '"""Util, now documented at length."""\n\n# a comment\ndef f(x):  # inline\n'
          '    """Add one."""\n\n    return (x\n            + 1)\n')
    assert fp.code_hash("scripts.step", root=repo) == before


def test_logic_change_changes_hash(repo: Path):
    before = fp.code_hash("scripts.step", root=repo)
    write(repo, "patristica/util.py", "def f(x):\n    return x + 2\n")
    assert fp.code_hash("scripts.step", root=repo) != before


def test_module_outside_closure_does_not_count(repo: Path):
    before = fp.code_hash("scripts.step", root=repo)
    write(repo, "patristica/unused.py", "X = 2\n")
    write(repo, "scripts/ingest/src.py", "Y = 3\n")
    assert fp.code_hash("scripts.step", root=repo) == before


def test_excluded_registry_entry_does_not_change_code_hash(repo: Path):
    excl = {"patristica.registry": ["LABELS"]}
    before = fp.code_hash("scripts.step", exclude=excl, root=repo)
    plain = fp.code_hash("scripts.step", root=repo)
    write(repo, "patristica/registry.py",
          'LABELS = {"a": "A", "b": "B", "c": "C"}\n\ndef label(s):\n    return LABELS[s]\n')
    assert fp.code_hash("scripts.step", exclude=excl, root=repo) == before
    assert fp.code_hash("scripts.step", root=repo) != plain


def test_excluded_registry_must_exist(repo: Path):
    with pytest.raises(fp.FingerprintError, match="NOPE"):
        fp.code_hash("scripts.step", exclude={"patristica.registry": ["NOPE"]}, root=repo)
    with pytest.raises(fp.FingerprintError, match="outside the closure"):
        fp.code_hash("scripts.step", exclude={"patristica.unused": ["X"]}, root=repo)


def test_data_files_count_by_content(repo: Path):
    write(repo, "patristica/data/table.csv", "a,b\n")
    files = [Path("patristica/data/table.csv")]
    before = fp.code_hash("scripts.step", data_files=files, root=repo)
    assert before != fp.code_hash("scripts.step", root=repo)
    write(repo, "patristica/data/table.csv", "a,c\n")
    assert fp.code_hash("scripts.step", data_files=files, root=repo) != before


def test_value_hash_ignores_dict_order_and_handles_tuple_keys():
    assert fp.value_hash({"a": 1, "b": [1, 2]}) == fp.value_hash({"b": [1, 2], "a": 1})
    assert fp.value_hash({"a": 1}) != fp.value_hash({"a": 2})
    assert fp.value_hash({("kjv", "Ps"): "eng"}) != fp.value_hash({("kjv", "Ps"): "org"})


def test_import_chain_explains_membership(repo: Path):
    assert fp.import_chain("scripts.ingest.src", "patristica.util", repo) == [
        "scripts.ingest.src", "scripts.ingest._common", "patristica.util"]
    assert fp.import_chain("scripts.step", "scripts.step", repo) == ["scripts.step"]
    assert fp.import_chain("scripts.step", "patristica.unused", repo) is None


def test_real_normalize_closure():
    """normalize's code: no ingestor and no per-source registry, so adding a
    data source never changes its hash (#130)."""
    assert fp.module_closure("scripts.normalize") == [
        "patristica", "patristica.authors", "patristica.genres", "patristica.models",
        "patristica.period", "patristica.section_numbers", "patristica.textfold",
        "patristica.versify", "scripts", "scripts.normalize",
    ]
    assert len(fp.code_hash("scripts.normalize")) == 16
