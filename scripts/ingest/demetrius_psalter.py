"""
Ingestion module for the Psalter of Demetrius (Sinai, St Catherine's, Cod. Sin. slav. NF 3).

Source:  H. Miklas, C. M. MacRobert, A. N. Sobolev et al., *Psalterium Demetrii
         Sinaitici et Folia Medicinalia (Monasterii sanctae Catharinae codex
         slavicus NF 3): Editio critica* (Glagolitica Sinaitica II), Wien:
         Holzhausen 2021, ISBN 978-3-902868-80-0. Open access from the FWF
         e-book library (https://e-book.fwf.ac.at/o:1578).
Format:  born-digital PDF (InDesign); the Glagolitic manuscript is printed in
         Cyrillic transliteration, so the text is extracted, not OCRed.
License: CC BY 4.0 (imprint, PDF p. 5: "Open Access: Wo nicht anders
         festgehalten, ist diese Publikation lizenziert unter der
         Creative-Commons-Lizenz Namensnennung 4.0 International"). The
         manuscript images are the monastery's; only the text is taken.

The manuscript was written 1058–1066 (edition p. 163); the translation it
carries is the Slavonic Psalter of the 9th–10th century (recension I, a sister
of the Psalterium Sinaiticum). One work, ``demetrius-psalter/ps``, in the
edition's numbering, which is Rahlfs' LXX (edition p. 42).

**Layout of a Psalter page** (PDF pp. 189–477; edition pp. 42–45):

- a running head and a bold page title (``Psalm. 5.13-6.5``);
- the text, line for line as in the manuscript, in the font *Cyrillica
  Bulgarian 10 Unicode* (12 pt), with verse labels in Times (``13a``, ``6.1``
  where a psalm starts), the folio (``f. 7r1``) and a line number every five
  lines on the right, the manuscript's psalm numeral in the left margin, and
  corrections and superscript letters at 8 pt above the line;
- the apparatus at the foot (11 pt), starting at the left page margin.

The extraction (pdfplumber) works on characters with their positions:
lines are rebuilt from baselines, the margins, folio and line numbers and the
apparatus are dropped, a word broken at a line end (``п-`` / ``раведънка``) is
joined again, and the half-verses (``13a``, ``13b``) are joined into one
verse, ``Ps.5.13``. A superscription is verse 1 where Rahlfs counts it as a
verse of its own (``6.1 ПЪСЛМЪ ДВЪ``, then ``2a``); where the title and the
first words share Rahlfs' verse 1 (``10.1 ПСАЛМЪ ДАДВЪ:``, then ``1a``), the
title is ``Ps.N.0`` and the text verse 1 (#239).

The font maps a few letters to the Private Use Area (``_PUA``): и, ч, Ч, И,
Ꙋ, ѥ, ѧ, the titlo and a swung-dash line filler. The edition's ``f`` (the new
fita, borrowed from Greek) is stored as ѳ, and its ``ı`` (a vertical stroke the
scribe uses as a pause) as ``|``.

**Editorial marks** (edition p. 42), as spans (#236): ``[…]`` (letters hard
to read), ``<…>`` (the editors' additions) and ``{…}`` (physical damage) are a
``supplement`` when they hold letters and a ``lacuna`` when they hold only dots
(letters lost) or nothing. Dittographies stay in the text in ``(…)`` as the
edition prints them, and a hyphen inside a line is the edition's haplography
mark (``же-с`` = же ес), kept too.

A handful of verses completed in the margin or between the lines can't be put
in order from the positions; they are corrected by hand (``_FIXES``, each
checked against the page image).

**Left out:** the additions of Demetrius, the priest who owned the manuscript
(his subscriptions and prayers, printed in italics): they were written after
the Psalter, prompted by the Synod of Split of 1059/60 (edition pp. 28, 163).
Composed after 1050 by an author whose birth year is unknown, they are out of
period (``patristica/period.py``); they are also fragmentary. Their lines are dropped (a line
whose Cyrillic is mostly italic), as are the Latin abecedarium (a line with
no Cyrillic) and the title of the first canticle after Psalm 151. The
*Folia medicinalia* (pp. 481–486, medical recipes) are not ingested.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._scripture_meta import book_work_id
from scripts.ingest._slavonic import glagolitic_to_cyrillic

log = logging.getLogger(__name__)

SOURCE_ID = "demetrius-psalter"
PDF_URL = "https://e-book.fwf.ac.at/api/object/o:1578/download"
LANDING_URL = "https://e-book.fwf.ac.at/o:1578"

#: PDF pages (1-based) of the Psalter, from Psalm 1 to the end of Psalm 151.
FIRST_PAGE = 189
LAST_PAGE = 477

#: The first word of the title of the first canticle, which follows Psalm 151.
_CANTICLE_TITLE = "ЇСХОДѢ"

#: Psalms in the manuscript (LXX numbering, with Psalm 151).
PSALMS = 151

EDITION = (
    "Psalter of Demetrius (Sinai, St Catherine's, Cod. Sin. slav. NF 3, written 1058–1066), "
    "ed. H. Miklas, C. M. MacRobert, A. N. Sobolev et al., Glagolitica Sinaitica II "
    "(Wien 2021), CC BY 4.0; Cyrillic transliteration of the Glagolitic"
)

# Private Use Area code points of the Cyrillica Bulgarian font, read off the
# rendered glyphs.
_PUA: dict[str, str] = {
    "": "҃",  # titlo
    "": "҃",  # wide titlo (marginal numerals)
    "": "ⷮ",  # superscript т (ѿ in the apparatus)
    "": "ѥ",
    "": "И",
    "": "и",
    "": "Ч",
    "": "ч",
    "": "Ꙋ",
    "": "ѧ",
    "": "⁓",  # swung-dash line filler
    "": "⁓",
}

# Other substitutions in the text (not in the apparatus).
_TEXT_MAP: dict[str, str] = {
    "f": "ѳ",   # the new fita, from Greek (edition p. 42)
    "ı": "|",   # the scribe's vertical stroke
    "o": "о",   # a Latin o typed for the Cyrillic (67.19)
}

_LABEL_RE = re.compile(r"^(?:(\d{1,3})\.)?(\d{1,3})([a-fа]?)$")  # "1а" with a Cyrillic а (108.1)
_FOLIO_RE = re.compile(r"f\.\s?\d+[rv]\w*")
_LINE_NO_RE = re.compile(r"^(\d{1,2})[ab]?$")   # "20a", "20b" around a line added later
_NOTE_RE = re.compile(r"^[a-z]{2,}\.$")
_BRACKET_RE = re.compile(r"\[[^\[\]]*\]|<[^<>]*>|\{[^{}]*\}")
_LACUNA_FILL = re.compile(r"^[\s.…?]*$")

#: Smallest size (pt) of a line of text: 12 pt, and 10 pt for verses the
#: scribe added in the margin. Smaller letters (8 pt) are corrections and
#: superscript letters, which belong to the line below them.
_MAIN_SIZE = 9.5


class ExtractionError(RuntimeError):
    """The PDF doesn't have the layout this ingestor expects."""


