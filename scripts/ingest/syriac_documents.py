"""
Ingestor for the "Memoirs of Edessa and Other Ancient Syriac Documents".

Source: CCEL Ante-Nicene Fathers Vol. 8 (tr. B. P. Pratten, from Cureton's
        *Ancient Syriac Documents* and *Spicilegium Syriacum*)
        https://ccel.org/ccel/s/schaff/anf08.xml
License: Public domain
Genre: patristic  Language: eng

ANF08 div1 ``ix`` is an anthology of unrelated pieces — the Abgar legend and the
Teaching of Addai, Edessene martyr acts, Jacob of Serugh's metrical homilies,
Bardaisan's dialogue on fate, Mara bar Serapion's letter, an extract from Moses
of Khoren, etc.  The generic ``ccel_anf`` ingestor would treat it as one
anonymous Work; this module carves it into one properly attributed Work per
text, driven by the ``_WORKS`` table below.  Editorial matter (title page,
Introductory Notice, Elucidations, the 1886 Introduction, the translator's
Syriac calendar) is left out.  Every div taken here or deliberately dropped is
registered in ``_ccel_common.EXCLUDED_DIVS["anf08"]``.

Canonical refs are ``{prefix}.{n}`` (sequential paragraph / verse-line number)
or, for works divided into numbered ``<div3>`` sections, ``{prefix}.{section}.{n}``
with the section's Roman numeral converted to Arabic.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from patristica.models import DateConfidence, Tradition, Work
from patristica.period import is_out_of_period
from scripts.ingest._ccel_common import _element_inner_text, _find_body, download_volume

log = logging.getLogger(__name__)

SOURCE_ID = "syriac-documents"
_ANF_VOL = "anf08"
_EDITION = (
    "Ante-Nicene Fathers Vol. 8 (1886), \"Memoirs of Edessa and Other Ancient "
    "Syriac Documents\", tr. B. P. Pratten (after W. Cureton)"
)


@dataclass(frozen=True)
class _WorkSpec:
    slug: str
    title: str
    author: str | None
    date_composed: int
    date_range: tuple[int, int]
    date_confidence: DateConfidence
    tradition: Tradition
    ref_prefix: str
    div_id: str                     # ThML @id of the div2/div3 holding the text
    title_check: str                # substring expected in that div's @title
    sectioned: bool = False         # number refs by the div's numbered <div3> children
    skip_ids: tuple[str, ...] = ()  # child divs belonging to another work / editorial
    #: work_id of the original-language Work in the corpus.  None for every row:
    #: no Syriac (or Armenian) original of these texts is in the corpus, and the
    #: Syriac version of Eusebius HE 1.13 is one chapter of a Greek original.
    translation_of: str | None = None


_WORKS: tuple[_WorkSpec, ...] = (
    _WorkSpec(
        slug="eusebius-abgar-story",
        title="The Story Concerning the King of Edessa "
              "(Eusebius, Church History 1.13, Syriac version)",
        author="Eusebius of Caesarea",
        date_composed=313, date_range=(300, 325), date_confidence="approximate",
        tradition="greek", ref_prefix="EusAbgar",
        div_id="ix.iii", title_check="King of Edessa",
    ),
    _WorkSpec(
        slug="jacob-serugh-canticle-on-edessa",
        title="A Canticle on Edessa (extracts)",
        author="Jacob of Serugh",
        date_composed=500, date_range=(470, 521), date_confidence="approximate",
        tradition="syriac", ref_prefix="JacSerug.Edessa",
        div_id="ix.iv", title_check="Canticle of Mar Jacob",
    ),
    _WorkSpec(
        slug="abgar-addai-extracts",
        title="Extracts from Various Books Concerning Abgar the King and Addaeus the Apostle",
        author=None,
        date_composed=500, date_range=(400, 600), date_confidence="uncertain",
        tradition="syriac", ref_prefix="AbgarExtr",
        div_id="ix.v", title_check="Extracts from Various Books",
        sectioned=True, skip_ids=("ix.v.vii",),
    ),
    _WorkSpec(
        slug="jacob-serugh-fall-of-idols",
        title="Homily on the Fall of Idols (extract)",
        author="Jacob of Serugh",
        date_composed=500, date_range=(470, 521), date_confidence="approximate",
        tradition="syriac", ref_prefix="JacSerug.FallIdols",
        div_id="ix.v.vii", title_check="fall of idols",
    ),
    _WorkSpec(
        slug="teaching-of-addai",
        title="The Teaching of Addaeus the Apostle (Doctrina Addai)",
        author=None,
        date_composed=400, date_range=(300, 450), date_confidence="uncertain",
        tradition="syriac", ref_prefix="DoctAddai",
        div_id="ix.vi.i", title_check="Teaching of Addæus",
    ),
    _WorkSpec(
        slug="teaching-of-the-apostles",
        title="The Teaching of the Apostles (Syriac Doctrina Apostolorum)",
        author=None,
        date_composed=375, date_range=(300, 450), date_confidence="uncertain",
        tradition="syriac", ref_prefix="DoctApost",
        div_id="ix.vii", title_check="Teaching of the Apostles",
    ),
    _WorkSpec(
        slug="teaching-of-simon-cephas",
        title="The Teaching of Simon Cephas in the City of Rome",
        author=None,
        date_composed=425, date_range=(350, 500), date_confidence="uncertain",
        tradition="syriac", ref_prefix="DoctSimon",
        div_id="ix.viii", title_check="Simon Cephas",
    ),
    _WorkSpec(
        slug="acts-of-sharbil",
        title="Acts of Sharbil",
        author=None,
        date_composed=425, date_range=(300, 500), date_confidence="uncertain",
        tradition="syriac", ref_prefix="ActSharbil",
        div_id="ix.ix.i", title_check="Sharbil",
    ),
    _WorkSpec(
        slug="martyrdom-of-barsamya",
        title="The Martyrdom of Barsamya, Bishop of Edessa",
        author=None,
        date_composed=425, date_range=(300, 500), date_confidence="uncertain",
        tradition="syriac", ref_prefix="MartBarsamya",
        div_id="ix.ix.ii", title_check="Barsamya",
    ),
    _WorkSpec(
        slug="martyrdom-of-habib",
        title="Martyrdom of Habib the Deacon",
        author=None,
        date_composed=360, date_range=(310, 450), date_confidence="uncertain",
        tradition="syriac", ref_prefix="MartHabib",
        div_id="ix.xi", title_check="Habib the Deacon",
    ),
    _WorkSpec(
        slug="metaphrastes-shamuna-guria-habib",
        title="Martyrdom of the Holy Confessors Shamuna, Guria, and Habib",
        author="Symeon Metaphrastes",
        date_composed=975, date_range=(950, 1000), date_confidence="approximate",
        tradition="greek", ref_prefix="MartShamuna",
        div_id="ix.xii", title_check="Shamuna, Guria",
    ),
    _WorkSpec(
        slug="moses-khoren-history-of-armenia",
        title="History of Armenia (extract: Abgar and the conversion of Edessa)",
        author="Moses of Khoren",
        date_composed=480, date_range=(450, 800), date_confidence="uncertain",
        tradition="armenian", ref_prefix="MosKhor.HistArm",
        div_id="ix.xiii", title_check="Moses of Chorene",
        sectioned=True,
    ),
    _WorkSpec(
        slug="jacob-serugh-homily-on-habib",
        title="Homily on Habib the Martyr",
        author="Jacob of Serugh",
        date_composed=500, date_range=(470, 521), date_confidence="approximate",
        tradition="syriac", ref_prefix="JacSerug.Habib",
        div_id="ix.xiv.i", title_check="Habib the Martyr",
    ),
    _WorkSpec(
        slug="jacob-serugh-homily-on-guria-and-shamuna",
        title="Homily on Guria and Shamuna",
        author="Jacob of Serugh",
        date_composed=500, date_range=(470, 521), date_confidence="approximate",
        tradition="syriac", ref_prefix="JacSerug.GuriaShamuna",
        div_id="ix.xiv.ii", title_check="Guria and Shamuna",
    ),
    _WorkSpec(
        slug="bardaisan-laws-of-countries",
        title="The Book of the Laws of Divers Countries",
        author="Bardaisan of Edessa",
        date_composed=210, date_range=(196, 225), date_confidence="approximate",
        tradition="syriac", ref_prefix="Bardesan.Laws",
        div_id="ix.xvi", title_check="Laws of Divers Countries",
    ),
    _WorkSpec(
        slug="mara-bar-serapion-letter",
        title="A Letter of Mara, Son of Serapion",
        author="Mara bar Serapion",
        date_composed=75, date_range=(73, 200), date_confidence="uncertain",
        tradition="syriac", ref_prefix="MaraSerap",
        div_id="ix.xvii", title_check="Mara",
    ),
    _WorkSpec(
        slug="ambrose-memorial",
        title="A Memorial which Ambrose Wrote (Syriac Discourse to the Greeks)",
        author=None,
        date_composed=200, date_range=(150, 250), date_confidence="uncertain",
        tradition="syriac", ref_prefix="AmbrMem",
        div_id="ix.xviii", title_check="Ambrose",
    ),
)

#: Div2/div3 ids under ANF08 ``ix`` deliberately dropped as editorial matter.
EDITORIAL_DIVS: dict[str, str] = {
    "ix.i": "Title page",
    "ix.ii": "Introductory Notice (A. C. Coxe / translator)",
    "ix.vi.ii": "Syriac Calendar (translator's note)",
    "ix.x": "Elucidation (Coxe)",
    "ix.xv": "Introduction to Ancient Syriac Documents (Coxe / translator)",
    "ix.xix": "Elucidations (Coxe)",
}

# Paragraphs that are layout/edition furniture rather than text: running
# headers, rule lines, lacuna dots, bare section numerals (already in the ref),
# and Cureton's collection heading.
_NOISE_RE = re.compile(
    r"^(?:"
    r"Ancient Syriac Documents\.?"
    r"|[\s—–\-_•.·]*"
    r"|[IVXLC]+\."
    r"|Relating to the Earliest Establishment of Christianity in Edessa"
    r" and the Neighbouring Countries\."
    r")$"
)

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman_to_int(s: str) -> int:
    """Convert a Roman numeral (e.g. ``"XIV"``) to an int; raise ValueError if invalid."""
    s = s.strip().upper()
    if not s or any(c not in _ROMAN for c in s):
        raise ValueError(f"Not a Roman numeral: {s!r}")
    total = 0
    for i, c in enumerate(s):
        v = _ROMAN[c]
        total += -v if i + 1 < len(s) and _ROMAN[s[i + 1]] > v else v
    return total


def is_noise(text: str) -> bool:
    """True for paragraphs that carry no text (headers, rules, lacuna dots, numerals)."""
    return bool(_NOISE_RE.match(text.strip()))


def _local(el: etree._Element) -> str:
    return etree.QName(el.tag).localname if isinstance(el.tag, str) else ""


def _paragraph_texts(div: etree._Element, skip_ids: frozenset[str]) -> list[str]:
    """Text of every non-noise ``<p>`` inside *div*, in order, skipping *skip_ids* subtrees."""
    texts: list[str] = []

    def _walk(el: etree._Element) -> None:
        for child in el:
            local = _local(child)
            if not local or child.get("id") in skip_ids:
                continue
            if local == "p":
                text = _element_inner_text(child)
                if text and not is_noise(text):
                    texts.append(text)
            elif local not in ("note", "pb"):
                _walk(child)

    _walk(div)
    return texts


def extract_paragraphs(div: etree._Element, spec: _WorkSpec) -> list[dict[str, str]]:
    """Return ``[{"ref", "text"}]`` for one work's div, numbered per *spec*."""
    skip = frozenset(spec.skip_ids)
    if not spec.sectioned:
        return [
            {"ref": f"{spec.ref_prefix}.{i}", "text": t}
            for i, t in enumerate(_paragraph_texts(div, skip), start=1)
        ]

    records: list[dict[str, str]] = []
    for sec in div:
        if _local(sec) != "div3" or sec.get("id") in skip:
            continue
        n = sec.get("n")
        if not n:
            raise ValueError(f"Section div {sec.get('id')!r} of {spec.slug} has no @n")
        sec_no = roman_to_int(n)
        for i, t in enumerate(_paragraph_texts(sec, skip), start=1):
            records.append({"ref": f"{spec.ref_prefix}.{sec_no}.{i}", "text": t})
    return records


