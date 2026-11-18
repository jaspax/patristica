"""OCR error metrics for Greek (#718).

Diplomatic scoring: both texts are NFC-normalized and their whitespace
collapsed (line breaks become spaces), nothing else. Case, punctuation,
accents and breathings all count, since they are what the pipeline has to get
right (#705). ``dehyphenate=True`` joins words split at a line end on both
sides, for comparing a stage that dehyphenates against the diplomatic ground
truth.

Metrics, per page and summed over a set of pages:

* **CER** = (S + D + I) / reference characters, the usual definition (the one
  Calfa's 1.05 % and CLLG's 1.18 % use; it can exceed 1).
* **base CER**: the same with every combining mark (accent, breathing, iota
  subscript, diaeresis) removed from both sides. **Accent share** =
  1 − base errors / errors: the share of character errors that are accents and
  breathings alone.
* **WER** over whitespace tokens.
* **Real-word substitutions**: substituted Greek words whose reading is a
  *different* valid Greek form (``_greek_lexicon``, accent-folded) that looks
  like the original (folded similarity ≥ ``MIN_PAIR_SIMILARITY``). These are
  the errors a dictionary check can't see (arXiv 2605.27750). Substitutions
  that differ only in diacritics are counted separately (``accent_words``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, fields

from rapidfuzz.distance import Levenshtein

from scripts.ingest._greek_lexicon import is_greek_form, normalize_token

_WS = re.compile(r"\s+")
# A substituted pair whose folded forms are less similar than this is an
# alignment artefact (two unrelated words paired in a shifted block), not a
# misreading of one word as another.
MIN_PAIR_SIMILARITY = 0.5
# A word broken at a line end: letter, hyphen, line break, letter.
_HYPHEN_BREAK = re.compile(r"(?<=\w)[-‐¬]\s*\n\s*(?=\w)")


# Transcription conventions that differ between sources without being
# misreadings:
# - the elision mark (Calfa ´, OGL ’, others ' ʼ ᾽) and the numeral sign ʹ,
#   which engines read as an apostrophe;
# - the hyphen character (- or U+2010); the stigma ϛ/Ϛ (one glyph in Migne)
#   and the curly beta ϐ;
# - Roman section numbers' case (Migne capitals, Calfa lower case);
# - footnote reference markers and Latin words (al., f.), which Calfa leaves
#   out and engines keep;
# - Migne prints a space before , · ; : ! ? » ) ] and after « ( [ (as #164's
#   typo() folds them), and the numeral sign as ΄ or ʹ; he keeps the grave accent on a word's
#   last syllable before punctuation (φωτὸς ,); Calfa drops the space and
#   writes the modern acute (φωτός,).
_APOSTROPHES = str.maketrans({**{c: "’" for c in "'´ʼ᾽‘`′ʹʹ΄"},
                              **{c: "-" for c in "‐‑‒"},
                              "Ϛ": "ϛ", "ϐ": "β"})
# Latin words (Migne's "[al. …]", "f."): Calfa transcribes Greek only and
# has no Latin letters except Roman section numbers.
_LATIN_WORD = re.compile(
    r"(?<![^\s\[(])(?![ivxlcdm]+\.|[IVXLCDM]+\.)[A-Za-z]{1,12}\.?(?=[\s\])]|$)")
# Section numbers in Roman numerals: Migne prints capitals, Calfa writes them
# lower case.
_ROMAN = re.compile(r"(?<!\S)[IVXLCDM]+(?=\.)|(?<!\S)[ivxlcdm]+(?=\.)")
# Note references: superscripts, (12), [12], 12*, (3*). Calfa's text has no
# digits at all, so every digit run an engine writes is a note reference.
_NOTE_MARKERS = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁽⁾]+|[(\[]\s*\d{1,3}\s*\*?\s*[)\]]|\d{1,3}\*?")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+(?=[,·;:.!?»)\]])")
_SPACE_AFTER_OPEN = re.compile(r"(?<=[«(\[])\s+")
_GRAVE = "̀"
_ACUTE = "́"
# The last vowel's accent of a word directly followed by punctuation.
_FINAL_GRAVE = re.compile("\u0300(?=[\w\u0300-\u036f]*[,\u00b7;:.])")


def fold_conventions(text: str) -> str:
    """Unify apostrophes and hyphens, drop footnote markers, and fold Migne's
    space and grave before punctuation onto the modern form."""
    text = _NOTE_MARKERS.sub("", text.translate(_APOSTROPHES))
    text = _LATIN_WORD.sub("", text)
    text = _SPACE_AFTER_OPEN.sub("", _SPACE_BEFORE_PUNCT.sub("", text))
    text = _ROMAN.sub(lambda m: m.group(0).lower(), text)
    nfd = unicodedata.normalize("NFD", text)
    return unicodedata.normalize("NFC", _FINAL_GRAVE.sub(_ACUTE, nfd))


def clean(text: str, dehyphenate: bool = False, conventions: bool = False) -> str:
    """NFC, optional dehyphenation and convention folding, whitespace collapsed."""
    text = unicodedata.normalize("NFC", text)
    if conventions:
        text = fold_conventions(text)
    if dehyphenate:
        text = _HYPHEN_BREAK.sub("", text)
    return _WS.sub(" ", text).strip()


def strip_marks(text: str) -> str:
    """``text`` without combining marks, recomposed (NFC)."""
    nfd = unicodedata.normalize("NFD", text)
    return unicodedata.normalize(
        "NFC", "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    )


def _edits(ref: list[str] | str, hyp: list[str] | str) -> tuple[int, int, int]:
    """(substitutions, deletions, insertions) of an optimal alignment."""
    s = d = i = 0
    for op in Levenshtein.editops(ref, hyp):
        if op.tag == "replace":
            s += 1
        elif op.tag == "delete":
            d += 1
        else:
            i += 1
    return s, d, i


@dataclass
class Counts:
    """Error counts of one page, or the sum over pages (``+``)."""

    pages: int = 0
    chars: int = 0
    char_errors: int = 0
    base_errors: int = 0
    words: int = 0
    word_errors: int = 0
    word_subs: int = 0
    accent_words: int = 0
    realword_subs: int = 0
    # Running-head column numbers: pages where both sides give them, and how
    # many of those agree exactly.
    column_pages: int = 0
    column_hits: int = 0
    examples: list[tuple[str, str]] = field(default_factory=list, compare=False)

    def __add__(self, other: Counts) -> Counts:
        out = Counts()
        for f in fields(Counts):
            setattr(out, f.name, getattr(self, f.name) + getattr(other, f.name))
        return out

    @property
    def cer(self) -> float:
        return self.char_errors / self.chars if self.chars else 0.0

    @property
    def base_cer(self) -> float:
        return self.base_errors / self.chars if self.chars else 0.0

    @property
    def accent_share(self) -> float:
        if not self.char_errors:
            return 0.0
        return max(0.0, 1 - self.base_errors / self.char_errors)

    @property
    def wer(self) -> float:
        return self.word_errors / self.words if self.words else 0.0

    @property
    def realword_rate(self) -> float:
        """Real-word substitutions per reference word."""
        return self.realword_subs / self.words if self.words else 0.0

    @property
    def column_accuracy(self) -> float | None:
        return self.column_hits / self.column_pages if self.column_pages else None


def score_page(
    ref: str,
    hyp: str,
    lexicon: frozenset[str],
    *,
    dehyphenate: bool = False,
    conventions: bool = False,
    ref_columns: tuple[int, ...] | None = None,
    hyp_columns: tuple[int, ...] | None = None,
    max_examples: int = 5,
) -> Counts:
    """Score one page's hypothesis against its reference."""
    ref_c, hyp_c = clean(ref, dehyphenate, conventions), clean(hyp, dehyphenate, conventions)
    c = Counts(pages=1, chars=len(ref_c))
    c.char_errors = sum(_edits(ref_c, hyp_c))
    c.base_errors = sum(_edits(strip_marks(ref_c), strip_marks(hyp_c)))

    ref_w, hyp_w = ref_c.split(), hyp_c.split()
    c.words = len(ref_w)
    for block in Levenshtein.opcodes(ref_w, hyp_w):
        n_ref, n_hyp = block.src_end - block.src_start, block.dest_end - block.dest_start
        if block.tag == "equal":
            continue
        c.word_errors += max(n_ref, n_hyp)
        if block.tag != "replace":
            continue
        # Pair the words of a replaced block one to one; an uneven block
        # (a split or merged word) is counted as errors but not classified.
        if n_ref != n_hyp:
            continue
        for r, h in zip(ref_w[block.src_start:block.src_end],
                        hyp_w[block.dest_start:block.dest_end]):
            c.word_subs += 1
            if strip_marks(r) == strip_marks(h):
                c.accent_words += 1
                continue
            fr, fh = normalize_token(r), normalize_token(h)
            if (fh != fr and is_greek_form(fr) and is_greek_form(fh) and fh in lexicon
                    and Levenshtein.normalized_similarity(fr, fh) >= MIN_PAIR_SIMILARITY):
                c.realword_subs += 1
                if len(c.examples) < max_examples:
                    c.examples.append((r, h))

    if ref_columns and hyp_columns:
        c.column_pages = 1
        c.column_hits = int(tuple(ref_columns) == tuple(hyp_columns))
    return c