@dataclass
class _Char:
    text: str
    x0: float
    x1: float
    base: float          # baseline, from the top of the page
    size: float
    times: bool          # Times (labels, folio, line numbers) vs the Cyrillic font
    italic: bool


@dataclass
class _Line:
    base: float
    chars: list[_Char] = field(default_factory=list)


def _is_mark(ch: str) -> bool:
    return unicodedata.category(ch) in ("Mn", "Me")


def _chars(page) -> list[_Char]:
    """The page's characters, PUA mapped, with combining marks on their base.

    A mark follows its base character in the content stream but is placed at
    the next character's x position, so it is attached by stream order.
    """
    out: list[_Char] = []
    height = page.height
    for c in page.chars:
        text = "".join(_PUA.get(ch, ch) for ch in c["text"])
        if not text:
            continue
        font = c["fontname"].split("+")[-1]
        m = c["matrix"]
        if all(_is_mark(ch) for ch in text) and out and abs(out[-1].base - (height - m[5])) < 4:
            out[-1].text += text
            continue
        out.append(_Char(
            text=text, x0=c["x0"], x1=c["x1"], base=height - m[5], size=c["size"],
            times=font.startswith("TimesNewRoman"),
            italic=font.startswith("Cyrillica") and abs(m[2]) > 0.05,
        ))
    return out


