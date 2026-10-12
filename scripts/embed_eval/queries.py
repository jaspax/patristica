"""
Generate ``exact`` and ``near`` (near-verbatim) queries for eval targets.

An exact query is a short span of the target's own text, as a scholar would
quote it. A near-verbatim query is the same span with its orthography changed
the way a user's typing differs from the edition: no accents, breathings,
points or vowel marks, lowercase, no punctuation, and for Latin the usual
spelling variants.

A query's relevance set is every corpus chunk in the target language that
contains the span (compared with ``textfold.squash``), since a verse quoted
from Rahlfs is equally answered by the same verse in another LXX edition.
Spans that occur in more than ``MAX_RELEVANT`` chunks are formulaic
("Glory to the Father…") and are re-drawn.
"""

from __future__ import annotations

import json
import logging
import random
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from patristica.textfold import squash

log = logging.getLogger(__name__)

# Authored (hand- or model-drafted) paraphrase and topical queries; tracked in git.
DEFAULT_AUTHORED = Path("data/eval_authored")

MIN_WORDS = 5
MAX_WORDS = 9
MAX_RELEVANT = 5
ATTEMPTS = 5

# Latin spelling variants, written classical → variant (the reverse of
# textfold's folding). Each applicable rule fires with probability 1/2.
_LATIN_VARIANTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bu(?=[aeiou])"), "v"),       # unus → vnus
    (re.compile(r"\bi(?=[aeiou])"), "j"),       # iustus → justus
    (re.compile(r"(?<=[aeiou])u(?=[aeiou])"), "v"),  # nouus → novus
    (re.compile(r"ae"), "e"),                   # caelum → celum
    (re.compile(r"\bmihi\b"), "michi"),
    (re.compile(r"\bnihil\b"), "nichil"),
    (re.compile(r"ti(?=[aeiou])"), "ci"),       # gratia → gracia
]

# Word-internal marks that a user would not type (Armenian accents, Coptic divider).
_IN_WORD = dict.fromkeys(map(ord, "՛՜՞⳿`"), None)


@dataclass(frozen=True)
class Query:
    query_id: str
    mode: str  # "exact" | "near" | "paraphrase" | "topical"
    text: str
    query_lang: str
    target_lang: str
    origin: str  # "scripture" | "unique"
    target_chunk_id: str
    relevant_ids: tuple[str, ...]

    def to_json(self) -> dict:
        d = asdict(self)
        d["relevant_ids"] = list(self.relevant_ids)
        return d

    @classmethod
    def from_json(cls, d: dict) -> Query:
        return cls(**{**d, "relevant_ids": tuple(d["relevant_ids"])})


def _strip_edges(words: list[str]) -> str:
    text = " ".join(words)
    return text.strip("".join(ch for ch in set(text) if unicodedata.category(ch)[0] in "PS"))


def draw_span(text: str, rng: random.Random) -> str | None:
    """Return a random run of MIN_WORDS–MAX_WORDS words from *text*, or None if too short."""
    words = text.split()
    if len(words) < MIN_WORDS:
        return None
    n = min(len(words), rng.randint(MIN_WORDS, MAX_WORDS))
    start = rng.randint(0, len(words) - n)
    return _strip_edges(words[start:start + n]) or None


def perturb(span: str, language: str, rng: random.Random) -> str:
    """Return *span* as a user might type it: unmarked, lowercase, unpunctuated."""
    t = unicodedata.normalize("NFD", span).translate(_IN_WORD)
    t = "".join(ch for ch in t if unicodedata.category(ch) not in ("Mn", "Me", "Cf"))
    t = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in t)
    t = " ".join(unicodedata.normalize("NFC", t).lower().split())
    if language == "lat":
        applicable = [(p, r) for p, r in _LATIN_VARIANTS if p.search(t)]
        fired = [rule for rule in applicable if rng.random() < 0.5]
        if applicable and not fired:
            fired = [rng.choice(applicable)]
        for pattern, repl in fired:
            t = pattern.sub(repl, t)
    return t


def relevant_ids(span: str, corpus: Iterable[tuple[str, str]]) -> list[str]:
    """Return ids of the (chunk_id, squashed_text) pairs that contain *span*."""
    needle = squash(span)
    return [cid for cid, hay in corpus if needle and needle in hay]


def make_queries(
    targets: list[tuple[str, str, str, str]],
    corpus: list[dict],
    *,
    seed: int = 0,
) -> list[Query]:
    """Build exact and near queries.

    *targets* are ``(chunk_id, language, origin, text)``; *corpus* holds dicts
    with ``chunk_id``, ``language`` and ``text``. Targets with no usable span
    are skipped.
    """
    rng = random.Random(seed)
    by_lang: dict[str, list[tuple[str, str]]] = {}
    for c in corpus:
        by_lang.setdefault(c["language"], []).append((c["chunk_id"], squash(c["text"])))

    out: list[Query] = []
    for chunk_id, lang, origin, text in targets:
        for _ in range(ATTEMPTS):
            span = draw_span(text, rng)
            if span is None:
                break
            rel = relevant_ids(span, by_lang.get(lang, []))
            if chunk_id in rel and len(rel) <= MAX_RELEVANT:
                break
        else:
            span = None
        if span is None:
            continue
        common = dict(
            query_lang=lang, target_lang=lang, origin=origin,
            target_chunk_id=chunk_id, relevant_ids=tuple(rel),
        )
        out.append(Query(f"exact:{chunk_id}", "exact", span, **common))
        out.append(Query(f"near:{chunk_id}", "near", perturb(span, lang, rng), **common))
    return out


def load_authored(paths: Iterable[Path], corpus: list[dict]) -> list[Query]:
    """Load authored queries and attach relevance sets from *corpus*.

    Each line holds ``query_id``, ``mode``, ``text``, ``query_lang``,
    ``target_lang``, ``origin`` and ``target_chunk_id``. A query is answered by
    its target, and for Scripture by any same-language chunk of the target's
    translation group (the same verse in another edition).
    """
    by_id = {c["chunk_id"]: c for c in corpus}
    by_group: dict[tuple[str, str], list[str]] = {}
    for c in corpus:
        if c.get("translation_group_id"):
            by_group.setdefault((c["translation_group_id"], c["language"]), []).append(
                c["chunk_id"])
    out: list[Query] = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            target = by_id.get(d["target_chunk_id"])
            if target is None:
                log.warning("%s: target %s not in corpus; skipped", path, d["target_chunk_id"])
                continue
            group = target.get("translation_group_id")
            rel = by_group.get((group, target["language"]), []) if group else []
            fields = {k: d[k] for k in ("query_id", "mode", "text", "query_lang",
                                        "target_lang", "origin", "target_chunk_id")}
            out.append(Query(**fields, relevant_ids=tuple(sorted({d["target_chunk_id"], *rel}))))
    return out
