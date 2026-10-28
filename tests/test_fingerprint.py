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
        "patristica", "patristica.anchor_store", "patristica.anchoring", "patristica.authors",
        "patristica.editorial", "patristica.genres",
        "patristica.models",
        "patristica.period", "patristica.section_numbers", "patristica.textfold",
        "patristica.translation_links", "patristica.versify", "scripts", "scripts.normalize",
    ]
    assert len(fp.code_hash("scripts.normalize")) == 16


MODELS = ('from typing import Literal\n\nLicense = Literal["cc-by-4.0", "unknown"]\n'
          'Language = Literal["grc"]\nGenre = Literal["scripture"]\nTradition = Literal["greek"]\n'
          'DateConfidence = Literal["uncertain"]\n\n'
          'class Work:\n    license: License = "unknown"\n')


@pytest.fixture
def models_repo(repo: Path) -> Path:
    write(repo, "patristica/models.py", MODELS)
    write(repo, "scripts/models_step.py", "from patristica.models import Work\n")
    return repo


def test_new_vocabulary_value_does_not_change_hash(models_repo: Path):
    """#262: a new licence or language leaves every stamp and code hash current."""
    before = fp.code_hash("scripts.models_step", root=models_repo)
    write(models_repo, "patristica/models.py",
          MODELS.replace('"unknown"]', '"used-with-permission", "unknown"]')
                .replace('Literal["grc"]', 'Literal["grc", "lat"]'))
    assert fp.code_hash("scripts.models_step", root=models_repo) == before


def test_other_models_change_still_changes_hash(models_repo: Path):
    before = fp.code_hash("scripts.models_step", root=models_repo)
    write(models_repo, "patristica/models.py", MODELS.replace('= "unknown"\n', '= "cc-by-4.0"\n'))
    assert fp.code_hash("scripts.models_step", root=models_repo) != before
    write(models_repo, "patristica/models.py", MODELS + "\nScope = Literal['x']\n")
    assert fp.code_hash("scripts.models_step", root=models_repo) != before


def test_vocabulary_must_be_a_literal_of_strings(models_repo: Path):
    write(models_repo, "patristica/models.py",
          MODELS.replace('Literal["grc"]', 'Literal["grc"] if True else str'))
    with pytest.raises(fp.FingerprintError, match="Language"):
        fp.code_hash("scripts.models_step", root=models_repo)
    write(models_repo, "patristica/models.py", MODELS.replace('Genre = Literal["scripture"]\n', ""))
    with pytest.raises(fp.FingerprintError, match="Genre"):
        fp.code_hash("scripts.models_step", root=models_repo)


def test_real_models_vocabularies_are_excluded():
    from typing import get_args

    from patristica import models
    for name in fp.VOCABULARIES["patristica.models"]:
        assert all(isinstance(v, str) for v in get_args(getattr(models, name)))
    assert len(fp.module_hash("patristica.models")) == 16
