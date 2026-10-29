"""
Corpus Cyrillo-Methodianum Helsingiense (CCMH): download, the ASCII → Cyrillic
converter, and the Gospel-codex ingest shared by its ingestors (#332).

CCMH (University of Helsinki, 1986–2017, now at Kielipankki, CC BY 4.0,
urn:nbn:fi:lb-20140730106) gives each Old Church Slavonic text as a 7-bit
ASCII transliteration, one numbered line per line of text. Each text has its
own table on its ``.html`` page (https://www.kielipankki.fi/download/ccmh-src/www/):
the Glagolitic codices (Marianus, Zographensis and its later leaves Zogr-B,
Assemanianus) and the Cyrillic ones (Savvina kniga, Suprasliensis, the Vitae)
use the same letters for most sounds but differ in the rest (``u`` is the
digraph оу in one and the ligature ѹ in the other; ``^`` sits on the next
letter in Marianus and on the previous one in Zographensis; ``/`` is a
numeral sign in the Vitae and a stroke over a vowel in Assemanianus). So the
converter is driven by a :class:`Table` per text, and a new CCMH text (the
Suprasliensis, #333) only needs a table.

**Output.** Unicode Cyrillic, NFC per letter, as TOROT's Cyrillic of the same
CCMH files writes it: Glagolitic witnesses in Cyrillic (owner's decision on
#29; izhe ``I`` → і, ``J`` → ꙇ, ``i`` → и), ``*`` an upper-case letter, a word
under a titlo (``!word``) with U+0483 over its second letter (its only letter
for a numeral), a letter written above the line (``!`` inside a word) as the
combining Cyrillic letter plus pokrytie (бꙑⷭ҇), diacritics as combining marks,
the paerok ``'`` as ꙿ (U+A67F), ``::`` → ⁘, ``:.`` → ⁖, ``:-`` → ⁛, ``--`` → ⁓.
Punctuation is attached to the word before it, since CCMH puts spaces around
every point.

**Editorial material (#236).** The edition's signs become spans
``[start, end, kind]`` on the converted text, the raw-unit format
``scripts.normalize`` reads:

- ``[…]`` (letters the editor supplied, Jagić) and Zogr-B's ``<…>`` (read by
  Jagić, no longer visible per Moszyński; written ⟨…⟩): ``supplement``, kept in
  the source text without the brackets;
- ``=…=`` (a later hand's addition in the manuscript): ``supplement`` without
  brackets, so the reader marks it and search still finds it;
- ``{…}`` (dittography, superfluous letters the editor flags): ``note``, kept
  for the reader with its braces, left out of embedding;
- ``?`` (a letter not readable) and ``-`` (a word cut off by a lost leaf):
  ``lacuna``;
- the scribe's lection marks кⷰ҇ "end" and заⷱ҇ "beginning" (``LECTION_MARKS``):
  ``metadata``, shown to readers but not Gospel text (TOROT omits them).

``%`` marks a place CCMH's transcribers meant to re-check against the
edition: data-entry markup, not text, so it is dropped (and counted).

Part of each CCMH ingestor's code hash (ingest stamps, #130): a change here
re-stamps every CCMH source on its next forced ingest.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._scripture_meta import BOOK_TITLE, book_work_id
from scripts.ingest._slavonic import glagolitic_to_cyrillic

log = logging.getLogger(__name__)

BASE_URL = "https://www.kielipankki.fi/download/ccmh-src/www/"
LICENSE_URL = "https://www.kielipankki.fi/lic/ccmh-eng/"
CACHE_DIR = Path("_cache") / "ccmh"
CORPUS = "Corpus Cyrillo-Methodianum Helsingiense (CCMH, Kielipankki, CC BY 4.0)"

TITLO = "\u0483"
POKRYTIE = "\u0487"
PAEROK = "ꙿ"

# Combining forms of letters written above the line (U+2DE0–2DFF, U+A674–A69F).
SUPERSCRIPT: dict[str, str] = {
    "б": "\u2de0", "в": "\u2de1", "г": "\u2de2", "д": "\u2de3", "ж": "\u2de4",
    "з": "\u2de5", "к": "\u2de6", "л": "\u2de7", "м": "\u2de8", "н": "\u2de9",
    "о": "\u2dea", "п": "\u2deb", "р": "\u2dec", "с": "\u2ded", "т": "\u2dee",
    "х": "\u2def", "ц": "\u2df0", "ч": "\u2df1", "ш": "\u2df2", "щ": "\u2df3",
    "ѳ": "\u2df4", "а": "\u2df6", "е": "\u2df7", "ꙉ": "\u2df8", "оу": "\u2df9",
    "ѹ": "\u2df9", "ꙋ": "\u2df9", "ѣ": "\u2dfa", "ю": "\u2dfb", "ꙗ": "\u2dfc",
    "ѧ": "\u2dfd", "ѫ": "\u2dfe", "ѭ": "\u2dff", "и": "\ua675", "і": "\ua675",
    "ꙇ": "\ua675", "ї": "\ua676", "у": "\ua677", "ъ": "\ua678", "ꙑ": "\ua679",
    "ь": "\ua67a", "ѡ": "\ua67b", "ф": "\ua69e", "ѥ": "\ua69f",
}

# Letters shared by every CCMH table (the tables' own names in comments).
_COMMON_LETTERS: dict[str, str] = {
    "a": "а",   # az
    "b": "б",   # buky
    "v": "в",   # vede
    "g": "г",   # glagol
    "d": "д",   # dobro
    "e": "е",   # jest
    "Z": "ж",   # zhivete
    "D": "ѕ",   # dzelo
    "z": "з",   # zemlja
    "i": "и",   # izhe, value 20: the "octal" и of Cyrillic
    "I": "і",   # i, value 10: the "decimal" і
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "r": "р",
    "s": "с", "t": "т",
    "f": "ф",   # fert
    "T": "ѳ",   # fita
    "x": "х",   # xer
    "w": "ѡ",   # ot (omega)
    "q": "щ",   # shta
    "c": "ц",   # ci
    "C": "ч",   # cherv
    "S": "ш",   # sha
    "&": "ъ",   # big jer
    "$": "ь",   # small jer
    "y": "ꙑ",   # jery
    "@": "ѣ",   # jat (Glagolitic: also ja)
    "ju": "ю",
    "E": "ѧ",   # small jus
    "jE": "ѩ",  # iotated small jus
    "O": "ѫ",   # big jus
    "jO": "ѭ",  # iotated big jus
}

#: Letters of the Glagolitic codices (Marianus, Zographensis, Assemanianus).
GLAGOLITIC_LETTERS: dict[str, str] = {
    **_COMMON_LETTERS,
    "J": "ꙇ",   # the broad i (initial izhe)
    "G": "ꙉ",   # gerv
    "u": "оу",  # uk: Glagolitic writes the digraph ⱁⱆ
    "U": "ѵ",   # izhica
    "Y": "ѵ",   # izhica as the second half of uk: o[Y]
    "A": "ꙙ",   # the "nasal jer"
    "jw": "ѡ\u0308",  # Marianus Matt 15:28, 16:17 (TOROT ѡ̈)
}

#: Letters of the Cyrillic texts (Savvina kniga, the Vitae; Suprasliensis's
#: table, whose principles the others follow).
CYRILLIC_LETTERS: dict[str, str] = {
    **_COMMON_LETTERS,
    "u": "ѹ",   # u as a digraph (the оу ligature)
    "U": "ꙋ",   # uk as one letter
    "ja": "ꙗ",  # ja (ligature, or az with a stroke)
    "je": "ѥ",
    "X": "ѯ",   # ksi
    "P": "ѱ",   # psi
    "Y": "ѵ",   # izhica
    "J": "ї",   # the Vitae's i with trema (TOROT ї); not in Suprasliensis
    "G": "ꙉ",
}

_COMMON_MARKS: dict[str, str] = {
    "~": "\u0306",  # breve above the next letter
    "(": "\u0485",  # spiritus asper (dasia)
}

#: Punctuation, longest first. ``:-`` is "two points and a dash" (TOROT ⁛).
PUNCTUATION: dict[str, str] = {
    ": .": "⁖", ": -": "⁛", "::": "⁘", ":.": "⁖", ":-": "⁛", "--": "⁓",
    ".": ".", ":": ":", ",": ",", ";": ";",
}

#: The Vitae's hyphen (``iz-d-raja``) is the edition's, kept as written.
_VITAE_PUNCTUATION = {**PUNCTUATION, "?": "?", "-": "-"}

_BRACKETS: dict[str, tuple[str, str, str, str]] = {
    # opener: (closer, kind, opener written, closer written)
    "[": ("]", "supplement", "[", "]"),
    "{": ("}", "note", "{", "}"),
}


@dataclass(frozen=True)
class Table:
    """How one CCMH text spells Slavonic in ASCII."""

    name: str
    letters: Mapping[str, str]
    #: Diacritics written before the letter they sit on.
    next_marks: Mapping[str, str] = field(default_factory=lambda: dict(_COMMON_MARKS))
    #: Diacritics written after the letter they sit on (Zographensis ``^``).
    prev_marks: Mapping[str, str] = field(default_factory=dict)
    punctuation: Mapping[str, str] = field(default_factory=lambda: dict(PUNCTUATION))
    brackets: Mapping[str, tuple[str, str, str, str]] = field(
        default_factory=lambda: dict(_BRACKETS))
    #: Sign before a letter used as a numeral (the Vitae's ``/``): a titlo over it.
    numeral_sign: str | None = None
    #: ``?`` is an unreadable letter (the codices), not a question mark (the Vitae).
    question_is_lacuna: bool = True
    #: ``=…=`` encloses a later hand's addition.
    later_addition: bool = True
    #: ``-`` marks a word cut off by a lost leaf (the codices), not a hyphen.
    hyphen_is_lacuna: bool = True
    #: Sequences read as ꙑ (Assemanianus spells jery as ъ + і).
    ligatures: Mapping[str, str] = field(default_factory=dict)
    #: Typos in the file, fixed before conversion: {wrong: right}.
    fixes: Mapping[str, str] = field(default_factory=dict)
    #: Whole ASCII words that are the scribe's lection marks, not Gospel text.
    rubrics: frozenset[str] = frozenset()
    #: A mark written twice over one letter (Assemanianus ``//``): {mark: double mark}.
    doubled: Mapping[str, str] = field(default_factory=dict)
    #: Punctuation that keeps the space before it (Assemanianus's dash ``-``).
    free_marks: frozenset[str] = frozenset()


# The scribes' lection marks in the Gospel codices: к(онь)ць "end" and
# за(чѧ)ло "beginning" under a titlo (TOROT leaves them out). Bare ``za``
# is the preposition за, so only the abbreviated spellings count.
LECTION_MARKS = frozenset({"k!c", "kc", "!kc", "ko!c", "!ko!c", "za!C", "!za!C", "!zaC"})

_MARIANUS_MARKS = {**_COMMON_MARKS, "^": "\u0484"}   # round circumflex above the next letter

MARIANUS = Table("Codex Marianus", GLAGOLITIC_LETTERS, next_marks=_MARIANUS_MARKS,
                 rubrics=LECTION_MARKS)

ZOGRAPHENSIS = Table("Codex Zographensis", GLAGOLITIC_LETTERS,
                     prev_marks={"^": "\u0484"},   # above the previous letter
                     fixes={"ubojte": "uboJte"}, rubrics=LECTION_MARKS)

# Zogr-B, the later leaves (Matt 16:19–24:20), has its own table: Cyrillic f,
# <…> for letters Jagić printed that Moszyński could no longer see, jery as
# &I where one half is bracketed, and a trema.
ZOGR_B = Table("Codex Zographensis, Zogr-B", {**GLAGOLITIC_LETTERS, "F": "ф"},
               next_marks={**_COMMON_MARKS, '"': "\u0308"},
               prev_marks={"^": "\u0484"},
               brackets={**_BRACKETS, "<": (">", "supplement", "\u27e8", "\u27e9")},
               ligatures={"&I": "ꙑ"},
               fixes={"<j>E": "<jE>"}, rubrics=LECTION_MARKS)

# Assemanianus has no table of its own ("the same principles as Marianus;
# possible differences have not been documented but should be self-explanatory
# with the help of the edition", assemanianus.html). Its signs, checked against
# the CCMH tables of the same family and their distribution in the file (#368):
#
# - ``/`` (17.5k) is the stroke the codex writes over letters: 82% stand before
#   a vowel at the start of a word or after another vowel (``/isa/aka``,
#   ``bratI/jO``, ``/ego``), where Glagolitic and early Cyrillic scribes mark
#   an initial or hiatus vowel; the rest at syllable edges in names
#   (``/es/roma``) and between consonants (``m/nog&I``). A stroke over the next
#   letter, U+0301 as the ASCII sign draws it; ``//`` (122, mostly before a
#   word-initial vowel: ``//wt&``) is two strokes, the double acute U+030B.
# - ``\`` (26) and the backtick (58) lean the other way: the grave U+0300; a
#   doubled backtick (4) the double grave U+030F.
# - ``"`` a trema and ``)`` a psili over the next letter: what both mean in
#   Suprasliensis's table, the only CCMH table that defines them.
# - ``+`` (9, between words at a line end) a cross ✝, as elsewhere in CCMH.
# - ``-`` is not Marianus's "missing part of a word": none of its 243 uses
#   touches a word (no word is broken over two lines in this file); all but
#   about 15 follow a stop at the end of a lection or verse (``:: -``,
#   ``:: . -``), the rest stand between words. It is the scribe's dash:
#   punctuation (–), not a lacuna.
#
# Jery is written ъ + і (``&I``); read as ꙑ, as glagolitic_to_cyrillic reads
# yer + i.
ASSEMANIANUS = Table(
    "Codex Assemanianus", GLAGOLITIC_LETTERS,
    next_marks={**_MARIANUS_MARKS, "/": "́", "\\": "̀", "`": "̀",
                '"': "̈", ")": "҆"},
    doubled={"́": "̋", "̀": "̏"},
    punctuation={**PUNCTUATION, "-": "–"},
    hyphen_is_lacuna=False,
    free_marks=frozenset({"-"}),
    ligatures={"&I": "ꙑ", "&i": "ꙑ", "&J": "ꙑ"},
    fixes={"h(l&m&": "x(l&m&"},
    rubrics=LECTION_MARKS,
)

# Savvina kniga and the Vitae follow Suprasliensis's table.
_CYRILLIC_MARKS = {**_COMMON_MARKS, ")": "\u0486", '"': "\u0308"}

# Savvina kniga writes no ``@``: jat is ``"e`` (2,956 times: pr"e-, v$l"eze,
# n"est&), ꙗ is ``"E`` (pri("Eti, mari("E) and iotated jat ``j"e`` (j"eko), so
# ``"`` is part of those letters here, not a trema.
SAVVINA = Table("Savvina kniga",
                {**CYRILLIC_LETTERS, '"e': "ѣ", '"E': "ꙗ", 'j"e': "ꙓ", "jo": "ѭ"},
                next_marks={**_COMMON_MARKS, ")": "\u0486"},
                prev_marks={"^": "\u0484"},
                fixes={" sH ": " sE ", "moZAxo": "moZaxo"}, rubrics=LECTION_MARKS)

# The Vitae: ``/`` marks a letter used as a numeral (``/D`` → ѕ҃), ``?`` and
# ``,`` are Tomšič's modern punctuation, and ``C4st$noje`` is a typo.
VITAE = Table("Vitae Constantini et Methodii", CYRILLIC_LETTERS,
              next_marks=_CYRILLIC_MARKS, numeral_sign="/", question_is_lacuna=False,
              punctuation=_VITAE_PUNCTUATION,
              later_addition=False, hyphen_is_lacuna=False, fixes={"C4st$noje": "Cst$noje"})


class ConversionError(ValueError):
    """CCMH text the table cannot read."""


@dataclass
class _Cluster:
    text: str
    group: int | None = None   # editorial group id, or None for plain text
    letter: bool = False       # a base letter (titlo placement)
    punct: bool = False        # a punctuation mark


@dataclass
class Converted:
    """A converted unit: Cyrillic text, its editorial spans and what was dropped."""

    text: str
    editorial: list[list]
    unknown: Counter = field(default_factory=Counter)
    dropped: Counter = field(default_factory=Counter)


def convert(ascii_text: str, table: Table) -> Converted:
    """Convert one unit of CCMH ASCII into Cyrillic with its editorial spans."""
    for wrong, right in table.fixes.items():
        ascii_text = ascii_text.replace(wrong, right)
    letter_keys = sorted({**table.letters, **table.ligatures}, key=len, reverse=True)
    letters = {**table.letters, **table.ligatures}
    punct_keys = sorted(table.punctuation, key=len, reverse=True)
    closers = {v[0]: k for k, v in table.brackets.items()}

    out: list[_Cluster] = []
    kinds: dict[int, str] = {}
    unknown: Counter = Counter()
    dropped: Counter = Counter()
    groups: list[tuple[int, str]] = []   # open groups: (id, closer)
    later: int | None = None             # open =…= group
    rubric: int | None = None            # open lection mark
    rubric_end = -1
    next_id = 0

    pending_marks: list[str] = []
    upper = superscript = numeral = word_titlo = False
    word: list[int] = []                 # indices of the current word's base letters

    def group() -> int | None:
        if rubric is not None:
            return rubric
        if groups:
            return groups[0][0]          # nested brackets belong to the outermost
        return later

    def new_group(kind: str) -> int:
        nonlocal next_id
        next_id += 1
        kinds[next_id] = kind
        return next_id

    def end_word() -> None:
        nonlocal word_titlo, upper, superscript, numeral
        if word_titlo and word:
            target = word[1] if len(word) > 1 else word[0]
            out[target].text += TITLO
        word.clear()
        word_titlo = upper = superscript = numeral = False
        pending_marks.clear()

    def emit_space() -> None:
        if out and out[-1].text != " ":
            out.append(_Cluster(" ", group()))

    i = 0
    n = len(ascii_text)
    while i < n:
        ch = ascii_text[i]
        if rubric is not None and i >= rubric_end:
            rubric = None
        if (table.rubrics and rubric is None and not groups and later is None
                and (i == 0 or ascii_text[i - 1] in " \t")
                and ascii_text[i:].split(" ", 1)[0] in table.rubrics):
            rubric = new_group("metadata")
            rubric_end = i + len(ascii_text[i:].split(" ", 1)[0])
        if ch in " \t":
            end_word()
            emit_space()
            i += 1
            continue
        if ch == "%":
            dropped["%"] += 1
            i += 1
            continue
        if ch == "*":
            upper = True
            i += 1
            continue
        if ch == "!":
            while i + 1 < n and ascii_text[i + 1] == "!":
                i += 1
            if not word and not superscript:
                word_titlo = True
            else:
                superscript = True
            i += 1
            continue
        if table.numeral_sign and ch == table.numeral_sign:
            numeral = True
            i += 1
            continue
        if ch in table.next_marks:
            mark = table.next_marks[ch]
            if pending_marks and pending_marks[-1] == mark and mark in table.doubled:
                pending_marks[-1] = table.doubled[mark]
            else:
                pending_marks.append(mark)
            i += 1
            continue
        if ch in table.prev_marks:
            if word:
                out[word[-1]].text += table.prev_marks[ch]
            else:
                pending_marks.append(table.prev_marks[ch])
            i += 1
            continue
        if ch == "'":
            out.append(_Cluster(PAEROK, group()))
            i += 1
            continue
        if ch in table.brackets:
            closer, kind, opener_out, _ = table.brackets[ch]
            if not groups and later is None:
                groups.append((new_group(kind), closer))
            else:
                groups.append((group() or 0, closer))
            out.append(_Cluster(opener_out, group()))
            i += 1
            continue
        if ch in closers:
            if not groups or groups[-1][1] != ch:
                dropped[f"unbalanced {ch}"] += 1   # a stray closer: not text
                i += 1
                continue
            out.append(_Cluster(table.brackets[closers[ch]][3], group()))
            groups.pop()
            i += 1
            continue
        if ch == "=" and table.later_addition:
            if later is None and not groups:
                later = new_group("supplement")
            elif later is not None and not groups:
                later = None
            i += 1
            continue
        if ch == "?" and table.question_is_lacuna:
            g = group()
            out.append(_Cluster("?", g if g is not None else new_group("lacuna")))
            i += 1
            continue
        if ch == "-" and table.hyphen_is_lacuna and not ascii_text.startswith("--", i):
            g = group()
            out.append(_Cluster("-", g if g is not None else new_group("lacuna")))
            i += 1
            continue
        key = next((k for k in letter_keys if ascii_text.startswith(k, i)), None)
        if key is not None:
            base = letters[key]
            if superscript and base in SUPERSCRIPT:
                text = SUPERSCRIPT[base] + "".join(pending_marks) + POKRYTIE
                out.append(_Cluster(text, group()))
            else:
                if upper:
                    base = base[0].upper() + base[1:]
                text = base + "".join(pending_marks) + (TITLO if numeral else "")
                out.append(_Cluster(unicodedata.normalize("NFC", text), group(), letter=True))
                word.append(len(out) - 1)
            pending_marks.clear()
            upper = superscript = numeral = False
            i += len(key)
            continue
        pkey = next((k for k in punct_keys if ascii_text.startswith(k, i)), None)
        if pkey is not None:
            end_word()
            # Attach a mark to the word before it ("словомъ ." → "словомъ."),
            # but keep a space between two marks ("⁘ ⁘") and before the dot
            # that opens a numeral framed by dots ("и .и҃і."). A mark written
            # against the next word ("чл҃вкомъ .приде") gets a space after it,
            # since derived verses break only between words.
            after = i + len(pkey)
            nxt = ascii_text[after:].split(" ", 1)[0]
            framed = (len(nxt) > 1 and nxt[-1] == "." and "." not in nxt[:-1]
                      and any(c.isalpha() for c in nxt))
            if (len(out) > 1 and out[-1].text == " " and out[-1].group == group()
                    and not out[-2].punct and not framed
                    and pkey not in table.free_marks):
                out.pop()
            out.append(_Cluster(table.punctuation[pkey], group(), punct=True))
            if (nxt and not framed and pkey != "-"
                    and (nxt[0].isalpha() or nxt[0] in "*!(~^/\"&$@")):
                out.append(_Cluster(" ", group()))
            i += len(pkey)
            continue
        if ch == "+":
            end_word()
            out.append(_Cluster("✝", group()))
            i += 1
            continue
        unknown[ch] += 1
        i += 1
    end_word()
    if groups or later is not None:   # the span runs to the end of the unit
        dropped["unclosed " + (groups[-1][1] if groups else "=")] += 1

    # Trim spaces at either end, then build the text and its spans.
    while out and out[0].text == " ":
        out.pop(0)
    while out and out[-1].text == " ":
        out.pop()
    text = ""
    spans: list[list] = []
    for c in out:
        start = len(text)
        text += c.text
        if c.group is None:
            continue
        if c.text == " " and (not spans or spans[-1][3] != c.group):
            continue
        if spans and spans[-1][3] == c.group and spans[-1][1] == start:
            spans[-1][1] = len(text)
        else:
            spans.append([start, len(text), kinds[c.group], c.group])
    editorial = []
    for s, e, kind, _ in spans:
        while e > s and text[e - 1] == " ":
            e -= 1
        if e > s:
            editorial.append([s, e, kind])
    text = glagolitic_to_cyrillic(text)
    return Converted(text, editorial, unknown, dropped)


# ---------------------------------------------------------------------------
# Files and line numbers
# ---------------------------------------------------------------------------

_LINE_RE = re.compile(r"^(\d{7})(\S?(?: .*)?)$")   # Savvina: "4190501% *v& ..."


def fetch(name: str, raw_root: Path, force: bool = False) -> Path:
    """Download one CCMH text file (``marianus.txt``) into the raw cache."""
    dest = raw_root / CACHE_DIR / name
    download_file(BASE_URL + name, dest, force=force)
    return dest


def read_lines(path: Path) -> list[tuple[str, str]]:
    """The numbered lines of a CCMH file: ``[(seven digits, text), …]``."""
    out: list[tuple[str, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        if not line.strip():
            continue
        m = _LINE_RE.match(line.rstrip())
        if not m:
            raise ConversionError(f"{path.name}:{lineno}: not a numbered CCMH line: {line!r}")
        out.append((m.group(1), (m.group(2) or "").strip()))
    return out


def join_lines(parts: list[str]) -> str:
    """Join a unit's lines with spaces; a word broken over two lines
    (``razli-`` / ``-C$n&``, or ``sjO-`` / ``botO``) is joined without one."""
    text = ""
    for part in parts:
        if not text:
            text = part
        elif re.search(r"[^\s:.-]-$", text) and part.startswith("-") and not part.startswith("--"):
            text = text[:-1] + part[1:]
        elif re.search(r"[^\s:.-]-$", text):
            text = text[:-1] + part
        elif re.match(r"[<\[]-[^-]", part):   # Zogr-B: "<-n&>" ends the main text's word
            text = text + part[0] + part[2:]
        else:
            text = f"{text} {part}"
    return text


# ---------------------------------------------------------------------------
# Gospel codices
# ---------------------------------------------------------------------------

GOSPEL_BOOKS = {"1": "Matt", "2": "Mark", "3": "Luke", "4": "John"}


@dataclass
class GospelText:
    """One codex's Gospel lines, grouped by verse."""

    #: (book digit, chapter, verse) → parallel digit → lines, in file order.
    verses: dict[tuple[str, int, int], dict[str, list[str]]]
    #: Book digit → the lines CCMH files under chapter 0, the codex's list of
    #: chapters (kephalaia) before that Gospel: [(line number, text), …].
    lists: dict[str, list[tuple[int, str]]] = field(default_factory=dict)
    #: Verses read with another table than the codex's (the Zogr-B leaves).
    tables: dict[tuple[str, int, int], Table] = field(default_factory=dict)