def _lines(chars: list[_Char]) -> list[_Line]:
    """Group characters into lines by baseline; small characters join the line below."""
    lines: list[_Line] = []
    for c in sorted((c for c in chars if c.size >= _MAIN_SIZE), key=lambda c: c.base):
        if lines and c.base - lines[-1].base < 4:
            lines[-1].chars.append(c)
        else:
            lines.append(_Line(base=c.base, chars=[c]))
    for c in (c for c in chars if c.size < _MAIN_SIZE):
        if not lines:
            continue
        below = [ln for ln in lines if -3 <= ln.base - c.base <= 10]
        target = min(below or lines, key=lambda ln: abs(ln.base - c.base))
        target.chars.append(c)
    for ln in lines:
        ln.chars.sort(key=lambda c: c.x0)
    return lines


def _drop_italic_runs(chars: list[_Char], pno: int) -> list[_Char]:
    """*chars* without italic runs of several words: Demetrius' additions inside a line.

    A run is italic letters with the spaces and punctuation between them. A
    ligature, which the edition also prints in italics, lies inside one word.
    """
    out: list[_Char] = []
    run: list[_Char] = []

    def flush() -> None:
        words = "".join(c.text if c.italic else " " for c in run).split()
        long_words = [w for w in words if sum(ch.isalpha() for ch in w) >= 3]
        if len(long_words) >= 2 and sum(ch.isalpha() for w in words for ch in w) >= 8:
            log.debug("p. %d: Demetrius' words dropped: %s", pno, "".join(c.text for c in run))
            # keep the spacing around the run
            out.extend(c for c in run if not c.italic and c.text.isspace())
        else:
            out.extend(run)
        run.clear()

    for c in chars:
        if c.italic or (run and not c.text[0].isalpha() and not c.times):
            run.append(c)
        else:
            flush()
            out.append(c)
    flush()
    return out


def _tokens(line: _Line) -> list[tuple[bool, str, float, float]]:
    """A line as tokens ``(times, text, x0, x1)``: each Times word on its own, Cyrillic in runs.

    A token's text starts with a space when a space or a gap precedes it.
    """
    tokens: list[list] = []
    prev: _Char | None = None
    space = False
    for c in line.chars:
        gap = c.x0 - prev.x1 if prev else 0.0
        if c.text.isspace():
            space = True
            prev = c
            continue
        space = space or gap >= 2.5
        joins = tokens and tokens[-1][0] == c.times and (not c.times or not space)
        if joins:
            tokens[-1][1] += (" " if space else "") + c.text
            tokens[-1][3] = c.x1
        else:
            tokens.append([c.times, (" " if space else "") + c.text, c.x0, c.x1])
        space = False
        prev = c
    return [tuple(t) for t in tokens]  # type: ignore[misc]


@dataclass
class _Piece:
    """A label or a stretch of text in reading order."""
    label: tuple[int | None, int, str] | None = None
    text: str = ""
    page: int = 0
    line_end: bool = False


