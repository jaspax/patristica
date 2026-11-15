"""
Ingestor for the English translations on Roger Pearse's *Early Church Fathers –
Additional Texts* (https://www.tertullian.org/fathers/, #347).

Source: the pages listed in :data:`TEXTS`, cached in
``data/raw/_cache/tertullian-org/`` (shared with ``pearse_arabic``)
Output: ``data/raw/tertullian-eng/{slug}.json``
Language: eng  License: public_domain

Each page ends "All material on this page is in the public domain - copy
freely": the transcriptions are of translations published before 1931
(Library of the Fathers, SPCK *Translations of Christian Literature*, Bohn,
Hakluyt Society, Wright's *Apocryphal Acts*, …) or of translations Pearse
commissioned and placed in the public domain.  Each work's ``edition`` names
the translator, the series and the date.

One work per translated text, ``translation_of`` its original in the corpus
(the critical edition where there is one, as ``patristica.anchor_rule`` would
anchor on it), so the translations are anchored on their originals (#638).
Refs are ``{prefix}.{section}.{n}``: the section is the page's (a book, a
letter group), ``n`` the block's place in it (``_tertullian_org``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup

from patristica.models import Work
from scripts.ingest._tertullian_org import (
    Block,
    Notes,
    Renderer,
    TertullianParseError,
    Unit,
    blocks,
    decode,
    fetch,
    heading_kind,
    is_noise,
    page_url,
    segment_words,
)

log = logging.getLogger(__name__)

SOURCE_ID = "tertullian-eng"


@dataclass(frozen=True)
class PageSpec:
    """One page of a text, and which part of it is the text."""

    file: str
    section: str | None = None          # ref section; None: refs are {prefix}.{n}
    segments: tuple[int, ...] | None = None   # <hr> segments holding the text (default: largest)
    start: str | None = None            # regex on a unit: the text starts there (inclusive)
    stop: str | None = None             # regex on a unit: the text ends before it


@dataclass(frozen=True)
class Text:
    slug: str
    title: str
    author: str | None
    edition: str
    translation_of: str | None
    prefix: str
    pages: tuple[PageSpec, ...]
    date_composed: int | None = None
    date_range: tuple[int, int] | None = None
    date_confidence: str = "uncertain"
    genre: str = "patristic"
    tradition: str | None = "greek"
    note_pages: tuple[str, ...] = ()    # pages holding the footnotes of the text
    table_text: bool = False            # table cells are text (else short ones are headings)
    strip: tuple[str, ...] = ()         # regexes for layout noise in the text (page numbers)
    bracket_notes: bool = False         # [bracketed] remarks in the text are the translator's notes
    english_only: bool = False          # the page interleaves the original: keep the English


_LF = "Library of Fathers of the Holy Catholic Church"
_SPCK = "Translations of Christian Literature (London: SPCK)"


def _tx(slug, title, author, edition, translation_of, prefix, pages, dates, **kw) -> Text:
    dc, dr, conf = dates
    return Text(slug, title, author, edition, translation_of, prefix, pages,
                date_composed=dc, date_range=dr, date_confidence=conf, **kw)


def _span(first: int, last: int) -> tuple[int, ...]:
    return tuple(range(first, last + 1))


TEXTS: tuple[Text, ...] = (
    # ---- Greek ------------------------------------------------------------
    _tx("eusebius-praeparatio-evangelica", "Preparation for the Gospel (Praeparatio evangelica)",
        "Eusebius of Caesarea",
        "E. H. Gifford, Eusebii Pamphili Evangelicae Praeparationis Libri XV, vol. 3 "
        "(Oxford: Clarendon Press, 1903); transcribed by Peter Kirby and Roger Pearse "
        "(tertullian.org, 2003)",
        "first1k/tlg2018/tlg001/1st1K-grc1", "EusPE",
        tuple(PageSpec(f"eusebius_pe_{b:02d}_book{b}.htm", str(b)) for b in range(1, 16)),
        (318, (313, 320), "approximate")),
    _tx("eusebius-demonstratio-evangelica", "The Proof of the Gospel (Demonstratio evangelica)",
        "Eusebius of Caesarea",
        f"W. J. Ferrar, The Proof of the Gospel, 2 vols. ({_SPCK}, 1920), books 1–10 (all that "
        "survives); transcribed by Peter Kirby and Roger Pearse (tertullian.org, 2002)",
        "first1k/tlg2018/tlg005/1st1K-grc1", "EusDE",
        tuple(PageSpec(f"eusebius_de_{b + 2:02d}_book{b}.htm", str(b)) for b in range(1, 11)),
        (320, (315, 325), "approximate")),
    _tx("eusebius-contra-hieroclem", "Against Hierocles (Contra Hieroclem)", "Eusebius of Caesarea",
        "F. C. Conybeare, in Philostratus, The Life of Apollonius of Tyana, vol. 2 (Loeb "
        "Classical Library, London: Heinemann, 1912); transcribed by Roger Pearse "
        "(tertullian.org, 2002)",
        "ogpg/vol-022/contra-hieroclem", "EusHier",
        (PageSpec("eusebius_against_hierocles.htm"),),
        (310, (303, 315), "uncertain")),
    _tx("eusebius-theophania", "Theophania", "Eusebius of Caesarea",
        "Samuel Lee, Eusebius, Bishop of Caesarea, on the Theophania or Divine Manifestation of "
        "our Lord and Saviour Jesus Christ, translated from an ancient Syriac version "
        "(Cambridge, 1843); transcribed by Roger Pearse (tertullian.org, 2002)",
        "dsc/eusebius-theophania", "EusTheoph",
        tuple(PageSpec(f"eusebius_theophania_{b + 1:02d}book{b}.htm", str(b)) for b in range(1, 6)),
        (333, (325, 337), "approximate"), tradition="syriac"),
    _tx("eusebius-chronicon-1", "Chronicle, book 1", "Eusebius of Caesarea",
        "Robert Bedrosian, Eusebius' Chronicle (Sources of the Armenian Tradition, Long Branch, "
        "NJ, 2008), book 1, translated from the classical Armenian version (a translation of a "
        "translation: the Greek original of book 1 is lost); placed in the public domain by "
        "the translator; formatted by Roger Pearse (tertullian.org, 2009)",
        "ogpg/vol-019/chronicon", "EusChron",
        (PageSpec("eusebius_chronicon_02_text.htm", segments=_span(1, 119)),),
        (311, (300, 325), "approximate"),
        strip=(r"\[g\d+\]", r"\[\d+\]")),   # Armenian and English page numbers
    _tx("cyril-in-joannem-1", "Commentary on the Gospel of John, books 1–6", "Cyril of Alexandria",
        f"P. E. Pusey, Commentary on the Gospel according to S. John by S. Cyril, vol. 1 ({_LF} "
        "43, Oxford: James Parker, 1874); transcribed by Roger Pearse (tertullian.org, 2005)",
        "ogpg/vol-073/in-joannem-1", "CyrJo",
        (PageSpec("cyril_on_john_00_praefatio.htm", "praef"),
         *(PageSpec(f"cyril_on_john_{b:02d}_book{b}.htm", str(b)) for b in range(1, 6)),
         PageSpec("cyril_on_john_06_book6.htm", "6", segments=(2, 3))),
        (428, (425, 429), "approximate")),
    _tx("cyril-in-joannem-2", "Commentary on the Gospel of John, books 7–12", "Cyril of Alexandria",
        f"T. Randell, Commentary on the Gospel according to S. John by S. Cyril, vol. 2 ({_LF} "
        "48, London: Walter Smith, 1885); books 7–8 survive in fragments; transcribed by Roger "
        "Pearse (tertullian.org, 2005)",
        "ogpg/vol-074/in-joannem-2", "CyrJo",
        tuple(PageSpec(f"cyril_on_john_{b:02d}_book{b}.htm", str(b)) for b in range(7, 13)),
        (428, (425, 429), "approximate")),
    _tx("cyril-adversus-nestorium", "Five Tomes against Nestorius (Adversus Nestorium)",
        "Cyril of Alexandria",
        f"P. E. Pusey, S. Cyril, Archbishop of Alexandria: That the Christ is One, … Five Tomes "
        f"against Nestorius ({_LF} 47, Oxford: James Parker, 1881); transcribed by Roger Pearse "
        "(tertullian.org, 2005)",
        "ogpg/vol-076/adversus-nestorium", "CyrNest",
        tuple(PageSpec(f"cyril_against_nestorius_{b:02d}_book{b}.htm", str(b))
              for b in range(1, 6)),
        (430, (430, 430), "approximate")),
    _tx("cyril-quod-unus-sit-christus", "That Christ is One (Quod unus sit Christus)",
        "Cyril of Alexandria",
        f"P. E. Pusey ({_LF} 47, Oxford: James Parker, 1881), pp. 237–319; transcribed by Roger "
        "Pearse (tertullian.org, 2005)",
        "ogpg/vol-075/quod-unus-sit-christus", "CyrUnus",
        (PageSpec("cyril_christ_is_one_01_text.htm"),),
        (437, (435, 438), "approximate")),
    _tx("cyril-scholia-de-incarnatione", "Scholia on the Incarnation of the Only-Begotten",
        "Cyril of Alexandria",
        f"P. E. Pusey ({_LF} 47, Oxford: James Parker, 1881), pp. 185–236, from the Greek where "
        "it survives and the old Latin version elsewhere; transcribed by Roger Pearse "
        "(tertullian.org, 2005)",
        "oglt-pl/cyrillus-alexandrinus/pl48_20_sa", "CyrSchol",
        (PageSpec("cyril_scholia_incarnation_01_text.htm"),),
        (435, (430, 440), "approximate")),
    _tx("origen-philocalia", "The Philocalia of Origen", "Origen",
        "George Lewis, The Philocalia of Origen (Edinburgh: T. & T. Clark, 1911); transcribed by "
        "Roger Pearse (tertullian.org, 2003)",
        "first1k/tlg2042/tlg019/1st1K-grc1", "OrPhil",
        (PageSpec("origen_philocalia_02_text.htm"),),
        (None, (358, 364), "uncertain"), note_pages=("origen_philocalia_02_text_fn.htm",)),
    _tx("evagrius-historia-ecclesiastica", "Ecclesiastical History", "Evagrius Scholasticus",
        "E. Walford, The Ecclesiastical History of Evagrius (Bohn's Ecclesiastical Library, "
        "London: Samuel Bagster, 1846); transcribed by Roger Pearse (tertullian.org, 2002)",
        "first1k/tlg2733/tlg001/1st1K-grc1", "EvagrHE",
        tuple(PageSpec(f"evagrius_{b}_book{b}.htm", str(b)) for b in range(1, 7)),
        (594, (593, 594), "approximate")),
    _tx("philostorgius-historia-ecclesiastica",
        "Ecclesiastical History (epitome by Photius)", "Philostorgius",
        "E. Walford, The Ecclesiastical History of Philostorgius, as epitomized by Photius "
        "(Bohn's Ecclesiastical Library, London: Henry G. Bohn, 1855); transcribed by Roger "
        "Pearse (tertullian.org, 2002)",
        "first1k/tlg2058/tlg001/1st1K-grc1", "Philost",
        (PageSpec("philostorgius.htm", segments=_span(5, 17)),),
        (430, (425, 433), "approximate"), note_pages=("philostorgius_fn.htm",)),
    _tx("palladius-historia-lausiaca", "The Lausiac History", "Palladius of Helenopolis",
        f"W. K. Lowther Clarke, The Lausiac History of Palladius ({_SPCK}, 1918); transcribed "
        "by Roger Pearse (tertullian.org, 2003)",
        "ogpg/vol-034/historia-lausiaca", "PallHL",
        (PageSpec("palladius_lausiac_02_text.htm"),),
        (420, (419, 420), "approximate")),
    _tx("palladius-dialogus", "Dialogue on the Life of St John Chrysostom",
        "Palladius of Helenopolis",
        f"Herbert Moore, The Dialogue of Palladius concerning the Life of Chrysostom ({_SPCK}, "
        "1921); transcribed by Roger Pearse (tertullian.org, 2006)",
        "ogpg/vol-047/palladius-dialogus", "PallDial",
        (PageSpec("palladius_dialogus_02_text.htm"),),
        (408, (407, 408), "approximate"), note_pages=("palladius_dialogus_03_footnotes.htm",)),
    _tx("gregory-nyssa-vita-macrinae", "The Life of St Macrina", "Gregory of Nyssa",
        f"W. K. Lowther Clarke, St. Gregory of Nyssa: The Life of St. Macrina ({_SPCK}, 1916); "
        "transcribed by Roger Pearse (tertullian.org, 2003)",
        "ogpg/vol-046/vita-macrinae", "GrNyssMacr",
        (PageSpec("gregory_macrina_1_life.htm"),),
        (381, (380, 383), "approximate"), strip=(r"\[\d{3,4}[A-D]\]",)),   # Migne columns
    _tx("cosmas-topographia", "Christian Topography", "Cosmas Indicopleustes",
        "J. W. McCrindle, The Christian Topography of Cosmas, an Egyptian Monk (London: Hakluyt "
        "Society, 1897); transcribed by Roger Pearse (tertullian.org, 2003)",
        "ogpg/vol-088/cosmas-topographia", "Cosmas",
        (PageSpec("cosmas_01_book1.htm", "1", segments=(1, 2)),
         *(PageSpec(f"cosmas_{b:02d}_book{b}.htm", str(b)) for b in range(2, 13))),
        (548, (545, 550), "approximate")),
    _tx("gregory-nazianzus-oratio-4", "Oration 4: First Invective against Julian",
        "Gregory of Nazianzus",
        "C. W. King, Julian the Emperor (Bohn's Classical Library, London: George Bell, 1888); "
        "transcribed by Roger Pearse (tertullian.org, 2003)",
        "ogpg/vol-035/oratio-4", "GrNazOr4",
        (PageSpec("gregory_nazianzen_2_oration4.htm"),),
        (363, (363, 364), "approximate")),
    _tx("gregory-nazianzus-oratio-5", "Oration 5: Second Invective against Julian",
        "Gregory of Nazianzus",
        "C. W. King, Julian the Emperor (Bohn's Classical Library, London: George Bell, 1888); "
        "transcribed by Roger Pearse (tertullian.org, 2003)",
        "ogpg/vol-035/oratio-5", "GrNazOr5",
        (PageSpec("gregory_nazianzen_3_oration5.htm"),),
        (363, (363, 364), "approximate")),
    *(_tx(f"dionysius-{slug}", title, "Pseudo-Dionysius the Areopagite",
          f"John Parker, The Works of Dionysius the Areopagite, vol. {vol} (London: James Parker, "
          f"{year}); transcribed by Roger Pearse (tertullian.org, 2004)",
          f"ogpg/vol-003/{orig}", prefix, (PageSpec(page, stop=stop),),
          (500, (480, 530), "approximate"))
      for slug, title, vol, year, orig, prefix, page, stop in (
          ("divine-names", "The Divine Names", 1, 1897, "de-divinis-nominibus", "DionDN",
           "areopagite_03_divine_names.htm", r"^27 October, 1896"),
          ("mystical-theology", "The Mystical Theology", 1, 1897, "de-mystica-theologia",
           "DionMT", "areopagite_06_mystic_theology.htm", None),
          ("letters", "Letters", 1, 1897, "epistulae", "DionEp", "areopagite_08_letters.htm", None),
          ("celestial-hierarchy", "The Celestial Hierarchy", 2, 1899, "de-caelesti-hierarchia",
           "DionCH", "areopagite_13_heavenly_hierarchy.htm", r"^St\. Michael and All Angels"),
          ("ecclesiastical-hierarchy", "The Ecclesiastical Hierarchy", 2, 1899,
           "de-ecclesiastica-hierarchia", "DionEH", "areopagite_14_ecclesiastical_hierarchy.htm",
           r"^JOHN PARKER\.$"),
      )),
    _tx("basil-ad-adolescentes", "Address to Young Men on the Right Use of Greek Literature",
        "Basil of Caesarea",
        "F. M. Padelford, Essays on the Study and Use of Poetry by Plutarch and Basil the Great "
        "(Yale Studies in English 15, New York: Henry Holt, 1902); transcribed by Roger Pearse "
        "(tertullian.org, 2002)",
        "perseus/tlg2040/tlg002/perseus-grc2", "BasAdol",
        (PageSpec("basil_litterature01.htm", start=r"^I\. Many considerations"),),
        (None, None, "uncertain")),
    _tx("chrysostom-in-kalendas", "On the Kalends of January (In Kalendas)", "John Chrysostom",
        "Seumas Macdonald, commissioned by Roger Pearse and placed in the public domain "
        "(tertullian.org, 2010)",
        "ogpg/vol-048/in-kalendas", "ChrysKal",
        (PageSpec("chrysostom_in_kalendas.htm"),),
        (387, (387, 388), "approximate")),
    _tx("chrysostom-in-natalem-christi", "On the Birthday of our Saviour Jesus Christ",
        "John Chrysostom",
        "Bryson Sewell, from the text of PG 56, 385–396, commissioned by Roger Pearse and placed "
        "in the public domain (tertullian.org, 2013)",
        "ogpg/vol-056/in-natalem-christi", "ChrysNat",
        (PageSpec("chrysostom_homily_2_on_christmas.htm"),),
        (386, (386, 388), "approximate")),
    _tx("chrysostom-contra-ludos", "Against the Circuses and the Theatre (Contra ludos et theatra)",
        "John Chrysostom",
        "Mark Vermes, from the text of PG 56, 263–270, commissioned by Roger Pearse and placed "
        "in the public domain (tertullian.org, 2012)",
        "ogpg/vol-056/contra-ludos", "ChrysLud",
        (PageSpec("chrysostom_against_theatres_and_circuses.htm"),),
        (399, (399, 399), "approximate"), strip=(r"\[\d{3}\]",)),   # Migne columns
    _tx("chrysostom-de-lazaro", "Discourses on the Rich Man and Lazarus, 1–4", "John Chrysostom",
        "F. Allen, Four Discourses of Chrysostom, chiefly on the Parable of the Rich Man and "
        "Lazarus (London: Longmans, Green, 1869), discourses 1–4 of the 7; transcribed by "
        "Roger Pearse (tertullian.org, 2006)",
        "ogpg/vol-048/de-lazaro", "ChrysLaz",
        tuple(PageSpec(f"chrysostom_four_discourses_{b:02d}_discourse{b}.htm", str(b))
              for b in range(1, 5)),
        (388, (388, 389), "approximate")),
    _tx("asterius-homilies", "Sermons 1–5", "Asterius of Amasea",
        "Galusha Anderson and Edgar Johnson Goodspeed, Ancient Sermons for Modern Times by "
        "Asterius, Bishop of Amasia (New York: Pilgrim Press, 1904), five of the homilies; "
        "transcribed by Roger Pearse (tertullian.org, 2003)",
        "ogpg/vol-040/asterius-amasenus", "Aster",
        tuple(PageSpec(f"asterius_{b:02d}_sermon{b}.htm", str(b)) for b in range(1, 6)),
        (400, (380, 410), "approximate")),
    _tx("theodoret-in-romanos", "Commentary on Romans", "Theodoret of Cyrrhus",
        "Anonymous translation (signed E. B.) in The Christian Remembrancer 21 (1839) and "
        "following, the commentary on Romans only; transcribed by Roger Pearse "
        "(tertullian.org, 2013)",
        "ogpg/vol-082/in-epistulas-pauli", "ThdtRom",
        (PageSpec("theodoret_commentary_on_romans_01.htm", "1", start=r"^ARGUMENT\.$"),
         PageSpec("theodoret_commentary_on_romans_02.htm", "2")),
        (440, (430, 448), "approximate")),
    _tx("severian-in-cosmogoniam-1", "On the Creation of the World, sermon 1", "Severian of Gabala",
        "Roger Pearse (tertullian.org, 2010), placed in the public domain; a translation of a "
        "translation: made from the French of J. Bareille, Œuvres complètes de S. Jean "
        "Chrysostome (Paris, 1865), not from the Greek",
        "pta/pta0001/pta057/pta-grc1", "SevGen",
        (PageSpec("severian_of_gabala_genesis_01.htm"),),
        (402, (401, 404), "approximate")),
    # ---- Latin ------------------------------------------------------------
    _tx("jerome-chronicle", "Chronicle", "Jerome",
        "Roger Pearse, Andrew S. Jacobs and others, Jerome, Chronicle (tertullian.org, 2005), "
        "from R. Helm's edition (1956), placed in the public domain; the prefaces and the "
        "chronological tables, read row by row",
        "oglt-pl/hieronymus/pl27_0_", "HierChron",
        (PageSpec("jerome_chronicle_01_prefaces.htm", "pr", segments=(1,)),
         PageSpec("jerome_chronicle_02_part1.htm", "1"),
         PageSpec("jerome_chronicle_03_part2.htm", "2")),
        (380, (380, 381), "approximate"), tradition="latin", table_text=True),
    _tx("chronography-354-liberian-catalogue",
        "The Chronography of 354, part 13: the Bishops of Rome (Liberian Catalogue)", None,
        "English translation in Roger Pearse's online edition of The Chronography of 354 "
        "(tertullian.org, 2006), part 13, beside the Latin of T. Mommsen, MGH Chronica Minora I "
        "(1892), pp. 73–76; placed in the public domain",
        "oglt-pl/anonymus-chronographus-anni-354/pl13_12_an", "Chr354Lib",
        (PageSpec("chronography_of_354_13_bishops_of_rome.htm"),),
        (354, (354, 354), "approximate"), tradition="latin", table_text=True,
        english_only=True),
    _tx("pseudo-hegesippus-de-excidio", "On the Ruin of the City of Jerusalem (De excidio)",
        "Pseudo-Hegesippus",
        "Wade Blocker (tertullian.org, 2005), placed in the public domain",
        "oglt-pl/pseudo-hegesippus/pl15_1_san", "Heges",
        tuple(PageSpec(f"hegesippus_{b:02d}_book{b}.htm", str(b)) for b in range(1, 6)),
        (372, (370, 375), "approximate"), tradition="latin"),
    _tx("sidonius-letters", "Letters", "Sidonius Apollinaris",
        "O. M. Dalton, The Letters of Sidonius, 2 vols. (Oxford: Clarendon Press, 1915); "
        "transcribed by Roger Pearse (tertullian.org, 2003)",
        "oglt-pl/sidonius-apollinaris/pl58_11_a", "SidEp",
        tuple(PageSpec(f"sidonius_letters_{b:02d}book{b}.htm", str(b)) for b in range(1, 10)),
        (470, (455, 485), "approximate"), tradition="latin",
        note_pages=("sidonius_letters_10notes.htm",)),
    _tx("gregory-dialogues", "Dialogues", "Gregory the Great",
        "The Dialogues of Saint Gregory, translated by P. W. (Paris, 1608), re-edited by Edmund "
        "G. Gardner (London: Philip Lee Warner, 1911); transcribed by Roger Pearse "
        "(tertullian.org, 2004)",
        "oglt-pl/gregorius-i-magnus/pl77_5_san", "GregDial",
        tuple(PageSpec(f"gregory_{b:02d}_dialogues_book{b}.htm", str(b)) for b in range(1, 5)),
        (597, (590, 604), "approximate"), tradition="latin"),
    _tx("gregory-vita-benedicti", "The Life of St Benedict (Dialogues, book 2)",
        "Gregory the Great",
        "The Dialogues of Saint Gregory, translated by P. W. (Paris, 1608), re-edited by Edmund "
        "G. Gardner (London: Philip Lee Warner, 1911), book 2; transcribed by Roger Pearse "
        "(tertullian.org, 2004)",
        "oglt-pl/gregorius-i-magnus/pl66_0_unknown", "GregBen",
        (PageSpec("gregory_02_dialogues_book2.htm"),),
        (593, (593, 594), "approximate"), tradition="latin"),
    _tx("salvian-de-gubernatione-dei", "On the Government of God", "Salvian of Marseilles",
        "Eva M. Sanford, On the Government of God (Records of Civilization, New York: Columbia "
        "University Press, 1930); transcribed by Roger Pearse (tertullian.org, 2005)",
        "csel/stoa0249a/stoa002/opp-lat1", "SalvGub",
        tuple(PageSpec(f"salvian_gov_{b:02d}_book{b}.htm", str(b)) for b in range(1, 9)),
        (440, (439, 451), "approximate"), tradition="latin"),
    _tx("jerome-in-danielem", "Commentary on Daniel", "Jerome",
        "Gleason L. Archer, Jerome's Commentary on Daniel (Grand Rapids: Baker Book House, "
        "1958), from the text of PL 25; the publisher (Baker Publishing Group) states the text "
        "is in the public domain; transcribed by Roger Pearse (tertullian.org, 2004)",
        "oglt-pl/hieronymus/pl25_1_unknown", "HierDan",
        (PageSpec("jerome_daniel_02_text.htm"),),
        (407, (407, 407), "approximate"), tradition="latin", bracket_notes=True,
        # Archer's page and Migne column numbers and section letters
        strip=(r"\(\s*(?:[Pp]\.\s*)?\d{2,4}(?:\s*-\s*\d{2,4})?\s*\)", r"\([A-D]\)")),
    _tx("optatus-contra-parmenianum", "Against the Donatists, books 1–7", "Optatus of Milevis",
        "O. R. Vassall-Phillips, The Work of St. Optatus, Bishop of Milevis, against the "
        "Donatists (London: Longmans, Green, 1917); transcribed by Roger Pearse "
        "(tertullian.org, 2006)",
        "csel/stoa0215a/stoa001/opp-lat1", "OptPar",
        (PageSpec("optatus_01_book1.htm", "1", segments=(2,)),
         *(PageSpec(f"optatus_{b:02d}_book{b}.htm", str(b)) for b in range(2, 8))),
        (367, (364, 385), "approximate"), tradition="latin"),
    _tx("optatus-appendix", "Against the Donatists: the appendix of documents",
        "Optatus of Milevis",
        "O. R. Vassall-Phillips, The Work of St. Optatus, Bishop of Milevis, against the "
        "Donatists (London: Longmans, Green, 1917), appendices 1–16; transcribed by Roger "
        "Pearse (tertullian.org, 2006)",
        "csel/stoa0215a/stoa002/opp-lat1", "OptApp",
        (PageSpec("optatus_09_appendix1.htm", "1", segments=(2,)),
         PageSpec("optatus_10_appendix2.htm", "2", segments=(2,)),
         PageSpec("optatus_11_appendices.htm", "3", segments=tuple(range(3, 30, 2)))),
        (None, None, "uncertain"), tradition="latin"),
    _tx("ambrose-letters-1-63", "Letters 1–63", "Ambrose of Milan",
        f"The Letters of S. Ambrose, Bishop of Milan ({_LF} 45, Oxford: James Parker, 1881), "
        "letters 1–63 (the first class); transcribed by Roger Pearse (tertullian.org, 2004)",
        "oglt-pl/ambrosius/pl16_19_sa", "AmbrEp",
        (PageSpec("ambrose_letters_01_letters01_10.htm", "1"),
         PageSpec("ambrose_letters_02_letters11_20.htm", "2", stop=r"^THE MEMORIAL OF SYMMACHUS"),
         PageSpec("ambrose_letters_02_letters11_20.htm", "2", start=r"^LETTER XVIII\b"),
         *(PageSpec(f"ambrose_letters_{p:02d}_letters{a}_{a + 9}.htm", str(p))
           for p, a in ((3, 21), (4, 31), (5, 41), (6, 51))),
         PageSpec("ambrose_letters_07_letters61_70.htm", "7", stop=r"^LETTER LXIV\b")),
        (385, (374, 397), "approximate"), tradition="latin"),
    _tx("ambrose-letters-64-91", "Letters 64–91", "Ambrose of Milan",
        f"The Letters of S. Ambrose, Bishop of Milan ({_LF} 45, Oxford: James Parker, 1881), "
        "letters 64–91 (the second class); transcribed by Roger Pearse (tertullian.org, 2004)",
        "oglt-pl/ambrosius/pl16_20_se", "AmbrEp",
        (PageSpec("ambrose_letters_07_letters61_70.htm", "7", start=r"^LETTER LXIV\b"),
         PageSpec("ambrose_letters_08_letters71_80.htm", "8"),
         PageSpec("ambrose_letters_09_letters81_91.htm", "9")),
        (385, (374, 397), "approximate"), tradition="latin"),
    _tx("symmachus-relatio-3", "The Memorial of Symmachus, Prefect of the City (Relatio 3)",
        "Symmachus",
        f"The Letters of S. Ambrose, Bishop of Milan ({_LF} 45, Oxford: James Parker, 1881), "
        "pp. 94 ff., printed between Ambrose's letters 17 and 18; transcribed by Roger Pearse "
        "(tertullian.org, 2004)",
        "oglt-pl/symmachus/pl18_12_q.", "SymmRel3",
        (PageSpec("ambrose_letters_02_letters11_20.htm", start=r"^THE MEMORIAL OF SYMMACHUS",
                  stop=r"^LETTER XVIII\b"),),
        (384, (384, 384), "established"), tradition="latin"),
    _tx("pacian-letters", "Letters to Sympronian", "Pacian of Barcelona",
        f"C. H. Collyns, The Extant Works of S. Pacian ({_LF} 17, Oxford: John Henry Parker, "
        "1842), letters 1–3; transcribed by Roger Pearse (tertullian.org, 2004)",
        "oglt-pl/pacianus-barcinonensis/pl13_33_sa", "PacEp",
        tuple(PageSpec(f"pacian_{b}_letter{b}.htm", str(b)) for b in range(1, 4)),
        (375, (360, 390), "approximate"), tradition="latin"),
    _tx("eugippius-vita-severini", "The Life of St Severinus", "Eugippius",
        "George W. Robinson, Eugippius: The Life of Saint Severin (Cambridge, Mass.: Harvard "
        "University Press, 1914); transcribed by Roger Pearse (tertullian.org, 2004)",
        "csel/stoa0119/stoa001/opp-lat2", "EugSev",
        (PageSpec("severinus_02_text.htm", segments=(4, 5, 7)),),
        (511, (509, 511), "approximate"), tradition="latin"),
    _tx("isidore-chronicon", "Chronicle", "Isidore of Seville",
        "Kenneth B. Wolf (2004), from the text of PL 83, placed in the public domain by the "
        "translator; published by Roger Pearse (tertullian.org, 2004)",
        "oglt-pl/isidorus-hispalensis/pl83_20_sa", "IsidChron",
        (PageSpec("isidore_chronicon_01_trans.htm"),),
        (618, (600, 636), "approximate"), tradition="latin"),
    _tx("chromatius-in-matthaeum-prologus", "Sermons on the Gospel of Matthew: prologue",
        "Chromatius of Aquileia",
        "Stephen C. Carlson (2005), the prologue only, placed in the public domain by the "
        "translator (tertullian.org)",
        "oglt-pl/chromatius-aquileiensis/pl20_6_sanctichromatiiaqu", "ChromMt",
        (PageSpec("chromatius_prologue_matthew_01.htm"),),
        (397, (388, 407), "approximate"), tradition="latin"),
    _tx("gildas-de-excidio", "The Ruin of Britain (De excidio Britanniae)", "Gildas",
        "Hugh Williams, Gildas (Cymmrodorion Record Series 3, London, 1899); transcribed by "
        "Roger Pearse (tertullian.org, 2003)",
        "oglt-pl/gildas/pl69_5_gil", "Gildas",
        (PageSpec("gildas_02_ruin_of_britain.htm"),),
        (545, (520, 570), "approximate"), tradition="latin"),
    # ---- Syriac -----------------------------------------------------------
    _tx("nestorius-bazaar-of-heracleides", "The Bazaar of Heracleides", "Nestorius",
        "G. R. Driver and Leonard Hodgson, Nestorius: The Bazaar of Heracleides (Oxford: "
        "Clarendon Press, 1925), translated from the Syriac; transcribed by Roger Pearse "
        "(tertullian.org, 2006)",
        "dsc/nestorius-book-of-heraclides", "NestHer",
        (PageSpec("nestorius_bazaar_1_book1_part1.htm", "1", segments=(3, 4)),
         PageSpec("nestorius_bazaar_2_book1_part2.htm", "2"),
         PageSpec("nestorius_bazaar_3_book1_part3.htm", "3"),
         PageSpec("nestorius_bazaar_4_book2_part1.htm", "4"),
         PageSpec("nestorius_bazaar_5_book2_part2.htm", "5")),
        (451, (450, 451), "approximate"), tradition="syriac"),
    _tx("philoxenus-discourses", "Ascetic Discourses", "Philoxenus of Mabbug",
        "E. A. Wallis Budge, The Discourses of Philoxenus, Bishop of Mabbôgh, vol. 2 (London: "
        "Asher, 1894); transcribed by Roger Pearse (tertullian.org, 2003)",
        "dsc/philoxenus-discourses", "Philox",
        tuple(PageSpec(f"philoxenus_discourse{b:02d}.htm", str(b)) for b in range(1, 14)),
        (None, None, "uncertain"), tradition="syriac", strip=(r"\[Page \d+\],?",)),
    _tx("ephrem-prose-refutations", "Prose Refutations of Mani, Marcion and Bardaisan",
        "Ephrem the Syrian",
        "C. W. Mitchell, S. Ephraim's Prose Refutations of Mani, Marcion and Bardaisan, 2 vols. "
        "(Text and Translation Society, London: Williams and Norgate, 1912–1921; vol. 2 "
        "completed by A. A. Bevan and F. C. Burkitt); transcribed by Roger Pearse "
        "(tertullian.org, 2002)",
        "dsc/ephrem-prose-refutations", "EphrRef",
        (*(PageSpec(f"ephraim1_{b}_hypatius{b}.htm", f"h{b}") for b in range(1, 6)),
         PageSpec("ephraim2_1_bardesan.htm", "domnus"),
         PageSpec("ephraim2_2_marcion1.htm", "marc1"),
         PageSpec("ephraim2_3_marcion2.htm", "marc2"),
         PageSpec("ephraim2_4_marcion3.htm", "marc3"),
         PageSpec("ephraim2_5_bardaisan.htm", "bard"),
         PageSpec("ephraim2_6_virginity.htm", "virg"),
         PageSpec("ephraim2_7_mani.htm", "mani")),
        (None, None, "uncertain"), tradition="syriac"),
    _tx("chronicle-of-pseudo-joshua", "The Chronicle of Joshua the Stylite", None,
        "William Wright, The Chronicle of Joshua the Stylite, composed in Syriac A.D. 507 "
        "(Cambridge: University Press, 1882); transcribed by Roger Pearse (tertullian.org, 2006)",
        "dsc/chronicle-of-pseudo-joshua", "PsJosh",
        (PageSpec("joshua_the_stylite_02_trans.htm"),),
        (507, (506, 507), "established"), tradition="syriac"),
    _tx("chronicle-of-edessa", "The Chronicle of Edessa", None,
        "B. Harris Cowper, The Journal of Sacred Literature, 4th series, vol. 5 (1864), "
        "pp. 28–45; transcribed by Roger Pearse (tertullian.org, 2003)",
        "dsc/chronicle-of-edessa", "ChrEdes",
        (PageSpec("chronicle_of_edessa.htm", start=r"^\[Translation\.\]$"),),
        (545, (540, 550), "approximate"), tradition="syriac"),
    *(_tx(slug, title, None,
          "William Wright, Apocryphal Acts of the Apostles, vol. 2: The English Translation "
          "(London: Williams and Norgate, 1871); transcribed by Colin Tunnicliffe "
          "(tertullian.org, 2004)",
          orig, prefix, (spec,), dates, tradition="syriac", genre="apocrypha")
      for slug, title, orig, prefix, spec, dates in (
          ("history-of-john", "The History of John, the Son of Zebedee", "dsc/history-of-john",
           "HistJohn", PageSpec("apocryphal_acts_02_john_history.htm"),
           (450, (400, 500), "uncertain")),
          ("decease-of-john", "An Account of the Decease of Saint John", "dsc/decease-of-john",
           "DecJohn", PageSpec("apocryphal_acts_03_john_decease.htm"),
           (400, (300, 500), "uncertain")),
          ("history-of-philip", "The History of Philip, the Apostle and Evangelist",
           "dsc/history-of-philip", "HistPhil", PageSpec("apocryphal_acts_04_philip.htm"),
           (500, (400, 600), "uncertain")),
          ("hymn-of-the-soul", "The Hymn of the Soul (from the Acts of Judas Thomas)",
           "dsc/hymn-of-the-soul", "HymnSoul",
           PageSpec("apocryphal_acts_07_judas_thomas.htm", start=r"^The Hymn of Judas Thomas",
                    stop=r"^The Song of praise of Thomas"),
           (225, (200, 250), "approximate")),
      )),
    _tx("rabbula-admonitions", "Admonitions to Monks", "Rabbula of Edessa",
        "R. H. Connolly, 'Some Early Rules for Syrian Monks', The Downside Review 25 (1907), "
        "pp. 152–162, the admonitions only; transcribed by Roger Pearse (tertullian.org, 2005)",
        "dsc/rabbula-corpus", "RabbAdm",
        (PageSpec("rabbula_some_early_rules.htm", start=r"^Admonitions concerning Monks",
                  stop=r"^This short, and purely occasional"),),
        (None, None, "uncertain"), tradition="syriac"),
)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def _soup_blocks(raw_dir: Path, file: str, force: bool) -> list[Block]:
    path = fetch(file, raw_dir, force=force)
    soup = BeautifulSoup(decode(path.read_bytes()), "lxml")
    if soup.body is None:
        raise TertullianParseError(f"{file}: no <body>")
    return blocks(soup.body, file)


def text_units(text: Text, raw_dir: Path, force: bool = False) -> list[tuple[str, Unit]]:
    """``[(ref, unit)]`` of one text."""
    page_blocks = {p.file: _soup_blocks(raw_dir, p.file, force) for p in text.pages}
    notes = Notes()
    for f in text.note_pages:
        notes.add_page(_soup_blocks(raw_dir, f, force))
    for bs in page_blocks.values():
        notes.add_page(bs)
    renderer = Renderer(notes, strip=text.strip)

    rendered: list[tuple[PageSpec, Block, Unit]] = []
    for spec in text.pages:
        bs = page_blocks[spec.file]
        if spec.segments is not None:
            segs = set(spec.segments)
        else:
            words = segment_words(bs)
            segs = {max(words, key=lambda s: words[s])}
        started = spec.start is None
        for b in bs:
            if b.segment not in segs or is_noise(b):
                continue
            unit = renderer.unit(b)
            if not unit.text:
                continue
            if not started:
                if not re.search(spec.start, unit.text):
                    continue
                started = True
            if spec.stop is not None and re.search(spec.stop, unit.text):
                break
            if text.english_only and not _is_english(unit.text):
                continue
            kind = heading_kind(b, unit)
            if (not kind and not text.table_text and len(unit.text) < 400
                    and _in_table(b)):
                kind = "heading"   # a table of contents, a margin summary
            if kind:
                unit = Unit(unit.text, [[0, len(unit.text), kind]])
            rendered.append((spec, b, unit))
        if not started:
            raise TertullianParseError(f"{text.slug}: {spec.file}: start {spec.start!r} not found")

    if renderer.missing:
        log.debug("%s: %d note markers without a note: %s", text.slug, len(renderer.missing),
                  renderer.missing[:10])
    if text.bracket_notes:
        rendered = [(spec, b, _bracket_notes(unit)) for spec, b, unit in rendered]
    out: list[tuple[str, Unit]] = []
    counters: dict[str | None, int] = {}
    for spec, b, unit in rendered:
        if id(b) in notes.used:
            continue
        n = counters[spec.section] = counters.get(spec.section, 0) + 1
        ref = (f"{text.prefix}.{spec.section}.{n}" if spec.section is not None
               else f"{text.prefix}.{n}")
        out.append((ref, unit))
    refs = [r for r, _ in out]
    if len(set(refs)) != len(refs):
        raise TertullianParseError(f"{text.slug}: duplicate refs")
    if not any(not u.editorial_only for _, u in out):
        raise TertullianParseError(f"{text.slug}: no text")
    return out


_ENG_WORDS = frozenset("the of and he was to from being that with his years months days".split())
_LAT_WORDS = frozenset("et fuit est ex usque cum ad qui quae non sed eius ann annos mens".split())


def _is_english(text: str) -> bool:
    words = re.findall(r"[a-z]+", text.lower())
    return sum(w in _ENG_WORDS for w in words) > sum(w in _LAT_WORDS for w in words)


_BRACKET_RE = re.compile(r"\[[^\[\]]+\]")


def _bracket_notes(unit: Unit) -> Unit:
    """*unit* with its bracketed remarks marked ``note`` (outside existing spans)."""
    if unit.editorial_only:
        return unit
    spans = list(unit.spans)
    for m in _BRACKET_RE.finditer(unit.text):
        if not any(s < m.end() and m.start() < e for s, e, _ in unit.spans):
            spans.append([m.start(), m.end(), "note"])
    return Unit(unit.text, sorted(spans))


def _in_table(b: Block) -> bool:
    node = b.nodes[0]
    return any(getattr(p, "name", None) in {"td", "th"} for p in [node, *node.parents])


def work(text: Text) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{text.slug}",
        source_id=SOURCE_ID,
        author=text.author,
        title=text.title,
        date_composed=text.date_composed,
        date_range=text.date_range,
        date_confidence=text.date_confidence,
        genre=text.genre,
        language="eng",
        tradition=text.tradition,
        license="public_domain",
        provenance_url=page_url(text.pages[0].file),
        edition=text.edition,
        translation_of=text.translation_of,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    works: list[Work] = []
    for text in TEXTS:
        out_path = out_dir / f"{text.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        units = text_units(text, output_dir, force=False)
        w = work(text)
        out_path.write_text(
            json.dumps({"work": w.model_dump(),
                        "paragraphs": [u.record(ref) for ref, u in units]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("%s: %d paragraphs", w.work_id, len(units))
        works.append(w)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