def parse_gospels(lines: list[tuple[str, str]],
                  renumber: Mapping[str, str] | None = None) -> GospelText:
    """Group ``GCCVVLP`` lines (Gospel, chapter, verse, line, parallel) by verse.

    Chapter 0 is the codex's chapter list, numbered by line (``GCC`` then a
    three-digit line number and ``P``). *renumber* corrects line numbers
    mistyped in the file (``{wrong: right}``).
    """
    verses: dict[tuple[str, int, int], dict[str, list[str]]] = {}
    lists: dict[str, list[tuple[int, str]]] = {}
    for num, text in lines:
        num = (renumber or {}).get(num, num)
        book, chap, verse, par = num[0], int(num[1:3]), int(num[3:5]), num[6]
        if book not in GOSPEL_BOOKS:
            raise ConversionError(f"line {num}: Gospel digit {book} is not 1–4")
        if chap == 0:
            lists.setdefault(book, []).append((int(num[3:6]), text))
            continue
        verses.setdefault((book, chap, verse), {}).setdefault(par, []).append(text)
    return GospelText(verses, lists)


def merge_leaves(main: GospelText, leaves: GospelText, table: Table) -> GospelText:
    """Add a codex's replacement leaves (Zogr-B) to its main text.

    A verse that the leaves share with the main text is split at a leaf edge:
    the leaves' part comes first if the verse is the leaves' last one
    (they end inside it), else after the main text's part. Every verse with
    lines from the leaves is read with their *table*, a superset of the main
    one for the few lines of a shared verse.
    """
    if leaves.lists:
        raise ConversionError("replacement leaves with a chapter list are not supported")
    merged = {k: {p: list(v) for p, v in d.items()} for k, d in main.verses.items()}
    last = max(leaves.verses)
    for key, pars in leaves.verses.items():
        for par, lines in pars.items():
            have = merged.setdefault(key, {}).setdefault(par, [])
            merged[key][par] = lines + have if key == last else have + lines
    return GospelText(dict(sorted(merged.items(), key=lambda kv: kv[0])), main.lists,
                      {**main.tables, **{key: table for key in leaves.verses}})


