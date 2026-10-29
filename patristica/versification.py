"""
Versification mapping for Scripture translation linking.

Sources number verses differently (Hebrew vs LXX vs Vulgate vs English
Psalms, LXX Jeremiah's chapter order, Malachi 3–4, …), so the same
``canonical_ref`` can name different text in different sources.  This module
maps each source's native ref onto one reference scheme — "org" (BHS for the
OT, Nestle-Aland for the NT) — so parallel verses can be grouped.

``canonical_ref`` itself is never changed: it stays in the source's native
numbering, which is what readers cite.  Only ``translation_group_id`` uses
the mapped ref.

Mapping data: Copenhagen Alliance standard mappings (see
``patristica/data/versification/ATTRIBUTION.md``).  Which scheme each source
follows was determined by comparing per-chapter verse counts against each
scheme's ``maxVerses`` (see ``SOURCE_SCHEMES``); a book or chapter can
follow another scheme (``BOOK_SCHEME_OVERRIDES``, ``CHAPTER_SCHEME_OVERRIDES``).

Some books follow no scheme: Ge'ez Proverbs (26 chapters, 766 verses) and
most of Ge'ez Job divide verses their own way, with offsets that change
within chapters, and verses that merge or split cannot be mapped one to one.
Aligning those by content is #179.  Psalm titles kept as their own unit,
``Ps.N.0`` (ASV, Armenian), map to where the psalm starts (``_psalm_title``).
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path

_DATA_DIR = Path(__file__).parent / "data" / "versification"

Scheme = str  # "org" | "eng" | "lxx" | "vul"

#: Versification scheme per scripture source (sniffed from verse counts:
#: each source matches its scheme on ≥ 97% of chapters unless noted).
SOURCE_SCHEMES: dict[str, Scheme] = {
    "oshb": "org",
    "sblgnt": "org",
    "pta-peshitta": "org",   # Hebrew verse numbering, incl. Psalm titles
    "wulfila": "org",
    # Old Church Slavonic Gospels (CCMH, #332): every chapter whose last verse
    # survives ends where NA's does (eng = org in the Gospels).
    "ccmh-marianus": "org",
    "ccmh-zographensis": "org",
    "ccmh-assemanianus": "org",
    "ccmh-savvina": "org",
    "kjv": "eng",
    "asv": "eng",
    "web": "eng",
    "clementine": "vul",
    "armenian": "vul",       # Zohrab; closest fit (vul 96%, lxx 84%)
    "lxx-rahlfs": "lxx",
    "pta-lxx": "lxx",
    "coptic-nt": "lxx",
    "gez": "lxx",            # weak fit overall; see overrides
}

#: Books that follow a different scheme from their source's default.  Chosen
#: by correlating verse lengths with the OSHB/SBLGNT verse each ref maps to
#: (a misaligned verse boundary destroys the correlation); each override beats
#: the default by > 0.02.  Values in comments are default → override.
BOOK_SCHEME_OVERRIDES: dict[tuple[str, str], Scheme] = {
    ("armenian", "Num"): "eng",
    ("armenian", "Neh"): "eng",     # 0.866 → 0.922
    ("armenian", "Hag"): "org",     # 0.501 → 0.939
    ("armenian", "Jonah"): "org",   # 0.826 → 0.913
    ("clementine", "Jonah"): "org",  # 0.844 → 0.956; this edition breaks 1:17/2:1 as Hebrew
    ("coptic-nt", "Eccl"): "vul",
    ("coptic-nt", "Dan"): "vul",    # 0.475 → 0.660
    # coptic-nt Hos follows its default (lxx): the "eng" override here misgrouped
    # 8 verses of chapters 2 and 14, lxx none (#186).
    ("gez", "Eccl"): "eng",         # 0.570 → 0.666
    ("gez", "Joel"): "eng",         # 0.738 → 0.874; 3 chapters, English-style
    ("gez", "Ezra"): "org",         # 0.752 → 0.900
    # Chosen like CHAPTER_SCHEME_OVERRIDES below (stored vectors, neighbour test;
    # values are misaligned verses default → override):
    ("gez", "2Kgs"): "eng",         # vs KJV 31 → 9; 11.21 / 12.1–21 English-style (#188)
    ("gez", "1Esd"): "vul",         # vs Armenian 152 → 44; chapter verse counts match vul exactly (#76)
}

#: Chapters that follow a different scheme from their book (#186).  Some
#: editions follow one scheme for most of a book and another around a few
#: chapter boundaries (Isaiah 8/9, Exodus 40), where a whole-book override
#: would fix one chapter and break another.  Chosen by content: for each verse,
#: whether a neighbouring KJV verse (org ±1) is clearly closer (cosine + 0.05,
#: stored vectors; rare languages through their English translations) than the
#: KJV verse in its group.  Comments give those misaligned verses before → after;
#: each override also raises the mean similarity and adds no duplicate groups
#: unless noted.  Verses that merge or split (n:m) are left to #179.
CHAPTER_SCHEME_OVERRIDES: dict[tuple[str, str, int], Scheme] = {
    ("armenian", "Gen", 50): "org",     # 4 → 0
    ("armenian", "Exod", 40): "org",    # 7 → 0
    ("armenian", "Num", 13): "vul",     # 32 → 0 (the rest of the book is English-style)
    ("armenian", "Josh", 21): "org",    # 5 → 0
    ("armenian", "Job", 16): "org",     # 12 → 4
    ("armenian", "Ps", 43): "lxx",      # 5 → 0
    ("clementine", "Ps", 115): "lxx",   # 4 → 0; vul grouped 9 of its 10 verses twice
    ("clementine", "Ps", 147): "lxx",   # 3 → 0; likewise
    ("coptic-nt", "Isa", 9): "eng",     # 19 → 0
    ("coptic-nt", "Job", 40): "vul",    # 4 → 0
    ("coptic-nt", "Job", 41): "vul",    # 20 → 1
    ("gez", "Exod", 21): "org",         # 2 → 0
    ("gez", "Exod", 40): "vul",         # 10 → 8
    ("gez", "Job", 16): "vul",          # 15 → 0; 16.5 joins 16.4's group (n:m)
    ("gez", "Job", 41): "vul",          # 17 → 3
    ("gez", "Isa", 9): "eng",           # 19 → 0
    ("gez", "Isa", 64): "vul",          # 10 → 1; 64.1 (= 63.19b-64.1) joins 63.19 (n:m)
}

#: OSIS-style book (as used in our canonical refs) → Paratext/USFM code.
_OSIS_TO_USFM: dict[str, str] = {
    "Gen": "GEN", "Exod": "EXO", "Lev": "LEV", "Num": "NUM", "Deut": "DEU",
    "Josh": "JOS", "Judg": "JDG", "Ruth": "RUT", "1Sam": "1SA", "2Sam": "2SA",
    "1Kgs": "1KI", "2Kgs": "2KI", "1Chr": "1CH", "2Chr": "2CH", "Ezra": "EZR",
    "Neh": "NEH", "Esth": "EST", "Job": "JOB", "Ps": "PSA", "Prov": "PRO",
    "Eccl": "ECC", "Song": "SNG", "Isa": "ISA", "Jer": "JER", "Lam": "LAM",
    "Ezek": "EZK", "Dan": "DAN", "Hos": "HOS", "Joel": "JOL", "Amos": "AMO",
    "Obad": "OBA", "Jonah": "JON", "Mic": "MIC", "Nah": "NAM", "Hab": "HAB",
    "Zeph": "ZEP", "Hag": "HAG", "Zech": "ZEC", "Mal": "MAL",
    "Matt": "MAT", "Mark": "MRK", "Luke": "LUK", "John": "JHN", "Acts": "ACT",
    "Rom": "ROM", "1Cor": "1CO", "2Cor": "2CO", "Gal": "GAL", "Eph": "EPH",
    "Phil": "PHP", "Col": "COL", "1Thess": "1TH", "2Thess": "2TH",
    "1Tim": "1TI", "2Tim": "2TI", "Titus": "TIT", "Phlm": "PHM", "Heb": "HEB",
    "Jas": "JAS", "1Pet": "1PE", "2Pet": "2PE", "1John": "1JN", "2John": "2JN",
    "3John": "3JN", "Jude": "JUD", "Rev": "REV",
    "Tob": "TOB", "Jdt": "JDT", "Wis": "WIS", "Sir": "SIR", "Bar": "BAR",
    "EpJer": "LJE", "1Macc": "1MA", "2Macc": "2MA", "3Macc": "3MA",
    "4Macc": "4MA", "1Esd": "1ES", "1Esr": "1ES", "PrMan": "MAN",
    "PsSol": "PSS", "Odes": "ODA", "Sus": "SUS", "BelDr": "BEL",
    # Recensions grouped with their base book: they are parallel texts.
    "SusThdt": "SUS", "BelDrThdt": "BEL", "JudgVat": "JDG",
    "TobSin": "TOB", "TobVatAl": "TOB",
}

#: Books whose Greek/Latin form (with additions) has its own Paratext code.
_GREEK_FORM: dict[Scheme, dict[str, str]] = {
    "lxx": {"Dan": "DAG", "DanThdt": "DAG", "Esth": "ESG"},
    "vul": {},  # the vul file's DAN *is* the Vulgate layout (3:1-100); its DAG is Greek-style
    "eng": {}, "org": {},
}

#: Reverse map for building group IDs.  Greek-form codes fold back onto the
#: base book so e.g. LXX Daniel and Hebrew Daniel share groups.
_USFM_TO_OSIS: dict[str, str] = {
    **{u: o for o, u in _OSIS_TO_USFM.items() if o not in (
        "1Esr", "SusThdt", "BelDrThdt", "JudgVat", "TobSin", "TobVatAl")},
    "DAG": "Dan", "ESG": "Esth",
}

#: Known typos in the upstream vul.json (range keys whose values are wrong).
#: ``None`` drops a malformed entry.
_UPSTREAM_FIXES: dict[Scheme, dict[str, str | None]] = {
    "vul": {
        "DAG 13:1-63": "SUS 1:1-63",
        "DAG 14:1-42": "BEL 1:1-42",
        "DAG 3:52-23": None,  # end before start; the neighbouring entries cover these verses
    },
    "lxx": {
        # Conflicts with "DAG 4:1-3" → DAN 3:31-33, which is correct for Theodotion
        # (4:1 = "Ναβουχοδονοσορ ὁ βασιλεὺς πᾶσι τοῖς λαοῖς" = MT 3:31); OG has no 4:1-3.
        "DAG 4:1-2": None,
    },
}

_REF_RE = re.compile(r"^([1-4A-Z][0-9A-Z]{2}) (\d+):(\d+)([a-z]?)(?:-(\d+))?$")


class VersificationError(ValueError):
    """Raised for unmappable or inconsistent versification data."""


@cache
def _scheme_map(scheme: Scheme) -> dict[tuple[str, int, str], tuple[str, int, str]]:
    """Expand a scheme's ``mappedVerses`` into single-verse entries.

    A source verse spanning two org verses appears twice upstream (e.g. vul
    ``SNG 1:1`` → ``SNG 1:1`` and, via ``SNG 1:1-16``, → ``SNG 1:2``).  A chunk
    has one group, so later entries win: upstream lists the title / first half
    first and the content verse second, so this picks the content verse.
    """
    if scheme == "org":
        return {}
    raw = json.loads((_DATA_DIR / f"{scheme}.json").read_text(encoding="utf-8"))
    entries = dict(raw["mappedVerses"])
    for key, value in _UPSTREAM_FIXES.get(scheme, {}).items():
        if value is None:
            entries.pop(key, None)
        else:
            entries[key] = value

    table: dict[tuple[str, int, str], tuple[str, int, str]] = {}
    for key, value in entries.items():
        src, dst = _REF_RE.match(key), _REF_RE.match(value)
        if not src or not dst:
            raise VersificationError(f"{scheme}: unparseable mapping {key!r} → {value!r}")
        s_book, s_ch, s_v, s_sfx, s_end = src.groups()
        d_book, d_ch, d_v, d_sfx, d_end = dst.groups()
        s_first, d_first = int(s_v), int(d_v)
        s_last = int(s_end) if s_end else s_first
        d_last = int(d_end) if d_end else d_first
        if s_last - s_first != d_last - d_first:
            raise VersificationError(
                f"{scheme}: range length mismatch {key!r} → {value!r}"
            )
        if s_end:
            for offset in range(s_last - s_first + 1):
                table[(s_book, int(s_ch), str(s_first + offset))] = (
                    d_book, int(d_ch), str(d_first + offset),
                )
        else:
            table[(s_book, int(s_ch), f"{s_v}{s_sfx}")] = (d_book, int(d_ch), f"{d_v}{d_sfx}")
    return table


def scheme_for(source_id: str, book: str, chapter: int | None = None) -> Scheme:
    """Return the versification scheme a source uses for *book* (and *chapter*)."""
    try:
        default = SOURCE_SCHEMES[source_id]
    except KeyError:
        raise VersificationError(
            f"No versification scheme registered for {source_id!r}; "
            "add it to SOURCE_SCHEMES in patristica/versification.py"
        ) from None
    if chapter is not None and (source_id, book, chapter) in CHAPTER_SCHEME_OVERRIDES:
        return CHAPTER_SCHEME_OVERRIDES[(source_id, book, chapter)]
    return BOOK_SCHEME_OVERRIDES.get((source_id, book), default)


def _esdras_b(chapter: int) -> tuple[str, int]:
    """Greek Esdras B (LXX 2 Esdras) = Ezra 1–10 + Nehemiah 1–13."""
    return ("Ezra", chapter) if chapter <= 10 else ("Neh", chapter - 10)


@cache
def _max_verses(scheme: Scheme, usfm: str, chapter: int) -> int:
    """Number of verses of *usfm* *chapter* in *scheme* (0 when the scheme lacks it)."""
    raw = json.loads((_DATA_DIR / f"{scheme}.json").read_text(encoding="utf-8"))
    chapters = raw["maxVerses"].get(usfm, [])
    return int(chapters[chapter - 1]) if 0 < chapter <= len(chapters) else 0


def _psalm_title(source_id: str, chapter: int) -> str:
    """The org ref of a psalm title kept as its own unit, ``Ps.N.0`` (#220, #255).

    Only sources whose scheme doesn't number titles have one (ASV, the
    Armenian Zohrab).  The title goes where the source's psalm starts in org
    numbering: org verse 1 when the psalm starts an org psalm, whether the org
    title is its own verse (Ps 3), the start of a verse that also holds text
    (Ps 23, the Hallelujah of Ps 111–113), verses 1–2 (Ps 51, 52, 54, 60;
    upstream maps a title spanning two verses to the later one) or absent
    (Ps 2, where the Armenian title only notes that the Hebrew has none).  A
    psalm that starts inside an org psalm (Vulgate/LXX Ps 115 = Heb 116:10–19,
    Ps 147 = Heb 147:12–20) puts its title at the org verse where it starts;
    the Vulgate scheme numbers such a psalm on from the org one (115:10–19).
    """
    numbered = sorted(int(v) for (b, c, v) in _scheme_map(scheme_for(source_id, "Ps", chapter))
                      if b == "PSA" and c == chapter and v.isdigit() and v != "0")
    first_v = numbered[0] if numbered and numbered[0] > 1 else 1
    first = to_org_ref(source_id, f"Ps.{chapter}.{first_v}")
    org_ch = first.split(".")[1]
    if chapter > 1:
        prev_scheme = scheme_for(source_id, "Ps", chapter - 1)
        last = _max_verses(prev_scheme, "PSA", chapter - 1)
        if last and to_org_ref(source_id, f"Ps.{chapter - 1}.{last}").split(".")[1] == org_ch:
            return first
    if first_v > 1:
        first = to_org_ref(source_id, f"Ps.{chapter}.1")
        org_ch = first.split(".")[1]
    return f"Ps.{org_ch}.1"


def to_org_ref(source_id: str, canonical_ref: str) -> str:
    """Map a source-native ``Book.C.V`` ref onto org versification.

    The result uses our OSIS-style book names (``Ps.24.1``) and serves as the
    translation group ID.  Refs in books with no USFM equivalent (Ethiopic
    extras, Syriac-numbered Esdras, …) are returned unchanged.
    """
    parts = canonical_ref.split(".")
    if len(parts) != 3 or not parts[1].isdigit():
        return canonical_ref
    book, chapter, verse = parts[0], int(parts[1]), parts[2]

    if book == "EzraNeh":
        book, chapter = _esdras_b(chapter)

    scheme = scheme_for(source_id, book, chapter)
    usfm = _GREEK_FORM[scheme].get(book) or _OSIS_TO_USFM.get(book)
    if usfm is None:
        return canonical_ref if parts[0] != "EzraNeh" else f"{book}.{chapter}.{verse}"

    if verse == "0" and usfm == "PSA" and scheme != "org":
        return _psalm_title(source_id, chapter)
    d_book, d_ch, d_v = _scheme_map(scheme).get((usfm, chapter, verse), (usfm, chapter, verse))
    return f"{_USFM_TO_OSIS.get(d_book, d_book)}.{d_ch}.{d_v}"
