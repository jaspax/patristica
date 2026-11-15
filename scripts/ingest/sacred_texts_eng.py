"""
Ingestor for English translations on the Internet Sacred Text Archive (#353).

Source: archive.sacred-texts.com (John Bruno Hare's transcriptions; shared
page parser ``_sacred_texts``).
Output: ``data/raw/sacred-texts-eng/{slug}.json``
Language: eng  License: public_domain

- Milton S. Terry, *The Sibylline Oracles, translated from the Greek into
  English blank verse* (new edition, New York: Eaton & Mains, 1899): books
  I-VIII and XI-XIV, of ``first1k/tlg1551/tlg001/1st1K-grc1``.  Units are
  runs of Terry's lines ending at a sentence end (about ten lines or more),
  ref ``SibOr.{book}.{first line}`` in Terry's line numbering; each book's
  table of contents is ``SibOr.{book}.0``.  Terry's appendix of fragments
  (Greek ``tlg1551.tlg002``) is not ingested.

Not ingested: Mead's "Letter to Flora" (*Fragments of a Faith Forgotten*,
1900, gno/fff/fff55.htm) is a paraphrase in Mead's words ("Opinions, says
Ptolemy, are divided ...") with his commentary, not a translation.

Editorial material (#236): Terry's preface is wholly editorial units
(``SibOr.0.{n}``, ``note``; its heading ``heading``); his notes, printed in
small type at the foot of each page, and the Greek line ranges he gives for
each page ("(1-10.)") are carried in brackets where they stand, marked
``note``; the contents of each book are a ``note`` unit.  Page markers are
dropped.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from patristica.models import Work
from scripts.ingest._sacred_texts import BASE_URL, Builder, Page, SacredTextsParseError, fetch, page_text, roman

log = logging.getLogger(__name__)

SOURCE_ID = "sacred-texts-eng"

SIBYL_DIR = "cla/sib"
SIBYL_PREFACE = "sib01.htm"
# Page → book number (Terry numbers the books as the Greek: XI-XIV follow VIII).
SIBYL_BOOKS: tuple[tuple[str, int], ...] = tuple(
    (f"sib{n:02d}.htm", book) for n, book in zip(range(3, 15), (1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13, 14)))

MIN_LINES = 10    # a unit closes at the first sentence end after this many lines
MAX_LINES = 40    # ... or at the first line end after this many, if no sentence ends

_GREEK_LINES_RE = re.compile(r"^\(\d+[-–]\d+\.?\)$")
_LINE_NO_RE = re.compile(r"^(\d+) (?=\S)")
_SENTENCE_END_RE = re.compile(r"[.!?;:][\"'’”)\]]*$")


@dataclass
class _Line:
    number: int
    text: str
    notes: list[str] = field(default_factory=list)   # notes that follow this line


def sibyl_lines(book: int, page: Page) -> tuple[str | None, list[_Line]]:
    """A book's contents and its lines, with the notes attached to the line before them."""
    contents: str | None = None
    lines: list[_Line] = []
    expect_contents = False
    leading: list[str] = []   # notes before the first line
    for kind, text in page.items:
        if kind == "H":
            expect_contents = text.upper().startswith("CONTENTS OF BOOK")
            if not expect_contents:
                m = re.match(r"^BOOK ([IVXL]+)\.?$", text)
                if m and roman(m.group(1)) != book:
                    raise SacredTextsParseError(f"Sibyllines: page of book {book} is headed {text!r}")
            continue
        if kind == "P" and expect_contents:
            contents = text.replace("\n", " ")
            expect_contents = False
            continue
        if kind == "N" or (kind == "P" and _GREEK_LINES_RE.match(text)):
            note = text if kind == "N" else f"Greek lines {text.strip('().')}"
            note = note.strip()
            if note.startswith("[") and note.endswith("]"):
                note = note[1:-1].strip()
            (lines[-1].notes if lines else leading).append(note)
            continue
        if kind != "P":
            continue
        for raw in text.split("\n"):
            raw = raw.strip()
            if not raw:
                continue
            number = lines[-1].number + 1 if lines else 1
            m = _LINE_NO_RE.match(raw)
            if m and number <= int(m.group(1)) <= number + 2:
                if int(m.group(1)) != number:
                    log.warning("Sibyllines %d: line %d numbered %s", book, number, m.group(1))
                number = int(m.group(1))
                raw = raw[m.end():]
            lines.append(_Line(number, raw))
    if not lines:
        raise SacredTextsParseError(f"Sibyllines {book}: no lines")
    if leading:
        lines[0].notes[:0] = leading
    return contents, lines