@dataclass
class GospelBook:
    osis: str
    verses: list[dict]          # raw units: {"ref", "text"[, "editorial"]}
    repeats_dropped: int = 0
    list_units: int = 0         # units of the chapter list (kephalaia)
    #: Verses whose kept reading is a later one (#370): [(ref, parallel digit)].
    later_readings: list[tuple[str, str]] = field(default_factory=list)


_BROKEN_WORD = re.compile(r"[^\s:.-]-$")


def chapter_list(osis: str, lines: list[tuple[int, str]],
                 table: Table) -> list[tuple[str, Converted]]:
    """The units of a codex's chapter list (kephalaia, #369): ``{osis}.0.{n}``.

    CCMH files the list under chapter 0 with the codex's own line division,
    and so does the ingest: one unit per line, numbered from 0, so the list's
    title (its first line, "глави евангелиѣ…") is ``{osis}.0.0``, which the
    reader shows as the heading of chapter 0, and the line after it
    ``{osis}.0.1``. A word broken over two lines (Zographensis ``razli-`` /
    ``-C$n&``) is joined onto the line it starts on, so a unit never holds
    half a word and the next number is skipped. The list is manuscript text,
    but no Gospel verse: each unit is marked as a ``title`` (#236), so readers
    see it and it gets no translation and no vector, and versification has
    nothing to map (``Mark.0.n`` is in no scheme, so it is its own group).
    """
    groups: list[tuple[int, list[str]]] = []
    for line, text in lines:
        if groups and _BROKEN_WORD.search(groups[-1][1][-1]):
            groups[-1][1].append(text)
        else:
            groups.append((line, [text]))
    out = []
    for line, parts in groups:
        conv = convert(join_lines(parts), table)
        conv.editorial = [[0, len(conv.text), "title"]] if conv.text else []
        out.append((f"{osis}.0.{line - 1}", conv))
    return out


