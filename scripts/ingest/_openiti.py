"""
Shared helpers for OpenITI mARkdown texts (#480).

OpenITI (https://github.com/OpenITI) keeps one GitHub repository per 25-year
bucket of the hijri calendar (``0300AH``, ``0475AH``, …); a text version is
``data/{author}/{author}.{book}/{author}.{book}.{version}-ara1`` with a ``.yml``
beside it describing the edition.  The text is OpenITI mARkdown:

- a header: ``######OpenITI#``, ``#META# Key: value`` lines (``~~`` continues
  one), closed by ``#META#Header#End#``;
- ``# `` starts a paragraph and ``~~`` continues it on the next line;
- ``### |`` is a level-1 heading, ``### ||`` level 2, and so on;
- ``PageV01P012`` closes page 12 of volume 1 (the tag stands at the page's
  end), on a line of its own or inline;
- ``ms001`` … are milestones, a citation grid laid over the text every ~300
  words; they are markup, not text.

Two kinds of text are handled here:

- **clean texts**, typed or corrected: :func:`blocks` yields their headings and
  paragraphs;
- **uncorrected Kraken OCR** of bilingual editions (Patrologia Orientalis): the
  page images carry the Arabic text, its apparatus and the facing translation,
  and the Arabic model turned the Latin-script pages into digit and letter
  noise.  :func:`page_body` keeps the Arabic text of one page and
  :func:`clean_ocr_line` strips the footnote numbers and stray marks from a
  kept line.  Real OCR letter errors are left alone: nothing is guessed.

This module stays free of ``patristica`` imports beyond the models, so that
editing the text helpers doesn't touch other ingestors' stamps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: Raw base URL; a file is ``{RAW_BASE}/{repo}/{commit}/data/{path}``.
RAW_BASE = "https://raw.githubusercontent.com/OpenITI"
#: The GitHub page of a repository at a commit.
TREE_BASE = "https://github.com/OpenITI"

_HEADER_END = "#META#Header#End#"
_PAGE_RE = re.compile(r"PageV(\d+)P(\d+)")
_MILESTONE_RE = re.compile(r"\bms\d+\b")
_HEADING_RE = re.compile(r"^### (\|+)\s*(.*)$")

#: Arabic letters (the base block's letters and the extended letters of
#: Arabic-script printing; no digits, punctuation or marks).
_AR_LETTER = r"ء-غف-يٱ-ۓ"
_AR_MARKS = r"ً-ْٰ"
_AR_LETTER_RE = re.compile(f"[{_AR_LETTER}]")


def raw_url(repo: str, commit: str, path: str) -> str:
    """URL of a file of OpenITI repository *repo* at *commit* (``path`` under ``data/``)."""
    return f"{RAW_BASE}/{repo}/{commit}/data/{path}"


def tree_url(repo: str, commit: str, path: str) -> str:
    """GitHub page of a text version at *commit*: the work's ``source_url``."""
    return f"{TREE_BASE}/{repo}/blob/{commit}/data/{path}"


# ---------------------------------------------------------------------------
# mARkdown structure
# ---------------------------------------------------------------------------

@dataclass
class Document:
    """An OpenITI text: its ``#META#`` header and the body lines after it."""
    meta: dict[str, str]
    lines: list[str]


def read_document(path: Path) -> Document:
    """Parse the header of an OpenITI mARkdown file and return its body lines.

    Raises ``ValueError`` when the file is not OpenITI mARkdown (no magic
    value or no header end), e.g. an HTML error page saved by mistake.
    """
    text = path.read_text(encoding="utf-8").lstrip("﻿")
    if not text.startswith("######OpenITI#"):
        raise ValueError(f"{path}: not an OpenITI mARkdown file")
    head, sep, body = text.partition(_HEADER_END)
    if not sep:
        raise ValueError(f"{path}: no {_HEADER_END}")
    meta: dict[str, str] = {}
    key = None
    for line in head.split("\n")[1:]:
        if line.startswith("#META#"):
            k, _, v = line[len("#META#"):].partition(":")
            key = k.strip()
            meta[key] = v.strip()
        elif line.startswith("~~") and key:
            meta[key] = f"{meta[key]} {line[2:].strip()}".strip()
    return Document(meta, body.split("\n"))


