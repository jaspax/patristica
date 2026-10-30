"""
Ingestor for Christian Arabic texts from OpenITI (#480, part of #83).

Source: the Open Islamicate Texts Initiative corpus, https://github.com/OpenITI,
one repository per 25-year AH bucket, each file pinned to a commit.
License: CC BY-NC-SA 4.0, OpenITI's release licence
(https://zenodo.org/records/17767721), for every text here.
Language: arb  Tradition: arabic  Genre: patristic

Works:

- ``openiti/apology-of-al-kindi``: the *Apology of al-Kindī*, the (fictional)
  letter of ʿAbd Allāh ibn Ismāʿīl al-Hāshimī inviting ʿAbd al-Masīḥ ibn Isḥāq
  al-Kindī to Islam and al-Kindī's reply: one composition by an unknown
  Christian author.  OpenITI's ``SyriacStudies00001`` version, a clean text
  from the Syriac Studies website, which follows Anton Tien's edition (London,
  1880; checked against the 1885 printing, archive.org ``AlKindi_201306``) but
  modernises the spelling, abbreviates the eulogies to "(ص)", names the two
  correspondents in the frame story where Tien has "we do not want to name
  them", and adds Qurʾān and Bible references in parentheses and section
  headings.  Those headings and references are marked editorial (#236).
- ``openiti/history-of-the-patriarchs-1`` … ``-4``: the *History of the
  Patriarchs of Alexandria* (*Siyar al-ābāʾ al-baṭārika*), Evetts's parts 1–4
  (Mark to Joseph I, d. 849), one work per part.  OpenITI's
  ``Kraken220321170803`` version: uncorrected Kraken OCR of Evetts's edition in
  Patrologia Orientalis 1.2, 1.4, 5.1 and 10.5 (1904–1915), whose pages carry
  the Arabic text, its apparatus and the English translation.  Only the Arabic
  text is kept (``_openiti.page_body``): the translation, which the Arabic OCR
  model turned into digit noise, the apparatus, running heads and footnote
  numbers are dropped as noise.  OCR letter errors are left as they are.

Refs.  The Apology: ``1.{p}`` the frame story, ``2.{p}`` al-Hāshimī's letter
(heading ``2``), ``3.{p}`` al-Kindī's reply, whose subsections are ``3.{s}``
(heading, numbered after the reply's opening paragraphs) and ``3.{s}.{p}``.
The History: section ``{n}`` is the life of the n-th patriarch (its Arabic
heading lines are the heading chunk ``{n}``) and ``{n}.{k}`` the k-th printed
page of it, in reading order; part 1 opens with the compiler's preface,
``0.{k}``.  Where a life starts is curated in
``scripts/ingest/data/openiti_hop_patriarchs.csv``.

Yaḥyā ibn Saʿīd al-Anṭākī's *Tārīkh* (Kraken OCR of PO 18.5) was evaluated
and left out: after the same cleanup about one token in eight is still an OCR
error (#485).
"""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from patristica.models import Work
from scripts.ingest import _openiti
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "openiti"
LICENSE = "cc-by-nc-sa-4.0"

_DATA = Path(__file__).parent / "data" / "openiti_hop_patriarchs.csv"