# Lectionary readings (#370). Letters compared on their base form, without
# diacritics, yers and the spelling differences between the codices.
_COMPARE = str.maketrans({"і": "и", "ꙇ": "и", "ї": "и", "ѡ": "о", "ѹ": "у", "ꙋ": "у",
                          "ꙑ": "ы", "ѣ": "е", "ꙗ": "я", "ѥ": "е", "ѕ": "з", "ь": "", "ъ": ""})
#: A later reading replaces the first only when the first is cut short: the
#: first is under this share of the later one's length …
CUT_SHORT_LENGTH = 0.8
#: … and covers at least this much less of the verse in the continuous text.
CUT_SHORT_RECALL = 0.2


def comparable(conv: Converted) -> str:
    """A unit's letters for comparing readings: no editorial notes, lection
    marks or lacunae, no diacritics, one spelling per letter, single spaces."""
    text = conv.text
    for s, e, kind in sorted(conv.editorial, reverse=True):
        if kind in ("metadata", "lacuna", "note"):
            text = f"{text[:s]} {text[e:]}"
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if not unicodedata.category(c).startswith("M"))
    text = text.replace("оу", "у").translate(_COMPARE)
    return " ".join(re.sub(r"\W+", " ", text).split())


def _trigrams(text: str) -> Counter:
    text = f" {text} "
    return Counter(text[i:i + 3] for i in range(len(text) - 2))