def strip_markup(line: str) -> str:
    """A body line without its line prefix (``# ``, ``~~``) and milestones."""
    while line.startswith("~~"):
        line = line[2:]
    if line.startswith("#") and not line.startswith("###"):
        line = line[1:]
    line = _MILESTONE_RE.sub("", line)
    return re.sub(r"\s+", " ", line).strip()


@dataclass
class Block:
    """A heading (``level`` ≥ 1, its text) or a paragraph (``level`` 0)."""
    level: int
    text: str


def blocks(lines: list[str]) -> list[Block]:
    """Headings and paragraphs of a clean mARkdown body.

    A paragraph is a ``# `` line and its ``~~`` continuation lines, joined with
    spaces; page tags and milestones are dropped.
    """
    out: list[Block] = []
    para: list[str] | None = None

    def flush() -> None:
        nonlocal para
        if para:
            text = re.sub(r"\s+", " ", " ".join(para)).strip()
            if text:
                out.append(Block(0, text))
        para = None

    for line in lines:
        line = _PAGE_RE.sub("", line).rstrip()
        m = _HEADING_RE.match(line)
        if m:
            flush()
            out.append(Block(len(m.group(1)), _MILESTONE_RE.sub("", m.group(2)).strip()))
        elif line.startswith("# ") or line == "#":
            flush()
            para = [strip_markup(line)]
        elif line.startswith("~~"):
            if para is None:
                para = []
            para.append(strip_markup(line))
        elif not line.strip():
            continue
        else:
            raise ValueError(f"unexpected mARkdown line: {line[:80]!r}")
    flush()
    return out


@dataclass
class Page:
    """The lines of one printed page: ``PageV{volume}P{page}`` closes it."""
    volume: int
    page: int
    lines: list[str] = field(default_factory=list)


def pages(lines: list[str]) -> list[Page]:
    """Split a body into pages at its page tags (each tag closes its page).

    Lines after the last tag (normally none) are dropped with the trailing
    page they would form, since it has no number.
    """
    out: list[Page] = []
    current: list[str] = []
    for line in lines:
        m = _PAGE_RE.search(line)
        if not m:
            current.append(line)
            continue
        before = line[:m.start()]
        if before.strip():
            current.append(before)
        out.append(Page(int(m.group(1)), int(m.group(2)), current))
        current = []
        after = line[m.end():]
        if after.strip():
            current.append(after)
    return out


# ---------------------------------------------------------------------------
# Uncorrected OCR of bilingual editions
# ---------------------------------------------------------------------------

#: A token that is an Arabic word, allowing glued footnote numbers, brackets
#: and punctuation around it.
_AR_WORD_RE = re.compile(
    rf"^[\(\[\*«\"']*\d*[{_AR_LETTER}][{_AR_LETTER}{_AR_MARKS}ـ]+\d*[\)\]\*»\"'،.:؛؟!]*\d*$"
)
_NUMBER_RE = re.compile(r"^[\(\[]?\d+[\)\]\.]?$")
#: The first line of a page's apparatus: footnote 1, then a point or dash
#: (``1. CE omit heading. — 2. AB …``).  Only a line that is not running text
#: counts: Kraken sometimes glues a margin's noise to the start of a text line.
_APPARATUS_RE = re.compile(r"^1\s*[\.\-—]\s*\S")
#: Consecutive noise lines that end a page's Arabic body: the facing
#: translation (or the apparatus) has begun.
NOISE_RUN = 3
#: A text line has at least this share of Arabic-word tokens …
TEXT_RATIO = 0.7
#: … and at least this many of them.
TEXT_MIN_WORDS = 2
#: After a page's apparatus, a line is still text only with this many Arabic
#: words, this share of them and no free number (``LineStats.is_late_text``).
LATE_MIN_WORDS = 4
LATE_RATIO = 0.85