@dataclass(frozen=True)
class Version:
    """One OpenITI text version at a pinned commit of its repository."""
    repo: str
    commit: str
    path: str   # under data/

    @property
    def uri(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def url(self) -> str:
        return _openiti.raw_url(self.repo, self.commit, self.path)

    @property
    def source_url(self) -> str:
        return _openiti.tree_url(self.repo, self.commit, self.path)


KINDI = Version(
    "0300AH", "01a1544130e0236850ef2698923ad01575c5bd7c",
    "0300Anonymous/0300Anonymous.RisalataHashimiWaKindi/"
    "0300Anonymous.RisalataHashimiWaKindi.SyriacStudies00001-ara1",
)
HOP = Version(
    "0500AH", "fff9e21790e2e54f14826322ae49ab7671f12744",
    "0500MultipleCoptic/0500MultipleCoptic.SiyarAbaBatarika/"
    "0500MultipleCoptic.SiyarAbaBatarika.Kraken220321170803-ara1",
)


def fetch(output_dir: Path, version: Version, force: bool = False) -> Path:
    """The text file of *version* (downloaded once into ``data/raw/_cache``)."""
    dest = output_dir / "_cache" / SOURCE_ID / version.repo / version.commit[:10] / version.uri
    return download_file(version.url, dest, etag_cache=False, force=force)


# ---------------------------------------------------------------------------
# Apology of al-Kindī
# ---------------------------------------------------------------------------

#: A Qurʾān or Bible reference the website added: parentheses with a number,
#: ``(مائدة 77، 78)``, ``(تك 22: 2)``.
_REFERENCE_RE = re.compile(r"\([^()]*[0-9٠-٩][^()]*\)")


def kindi_units(blocks: list[_openiti.Block]) -> list[dict]:
    """The Apology's raw units from its mARkdown blocks (see the module doc).

    The first level-1 heading is OpenITI's ``|PARATEXT|`` marker over the
    frame story (part of the work, not paratext in our sense); the second
    heads al-Hāshimī's letter and the third, empty, opens the reply.  Every
    heading is the website's, so heading units are editorial as a whole.
    """
    units: list[dict] = []
    section = 0
    sub = 0          # current subsection (0: before the section's first)
    para = 0         # paragraphs so far in the section's opening or in its subsection
    for b in blocks:
        if b.level == 1:
            section += 1
            sub, para = 0, 0
            if b.text and b.text != "PARATEXT|" and b.text != "|PARATEXT|":
                units.append({"ref": str(section), "text": b.text,
                              "editorial": [[0, len(b.text), "heading"]]})
        elif b.level == 2:
            if section == 0:
                raise ValueError("subheading before the first section")
            # subsections are numbered after the section's opening paragraphs
            sub = sub + 1 if sub else para + 1
            para = 0
            units.append({"ref": f"{section}.{sub}", "text": b.text,
                          "editorial": [[0, len(b.text), "heading"]]})
        else:
            if section == 0:
                raise ValueError("paragraph before the first heading")
            para += 1
            ref = f"{section}.{sub}.{para}" if sub else f"{section}.{para}"
            unit: dict = {"ref": ref, "text": b.text}
            notes = [[m.start(), m.end(), "note"] for m in _REFERENCE_RE.finditer(b.text)]
            if notes:
                unit["editorial"] = notes
            units.append(unit)
    if section != 3:
        raise ValueError(f"expected 3 sections in the Apology, found {section}")
    return units


def kindi_work() -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/apology-of-al-kindi",
        source_id=SOURCE_ID,
        author="ʿAbd al-Masīḥ ibn Isḥāq al-Kindī",
        title=("Apology of al-Kindī "
               "(Risālat al-Hāshimī ilā al-Kindī wa-risālat al-Kindī ilā al-Hāshimī)"),
        date_range=(813, 1000),
        date_confidence="approximate",
        genre="patristic",
        language="arb",
        tradition="arabic",
        license=LICENSE,
        provenance_url=KINDI.source_url,
        edition=(
            "OpenITI 0300Anonymous.RisalataHashimiWaKindi.SyriacStudies00001-ara1 "
            "(text of syriacstudies.com, 2007), which follows A. Tien's edition "
            "(London: Turkish Mission Aid Society, 1880; reprinted 1885) with modernised "
            "spelling, abbreviated eulogies, the correspondents named in the frame story, "
            "and the website's section headings and scripture references (marked editorial)"
        ),
    )


# ---------------------------------------------------------------------------
# History of the Patriarchs
# ---------------------------------------------------------------------------

#: Evetts's parts: (Patrologia Orientalis fascicle, year, first and last patriarch).
HOP_PARTS: dict[int, tuple[str, int, str]] = {
    1: ("1.2", 1904, "Mark to Theonas (d. 300)"),
    2: ("1.4", 1905, "Peter I to Benjamin I (d. 661)"),
    3: ("5.1", 1910, "Agathon to Michael I (d. 766)"),
    4: ("10.5", 1915, "Mennas I to Joseph I (d. 849)"),
}
#: Composition of each part's Coptic sources (the lives) to the Arabic
#: redaction of Mawhūb ibn Manṣūr ibn Mufarrij (c. 1088): see the PR of #480.
HOP_DATES: dict[int, tuple[int, int]] = {
    1: (600, 1088),
    2: (690, 1088),
    3: (715, 1088),
    4: (850, 1088),
}
#: The author string: a compilation (author_strings.csv).
HOP_AUTHOR = "History of the Patriarchs of Alexandria (compilation)"
#: Tokens that are never Arabic words: debris of marginal marks.
_DEBRIS = {"ال", "اال", "اا", "ا"}


@dataclass(frozen=True)
class Patriarch:
    number: int
    part: int
    name: str
    marker: str
    back: int
    extra: int


def load_patriarchs(path: Path = _DATA) -> list[Patriarch]:
    rows = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    out = [
        Patriarch(int(r["number"]), int(r["part"]), r["name"], r["marker"],
                  int(r["back"]), int(r["extra"]))
        for r in csv.DictReader(rows)
    ]
    if [p.number for p in out] != list(range(1, len(out) + 1)):
        raise ValueError(f"{path}: patriarchs must be numbered 1…n in order")
    return out


@dataclass
class Line:
    page: int
    text: str


@dataclass
class OcrStats:
    kept: int = 0
    dropped: int = 0