def recall(text: str, reference: str) -> float:
    """Share of *reference*'s letter trigrams that *text* has."""
    ref = _trigrams(reference)
    total = sum(ref.values())
    return sum((_trigrams(text) & ref).values()) / total if total else 0.0


def choose_reading(readings: Mapping[str, Converted], reference: str | None) -> str:
    """The parallel digit of the reading of a lectionary verse to keep (#370).

    The first reading (the lowest digit) is kept, unless it is cut short: a
    lection that ends or starts inside the verse (Assemanianus Matt 10:37 has
    only its first half, Savvina Matt 10:40 lacks its second clause). It is
    then replaced by the reading that covers the most of the verse as the
    continuous-text codices have it (*reference*, Marianus or Zographensis),
    if that reading is clearly longer (the first is under
    ``CUT_SHORT_LENGTH`` of it) and covers clearly more (``CUT_SHORT_RECALL``
    more of the reference's letter trigrams). Both tests together keep the
    first reading where the readings only differ in wording or a later one
    only adds a lection formula ("рече господь своимъ ученикомъ"); a later
    reading kept for its completeness keeps the formula it opens with, since
    that is the codex's text. A verse no continuous codex has keeps its first.
    """
    first = min(readings)
    if reference is None or len(readings) < 2:
        return first
    text = {p: comparable(c) for p, c in readings.items()}
    score = {p: recall(text[p], reference) for p in readings}
    best = max(readings, key=lambda p: (score[p], -int(p)))
    if (best != first and score[best] > score[first] + CUT_SHORT_RECALL
            and len(text[first]) < CUT_SHORT_LENGTH * len(text[best])):
        return best
    return first


