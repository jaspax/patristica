"""
Leading section numbers that duplicate a chunk's ``canonical_ref``.

Many printed editions number their paragraphs in the text itself
(``<p>3 Αὐτοκράτορι …</p>`` in First1KGreek, "1. Great art Thou…" in NPNF,
"α. Πᾶσαι…" in PTA).  The ingestors already put that number in the ref, so
the copy at the start of the text is a duplicate: the reader shows it twice
and it is noise for search and embeddings (#30).

:func:`leading_section_number` finds such a prefix and
:func:`strip_section_number` removes it.  The rule is deliberately narrow:
the prefix is removed **only when its value equals the ref's last segment**.
Recognised forms:

- Arabic digits, bare or followed by ``.`` or ``)``, or wrapped in ``[ ]`` or
  ``( )``: ``3 …``, ``3. …``, ``3) …``, ``[3] …``, ``(3) …``
  (leading zeros in the ref are ignored: ``Dec.0002`` matches ``2.``);
- Greek alphabetic numerals with a keraia and/or a dot, in Greek text only:
  ``γ. …``, ``γʹ …``, ``ιβʹ. …``;
- Roman numerals with a following ``.`` or ``)`` (never bare, so the English
  pronoun "I" is safe): ``IV. …`` for a ref ending in ``iv``/``IV``.

Guards against stripping real content:

- the number must be followed by whitespace and then a non-digit, so
  ``3.5``, ``3:16`` and ``3 4 5`` are untouched;
- a bare number followed by a numbered biblical book (``1 Cor``,
  ``1 Timothy``, ``1 Βασ.``) is a scripture citation, and one followed by
  ``bis`` or a Roman calendar word (``8 kal. decembris``) is content;
- something with letters must be left after stripping;
- single-letter Roman "numerals" ``C``, ``D``, ``L``, ``M`` are not matched,
  since a ref ending in ``c``/``d`` is usually a lettered subsection and the
  text may start with an initial ("C. Julius …");
- sources whose refs are serial counters rather than the edition's numbers
  (:data:`SERIAL_REF_SOURCES`) are skipped: a printed number there that equals
  the counter is a coincidence (e.g. a footnote marker "(90)" in OCR'd Migne).

Numbering that does not equal the ref's last segment (continuous paragraph
numbers against chapter.section refs) is left alone on purpose: there is no
way to tell it from content without the edition at hand.
"""

from __future__ import annotations

import re

#: Sources whose refs are synthetic sequence numbers, not edition numbering.
#: OGPG refs (``ogpg.vol-045.c0009.3``) end in the paragraph's position on its
#: Migne page, which the OCR text never prints, so a match is still chance.
SERIAL_REF_SOURCES: frozenset[str] = frozenset({"ogpg"})

_GREEK_VALUES: dict[str, int] = {
    "α": 1,
    "β": 2,
    "γ": 3,
    "δ": 4,
    "ε": 5,
    "ϛ": 6,
    "ς": 6,
    "ϝ": 6,
    "ζ": 7,
    "η": 8,
    "θ": 9,
    "ι": 10,
    "κ": 20,
    "λ": 30,
    "μ": 40,
    "ν": 50,
    "ξ": 60,
    "ο": 70,
    "π": 80,
    "ϟ": 90,
    "ϙ": 90,
    "ρ": 100,
    "σ": 200,
    "τ": 300,
    "υ": 400,
    "φ": 500,
    "χ": 600,
    "ψ": 700,
    "ω": 800,
    "ϡ": 900,
}
_ROMAN_VALUES: dict[str, int] = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

# Keraia (U+0374), modifier prime (U+02B9), Greek tonos (U+0384), acute,
# apostrophe and right single quote all occur as the numeral sign.
_KERAIA = "ʹʹ΄´'’"

_ARABIC_RE = re.compile(r"(?:\[\s*(\d+)\s*\]|\(\s*(\d+)\s*\)|(\d+)\s*[.)]?)\s+")
_GREEK_RE = re.compile(
    rf"(στ|[{''.join(_GREEK_VALUES)}]{{1,4}})(?:[{_KERAIA}]\.?|\.)\s+",
    re.IGNORECASE,
)
_ROMAN_RE = re.compile(r"([ivxlcdm]+)[.)]\s+", re.IGNORECASE)