@dataclass(frozen=True)
class LineStats:
    tokens: int
    words: int      # Arabic-word tokens
    numbers: int    # free-standing numbers

    @property
    def ratio(self) -> float:
        return self.words / self.tokens if self.tokens else 0.0

    @property
    def is_text(self) -> bool:
        """Arabic running text: mostly Arabic words and at most one free number.

        Apparatus lines also carry Arabic words (variant readings), but
        interleaved with sigla and footnote numbers.
        """
        return (
            self.words >= TEXT_MIN_WORDS
            and self.ratio >= TEXT_RATIO
            and self.numbers <= max(1, self.tokens // 8)
        )


    @property
    def is_word(self) -> bool:
        """A line of one Arabic word: the end of a paragraph, kept only right
        after a text line (in the apparatus, single words are variants)."""
        return self.tokens == 1 and self.words == 1

    @property
    def is_late_text(self) -> bool:
        """Running text found after the apparatus: held to a stricter test,
        since variant readings are Arabic words too (but come with numbers)."""
        return self.words >= LATE_MIN_WORDS and self.ratio >= LATE_RATIO and self.numbers == 0


def line_stats(text: str) -> LineStats:
    toks = text.split()
    return LineStats(
        tokens=len(toks),
        words=sum(1 for t in toks if _AR_WORD_RE.match(t)),
        numbers=sum(1 for t in toks if _NUMBER_RE.match(t)),
    )


@dataclass
class PageBody:
    """A page's Arabic text lines (markup stripped, not yet cleaned) and the
    non-empty lines dropped from it."""
    kept: list[str]
    dropped: list[str]


def page_body(lines: list[str]) -> PageBody:
    """The Arabic running text of one OCR page.

    The body starts at the first text line (running headers and page numbers
    before it are dropped) and ends at the apparatus (a line starting with a
    footnote number) or at a run of :data:`NOISE_RUN` noise lines (the facing
    translation); noise lines inside it (marginal numbers) are dropped, and a
    one-word line is kept only right after a text line.  Kraken
    doesn't always keep reading order: the last lines of the Arabic block may
    come after the apparatus, so a clean Arabic line after the end
    (:attr:`LineStats.is_late_text`) is still kept.
    """
    stripped = [strip_markup(ln) for ln in lines]
    stripped = [s for s in stripped if s and not s.startswith("====")]
    kept: list[str] = []
    dropped: list[str] = []
    started = ended = False
    run: list[str] = []
    for s in stripped:
        stats = line_stats(s)
        if ended:
            if stats.is_late_text:
                kept.append(s)
            else:
                dropped.append(s)
            continue
        if started and _APPARATUS_RE.match(s) and not stats.is_text and stats.tokens >= 3:
            ended = True
            dropped.extend(run)
            dropped.append(s)
            continue
        if stats.is_text or (started and not run and stats.is_word):
            started = True
            dropped.extend(run)
            run = []
            kept.append(s)
            continue
        if not started:
            dropped.append(s)
            continue
        run.append(s)
        if len(run) >= NOISE_RUN:
            ended = True
            dropped.extend(run)
            run = []
    dropped.extend(run)
    return PageBody(kept, dropped)


#: A footnote or line number, with a bracket glued to it: ``(1``, ``12)``, ``3``.
_FOOTNOTE_RE = re.compile(r"[\(\[]?\d+[\)\]]?")
#: Latin letters and the marks the OCR noise is made of.
_NOISE_CHARS_RE = re.compile(r"[A-Za-z\*\[\]\|/\\_\^~=<>{}#@&%$+]")
#: Tokens kept although they have no Arabic letter.
_KEEP_PUNCT = {"،", ".", ":", "؛", "؟", "!", "(", ")", "«", "»", "-", "—"}


def clean_ocr_line(text: str) -> str:
    """Strip OCR noise from a kept line: footnote numbers glued to words
    (``مرقيانوس1``), free numbers, Latin-letter debris and ``*`` (the edition's
    manuscript-page mark).  Arabic words, their OCR letter errors included,
    and Arabic punctuation are kept.
    """
    out: list[str] = []
    for tok in text.split():
        had_noise = bool(re.search(r"\d|[A-Za-z]", tok))
        t = _FOOTNOTE_RE.sub("", tok)
        t = _NOISE_CHARS_RE.sub("", t)
        if not t:
            continue
        if _AR_LETTER_RE.search(t):
            if had_noise:
                # a bracket left orphaned by a removed number
                t = t.strip("()")
            out.append(t)
        elif t in _KEEP_PUNCT and not had_noise:
            out.append(t)
    return " ".join(out)


def is_arabic_letter(ch: str) -> bool:
    return bool(_AR_LETTER_RE.match(ch))