def _page_pieces(page, pno: int) -> list[_Piece]:
    """The Psalter text of one page as labels and text, apparatus and margins dropped."""
    title = "".join(c["text"] for c in page.chars if c["top"] < 100 and "Bold" in c["fontname"])
    if not re.search(r"(^|;)\s*Psalm\. \d", title):
        log.debug("p. %d: no Psalter text (%s)", pno, title)
        return []  # a page of Demetrius' additions
    chars = _chars(page)
    # The apparatus starts at the page margin, left of the text block.
    app_top = min((c.base for c in chars if c.x0 < 70 and c.base > 100 and 10.5 <= c.size <= 11.5
                   and c.text.strip()), default=page.height)
    body = [c for c in chars if 100 < c.base < app_top - 6]
    if not body:
        return []
    lines = _lines(body)
    # The text block's left edge: where most lines start.
    starts = sorted(round(ln.chars[0].x0) for ln in lines if ln.chars)
    left = max(set(starts), key=starts.count) - 3
    if pno == LAST_PAGE:
        # After Psalm 151 the title of the first canticle (Exodus 15) begins.
        titles = [i for i, ln in enumerate(lines)
                  if _CANTICLE_TITLE in "".join(c.text for c in ln.chars)]
        if not titles:
            raise ExtractionError(f"p. {pno}: the title {_CANTICLE_TITLE!r} is missing")
        lines = lines[:titles[0]]
    pieces: list[_Piece] = []
    for lno, ln in enumerate(lines, start=1):
        ln.chars = [c for c in ln.chars if c.x1 > left]   # marginal psalm numerals
        if not ln.chars:
            continue
        cyr = [c for c in ln.chars if not c.times and c.text.strip()]
        if not cyr:
            continue  # the Latin abecedarium, a bare folio or line number
        if sum(c.italic for c in cyr) >= max(5, 0.7 * len(cyr)):
            log.debug("p. %d: Demetrius' line dropped: %s", pno, "".join(c.text for c in ln.chars))
            continue  # Demetrius' additions (a ligature is a few italic letters)
        ln.chars = _drop_italic_runs(ln.chars, pno)
        tokens = _tokens(ln)
        # The folio: "f." and "7r1", on the right.
        for i in range(len(tokens) - 1):
            if tokens[i][0] and tokens[i + 1][0] and \
                    _FOLIO_RE.fullmatch(f"{tokens[i][1].strip()} {tokens[i + 1][1].strip()}"):
                del tokens[i:i + 2]
                break
        # The line number at the end of the line: after a wide gap, or a
        # multiple of five near this line's position on the page (the PDF
        # sometimes places it right after the text, p. 439).
        m = _LINE_NO_RE.match(tokens[-1][1].strip()) if len(tokens) > 1 and tokens[-1][0] else None
        if m and (tokens[-1][2] - tokens[-2][3] > 12
                  or (int(m.group(1)) % 5 == 0 and abs(int(m.group(1)) - lno) <= 2)):
            tokens.pop()
        out: list[_Piece] = []
        for i, (times, text, x0, x1) in enumerate(tokens):
            stripped = text.strip()
            if times and (stripped == "/" or _NOTE_RE.match(stripped)):
                continue  # a line end in a marginal addition; the note "marg."
            m = _LABEL_RE.match(stripped) if times else None
            if m:
                out.append(_Piece(label=(int(m.group(1)) if m.group(1) else None,
                                         int(m.group(2)), m.group(3).replace("а", "a")),
                                  page=pno))
                continue
            text = "".join(_TEXT_MAP.get(ch, ch) for ch in text)
            if out and out[-1].label is None:
                out[-1].text += text
            else:
                out.append(_Piece(text=text, page=pno))
        if out:
            out[-1].line_end = True
            pieces.extend(out)
    return pieces


_LINE_END_HYPHEN = re.compile(r"-([\])}>]*)$")
#: A word broken at a line end with an erasure after the hyphen
#: (8.8 "полъск- [...]" / "ъиѩ").
_HYPHEN_GAP = re.compile(r"(\S)- (\[[.…]*\]) (?=\S)")