def gospel_books(text: GospelText, table: Table,
                 reference: Mapping[tuple[str, int, int], str] | None = None,
                 ) -> tuple[list[GospelBook], Counter, Counter]:
    """Convert a codex into one raw book per Gospel, in verse order.

    A lectionary (Assemanianus, Savvina) reads some verses on several days;
    CCMH gives each reading a parallel digit. One reading is kept, so the book
    has one unit per verse, as versification expects: the first, unless it is
    cut short and *reference* (the verse in the continuous-text codices,
    ``comparable`` form) shows a later one is the full verse
    (``choose_reading``, #370). The codex's chapter list, if it has one, comes
    first (``chapter_list``, #369).
    """
    books: dict[str, GospelBook] = {}
    unknown: Counter = Counter()
    dropped: Counter = Counter()

    def book_for(digit: str) -> GospelBook:
        osis = GOSPEL_BOOKS[digit]
        if osis not in books:
            books[osis] = gb = GospelBook(osis, [])
            for ref, conv in chapter_list(osis, text.lists.get(digit, []), table):
                unknown.update(conv.unknown)
                dropped.update(conv.dropped)
                if conv.text:
                    gb.verses.append({"ref": ref, "text": conv.text, "editorial": conv.editorial})
                    gb.list_units += 1
        return books[osis]

    for digit in sorted(text.lists):
        book_for(digit)
    for (book, chap, verse), pars in sorted(text.verses.items()):
        osis = GOSPEL_BOOKS[book]
        gb = book_for(book)
        verse_table = text.tables.get((book, chap, verse), table)
        readings = {p: convert(join_lines(lines), verse_table) for p, lines in pars.items()}
        kept = choose_reading(readings, (reference or {}).get((book, chap, verse)))
        gb.repeats_dropped += len(pars) - 1
        if kept != min(pars):
            gb.later_readings.append((f"{osis}.{chap}.{verse}", kept))
        conv = readings[kept]
        unknown.update(conv.unknown)
        dropped.update(conv.dropped)
        if not conv.text:
            continue
        unit: dict = {"ref": f"{osis}.{chap}.{verse}", "text": conv.text}
        if verse == 0:
            # A lection title the codex writes before a verse (Marianus Luke
            # 2:0 "on the eve of the Nativity"): the manuscript's, kept for
            # readers, but no Gospel text, so marked as a title (#236).
            unit["editorial"] = [[0, len(conv.text), "title"]]
        elif conv.editorial:
            unit["editorial"] = conv.editorial
        gb.verses.append(unit)
    return [books[b] for b in GOSPEL_BOOKS.values() if b in books], unknown, dropped