def ocr_lines(pages: list[_openiti.Page], stats: OcrStats) -> list[Line]:
    """The cleaned Arabic lines of *pages*, in order."""
    out: list[Line] = []
    for page in pages:
        body = _openiti.page_body(page.lines)
        stats.kept += len(body.kept)
        stats.dropped += len(body.dropped)
        for raw in body.kept:
            words = [w for w in _openiti.clean_ocr_line(raw).split() if w not in _DEBRIS]
            if words:
                out.append(Line(page.page, " ".join(words)))
    return out


def hop_units(lines: list[Line], patriarchs: list[Patriarch]) -> list[dict]:
    """One part's raw units: each patriarch's heading and his life by page.

    Lines before the part's first life (part 1's preface) are section 0.
    """
    starts: list[tuple[int, int, Patriarch]] = []   # (start line, end of heading, patriarch)
    for p in patriarchs:
        hits = [i for i, ln in enumerate(lines) if p.marker in ln.text]
        if len(hits) != 1:
            raise ValueError(
                f"History of the Patriarchs: marker of patriarch {p.number} ({p.name}) "
                f"found {len(hits)} times in part {p.part}"
            )
        i = hits[0]
        starts.append((i - p.back, i + p.extra + 1, p))
    if [s for s, _, _ in starts] != sorted(s for s, _, _ in starts):
        raise ValueError(
            f"History of the Patriarchs: lives out of order in part {patriarchs[0].part}"
        )

    units: list[dict] = []

    def body(section: int, chunk: list[Line]) -> None:
        k = 0
        page = None
        texts: list[str] = []
        for ln in chunk + [Line(-1, "")]:
            if ln.page != page:
                if texts:
                    k += 1
                    units.append({"ref": f"{section}.{k}", "text": " ".join(texts)})
                page, texts = ln.page, []
            if ln.text:
                texts.append(ln.text)

    first = starts[0][0] if starts else len(lines)
    if first > 0:
        body(0, lines[:first])
    for j, (start, head_end, p) in enumerate(starts):
        end = starts[j + 1][0] if j + 1 < len(starts) else len(lines)
        heading = " ".join(ln.text for ln in lines[start:head_end])
        units.append({"ref": str(p.number), "text": heading})
        body(p.number, lines[head_end:end])
    return units


def hop_work(part: int) -> Work:
    fascicle, year, span = HOP_PARTS[part]
    return Work(
        work_id=f"{SOURCE_ID}/history-of-the-patriarchs-{part}",
        source_id=SOURCE_ID,
        author=HOP_AUTHOR,
        title=(f"History of the Patriarchs of Alexandria (Siyar al-ābāʾ al-baṭārika), "
               f"part {part}: {span}"),
        date_range=HOP_DATES[part],
        date_confidence="approximate",
        genre="patristic",
        language="arb",
        tradition="arabic",
        license=LICENSE,
        provenance_url=HOP.source_url,
        edition=(
            f"B. T. A. Evetts, History of the Patriarchs of the Coptic Church of Alexandria "
            f"{'I II III IV'.split()[part - 1]}, Patrologia Orientalis {fascicle} ({year}), "
            f"Arabic text; uncorrected Kraken OCR by OpenITI "
            f"(0500MultipleCoptic.SiyarAbaBatarika.Kraken220321170803-ara1, 2022), "
            f"English translation pages, apparatus and footnote numbers removed"
        ),
    )


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def _write(out_dir: Path, slug: str, work: Work, units: list[dict]) -> None:
    path = out_dir / f"{slug}.json"
    record = {"work": work.model_dump(), "paragraphs": units}
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log.info("Wrote %s (%d units)", path, len(units))


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    slugs = ["apology-of-al-kindi"] + [f"history-of-the-patriarchs-{n}" for n in HOP_PARTS]
    if not force and all((out_dir / f"{s}.json").exists() for s in slugs):
        return [Work(**json.loads((out_dir / f"{s}.json").read_text(encoding="utf-8"))["work"])
                for s in slugs]

    works: list[Work] = []

    kindi = _openiti.read_document(fetch(output_dir, KINDI, force))
    work = kindi_work()
    _write(out_dir, "apology-of-al-kindi", work, kindi_units(_openiti.blocks(kindi.lines)))
    works.append(work)

    hop = _openiti.read_document(fetch(output_dir, HOP, force))
    pages = _openiti.pages(hop.lines)
    patriarchs = load_patriarchs()
    for part in HOP_PARTS:
        stats = OcrStats()
        lines = ocr_lines([p for p in pages if p.volume == part], stats)
        units = hop_units(lines, [p for p in patriarchs if p.part == part])
        log.info("History of the Patriarchs part %d: %d OCR lines kept, %d dropped",
                 part, stats.kept, stats.dropped)
        work = hop_work(part)
        _write(out_dir, f"history-of-the-patriarchs-{part}", work, units)
        works.append(work)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
