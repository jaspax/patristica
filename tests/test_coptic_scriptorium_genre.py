"""Genre assignment for the Coptic Scriptorium ingestor (#40).

None of the Coptic Scriptorium works is a liturgy: they are homilies, saints'
lives, Shenoute, letters, monastic texts and apocrypha, so every one is
``patristic`` despite the historical ``liturgical/`` source_id prefix.
"""

from __future__ import annotations

import pytest

from scripts.ingest.coptic_scriptorium import _CORPUS_META, _SHENOUTE_META, _corpus_meta


@pytest.mark.parametrize("corpus", sorted(_CORPUS_META))
def test_corpus_genre_is_patristic(corpus: str) -> None:
    assert _corpus_meta(corpus)["genre"] == "patristic"


def test_shenoute_genre_is_patristic() -> None:
    assert _SHENOUTE_META["genre"] == "patristic"
    assert _corpus_meta("shenoute-considering")["genre"] == "patristic"


@pytest.mark.parametrize("corpus", ["dormition-john", "lament-mary", "mysteries-john"])
def test_apocrypha_formerly_liturgical(corpus: str) -> None:
    assert _corpus_meta(corpus)["genre"] == "patristic"
