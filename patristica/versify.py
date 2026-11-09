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
from collections.abc import Collection, Mapping, Sequence
from functools import lru_cache

import tiktoken

from patristica.models import Chunk

#: Mean ``cl100k_base`` tokens per Scripture verse, per language (measured
#: 2026-10-14 over every scripture source in the corpus; Hebrew: OSHB,
#: Greek: SBLGNT + LXX, Latin: Clementine, English: KJV/ASV/WEB, …).
#: Church Slavonic was measured before its first source (#330): the mean over
#: the 3,614 verses of Codex Marianus in TOROT's Cyrillic (67.7; Zographensis
#: 71, Psalterium Sinaiticum 56), in the Cyrillic the corpus stores.
#: Arabic too (#83): no in-period Arabic Scripture is in the corpus, so the
#: mean over the 3,779 Gospel verses of the Van Dyck Bible (eBible arb-vd)
#: with its harakat removed (59.5, median 57; 108 vocalized), since the
#: Christian Arabic sources are unvocalized.
#: Old Georgian too (#222): the mean over the 3,667 extant verses of the
#: Adishi/Khanmeti Gospels (TITUS ARMAZI, Sarjveladze and Tvaltvadze 2001-02),
#: in the Mkhedruli with archaic letters (ჱ ჲ ჳ ჴ) the sources store, with the
#: editors' brackets and lacuna marks removed (185.9, median 179; every
#: Gospel 184-187; the pre-Athonite redaction's 3,774 verses: 189.0).
VERSE_TOKENS: dict[str, int] = {
    "eng": 31,
    "lat": 37,
    "got": 44,
    "chu": 68,
    "arb": 60,
    "oge": 186,
    # Old Irish (#225): there is no Old Irish Scripture, so this is the English
    # verse (31) times the sga/eng token ratio of the Würzburg glosses and
    # their Thesaurus Palaeohibernicus translations (1.02 over the 2,204
    # glosses with no Latin); a Félire Óengusso quatrain averages 30.
    "sga": 32,
    # Old High German (#224): the OHG Tatian (ReA 1.2, Sievers' edition, as it
    # will be stored) against ReA's Latin Tatian, chapter by chapter: 1.21
    # OHG tokens per Latin one over 236 chapters, times the Latin verse (37).
    # (Sievers' subchapters average 65 tokens, but they run ~1.4 verses: the
    # Latin of a subchapter is ~50 tokens.)
    "goh": 45,
    # Old Saxon (#224): there is no Old Saxon Scripture or parallel text, so
    # this is the words of a verse in the two neighbouring languages (OHG
    # 45/2.25 tokens per word = 20.0, Old English 55/2.51 = 21.9; mean 21.0)
    # times the Heliand's 2.47 tokens per word (ReA 1.2, with its ð ƀ and
    # circumflexes).
    "osx": 52,
    # Old English (#223): there is no openly licensed Old English Scripture in
    # the corpus, so this is the mean English verse (KJV/ASV/WEB: 130 chars)
    # carried over by characters on Thorpe's Catholic Homilies I (PG #38334,
    # with þ ð æ and accents): its 724 facing paragraphs have 1.027 English
    # characters per Old English one, and the Old English has 2.31 characters
    # per token: 130 / 1.027 / 2.31 = 55. The token ratio against Thorpe's own
    # English (1.84 × 31 = 57) runs high, since his Victorian English packs more
    # characters per token than the Bible versions; the West Saxon Gospels
    # (Royal MS 1 A XIV, 284 verses of Mt 1, 5, 13, 26 and Jn 1, 3, 17) have
    # 45.3 tokens a verse where the KJV has 27.9: × 31/27.9 = 50.
    "ang": 55,
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
    # Church Slavonic (#330): "." is the manuscripts' main stop (Marianus ~3 a
    # verse), ";" the question mark as in Greek, and the multi-dot marks
    # ⁖ ⁘ ⁙ ⁛ ⁜ ⁝ end a reading or section; ჻ is used the same way in TOROT.
    "chu": ".;!?⁖⁘⁙⁛⁜⁝჻",
    # Arabic (#83): the Arabic question mark ؟ besides the Latin stops.
    "arb": ".!?؟",
    # Old Georgian (#222): the editions (TITUS, Wikisource) punctuate in the
    # modern way (. ! ? for stops, ":" before speech, ";" between clauses,
    # as the defaults have it); manuscripts and diplomatic texts end a
    # sentence or section with the three-dot ჻ (U+10FB).
    "oge": ".!?჻",
}
_DEFAULT_SENTENCE_MARKS = ".!?"

