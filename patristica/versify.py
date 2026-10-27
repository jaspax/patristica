"""
Derived verses: split long prose chunks into verse-sized units (#2).

Search results point at units, so units should be about the size of a
Scripture verse. Scripture already has verses. Most other works come
as paragraphs, chapters or whole texts (one Perseus work is a single
13,700-character chunk). This module splits such a chunk into *derived
verses*, preferring to break at the ends of sentences, then at clause
punctuation, then at commas, and only then between words.

**Size.** The target is the mean length of a Scripture verse *in the same
language* (:data:`VERSE_TOKENS`), so a unit carries about the same amount
of text whatever the language. A fixed token count would not: an English
verse is ~31 ``cl100k_base`` tokens and a Coptic one ~221.

**Refs.** The derived verses of the chunk at ``ref`` are ``ref.s1``,
``ref.s2``, …. The ``s`` marks a unit we made, as opposed to one numbered by
the source (:func:`is_derived_ref`); no source uses ``s<digits>`` segments.
Chunks that are already about a verse long keep their ref, and works that
come with a standard versification are not split (:func:`versify_chunks`),
except the units listed in :data:`UNVERSIFIED_UNITS` (#129).

**Stability.** Derived refs are in reader URLs and translation keys, so the
split must be repeatable: it depends only on the chunk's text and language,
the constants below and the ``cl100k_base`` encoding. Changing any of them
renumbers derived verses across the corpus; treat them as frozen.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from functools import lru_cache

import tiktoken

from patristica.models import Chunk

#: Mean ``cl100k_base`` tokens per Scripture verse, per language (measured
#: 2026-10-14 over every scripture source in the corpus; Hebrew: OSHB,
#: Greek: SBLGNT + LXX, Latin: Clementine, English: KJV/ASV/WEB, …).
VERSE_TOKENS: dict[str, int] = {
    "eng": 31,
    "lat": 37,
    "got": 44,
    "grc": 130,
    "syc": 155,
    "hbo": 177,
    "hye": 194,
    "gez": 201,
    "cop": 221,
}

#: A unit is at most this many verses long, unless it is a single word.
MAX_VERSES = 3.0

#: Units of standard-versification works (Scripture, works ingested as verses)
#: that are not one verse but many run together, so they are split like prose
#: (#129). Keyed by work id (every unit of the work) or chunk id, with the
#: reason. Only what is listed here is split: a long real verse keeps its ref.
UNVERSIFIED_UNITS: dict[str, str] = {
    "gez/4bar": "the source (LPettay/ethiopian-bible) has no verse numbers for 4 Baruch: "
                "one unit per chapter, each the whole chapter",
    "armenian/1kgs#1Kgs.2.35": "the LXX additions 2:35a–o run together in one unit (~16 verses)",
    "clementine/sir#Sir.1.1": "the Prologue (Multorum nobis…) merged into 1:1 (~14 verses)",
    "pta-lxx/john#John.7.52": "the edition's 7:53–8:11 (pericope adulterae, with its own "
                              "verse numbers) appended to 7:52 (~12 verses)",
}

# Boundary strengths, from strongest to weakest, and the cost of breaking at
# each. A unit costs (length / target − 1)², so a sentence break is worth
# a unit 1.5× the target, and a break between words is used only for a
# run of text with no punctuation more than about twice the target.
SENTENCE, CLAUSE, COMMA, WORD = range(4)
_BREAK_COST = (0.0, 0.25, 0.6, 1.5)

_SENTENCE_MARKS: dict[str, str] = {
    "grc": ".;;!",  # ";" and U+037E are the Greek question mark
    "hye": ":։",  # verjaket, often typed as ":"
    "syc": ".!?܀܁܂",
    "cop": ".!?⳾",
    "gez": "።፧፨",  # ። ፧ ፨
    "hbo": ".!?׃",  # sof pasuq
}
_DEFAULT_SENTENCE_MARKS = ".!?"

_CLAUSE_MARKS: dict[str, str] = {
    "grc": ":··—…",  # not ";"
    "hye": ".․;",  # mijaket, typed as "."
    "syc": ":;܃܄܅܆܇·",
    "gez": "፤፥፦:;",  # ፤ ፥ ፦
}
_DEFAULT_CLAUSE_MARKS = ";:··—…"

_COMMA_MARKS: dict[str, str] = {
    "hye": ",՝`",  # Armenian comma, typed as "`" in some sources
    "gez": "፣,",  # ፣
}
_DEFAULT_COMMA_MARKS = ",،"

# Closing quotes and brackets that may follow the punctuation of a word.
_CLOSERS = "\"'”’»›)]}"

# Words: a run of non-separators with the whitespace before it, which is how
# cl100k_base splits text (" word"), so per-word token counts add up.
# U+1361 ETHIOPIC WORDSPACE (፡) separates Ge'ez words, often with no space;
# it stays with the word before it.
_ATOM_RE = re.compile(r"\s*[^\s፡]+፡*|\s*፡+|\s+$")
_DERIVED_RE = re.compile(r"\.s\d+$")


def is_derived_ref(ref: str) -> bool:
    """True if *ref* names a derived verse (``….s3``), not a source unit."""
    return _DERIVED_RE.search(ref) is not None


def derived_ref(ref: str, n: int) -> str:
    """The ref of the *n*-th (1-based) derived verse of the chunk at *ref*."""
    return f"{ref}.s{n}"


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoding().encode_ordinary(text))


@lru_cache(maxsize=1 << 20)
def _word_tokens(word: str) -> int:
    # Cached: words repeat a lot, and one encode call per word is the main cost.
    return len(_encoding().encode_ordinary(word))


def _atoms(text: str) -> list[str]:
    """Split *text* into words, each keeping the whitespace before it.

    ``"".join(_atoms(text)) == text``.
    """
    return _ATOM_RE.findall(text)


def _strength(word: str, next_word: str | None, language: str) -> int:
    """How strong a break after *word* is."""
    core = word.rstrip("፡").rstrip(_CLOSERS)
    if not core:
        return WORD
    mark = core[-1]
    if mark in _SENTENCE_MARKS.get(language, _DEFAULT_SENTENCE_MARKS):
        if mark == ".":
            letters = core[:-1].lstrip().lstrip("\"'“‘«‹([{")
            # Abbreviations ("cf.", "S.") and citations ("cap. 5", "lib. 3").
            if len(letters) <= 2 or (next_word and next_word.lstrip()[:1].isdigit()):
                return COMMA
        return SENTENCE
    if mark in _CLAUSE_MARKS.get(language, _DEFAULT_CLAUSE_MARKS):
        return CLAUSE
    if mark in _COMMA_MARKS.get(language, _DEFAULT_COMMA_MARKS):
        return COMMA
    return WORD


def split_text(text: str, language: str, target: float | None = None) -> list[str]:
    """Split *text* into units about one verse long (see the module docstring).

    Returns ``[text]`` when it is already about a verse long. Units are
    contiguous slices of *text*, stripped of surrounding whitespace.
    *target* overrides the language's verse length in tokens: anchored
    derived verses (``patristica.anchoring``, #292) cut a stretch whose
    boundaries they can't project to the size of the original's units.
    """
    if target is None:
        target = VERSE_TOKENS.get(language)
    if target is None:
        raise ValueError(f"No verse length for language {language!r}; add it to VERSE_TOKENS")
    atoms = _atoms(text)
    if len(atoms) < 2:
        return [text]
    tokens = [_word_tokens(a) for a in atoms]
    total = sum(tokens)
    if total <= target:
        return [text]

    n = len(atoms)
    strengths = [
        _strength(atoms[i], atoms[i + 1] if i + 1 < n else None, language)
        for i in range(n)
    ]
    ends = _candidate_ends(tokens, strengths, target)

    # prefix[i] = tokens in atoms[:i]; candidate end e means a break after atoms[e-1].
    prefix = [0]
    for t in tokens:
        prefix.append(prefix[-1] + t)
    max_len = MAX_VERSES * target
    best: dict[int, tuple[float, int]] = {0: (0.0, -1)}  # end → (cost, previous end)
    starts: list[int] = [0]
    for e in ends:
        break_cost = 0.0 if e == n else _BREAK_COST[strengths[e - 1]]
        choice: tuple[float, int] | None = None
        for s in reversed(starts):
            length = prefix[e] - prefix[s]
            if length > max_len and choice is not None:
                break
            cost = best[s][0] + (length / target - 1.0) ** 2 + break_cost
            if choice is None or cost < choice[0]:
                choice = (cost, s)
        assert choice is not None
        best[e] = choice
        starts.append(e)

    cuts: list[int] = []
    e = n
    while e > 0:
        cuts.append(e)
        e = best[e][1]
    cuts.reverse()

    units: list[str] = []
    s = 0
    for e in cuts:
        unit = "".join(atoms[s:e]).strip()
        if unit:
            units.append(unit)
        s = e
    return units


def _candidate_ends(tokens: Sequence[int], strengths: Sequence[int], target: int) -> list[int]:
    """Positions where a unit may end, ascending, always including the end.

    Every punctuation break is a candidate. Breaks between words are
    candidates only inside a run without punctuation longer than 1.5 verses,
    where the run cannot be kept whole cheaply anyway; this keeps the search
    small for long texts.
    """
    n = len(tokens)
    punct = [i + 1 for i in range(n - 1) if strengths[i] != WORD]
    ends: list[int] = []
    prev = 0
    for stop in [*punct, n]:
        run = sum(tokens[prev:stop])
        if run > 1.5 * target:
            ends.extend(range(prev + 1, stop))
        ends.append(stop)
        prev = stop
    return ends


def versify_chunks(
    chunks: Sequence[Chunk],
    standard: bool = False,
    units_of: Mapping[str, list[str]] | None = None,
) -> list[Chunk]:
    """Replace each long chunk of a work with its derived verses.

    A derived verse copies its chunk's metadata, with ref ``ref.sN``.
    ``chunk_index`` is renumbered when anything was split. A work whose units
    are a *standard* versification (Scripture, and any work ingested as
    verses, such as apocrypha from a Bible edition) is left alone, except
    its units in :data:`UNVERSIFIED_UNITS`. Chunks that are already derived
    verses are left alone too, so this is idempotent.

    *units_of* gives the units of some chunks by chunk id, cut elsewhere
    (anchored derived verses, ``patristica.anchoring``, #292); every other
    chunk is cut by :func:`split_text`.
    """
    if standard and not any(
        c.work_id in UNVERSIFIED_UNITS or c.chunk_id in UNVERSIFIED_UNITS for c in chunks
    ):
        return list(chunks)
    out: list[Chunk] = []
    split = False
    for chunk in chunks:
        if is_derived_ref(chunk.canonical_ref) or (
            standard
            and chunk.work_id not in UNVERSIFIED_UNITS
            and chunk.chunk_id not in UNVERSIFIED_UNITS
        ):
            out.append(chunk)
            continue
        if units_of is not None and chunk.chunk_id in units_of:
            units = units_of[chunk.chunk_id]
        else:
            units = split_text(chunk.text, chunk.language)
        if len(units) == 1:
            out.append(chunk)
            continue
        split = True
        for n, text in enumerate(units, start=1):
            ref = derived_ref(chunk.canonical_ref, n)
            out.append(chunk.model_copy(update={
                "chunk_id": f"{chunk.work_id}#{ref}",
                "canonical_ref": ref,
                "text": text,
            }))
    if split:
        out = [c.model_copy(update={"chunk_index": i}) for i, c in enumerate(out)]
    return out