def group_units(lines: list[tuple[str, str]],
                width: tuple[int, int]) -> dict[tuple[int, int], list[str]]:
    """Group lines by a (chapter, verse) number read from digit slices *width*
    (``(2, 5)``: chapter = digits 0–1, verse = digits 2–4)."""
    out: dict[tuple[int, int], list[str]] = defaultdict(list)
    a, b = width
    for num, text in lines:
        out[(int(num[:a]), int(num[a:b]))].append(text)
    return dict(out)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

#: The Slavonic Gospel translation: Constantine-Cyril and Methodius, from 863
#: (the aprakos first), complete by Methodius's death in 885. The codices are
#: 10th–11th-century copies; works are dated by the translation.
GOSPEL_DATE: dict = {"date_composed": 863, "date_range": (863, 885),
                     "date_confidence": "approximate"}


@dataclass(frozen=True)
class Codex:
    """A CCMH Gospel codex: its file, table and description."""

    source_id: str
    name: str                     # "Codex Marianus"
    file: str                     # "marianus.txt"
    table: Table
    edition: str                  # the printed edition CCMH's text follows
    leaves: tuple[str, Table] | None = None   # Zogr-B: (file, table)
    renumber: Mapping[str, str] = field(default_factory=dict)
    #: A lectionary: a repeated verse keeps its full reading (#370).
    lectionary: bool = False