_CLAUSE_MARKS: dict[str, str] = {
    "grc": ":··—…",  # not ";"
    "hye": ".․;",  # mijaket, typed as "."
    "syc": ":;܃܄܅܆܇·",
    "gez": "፤፥፦:;",  # ፤ ፥ ፦
    # Church Slavonic: the raised dot (Suprasliensis' commonest mark, before
    # speech and between clauses; Zographensis), two points (CCMH ":"; the
    # Psalter's half-verse mark), two-dot marks ⁚ ⸪, and dashes.
    "chu": ":\u00b7\u0387⁚⸪—…",  # · (middle dot) and · (ano teleia)
    # Arabic: the Arabic semicolon ؛ besides the default marks.
    "arb": "؛;:—…",
}
_DEFAULT_CLAUSE_MARKS = ";:··—…"

_COMMA_MARKS: dict[str, str] = {
    "hye": ",՝`",  # Armenian comma, typed as "`" in some sources
    "gez": "፣,",  # ፣
}
_DEFAULT_COMMA_MARKS = ",،"

# Closing quotes and brackets that may follow the punctuation of a word.
_CLOSERS = "\"'”’»›)]}"

# Quotation marks (#622). The straight "'" is left out: it is also the
# apostrophe. A straight '"' opens or closes; where it stands alone, the
# straight quotes before it in the text decide which.
_QUOTE_OPENERS = "\"“„«‹‘"
_QUOTE_CLOSERS = "\"”’»›"
_LONE_QUOTE_RE = re.compile(r"\s*[\"“”„«»‹›‘’)\]}]+$")

#: Editorial kinds (``patristica.editorial``, #236) that belong with the text
#: before them, so a break never falls between that text and them (#622): a
#: note or citation follows what it comments on.
TRAILING_EDITORIAL_KINDS = frozenset({"note"})

#: Sources whose notes the rule above leaves alone: OGLT PL's notes are
#: Migne's footnote blocks, dropped by the OCR wherever a page ended, so they
#: don't belong with the text before them (#623).
NOTE_RULE_EXCLUDED_SOURCES = frozenset({"oglt-pl"})

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


def strengths(atoms: Sequence[str], language: str,
              spans: Sequence[Sequence[object]] = ()) -> list[int]:
    """The strength of a break after each of *atoms* (:func:`_atoms` of a text),
    in context (#622):

    - *spans* are the text's editorial spans ``(start, end, kind)``, offsets
      into ``"".join(atoms)``. A break before a span of
      :data:`TRAILING_EDITORIAL_KINDS` moves to its end, with its strength,
      and breaks inside it are only between words: a note stays with its
      text, and whole.
    - A quotation mark standing alone (``… Spirit. [Matthew 1:18] " So``) that
      closes a quotation stays with the word before it, which passes it its
      break.
    - A comma or clause mark before an opening quotation mark (``written,
      "Mary``) is as strong a break as a full stop.
    - A comma or clause mark after the first word of a quotation (``"Mary,``)
      is no break.
    """
    n = len(atoms)
    st = [_strength(atoms[i], atoms[i + 1] if i + 1 < n else None, language)
          for i in range(n)]
    if spans:
        _attach_trailing_editorial(atoms, st, spans)
    quotes = 0  # straight double quotes so far
    for j, atom in enumerate(atoms):
        word = atom.strip()
        if _LONE_QUOTE_RE.fullmatch(word) and j > 0 and _closes(word, quotes):
            st[j] = min(st[j], st[j - 1])
            st[j - 1] = WORD
        quotes += word.count('"')
    for i in range(n - 1):
        if st[i] not in (CLAUSE, COMMA):
            continue
        word = atoms[i].strip().lstrip("([{")
        nxt = atoms[i + 1].strip()
        if word[:1] in _QUOTE_OPENERS and word[-1:] not in _QUOTE_CLOSERS:
            st[i] = WORD
        elif nxt[:1] in _QUOTE_OPENERS:  # a closing one was attached above
            st[i] = SENTENCE
    return st


def _closes(word: str, quotes: int) -> bool:
    """Whether a lone quotation mark (or closing bracket) *word* closes a
    quotation, after *quotes* straight double quotes."""
    mark = word[0]
    if mark == '"':
        return quotes % 2 == 1
    return mark not in _QUOTE_OPENERS