# A number followed by one of these is a citation ("1 Cor. 13", "1 Timothy i. 1",
# "1 Joann. v. 7"), not a section number.  Greek abbreviations need their dot,
# so a section starting "1 Βασιλεύοντος …" is still recognised.
_NUMBERED_BOOK_RE = re.compile(
    r"(?:(?:Cor|Corinth|Corinthians|Kings?|Kgs|Sam|Samuel|Chron|Chronicles|Chr"
    r"|Paral|Paralip\w*|Par|Thes|Thess|Thessalonians|Tim|Timothy|Pet|Peter|Petr"
    r"|John|Jn|Joh|Joann|Joannis|Johannis|Ioann\w*|Macc?|Maccabees|Esd|Esdr|Esdras"
    r"|Reg|Regn|Regum)\b"
    r"|(?:Κορ|Βασ|Παρ|Θεσ|Τιμ|Πετ|Ἰω|Μακ)\w*\.)",
)

# A bare number followed by one of these is part of the text: "29 bis." (a
# duplicated section number), "8 kal. decembris" (a Roman calendar date).
_NUMBER_CONTENT_RE = re.compile(
    r"(?:bis|ter|quater)\b"
    r"|(?:\(al\.[^)]*\)\s*)?(?:(?:kal|kalend|id|non)\.|(?:kalendas|kalendis|idus|idibus|nonas|nonis)\b)",
    re.IGNORECASE,
)


def _greek_value(token: str) -> int | None:
    token = token.lower()
    if token == "στ":
        return 6
    values = [_GREEK_VALUES.get(ch) for ch in token]
    if None in values:
        return None
    # A Greek numeral is written largest place first, one letter per place.
    if any(a <= b for a, b in zip(values, values[1:])):  # type: ignore[operator]
        return None
    places = [len(str(v)) for v in values]  # type: ignore[arg-type]
    if len(set(places)) != len(places):
        return None
    return sum(values)  # type: ignore[arg-type]


def _roman_value(token: str) -> int | None:
    token = token.lower()
    if not token or any(ch not in _ROMAN_VALUES for ch in token):
        return None
    total = 0
    for i, ch in enumerate(token):
        v = _ROMAN_VALUES[ch]
        if i + 1 < len(token) and v < _ROMAN_VALUES[token[i + 1]]:
            total -= v
        else:
            total += v
    if _to_roman(total) != token:  # reject non-canonical forms ("iiii", "vx")
        return None
    return total


def _to_roman(n: int) -> str:
    out = []
    for value, sym in (
        (1000, "m"),
        (900, "cm"),
        (500, "d"),
        (400, "cd"),
        (100, "c"),
        (90, "xc"),
        (50, "l"),
        (40, "xl"),
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    ):
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)


def _rest_ok(rest: str) -> bool:
    """Is *rest* plausibly the text that follows a section number?"""
    if not rest or rest[0].isdigit():
        return False
    if not any(ch.isalpha() for ch in rest):
        return False
    return True


def leading_section_number(
    text: str,
    ref: str,
    language: str | None = None,
    source_id: str | None = None,
) -> str | None:
    """Return the prefix of *text* that repeats *ref*'s last segment, or ``None``.

    The returned prefix includes the whitespace after the number, so
    ``text[len(prefix):]`` is the text without it.
    """
    if source_id in SERIAL_REF_SOURCES or not text or not ref:
        return None
    last = ref.rsplit(".", 1)[-1]

    if last.isdigit():
        n = int(last)
        m = _ARABIC_RE.match(text)
        if m:
            digits = next(g for g in m.groups() if g is not None)
            rest = text[m.end() :]
            # Only a bare number can be the start of a citation or a date
            # ("1 Cor.", "8 kal."); "3. John …" is a section number.
            bare = m.group(0).strip().isdigit()
            if (
                int(digits) == n
                and _rest_ok(rest)
                and not (bare and _NUMBERED_BOOK_RE.match(rest))
                and not (bare and _NUMBER_CONTENT_RE.match(rest))
            ):
                return m.group(0)
        if language == "grc":
            m = _GREEK_RE.match(text)
            if m and _greek_value(m.group(1)) == n and _rest_ok(text[m.end() :]):
                return m.group(0)
        return None

    value = _roman_value(last)
    if value is not None and not (len(last) == 1 and last.lower() in "cdlm"):
        m = _ROMAN_RE.match(text)
        if m and m.group(1).lower() == last.lower() and _rest_ok(text[m.end() :]):
            return m.group(0)
    return None


def strip_section_number(
    text: str,
    ref: str,
    language: str | None = None,
    source_id: str | None = None,
) -> str:
    """Return *text* without a leading number that repeats *ref*'s last segment."""
    prefix = leading_section_number(text, ref, language, source_id)
    return text[len(prefix) :] if prefix else text