#: Two lines of marianus.txt carry mistyped numbers: Luke 1:55 and the second
#: line of John 5:9.
MARIANUS_RENUMBER = {"3105500": "3015500", "4059100": "4050910"}

#: The continuous-text codices a lectionary's readings are measured against
#: (#370), in order of preference: (file, table, renumber, leaves).
CONTINUOUS_TEXTS: tuple[tuple[str, Table, Mapping[str, str], tuple[str, Table] | None], ...] = (
    ("marianus.txt", MARIANUS, MARIANUS_RENUMBER, None),
    ("zographensis.txt", ZOGRAPHENSIS, {}, ("zogr-b.txt", ZOGR_B)),
)


def read_codex(file: str, renumber: Mapping[str, str], leaves: tuple[str, Table] | None,
               raw_root: Path, force: bool = False) -> GospelText:
    """A codex's lines by verse, with its replacement leaves merged in."""
    text = parse_gospels(read_lines(fetch(file, raw_root, force)), renumber)
    if leaves:
        leaves_file, leaves_table = leaves
        text = merge_leaves(text, parse_gospels(read_lines(fetch(leaves_file, raw_root, force))),
                            leaves_table)
    return text


def continuous_reference(raw_root: Path, force: bool = False) -> dict[tuple[str, int, int], str]:
    """Every verse of the continuous-text codices, ``comparable`` (Marianus
    where it has the verse, else Zographensis)."""
    out: dict[tuple[str, int, int], str] = {}
    for file, table, renumber, leaves in CONTINUOUS_TEXTS:
        text = read_codex(file, renumber, leaves, raw_root, force)
        for key, pars in text.verses.items():
            if key not in out:
                out[key] = comparable(convert(join_lines(pars[min(pars)]),
                                              text.tables.get(key, table)))
    return out


def log_conversion(name: str, unknown: Counter, dropped: Counter) -> None:
    """Log what a conversion could not read (ERROR: text was lost, so a forced
    run is not stamped) and the markup it dropped on purpose (INFO)."""
    if unknown:
        log.error("%s: characters the table does not know, dropped: %s", name, dict(unknown))
    if dropped:
        log.info("%s: dropped markup %s", name, dict(dropped))


def ingest_codex(codex: Codex, output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw work per Gospel book of *codex* to ``output_dir/{source_id}/``."""
    source_dir = output_dir / codex.source_id
    source_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(source_dir.glob("*.json"))
    if existing and not force:
        log.info("%s: %d books already ingested (--force rebuilds them)", codex.name, len(existing))
        return [Work(**json.loads(p.read_text(encoding="utf-8"))["work"]) for p in existing]

    text = read_codex(codex.file, codex.renumber, codex.leaves, output_dir, force)
    reference = continuous_reference(output_dir, force) if codex.lectionary else None
    books, unknown, dropped = gospel_books(text, codex.table, reference)
    log_conversion(codex.name, unknown, dropped)

    works: list[Work] = []
    for book in books:
        if book.repeats_dropped:
            log.info("%s %s: dropped %d repeated readings of a verse (lectionary)",
                     codex.name, book.osis, book.repeats_dropped)
        if book.later_readings:
            log.info("%s %s: kept a later reading of %d verses whose first is cut short: %s",
                     codex.name, book.osis, len(book.later_readings),
                     ", ".join(f"{ref} (P={p})" for ref, p in book.later_readings))
        if book.list_units:
            log.info("%s %s: chapter list (kephalaia) as %d units %s.0.*",
                     codex.name, book.osis, book.list_units, book.osis)
        work = Work(
            work_id=book_work_id(codex.source_id, book.osis),
            source_id=codex.source_id,
            title=BOOK_TITLE.get(book.osis, book.osis),
            author=None,
            **GOSPEL_DATE,
            genre="scripture",
            language="chu",
            tradition="slavonic",
            license="cc-by-4.0",
            provenance_url=BASE_URL + codex.file,
            edition=f"{codex.name}, {codex.edition}; {CORPUS}, ASCII transliteration "
                    f"converted to Cyrillic",
        )
        out = source_dir / f"{book.osis}.json"
        out.write_text(json.dumps({"work": work.model_dump(), "verses": book.verses},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("%s %s: %d verses → %s", codex.name, book.osis, len(book.verses), out)
        works.append(work)
    return works