def _attach_trailing_editorial(atoms: Sequence[str], st: list[int],
                               spans: Sequence[Sequence[object]]) -> None:
    ends: list[int] = []
    pos = 0
    for a in atoms:
        pos += len(a)
        ends.append(pos)
    for start, end, kind in spans:
        if kind not in TRAILING_EDITORIAL_KINDS or end <= start:
            continue
        # The atoms holding the span's first and last characters.
        i0 = next(i for i, e in enumerate(ends) if e > start)
        i1 = next(i for i, e in enumerate(ends) if e >= end)
        if i0 == 0:
            continue
        for k in range(i0, i1):
            st[k] = WORD
        st[i1] = st[i0 - 1]
        st[i0 - 1] = WORD


def splitting_spans(work_id: str, spans: Sequence[Sequence[object]]
                    ) -> Sequence[Sequence[object]]:
    """The editorial spans of a unit of *work_id* that its cut takes into
    account: none for :data:`NOTE_RULE_EXCLUDED_SOURCES`."""
    return () if work_id.split("/", 1)[0] in NOTE_RULE_EXCLUDED_SOURCES else spans


def split_text(text: str, language: str,
               spans: Sequence[Sequence[object]] = ()) -> list[str]:
    """Split *text* into units about one verse long (see the module docstring).

    Returns ``[text]`` when it is already about a verse long. Units are
    contiguous slices of *text*, stripped of surrounding whitespace. *spans*
    are the text's editorial spans (:func:`strengths`).
    """
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
    st = strengths(atoms, language, spans)
    ends = _candidate_ends(tokens, st, target)

    # prefix[i] = tokens in atoms[:i]; candidate end e means a break after atoms[e-1].
    prefix = [0]
    for t in tokens:
        prefix.append(prefix[-1] + t)
    max_len = MAX_VERSES * target
    best: dict[int, tuple[float, int]] = {0: (0.0, -1)}  # end → (cost, previous end)
    starts: list[int] = [0]
    for e in ends:
        break_cost = 0.0 if e == n else _BREAK_COST[st[e - 1]]
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


def _candidate_ends(tokens: Sequence[int], st: Sequence[int], target: int) -> list[int]:
    """Positions where a unit may end, ascending, always including the end.

    Every punctuation break is a candidate. Breaks between words are
    candidates only inside a run without punctuation longer than 1.5 verses,
    where the run cannot be kept whole cheaply anyway; this keeps the search
    small for long texts.
    """
    n = len(tokens)
    punct = [i + 1 for i in range(n - 1) if st[i] != WORD]
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
    keep: Collection[str] = (),
    spans_of: Mapping[str, Sequence[Sequence[object]]] | None = None,
) -> list[Chunk]:
    """Replace each long chunk of a work with its derived verses.

    A derived verse copies its chunk's metadata, with ref ``ref.sN``.
    ``chunk_index`` is renumbered when anything was split. A work whose units
    are a *standard* versification (Scripture, and any work ingested as
    verses, such as apocrypha from a Bible edition) is left alone, except
    its units in :data:`UNVERSIFIED_UNITS`. Chunks that are already derived
    verses are left alone too, so this is idempotent.

    *units_of* gives the units of some chunks by chunk id, cut elsewhere
    (anchored derived verses, ``patristica.anchoring``, #304): contiguous
    stripped slices of the chunk's text. Every other chunk is cut by
    :func:`split_text`, with its editorial spans from *spans_of* (by chunk
    id; none for :data:`NOTE_RULE_EXCLUDED_SOURCES`), except those whose ids
    are in *keep* (a heading that is editorial material as a whole, #259),
    which stay whole.
    """
    if standard and not any(
        c.work_id in UNVERSIFIED_UNITS or c.chunk_id in UNVERSIFIED_UNITS for c in chunks
    ):
        return list(chunks)
    out: list[Chunk] = []
    split = False
    for chunk in chunks:
        if is_derived_ref(chunk.canonical_ref) or chunk.chunk_id in keep or (
            standard
            and chunk.work_id not in UNVERSIFIED_UNITS
            and chunk.chunk_id not in UNVERSIFIED_UNITS
        ):
            out.append(chunk)
            continue
        if units_of is not None and chunk.chunk_id in units_of:
            units = units_of[chunk.chunk_id]
        else:
            spans = (spans_of or {}).get(chunk.chunk_id, ())
            units = split_text(chunk.text, chunk.language,
                               splitting_spans(chunk.work_id, spans))
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
