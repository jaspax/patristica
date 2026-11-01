"""
Ingest the in-period Old and early Middle Irish religious texts of CELT, the
Corpus of Electronic Texts (celt.ucc.ie, University College Cork; #541).

Every Irish text is language ``sga`` (#225: one code for Old and early Middle
Irish up to the period's end), tradition ``latin``. Where CELT has the English
translation of an included text (a ``T…`` file), it is ingested too, as an
English work with ``translation_of`` the Irish one.

Selection (#541): CELT's Irish religious texts, kept only when in period by
``patristica/period.py`` (anonymous texts composed by 1050). CELT's own
"Created" date is used unless the standard scholarship differs (noted per
text in :data:`TEXTS`). Middle Irish texts that CELT dates only to "900–1200"
and later lives, homilies and visions are left out; the full survey is in the
PR for #541 and in ``DATA_COLLECTION_PLAN.md`` §3.7.

Refs follow CELT's (that is, the printed edition's) numbering: stanza numbers
for poems (``Fel.Jan.1``, ``AdamCoim.3``), first-line numbers of quatrains for
Saltair na Rann (``SnR.{poem}.{line}``), section or paragraph numbers for prose.
Poems are written as ``verses`` (a stanza is never cut into derived verses),
prose as ``paragraphs``.

Licence: ``_celt.CELT_LICENSE`` (``unknown`` until CELT grants permission,
#542): the works are ingested and normalized but never translated, embedded,
indexed or published.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patristica.models import Work
from scripts.ingest import _celt as C

log = logging.getLogger(__name__)

SOURCE_ID = "celt"


@dataclass(frozen=True)
class Text:
    celt_id: str
    slug: str
    prefix: str
    title: str
    author: str
    date_range: tuple[int, int] | None
    date_confidence: str
    genre: str
    mode: str  # stanzas | paras | numbered | felire | saltair
    date_composed: int | None = None
    language: str = "sga"
    start: str | None = None  # raw-HTML substring: the text starts after it
    end: str | None = None  # raw-HTML substring: the text ends before it
    sections: bool = False  # headings open numbered sections
    parts: tuple[tuple[str, str], ...] = ()  # numbered mode: heading → part ref
    translation_of: str | None = None  # slug of the Irish work (English texts)
    dating: str = ""  # basis of the date (kept in the module, not in the data)


def _t(**kw: Any) -> Text:
    return Text(**kw)


ANON = "Anonymous"

# Murphy, Early Irish Lyrics (1956), dates each poem; CELT copies his dates.
MURPHY = "CELT's date, after Murphy, Early Irish Lyrics (1956)"
# Kuno Meyer's small editions ("Mitteilungen aus irischen Handschriften", ZCP
# and "A medley of Irish texts", ACL), dated by CELT to the Old Irish period.
MEYER = "CELT: Old Irish period (600–900), from the language (Meyer's edition)"

TEXTS: tuple[Text, ...] = (
    # --- Martyrology and hymns -------------------------------------------
    _t(
        celt_id="G200001",
        slug="felire-oengusso",
        prefix="Fel",
        title="Félire Óengusso Céli Dé (The Martyrology of Óengus the Culdee)",
        author="Óengus mac Óengobann",
        date_range=(797, 833),
        date_confidence="approximate",
        genre="liturgical",
        mode="felire",
        dating="Stokes: 797–808; Ó Riain and Dumville: c. 828–833 (CELT: 828–833). The "
        "Middle Irish prose prefaces of Stokes's edition are left out.",
    ),
    _t(
        celt_id="G201022",
        slug="tiugraind-beccain",
        prefix="TiugBecc",
        title="Tiugraind Beccáin (Beccán's last poem on Colum Cille)",
        author="Beccán mac Luigdech",
        date_range=(650, 677),
        date_confidence="approximate",
        genre="patristic",
        mode="stanzas",
        dating="Kelly, Ériu 26 (1975): 7th c., by Beccán of Rum (d. 677); CELT: 900–1200",
    ),
    # --- Hagiography ------------------------------------------------------
    _t(
        celt_id="G201002",
        slug="bethu-brigte",
        prefix="BBrig",
        title="Bethu Brigte (The Old Irish Life of Brigit)",
        author=ANON,
        date_range=(800, 850),
        date_confidence="approximate",
        genre="patristic",
        mode="numbered",
        parts=(("Slicht sain in so budesta", "Slicht"),),
        dating="CELT: c. 800–850 (Ó hAodha)",
    ),
    _t(
        celt_id="T201002",
        slug="bethu-brigte-eng",
        prefix="BBrig",
        title="Bethu Brigte (The Old Irish Life of Brigit), English translation",
        author=ANON,
        date_range=(800, 850),
        date_confidence="approximate",
        genre="patristic",
        mode="numbered",
        language="eng",
        translation_of="bethu-brigte",
        dating="as the Irish",
    ),
    _t(
        celt_id="G201015",
        slug="betha-adamnain",
        prefix="BAdamn",
        title="Betha Adamnáin (The Irish Life of Adamnán)",
        author=ANON,
        date_range=(956, 964),
        date_confidence="approximate",
        genre="patristic",
        mode="paras",
        dating="Herbert and Ó Riain (1988): 956×964; CELT: c. 700–900",
    ),
    _t(
        celt_id="G201026",
        slug="molaisse-and-his-sister",
        prefix="Molaisse",
        title="Molaisse and his sister (Molaisse und seine Schwester)",
        author=ANON,
        date_range=(800, 1000),
        date_confidence="uncertain",
        genre="patristic",
        mode="paras",
        dating="CELT: c. 800–1000",
    ),
    _t(
        celt_id="G201028",
        slug="cain-eimine-bain",
        prefix="CainEim",
        title="Cáin Eimíne Báin",
        author=ANON,
        date_range=(700, 800),
        date_confidence="uncertain",
        genre="patristic",
        mode="paras",
        dating="CELT: 700–800 (Old Irish, with much Middle Irish spelling)",
    ),
    # --- Biblical and devotional verse ------------------------------------
    _t(
        celt_id="G202001",
        slug="saltair-na-rann",
        prefix="SnR",
        title="Saltair na Rann (The Psalter of Quatrains)",
        author=ANON,
        date_composed=988,
        date_range=(985, 1000),
        date_confidence="approximate",
        genre="patristic",
        mode="saltair",
        dating="Mac Eoin: 988 (the regnal list and the murrain of 987); CELT: 1000–1070",
    ),
    _t(
        celt_id="G202007",
        slug="a-de-dulig-adateoch",
        prefix="ADeDul",
        title="A Dé dúilig adateoch (Airbertach mac Coise's poem on the Psalms)",
        author="Airbertach Mac Cosse",
        date_composed=982,
        date_range=(982, 982),
        date_confidence="established",
        genre="patristic",
        mode="stanzas",
        start="<h3><i>Commentary on the Psalms by Airbertach mac Cosse</i></h3>",
        dating="dated 982 in stanzas 34 and 36 (Meyer)",
    ),
    _t(
        celt_id="G202010",
        slug="cenn-ard-adaim",
        prefix="CennArd",
        title="Cenn ard Ádaim étrocht rád",
        author="Airbertach Mac Cosse",
        date_range=(950, 1000),
        date_confidence="approximate",
        genre="patristic",
        mode="stanzas",
        start="Z Vergl Spr NF 13, 94.</i></h3>",  # after Meyer's German note
        dating="CELT: c. 950–1000, attributed to Airbertach mac Coise (d. 1016)",
    ),
    # --- Rules and teaching -----------------------------------------------
    _t(
        celt_id="G203000",
        slug="regula-mucuta-raithni",
        prefix="RegMoch",
        title="Regula Mucuta Raithni (The Rule of Mo Chutu of Rahan)",
        author=ANON,
        date_range=(800, 1000),
        date_confidence="uncertain",
        genre="patristic",
        mode="stanzas",
        sections=True,
        # The Rule, not the late Life of Mo Chutu: in period (owner, 2026-11-01).
        dating="usually taken as a late Old Irish rule (9th c.); CELT: 900–1200",
    ),
    _t(
        celt_id="G203001",
        slug="regula-choluimb-chille",
        prefix="RegCol",
        title="Regula Choluimb Chille (The Rule of Colum Cille)",
        author=ANON,
        date_range=(600, 900),
        date_confidence="uncertain",
        genre="patristic",
        mode="paras",
        start="<address>Kuno Meyer</address></div>",
        dating="CELT: 600–900 (G203001A)",
    ),
    _t(
        celt_id="G204001",
        slug="todsunden",
        prefix="Todsund",
        title="On the deadly sins (Von den Todsünden)",
        author=ANON,
        date_range=(800, 900),
        date_confidence="approximate",
        genre="patristic",
        mode="paras",
        sections=True,
        dating="CELT: c. 800–900",
    ),
    _t(
        celt_id="G206001",
        slug="heimliche-sunden",
        prefix="HeimSund",
        title="On secret sins (Von heimlichen Sünden)",
        author=ANON,
        date_range=(600, 900),
        date_confidence="uncertain",
        genre="patristic",
        mode="paras",
        dating="CELT: c. 600–900",
    ),
    _t(
        celt_id="G206003",
        slug="apgitir-chrabaid",
        prefix="Apgitir",
        title="Apgitir Chrábaid (The Alphabet of Piety)",
        author="Colmán maccu Béognae",
        date_range=(600, 800),
        date_confidence="approximate",
        genre="patristic",
        mode="paras",
        sections=True,
        dating="Ó Néill (1987): c. 600, by Colmán maccu Béognae (d. 611); others 8th c.; "
        "CELT: 900–1200 (Meyer's late manuscripts)",
    ),
    _t(
        celt_id="G206004",
        slug="briathra-flainn-fina",
        prefix="BrFlainn",
        title="Bríathra Flainn Fína maic Ossu (The sayings of Flann Fína)",
        author=ANON,
        date_range=(600, 900),
        date_confidence="uncertain",
        genre="patristic",
        mode="paras",
        dating=MEYER,
    ),
    _t(
        celt_id="G206006",
        slug="eineach-uaisle",
        prefix="Eineach",
        title="Eineach úaisle ná gach dán (from Laud 615)",
        author=ANON,
        date_range=(600, 900),
        date_confidence="uncertain",
        genre="patristic",
        mode="stanzas",
        dating=MEYER,
    ),
    # --- Visions and eschatology ------------------------------------------
    _t(
        celt_id="G207003",
        slug="vision-of-laisren",
        prefix="Laisren",
        title="Fís Laisréin (The Vision of Laisrén)",
        author=ANON,
        date_range=(850, 925),
        date_confidence="approximate",
        genre="patristic",
        mode="paras",
        start="{folio 44ra}",  # after Meyer's introduction
        dating="CELT: c. 850–925 (Meyer: Old Irish)",
    ),
    _t(
        celt_id="T207003",
        slug="vision-of-laisren-eng",
        prefix="Laisren",
        title="Fís Laisréin (The Vision of Laisrén), English translation",
        author=ANON,
        date_range=(850, 925),
        date_confidence="approximate",
        genre="patristic",
        mode="paras",
        language="eng",
        translation_of="vision-of-laisren",
        dating="as the Irish",
    ),
    _t(
        celt_id="G207006",
        slug="dofil-aimser-laithe-bratha",
        prefix="Dofil",
        title="Dofil aimser laithe mbratha (An Old Irish poem on the end of the world)",
        author=ANON,
        date_range=(600, 900),
        date_confidence="uncertain",
        genre="patristic",
        mode="stanzas",
        dating=MEYER,
    ),
    _t(
        celt_id="G207008",
        slug="baile-bricin",
        prefix="BaileBric",
        title="Baile Bricín (The Vision of Bricín)",
        author=ANON,
        date_range=(800, 900),
        date_confidence="approximate",
        genre="patristic",
        mode="paras",
        start="Mesi an Gillo r&iacute;ab<i>ach</i>",  # a scribe's note before the text
        dating="CELT: c. 800–900",
    ),
    _t(
        celt_id="G208005",
        slug="patraic-cecinit",
        prefix="PatCec",
        title="Pátraic cecinit",
        author=ANON,
        date_range=(600, 900),
        date_confidence="uncertain",
        genre="patristic",
        mode="stanzas",
        dating=MEYER,
    ),
    _t(
        celt_id="G100040",
        slug="irish-bede",
        prefix="IrBede",
        title=(
            "An Irish version of Bede's Ecclesiastical History "
            "(Eine irische Version von Beda's Historia)"
        ),
        author=ANON,
        date_range=(800, 900),
        date_confidence="approximate",
        genre="patristic",
        mode="paras",
        dating="CELT: 9th c. (Meyer)",
    ),
)


def _lyric(
    celt_id: str,
    slug: str,
    prefix: str,
    title: str,
    rng: tuple[int, int],
    conf: str = "approximate",
    dating: str = MURPHY,
) -> Text:
    return _t(
        celt_id=celt_id,
        slug=slug,
        prefix=prefix,
        title=title,
        author=ANON,
        date_range=rng,
        date_confidence=conf,
        genre="patristic",
        mode="stanzas",
        dating=dating,
    )


# Religious poems from Murphy's Early Irish Lyrics and Meyer's small editions.
LYRICS: tuple[Text, ...] = (
    _lyric("G400003", "clocan-binn", "Clocan", "Clocán binn (The Bell)", (800, 900)),
    _lyric(
        "G400004",
        "adram-in-coimdid",
        "AdramCoim",
        "Adram in Coimdid (The Lord of Creation)",
        (800, 900),
    ),
    _lyric(
        "G400007",
        "a-ben-bennacht-fort",
        "ABen",
        "A ben, bennacht fort, ná ráid! (Sell not Heaven for Sin)",
        (825, 875),
    ),
    _lyric(
        "G400008",
        "a-marbain-a-dithrubaig",
        "Marban",
        "A Marbáin, a díthrubaig (King and Hermit)",
        (800, 900),
    ),
    _lyric(
        "G400009",
        "m-oenuran-im-airiclan",
        "Oenuran",
        "M'óenurán im aireclán (A Hermit Song)",
        (800, 900),
    ),
    _lyric(
        "G400010",
        "dia-lim-fri-cach-snim",
        "DiaLim",
        "Día lim fri cach sním (God be with me)",
        (800, 900),
    ),
    _lyric("G400011", "isucan", "Isucan", "Ísucán (Jesus and Saint Íte)", (875, 925)),
    _lyric(
        "G400012",
        "duthracar-a-maic-de-bi",
        "Manchan",
        "Dúthracar, a Maic Dé bí (Manchán's Wish)",
        (900, 1000),
    ),
    _lyric(
        "G400013",
        "tan-bim-eter-mo-shruithe",
        "TanBim",
        "Tan bím eter mo shruithe (All Things to All Men)",
        (900, 1000),
    ),
    _lyric(
        "G400014",
        "cros-christ",
        "CrosChrist",
        "Cros Chríst tarsin ngnúis-se (Christ's Cross)",
        (965, 981),
    ),
    # Murphy's edition of the first three stanzas of Airbertach's poem (G202007).
    _t(
        celt_id="G400015",
        slug="a-de-duilig-atat-teoch",
        prefix="ADeDuilig",
        title="A Dé dúilig atat-teoch (I Invoke Thee, God)",
        author="Airbertach Mac Cosse",
        date_composed=982,
        date_range=(982, 982),
        date_confidence="established",
        genre="patristic",
        mode="stanzas",
        dating=MURPHY + "; the opening of G202007",
    ),
    _lyric(
        "G400016", "isam-aithrech", "Isam", "Isam aithrech (Prayer for Forgiveness)", (987, 987)
    ),
    _lyric(
        "G400017",
        "is-mebul-dom-imradud",
        "Mebul",
        "Is mebul dom imrádud (On the Flightiness of Thought)",
        (900, 1000),
    ),
    _lyric(
        "G400043",
        "m-airiuclan",
        "Airiuclan",
        "M’airiuclán hi Túaim Inbir (My Little Oratory)",
        (775, 825),
    ),
    _lyric(
        "G400072",
        "sitz-geistiger-krafte",
        "Sitz",
        "The seat of the faculties and passions in the body (Der Sitz geistiger Kräfte)",
        (600, 900),
        "uncertain",
        MEYER,
    ),
    _lyric(
        "G400074",
        "colum-cilles-lieblingsstatten",
        "ColLieb",
        "Colum Cille's favourite places (Colum Cilles Lieblingsstätten)",
        (600, 900),
        "uncertain",
        MEYER,
    ),
    _lyric(
        "G400076",
        "spruch-adamnans",
        "SprAdamn",
        "A saying of Adamnán (Ein Spruch Adamnans)",
        (600, 900),
        "uncertain",
        MEYER,
    ),
    _lyric(
        "G400077",
        "weissagung-colum-cilles",
        "WeisCol",
        "A prophecy of Colum Cille (Eine Weissagung Colum Cilles)",
        (600, 900),
        "uncertain",
        MEYER,
    ),
    _lyric(
        "G400078",
        "gebet-um-tranen",
        "GebTran",
        "Prayer for tears (Gebet um Thränen)",
        (600, 900),
        "uncertain",
        MEYER,
    ),
    _lyric(
        "G400079",
        "gebet-fursas",
        "GebFursa",
        "A prayer of Fursa (Ein Gebet Fursas)",
        (600, 900),
        "uncertain",
        MEYER,
    ),
    _lyric(
        "G400080", "uch-a-de", "UchDe", "Uch, a Dé (Ach und Weh)", (600, 900), "uncertain", MEYER
    ),
    _lyric(
        "G400081",
        "segenbringender-glockenklang",
        "Glocken",
        "The blessed sound of the bell (Segenbringender Glockenklang)",
        (600, 900),
        "uncertain",
        MEYER,
    ),
    _lyric(
        "G400107",
        "segen-der-freigebigkeit",
        "Freigeb",
        "The blessing of generosity (Segen der Freigebigkeit)",
        (600, 900),
        "uncertain",
        MEYER,
    ),
    _lyric(
        "G400108",
        "priester-schmahen",
        "Priest",
        "Who reviles a priest goes to hell (Wer einen Priester schmäht, fährt zur Hölle)",
        (600, 900),
        "uncertain",
        MEYER,
    ),
    _t(
        celt_id="G400112",
        slug="altirischer-spruch",
        prefix="Spruch",
        title="Mór ndrúiss, mór mbáis (An Old Irish saying)",
        author=ANON,
        date_range=(600, 900),
        date_confidence="uncertain",
        genre="patristic",
        mode="stanzas",
        start="<ol>",
        dating=MEYER,
    ),  # after Meyer's German note
)


# Borderline texts the owner left out (2026-11-01, #541): in range by CELT's
# dates, but probably composed after the period's end. Kept here so a later
# survey doesn't add them back.
OWNER_EXCLUDED: dict[str, str] = {
    "G400018": "Rop tú mo baile: composition probably after 1050 (owner, 2026-11-01)",
    "G400019": "Tórramat do nóebaingil: composition probably after 1050 (owner, 2026-11-01)",
    "G400020": "A Maire mín maithingen: composition probably after 1050 (owner, 2026-11-01)",
    "G400021": "Mé Éba: composition probably after 1050 (owner, 2026-11-01)",
    "G400026": "Ropo mían dom menmain: composition probably after 1050 (owner, 2026-11-01)",
}

ALL_TEXTS: tuple[Text, ...] = TEXTS + LYRICS


# ---------------------------------------------------------------------------
# Unit builders, one per layout
# ---------------------------------------------------------------------------


def _cut(body: str, text: Text) -> str:
    if text.start:
        i = body.find(text.start)
        if i < 0:
            raise C.CeltError(f"{text.celt_id}: start marker {text.start!r} not found")
        body = body[i + len(text.start) :]
    if text.end:
        i = body.find(text.end)
        if i < 0:
            raise C.CeltError(f"{text.celt_id}: end marker {text.end!r} not found")
        body = body[:i]
    return body


def _ref(prefix: str, section: int | None, n: int | str) -> str:
    return f"{prefix}.{section}.{n}" if section is not None else f"{prefix}.{n}"


def build_stanzas(events: list[C.Event], prefix: str, sections: bool) -> list[dict[str, Any]]:
    """Poems: one unit per ``<li value=N>`` stanza; prose before a section's
    first stanza is its unit 0 (the prose frame of a poem), prose after a
    stanza joins it. With *sections*, headings open numbered sections."""
    units: list[dict[str, Any]] = []
    section: int | None = 1 if sections else None
    started = False
    intro: list[tuple[str, list[list[Any]]]] = []
    last: dict[str, Any] | None = None  # the stanza that prose after it joins
    count = 0  # the last stanza number, for <li> without a value
    for ev in events:
        if ev.kind == "head":
            if not sections:
                continue  # an editor's title: the work's title already says it
            text, _ = C.inline(ev.html)
            if not text:
                continue
            if intro:
                raise C.CeltError(f"{prefix}: prose with no stanza after it")
            if started:
                assert section is not None
                section += 1
            started = True
            last = None
            units.append(C.heading_unit(f"{prefix}.{section}", text))
            continue
        text, spans = C.inline(ev.html)
        if not text:
            continue
        started = True
        if ev.kind == "stanza":
            if intro:
                t, sp = C.join_units(intro)
                units.append(C.unit(_ref(prefix, section, 0), t, sp))
                intro = []
            number = ev.number if ev.number is not None else count + 1
            count = number
            last = C.unit(_ref(prefix, section, number), text, spans)
            units.append(last)
        elif last is None:
            intro.append((text, spans))
        else:
            t, sp = C.join_units([(last["text"], last.get("editorial", [])), (text, spans)])
            last["text"] = t
            if sp:
                last["editorial"] = sp
    if intro:
        raise C.CeltError(f"{prefix}: prose with no stanza after it")
    return units


def build_paras(events: list[C.Event], prefix: str, sections: bool) -> list[dict[str, Any]]:
    """Prose: one unit per paragraph, numbered in order; with *sections*,
    headings open numbered sections. Where the edition numbers its paragraphs
    (``¶N``), those numbers are the refs and an unnumbered paragraph continues
    the one before. Verse quoted in the prose (``<li>``) joins the paragraph
    before it."""
    units: list[dict[str, Any]] = []
    section: int | None = 1 if sections else None
    numbered = any(ev.number is not None for ev in events if ev.kind == "para")
    k = 0
    started = False
    last: dict[str, Any] | None = None
    for ev in events:
        if ev.kind == "head":
            if not sections:
                continue
            text, _ = C.inline(ev.html)
            if not text:
                continue
            if started:
                assert section is not None
                section += 1
                k = 0
            started = True
            last = None
            units.append(C.heading_unit(f"{prefix}.{section}", text))
            continue
        text, spans = C.inline(ev.html)
        if not text:
            continue
        started = True
        wholly_note = spans == [[0, len(text), "note"]]  # a marginal reference
        joins = ev.kind == "stanza" or wholly_note or (numbered and ev.number is None)
        if joins and last is not None:
            _append(last, text, spans)
            continue
        if numbered and ev.number is None:
            raise C.CeltError(f"{prefix}: text before the first numbered paragraph")
        k = ev.number if numbered and ev.number is not None else k + 1
        last = C.unit(_ref(prefix, section, k), text, spans)
        units.append(last)
    return units


def _append(unit: dict[str, Any], text: str, spans: list[list[Any]]) -> None:
    t, sp = C.join_units([(unit["text"], unit.get("editorial", [])), (text, spans)])
    unit["text"] = t
    if sp:
        unit["editorial"] = sp


def build_numbered(
    events: list[C.Event], prefix: str, parts: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """Prose in numbered sections (``<h4>N</h4>``): one unit per section. A
    heading named in *parts* opens a part of its own (``{prefix}.{part}.{N}``,
    a heading unit at ``{prefix}.{part}``). A number the edition repeats gets
    the suffix ``b`` (Bethu Brigte prints §41 twice)."""
    units: list[dict[str, Any]] = []
    current: list[tuple[str, list[list[Any]]]] = []
    number: str | None = None
    part: str | None = None
    seen: set[str] = set()

    def flush() -> None:
        if number is not None and current:
            t, sp = C.join_units(current)
            units.append(C.unit(f"{prefix}.{number}", t, sp))

    for ev in events:
        if ev.kind == "head":
            label = C.inline(ev.html)[0].rstrip(".").strip()
            if parts and label in parts:
                flush()
                part, number, current = parts[label], None, []
                units.append(C.heading_unit(f"{prefix}.{part}", label))
                continue
            if not re.fullmatch(r"\d+", label):
                raise C.CeltError(f"{prefix}: unexpected heading {label!r}")
            flush()
            n = f"{part}.{label}" if part else label
            if n in seen:
                log.debug("%s: section %s printed twice; the second is %sb", prefix, n, n)
                n += "b"
            seen.add(n)
            number, current = n, []
            continue
        if number is None:
            raise C.CeltError(f"{prefix}: text before the first numbered section")
        current.append(C.inline(ev.html))
    flush()
    return units


_MONTHS = {
    "ENAIR": "Jan",
    "FEBRAI": "Feb",
    "MARTA": "Mar",
    "APRÉIL": "Apr",
    "MÁI": "May",
    "IÚIN": "Jun",
    "IÚIL": "Jul",
    "AUGUIST": "Aug",
    "SEPTIMBIR": "Sep",
    "OCHTIMBIR": "Oct",
    "NOUIMBIR": "Nov",
    "DECIMBIR": "Dec",
}


_MONTH_DAYS = {
    "Jan": 31,
    "Feb": 28,
    "Mar": 31,
    "Apr": 30,
    "May": 31,
    "Jun": 30,
    "Jul": 31,
    "Aug": 31,
    "Sep": 30,
    "Oct": 31,
    "Nov": 30,
    "Dec": 31,
}


def build_felire(body: str, prefix: str) -> list[dict[str, Any]]:
    """The Félire: prologue (``Fel.Prol.N``), the calendar (``Fel.{Mon}.{day}``,
    a month heading at ``Fel.{Mon}``) and epilogue (``Fel.Epil.N``). Each day's
    calendar line (``A. Kalendis Januarii.``) is ``metadata``. The Middle Irish
    prose prefaces before the poem are left out (later than the period's end)."""
    i = body.find("<h3>IN PROLACH.</h3>")
    if i < 0:
        raise C.CeltError("Félire: no prologue heading")
    units: list[dict[str, Any]] = []
    part: str | None = None
    counts: dict[str, int] = {}
    for ev in C.events(body[i:]):
        if ev.kind == "head":
            label = C.inline(ev.html)[0].rstrip(".").strip()
            if label == "IN PROLACH":
                part = "Prol"
            elif label == "EPILOGUE":
                part = "Epil"
            elif label.startswith(("MÍ ", "MI ")):
                month = _MONTHS[label.split(" ", 1)[1]]
                part = month
                units.append(C.heading_unit(f"{prefix}.{month}", label + "."))
            elif label.startswith("FÉLIRE"):
                continue
            else:
                raise C.CeltError(f"Félire: unexpected heading {label!r}")
            continue
        if ev.kind == "para" and units and part is not None:
            # CELT's own notes between stanzas (Thurneysen on the interpolation).
            note, _ = C.inline(ev.html)
            _append(units[-1], note, [[0, len(note), "note"]])
            continue
        if ev.kind != "stanza" or part is None:
            raise C.CeltError(f"Félire: unexpected text in {part}: {C.inline(ev.html)[0][:60]!r}")
        html = ev.html
        m = re.match(r"\s*<b>(.*?)</b>\s*(?=<br>)", html, re.S)
        if m and part not in ("Prol", "Epil"):
            html = C.mark(m.group(1), "metadata") + " " + html[m.end() :]
        elif part not in ("Prol", "Epil"):
            raise C.CeltError(f"Félire {part} {ev.number}: no calendar line")
        text, spans = C.inline(html)
        # Numbered by position: the edition's stanza numbers have slips (May 13
        # is printed as 33), and a day is a stanza, so the count is the date.
        n = counts[part] = counts.get(part, 0) + 1
        if ev.number != n:
            log.debug("Félire %s: stanza %d printed as %s", part, n, ev.number)
        units.append(C.unit(f"{prefix}.{part}.{n}", text, spans))
    for month, days in _MONTH_DAYS.items():
        if counts.get(month) != days:
            raise C.CeltError(f"Félire {month}: {counts.get(month)} days, expected {days}")
    return units


def build_saltair(body: str, prefix: str) -> list[dict[str, Any]]:
    """Saltair na Rann: poems (``<h2>N.</h2>``) of quatrains, each cited by the
    number of its first line (``SnR.{poem}.{line}``; Stokes numbers every
    fourth line). Stokes's preface and the list before poem 1 are left out."""
    marker = "<h2>Saltair na Rann</h2>"
    i = body.find(marker)
    if i < 0:
        raise C.CeltError("Saltair: no text heading after the preface")
    body = C.strip_layout(body[i + len(marker) :])
    body = re.sub(r"</?(?:ol|li)[^>]*>", "", body)
    units: list[dict[str, Any]] = []
    parts = re.split(r"<h[23]>\s*(\d+)\.\s*</h[23]>", body)
    if C.inline(parts[0])[0]:
        raise C.CeltError(f"Saltair: text before poem 1: {C.inline(parts[0])[0][:60]!r}")
    for poem, chunk in zip(parts[1::2], parts[2::2]):
        pieces = re.split(r"(?:^|<br>)\s*(\d{1,5})\]", chunk.strip())
        lines = [int(n) for n in pieces[1::2]]
        if not lines:
            raise C.CeltError(f"Saltair {poem}: no line numbers")
        head, _ = C.inline(pieces[0])
        if head:  # the poem's first quatrain, before the first printed number
            first = lines[0] - 4
            if first < 1:
                raise C.CeltError(f"Saltair {poem}: text before line {lines[0]}")
            units.append(C.unit(f"{prefix}.{poem}.{first}", *C.inline(pieces[0])))
        for line, html in zip(lines, pieces[2::2]):
            text, spans = C.inline(html)
            if text:
                units.append(C.unit(f"{prefix}.{poem}.{line}", text, spans))
    return units


def parse(text: Text, page: str) -> list[dict[str, Any]]:
    """The raw units of *text* from its CELT page."""
    body = _cut(C.body_html(page, text.celt_id), text)
    if text.mode == "felire":
        units = build_felire(body, text.prefix)
    elif text.mode == "saltair":
        units = build_saltair(body, text.prefix)
    else:
        events = C.events(body)
        if text.mode == "stanzas":
            units = build_stanzas(events, text.prefix, text.sections)
        elif text.mode == "paras":
            units = build_paras(events, text.prefix, text.sections)
        elif text.mode == "numbered":
            units = build_numbered(events, text.prefix, dict(text.parts))
        else:
            raise C.CeltError(f"unknown mode {text.mode!r}")
    refs = [u["ref"] for u in units]
    if not units:
        raise C.CeltError(f"{text.celt_id}: no text")
    if len(set(refs)) != len(refs):
        dup = sorted({r for r in refs if refs.count(r) > 1})
        raise C.CeltError(f"{text.celt_id}: duplicate refs {dup[:5]}")
    return units


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------


def edition_line(text: Text, header: C.Header) -> str:
    used = header.edition or "the edition named in CELT's header"
    return f"CELT {text.celt_id} (University College Cork), from {used}"


def make_work(text: Text, header: C.Header) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{text.slug}",
        source_id=SOURCE_ID,
        author=text.author,
        title=text.title,
        date_composed=text.date_composed,
        date_range=text.date_range,
        date_confidence=text.date_confidence,  # type: ignore[arg-type]
        genre=text.genre,  # type: ignore[arg-type]
        language=text.language,  # type: ignore[arg-type]
        tradition="latin",
        license=C.CELT_LICENSE,  # type: ignore[arg-type]
        provenance_url=C.page_url(text.celt_id),
        edition=edition_line(text, header),
        translation_of=f"{SOURCE_ID}/{text.translation_of}" if text.translation_of else None,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Fetch (or read from the cache) every selected CELT text; one raw file per work."""
    works: list[Work] = []
    for text in ALL_TEXTS:
        out_path = output_dir / SOURCE_ID / f"{text.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        page = C.fetch(text.celt_id, output_dir, force=force)
        header = C.parse_header(page)
        if "RESTRICTED" not in header.availability and "prior consent" not in header.availability:
            log.warning("%s: availability changed: %s", text.celt_id, header.availability)
        units = parse(text, page)
        work = make_work(text, header)
        key = "verses" if text.mode in ("stanzas", "felire", "saltair") else "paragraphs"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"work": work.model_dump(), key: units}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.debug("%s → %s: %d units", text.celt_id, work.work_id, len(units))
        works.append(work)
    log.info("CELT (Old Irish): %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main

    ingestor_main(ingest, SOURCE_ID)