def sibyl_units(book: int, contents: str | None, lines: list[_Line]) -> list[dict]:
    """Runs of lines ending at a sentence end, about ``MIN_LINES`` long or more."""
    records: list[dict] = []
    if contents:
        records.append({"ref": f"SibOr.{book}.0", "text": contents,
                        "editorial": [[0, len(contents), "note"]]})
    run: list[_Line] = []

    def close() -> None:
        b = Builder()
        for ln in run:
            b.add(ln.text + " ")
            for note in ln.notes:
                b.add(f"[{note}]", "note")
        records.append(b.record(f"SibOr.{book}.{run[0].number}"))
        run.clear()

    for i, ln in enumerate(lines):
        run.append(ln)
        last = i == len(lines) - 1
        if last or (len(run) >= MIN_LINES and _SENTENCE_END_RE.search(ln.text)) or len(run) >= MAX_LINES:
            close()
    return records


def preface_units(page: Page) -> list[dict]:
    records = []
    for n, (kind, text) in enumerate(((k, t) for k, t in page.items if k in ("H", "P")), 1):
        text = text.replace("\n", " ").strip()
        if text.startswith("Next:"):
            continue  # the archive's navigation
        records.append({"ref": f"SibOr.0.{n}", "text": text,
                        "editorial": [[0, len(text), "heading" if kind == "H" else "note"]]})
    return records


@dataclass(frozen=True)
class Text:
    slug: str
    author: str | None
    title: str
    translation_of: str
    tradition: str
    genre: str
    provenance: str
    edition: str


SIBYLLINES = Text(
    slug="sibylline-oracles-terry",
    author=None,
    title="Sibylline Oracles",
    translation_of="first1k/tlg1551/tlg001/1st1K-grc1",
    tradition="greek",
    genre="apocrypha",
    provenance=f"{BASE_URL}{SIBYL_DIR}/index.htm",
    edition=("Milton S. Terry (tr.), The Sibylline Oracles, translated from the Greek into English "
             "blank verse, new edition (New York: Eaton & Mains, 1899): books I-VIII and XI-XIV, in "
             "Terry's line numbering. Transcription: Internet Sacred Text Archive (J. B. Hare)."),
)


def parse_sibyllines(pages: dict[str, Page]) -> list[dict]:
    records = preface_units(pages[SIBYL_PREFACE])
    for name, book in SIBYL_BOOKS:
        contents, lines = sibyl_lines(book, pages[name])
        records.extend(sibyl_units(book, contents, lines))
    return records


def _work(text: Text) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{text.slug}",
        source_id=SOURCE_ID,
        author=text.author,
        title=text.title,
        date_composed=None,
        date_range=None,
        date_confidence="uncertain",
        genre=text.genre,
        language="eng",
        tradition=text.tradition,
        license="public_domain",
        provenance_url=text.provenance,
        edition=text.edition,
        translation_of=text.translation_of,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{SIBYLLINES.slug}.json"
    if out_path.exists() and not force:
        return [Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"])]
    names = [SIBYL_PREFACE] + [name for name, _ in SIBYL_BOOKS]
    pages = {name: page_text(fetch(f"{SIBYL_DIR}/{name}", output_dir, force=force)
                             .read_text(encoding="utf-8", errors="replace"))
             for name in names}
    records = parse_sibyllines(pages)
    work = _work(SIBYLLINES)
    out_path.write_text(
        json.dumps({"work": work.model_dump(), "paragraphs": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("%s: %d paragraphs", work.work_id, len(records))
    return [work]


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
