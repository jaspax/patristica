"""
Registry of embedding models the eval can score (``--retriever dense:NAME``).

Each entry maps a name to a zero-argument factory returning an ``Embedder``
(see ``retrieval.Embedder``). Factories import their backend lazily, so a
missing optional dependency only matters for the model actually requested.
Model backends are added in follow-up changes to #3.
"""

from __future__ import annotations

from collections.abc import Callable

from scripts.embed_eval.retrieval import Embedder

EMBEDDERS: dict[str, Callable[[], Embedder]] = {}


def get_embedder(name: str) -> Embedder:
    try:
        factory = EMBEDDERS[name]
    except KeyError:
        known = ", ".join(sorted(EMBEDDERS)) or "none registered yet"
        raise KeyError(f"Unknown embedder {name!r} (available: {known})") from None
    return factory()