#: Hand corrections, checked against the page images, where a verse was
#: completed in the margin or between the lines and the extraction can't put
#: the words in order: ``ref -> (extracted, corrected)``. The extracted text
#: must occur once in the verse, so a change to the extraction shows here.
_FIXES: dict[str, tuple[str, str]] = {
    # p. 257: "скръбе/и его" is a later correction over an erasure, its last
    # words on the next line, beside the title of Psalm 25.
    "Ps.24.22": ("ото въсѣхъ скръбе- Д҃АВЪ:", "ото въсѣхъ скръбеи его –"),
    "Ps.25.0": ("ПЪСАЛОМЪ:– и его –", "Д҃АВЪ: ПЪСАЛОМЪ:–"),
    # p. 389: "дѣла его:" is written above the end of the line.
    "Ps.95.6": ("с҃тъі- дѣла его: ні і", "с҃тъіні дѣла его: і"),
    # p. 406: 17b–18b are written between the lines; "сѧ огнъ … їхъ" is the
    # rest of 18a, marked by "≈".
    "Ps.105.18": ("Ї раждеже≈ Пласѧ огнъ въ соньмѣ їхъ:– менъ",
                  "Ї раждеже≈ сѧ огнъ въ соньмѣ їхъ:– Пламенъ"),
    # p. 418: 10c is written between the lines and ends after "СЛАВА≈" on
    # the line of the title of Psalm 112.
    "Ps.111.10": ("грѣшъникъ по-", "грѣшъникъ погъібнетъ⁓–"),
    "Ps.112.0": ("СЛАВА≈ гъібнетъ⁓–", "СЛАВА≈"),
}
_TITLO = "\u0483"


def _join(parts: list[str]) -> str:
    """Join a verse's lines: a hyphen at a line end (``сл[а-]``) joins the word."""
    text = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = _LINE_END_HYPHEN.search(text)
        if m:
            text = text[:m.start()] + m.group(1) + part
        elif text:
            text += " " + part
        else:
            text = part
    text = _HYPHEN_GAP.sub(r"\1\2", text)
    # "/" (or "⁄") marks a line end inside a marginal addition (85.7: "[во]/ꙁ[вахъ]").
    text = re.sub(r"\s*[/⁄]\s*", lambda m: " " if m.group(0).strip() != m.group(0) else "", text)
    return re.sub(r"\s+", " ", text).strip()


def _one_titlo(text: str) -> str:
    """One titlo per word: the edition draws a long titlo in pieces (``П҃С҃А҃Л҃М҃Ъ``)."""
    def word(m: re.Match) -> str:
        w = m.group(0)
        first = w.find(_TITLO)
        if first < 0:
            return w
        return w[:first + 1] + w[first + 1:].replace(_TITLO, "")
    return re.sub(r"\S+", word, text)


def _editorial(text: str) -> list[list]:
    """Spans for the edition's brackets (edition p. 42)."""
    spans = []
    for m in _BRACKET_RE.finditer(text):
        inner = m.group(0)[1:-1]
        kind = "lacuna" if _LACUNA_FILL.match(inner) else "supplement"
        spans.append([m.start(), m.end(), kind])
    return spans


