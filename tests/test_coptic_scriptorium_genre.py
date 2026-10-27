"""Genre and ids for the Coptic Scriptorium ingestor (#40, #52).

The ingestor makes every Coptic Scriptorium work ``patristic``: homilies,
saints' lives, Shenoute, letters, monastic texts and apocrypha.  The curated
genres in ``patristica/data/genre_overrides.csv`` reclassify the apocrypha and
the Lament of the Virgin at normalize time (#103; see tests/test_genres.py).  The source_id and work ids carried a genre until #102
(``liturgical/coptic-scriptorium``, then ``patristic/coptic-scriptorium`` from
#52); now they are just ``coptic-scriptorium``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica.sources import SOURCE_LABELS
from scripts.ingest.coptic_scriptorium import (
    _CORPUS_META,
    _SHENOUTE_META,
    SOURCE_ID,
    _corpus_meta,
    ingest,
)
from tests.test_coptic_scriptorium import _TEI, _TEI_TT


@pytest.mark.parametrize("corpus", sorted(_CORPUS_META))
def test_corpus_genre_is_patristic(corpus: str) -> None:
    assert _corpus_meta(corpus)["genre"] == "patristic"


def test_shenoute_genre_is_patristic() -> None:
    assert _SHENOUTE_META["genre"] == "patristic"
    assert _corpus_meta("shenoute-considering")["genre"] == "patristic"


@pytest.mark.parametrize("corpus", ["dormition-john", "lament-mary", "mysteries-john"])
def test_apocrypha_formerly_liturgical(corpus: str) -> None:
    assert _corpus_meta(corpus)["genre"] == "patristic"


def test_source_id_has_no_genre() -> None:
    assert SOURCE_ID == "coptic-scriptorium"
    assert SOURCE_ID in SOURCE_LABELS
    assert "liturgical/coptic-scriptorium" not in SOURCE_LABELS
    assert "patristic/coptic-scriptorium" not in SOURCE_LABELS


def test_ingest_writes_work_ids_under_source_id(tmp_path: Path) -> None:
    # A one-corpus stand-in for the cloned repo, so no network or data/raw.
    tei_dir = tmp_path / "_repos" / "coptic-scriptorium" / "dormition-john" / "dormition-john_TEI"
    tei_dir.mkdir(parents=True)
    (tei_dir / "dormition.xml").write_text(_TEI, encoding="utf-8")
    tt_dir = tei_dir.parent / "dormition-john_TT"
    tt_dir.mkdir()
    (tt_dir / "dormition.tt").write_text(_TEI_TT, encoding="utf-8")

    works = ingest(tmp_path)

    assert [w.work_id for w in works] == ["coptic-scriptorium/dormition_john"]
    assert works[0].source_id == SOURCE_ID
    out = tmp_path / "coptic-scriptorium" / "dormition_john.json"
    assert json.loads(out.read_text(encoding="utf-8"))["work"]["work_id"] == works[0].work_id