def _make_work(spec: _WorkSpec) -> Work:
    return Work(
        work_id=f"syriac-documents/{spec.slug}",
        source_id=SOURCE_ID,
        author=spec.author,
        title=spec.title,
        date_composed=spec.date_composed,
        date_range=spec.date_range,
        date_confidence=spec.date_confidence,
        genre="patristic",
        language="eng",
        tradition=spec.tradition,
        license="public_domain",
        provenance_url=f"https://ccel.org/ccel/s/schaff/{_ANF_VOL}.xml",
        edition=_EDITION,
        translation_of=spec.translation_of,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Carve ANF08 ``ix`` into one JSON per work under ``output_dir/{SOURCE_ID}/``.

    Re-parses the cached volume each run (cheap) and writes a file only when its
    content changed, so re-runs are idempotent and keep downstream mtimes.
    *force* only re-downloads the XML.
    """
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)

    # The volume is shared with ccel_anf's cache.  Use it as-is when present:
    # download_volume would issue a conditional GET, and CCEL answers 200 (not
    # 304), rewriting the cache on every run.
    anf_cache = output_dir / "ccel-anf"
    xml_path = anf_cache / f"{_ANF_VOL}.xml"
    if force or not xml_path.exists():
        anf_cache.mkdir(parents=True, exist_ok=True)
        xml_path = download_volume(_ANF_VOL, anf_cache, force=force)

    body = _find_body(etree.parse(str(xml_path)).getroot())
    if body is None:
        raise RuntimeError(f"No body element found in {xml_path}")
    by_id = {el.get("id"): el for el in body.iter() if isinstance(el.tag, str) and el.get("id")}

    works: list[Work] = []
    produced: set[Path] = set()
    for spec in _WORKS:
        div = by_id.get(spec.div_id)
        if div is None:
            raise RuntimeError(f"{_ANF_VOL}: div {spec.div_id!r} ({spec.slug}) not found")
        if spec.title_check.lower() not in (div.get("title") or "").lower():
            raise RuntimeError(
                f"{_ANF_VOL}: div {spec.div_id!r} has title {div.get('title')!r}; "
                f"expected it to contain {spec.title_check!r} ({spec.slug})"
            )
        paragraphs = extract_paragraphs(div, spec)
        if not paragraphs:
            raise RuntimeError(f"No paragraphs extracted for {spec.slug} from {spec.div_id}")

        work = _make_work(spec)
        if is_out_of_period(work.date_composed, work.date_range):
            raise ValueError(
                f"{spec.slug} is dated after the collection period ({work.date_composed})"
            )

        out_path = out_dir / f"{spec.slug}.json"
        produced.add(out_path)
        content = json.dumps(
            {"work": work.model_dump(), "paragraphs": paragraphs},
            ensure_ascii=False, indent=2,
        )
        if not out_path.exists() or out_path.read_text(encoding="utf-8") != content:
            out_path.write_text(content, encoding="utf-8")
            log.info("Wrote %s (%d paragraphs)", out_path, len(paragraphs))
        else:
            log.debug("Unchanged: %s", out_path)
        works.append(work)

    for stale in sorted(out_dir.glob("*.json")):
        if stale not in produced:
            log.info("Removing %s (no longer produced)", stale)
            stale.unlink()

    log.info("%s: %d works", SOURCE_ID, len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