def extract_verses(pdf_path: Path) -> list[tuple[str, str]]:
    """``[(ref, text)]`` for the Psalter, in order, refs ``Ps.N.V``."""
    import pdfplumber

    pieces: list[_Piece] = []
    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) < LAST_PAGE:
            raise ExtractionError(f"{pdf_path}: {len(pdf.pages)} pages, expected ≥ {LAST_PAGE}")
        for pno in range(FIRST_PAGE, LAST_PAGE + 1):
            pieces.extend(_page_pieces(pdf.pages[pno - 1], pno))

    verses: dict[tuple[int, int], list[str]] = {}
    psalm, verse = 0, -1
    pending_title: tuple[int, int] | None = None   # a title labelled N.1
    current: tuple[int, int] | None = None
    for piece in pieces:
        if piece.label is None:
            if current is None:
                if piece.text.strip():
                    log.debug("p. %d: text before the first label dropped: %r",
                              piece.page, piece.text)
                continue
            verses[current].append(piece.text + ("\n" if piece.line_end else ""))
            continue
        ps, v, half = piece.label
        where = f"p. {piece.page}: {ps or psalm}.{v}{half}"
        if ps is not None:
            if ps != psalm + 1:
                raise ExtractionError(f"{where}: psalm {ps} after psalm {psalm}")
            psalm = ps
        elif current == (psalm - 1, v) and half:
            continue  # the second half of that squeezed-in verse
        elif psalm and verse <= 1 and (psalm - 1, v - 1) in verses and (psalm - 1, v) not in verses:
            # The last verse of the previous psalm, squeezed in after this
            # psalm's title (108.31 after 109.1).
            current = (psalm - 1, v)
            verses[current] = []
            continue
        elif v == verse and not half and current == (psalm, v):
            # "3a … 3 … 3b": the edition's "a" half is the end of Rahlfs'
            # previous verse (61.12–13, 74.2–3).
            verses.setdefault((psalm, v - 1), []).extend(["\n"] + verses[current])
            verses[current] = []
            continue
        elif v < verse or (v == verse and not half):
            raise ExtractionError(f"{where}: after verse {verse}")
        if pending_title and v == 1 and pending_title[0] == psalm:
            # The title shares Rahlfs' verse 1 with the text: it is verse 0.
            verses[(psalm, 0)] = verses.pop(pending_title)
        pending_title = None
        verse = v
        current = (psalm, v)
        if ps is not None and not half and v == 1:
            pending_title = current
        verses.setdefault(current, [])

    out = []
    for key in sorted(verses):
        text = _one_titlo(_join("".join(verses[key]).split("\n")))
        text = glagolitic_to_cyrillic(unicodedata.normalize("NFC", text))
        ref = f"Ps.{key[0]}.{key[1]}"
        if ref in _FIXES:
            old, new = _FIXES[ref]
            if text.count(old) != 1:
                raise ExtractionError(f"{ref}: the hand correction doesn't apply to {text!r}")
            text = text.replace(old, new)
        if text:
            out.append((ref, text))
    if psalm != PSALMS:
        raise ExtractionError(f"the Psalter ends at psalm {psalm}, expected {PSALMS}")
    return out


def _work() -> Work:
    return Work(
        work_id=book_work_id(SOURCE_ID, "Ps"),
        source_id=SOURCE_ID,
        title="Psalms (Psalter of Demetrius)",
        author=None,
        date_composed=900,
        date_range=(863, 1000),
        date_confidence="approximate",
        genre="scripture",
        language="chu",
        tradition="slavonic",
        license="cc-by-4.0",
        provenance_url=LANDING_URL,
        edition=EDITION,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Extract the Psalter from the edition's PDF into ``{output_dir}/demetrius-psalter/Ps.json``."""
    out_dir = output_dir / SOURCE_ID
    out_file = out_dir / "Ps.json"
    if out_file.exists() and not force:
        log.info("%s exists, skipping", out_file)
        return [Work(**json.loads(out_file.read_text(encoding="utf-8"))["work"])]

    pdf_path = download_file(
        PDF_URL, output_dir / "_cache" / SOURCE_ID / "glagolitica-sinaitica-2.pdf", force=force)
    verses = extract_verses(pdf_path)
    work = _work()
    units = []
    for ref, text in verses:
        unit: dict = {"ref": ref, "text": text}
        spans = _editorial(text)
        if spans:
            unit["editorial"] = spans
        units.append(unit)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({"work": work.model_dump(), "verses": units},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("%s: %d verses", work.work_id, len(units))
    return [work]


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
