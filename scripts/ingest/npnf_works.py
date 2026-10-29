"""
Ingestor for properly attributed works carved out of the CCEL Nicene and
Post-Nicene Fathers, Series 1 and 2.

Source: CCEL NPNF Series 1 Vols. 1–14 and Series 2 Vols. 1–14 (ed. Schaff and
        Wace, 1886–1900)  https://ccel.org/ccel/s/schaff/npnf{1,2}{01..14}.xml
License: Public domain
Language: eng

The generic ``ccel_npnf1`` / ``ccel_npnf2`` ingestors emit one Work per ThML
``<div1>``.  In nearly every volume the div1 is a section of the printed book
rather than a work — "Doctrinal Treatises of St. Augustin", "Dogmatic
Treatises", "Selected Epistles" — and its heading is either a running title
or missing, so the Work came out titled "NPNF Series 1 Vol. 3 Part 4" with no
author.  This module re-emits the text as one Work per distinct work (one per
treatise, homily series, letter collection or oration) with its own title,
author, date and tradition, driven by the ``_WORKS`` table below; the
collection identity survives only in ``Work.edition`` ("NPNF Series 2 Vol. 4").

Every div taken here is registered in ``_ccel_common.EXCLUDED_DIVS`` (value
``"npnf-works"``); title pages, contents, indexes and the editors'
apparatus are registered there as ``"non-text: …"``.  With both in place the
generic NPNF ingestors produce no Works at all.  Councils in NPNF2 Vol. 14 are
owned by ``ecumenical``; only its appendix of canonical epistles is
taken here.  Extraction mechanics are in ``_ccel_works``.

Output: ``data/raw/npnf-works/{volume}/{slug}.json``; work_id
``npnf-works/{slug}``.
"""

from __future__ import annotations

import logging
from pathlib import Path

from patristica.models import Work
from scripts.ingest._ccel_works import P, W, _WorkSpec, ingest_table, link_originals

log = logging.getLogger(__name__)

SOURCE_ID = "npnf-works"

_AUG = "Augustine of Hippo"
_CHRYS = "John Chrysostom"
_ATH = "Athanasius of Alexandria"
_NYSS = "Gregory of Nyssa"
_NAZ = "Gregory of Nazianzus"
_RUF = "Rufinus of Aquileia"
_JER = "Jerome"
_AMB = "Ambrose of Milan"


def _aug(vol: str, slug: str, title: str, date: int | None, rng: tuple[int, int],
         prefix: str, *parts, conf: str = "approximate") -> _WorkSpec:
    return W(vol, f"augustine-{slug}", title, _AUG, date, rng, conf, "latin",
             f"Aug.{prefix}", *parts)


def _chrys(vol: str, slug: str, title: str, date: int | None, rng: tuple[int, int],
           prefix: str, *parts, conf: str = "approximate") -> _WorkSpec:
    return W(vol, f"chrysostom-{slug}", title, _CHRYS, date, rng, conf, "greek",
             f"Chrys.{prefix}", *parts)


def _ath(slug: str, title: str, date: int | None, rng: tuple[int, int], prefix: str,
         *parts, conf: str = "approximate") -> _WorkSpec:
    return W("npnf204", f"athanasius-{slug}", title, _ATH, date, rng, conf, "greek",
             f"Ath.{prefix}", *parts)


# Gregory Nazianzen, Select Orations (NPNF2 Vol. 7): (div, title check, oration
# number, title, date)
_NAZ_ORATIONS = (
    ("iii.iii", "On Easter and His Reluctance", 1, "Oration 1: On Easter and His Reluctance", 362),
    ("iii.iv", "Defence of His Flight", 2, "Oration 2: In Defence of His Flight to Pontus", 362),
    ("iii.v", "Had Invited Him", 3, "Oration 3: To Those Who Had Invited Him, and Not Come to Receive Him", 362),
    ("iii.vi", "Cæsarius", 7, "Oration 7: Panegyric on His Brother S. Caesarius", 369),
    ("iii.vii", "Gorgonia", 8, "Oration 8: On His Sister Gorgonia", 370),
    ("iii.viii", "To His Father", 12, "Oration 12: To His Father, When He Had Entrusted to Him the Care of the Church of Nazianzus", 372),
    ("iii.ix", "Plague of Hail", 16, "Oration 16: On His Father's Silence, Because of the Plague of Hail", 373),
    ("iii.x", "Death of His Father", 18, "Oration 18: On the Death of His Father", 374),
    ("iii.xi", "Athanasius", 21, "Oration 21: On the Great Athanasius, Bishop of Alexandria", 379),
    ("iii.xiii", "First Theological Oration", 27, "Oration 27: The First Theological Oration, Against the Eunomians", 380),
    ("iii.xiv", "Second Theological Oration", 28, "Oration 28: The Second Theological Oration", 380),
    ("iii.xv", "Third Theological Oration", 29, "Oration 29: The Third Theological Oration, On the Son", 380),
    ("iii.xvi", "Fourth Theological Oration", 30, "Oration 30: The Fourth Theological Oration, Second Concerning the Son", 380),
    ("iii.xvii", "Fifth Theological Oration", 31, "Oration 31: The Fifth Theological Oration, On the Holy Spirit", 380),
    ("iii.xviii", "Against The Arians", 33, "Oration 33: Against the Arians, and Concerning Himself", 379),
    ("iii.xix", "Arrival of the Egyptians", 34, "Oration 34: On the Arrival of the Egyptians", 380),
    ("iii.xx", "Finished These Sayings", 37, "Oration 37: On the Words of the Gospel, 'When Jesus Had Finished These Sayings'", 380),
    ("iii.xxi", "Theophany", 38, "Oration 38: On the Theophany, or Birthday of Christ", 380),
    ("iii.xxii", "Holy Lights", 39, "Oration 39: Oration on the Holy Lights", 381),
    ("iii.xxiii", "Holy Baptism", 40, "Oration 40: The Oration on Holy Baptism", 381),
    ("iii.xxiv", "Pentecost", 41, "Oration 41: On Pentecost", 379),
    ("iii.xxv", "Last Farewell", 42, "Oration 42: The Last Farewell in the Presence of the 150 Bishops", 381),
    ("iii.xxvi", "Funeral Oration on the Great S. Basil", 43, "Oration 43: Funeral Oration on the Great S. Basil", 381),
    ("iii.xxvii", "Second Oration on Easter", 45, "Oration 45: The Second Oration on Easter", 383),
)


def _roman(n: int) -> str:
    out = ""
    for value, numeral in ((90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
                           (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += numeral
            n -= value
    return out


# Containers split into works of their own (#380).  The pieces share the
# container's registered div and take or leave out its nested divs
# (``keep`` / ``skip``), so their refs are the container's.
#: Chrysostom on Matthew: CCEL div2s ``iii.XLV``-``iii.LXXXVI`` hold Homilies
#: XLV-XC, Migne's second volume (PG 58).
_MATT_PG58 = tuple(f"iii.{_roman(n)}" for n in range(45, 87))
#: Athanasius's personal letters (NPNF2 vol. 4, Letters XLVI-LXIV): div4 →
#: (slug, title, date, date range, ref prefix).  The rest (Letters XLVI-XLVII,
#: L-LI to Lucifer, LXIV to Diodorus, the Memorandum) stay in
#: ``athanasius-personal-letters``: their originals are not in the corpus.
_ATH_LETTERS = (
    ("xxv.iii.iv.iii", "letter-48-to-amun", "Letter XLVIII: To Amun", 354, (350, 354), "EpAmun"),
    ("xxv.iii.iv.iv", "letter-49-to-dracontius", "Letter XLIX: To Dracontius", 354,
     (354, 355), "EpDrac"),
    ("xxv.iii.iv.vii", "letter-52-first-to-monks", "Letter LII: First Letter to Monks", 358,
     (358, 360), "EpMon1"),
    ("xxv.iii.iv.viii", "letter-53-second-to-monks", "Letter LIII: Second Letter to Monks", 358,
     (358, 360), "EpMon2"),
    ("xxv.iii.iv.ix", "letter-54-to-serapion-on-the-death-of-arius",
     "Letter LIV: To Serapion, Concerning the Death of Arius", 358, (357, 359), "EpSerap"),
    ("xxv.iii.iv.x", "letter-55-to-rufinianus", "Letter LV: To Rufinianus", 362, (362, 363),
     "EpRuf"),
    ("xxv.iii.iv.xiv", "letter-59-to-epictetus", "Letter LIX: To Epictetus", 371, (370, 372),
     "EpEpict"),
    ("xxv.iii.iv.xv", "letter-60-to-adelphius", "Letter LX: To Adelphius", 371, (370, 372),
     "EpAdelph"),
    ("xxv.iii.iv.xvi", "letter-61-to-maximus", "Letter LXI: To Maximus the Philosopher", 371,
     (370, 372), "EpMax"),
    ("xxv.iii.iv.xvii", "letter-62-to-john-and-antiochus", "Letter LXII: To John and Antiochus",
     None, (335, 373), "EpJoh"),
    ("xxv.iii.iv.xviii", "letter-63-to-palladius", "Letter LXIII: To the Presbyter Palladius",
     372, (371, 372), "EpPall"),
)
_ATH_JOVIAN = "xxv.iii.iv.xi"      # Letter LVI with Jovian's letter, then the Arians' petitions
_ATH_ORSISIUS = ("xxv.iii.iv.xii", "xxv.iii.iv.xiii")   # Letters LVII-LVIII
#: Gregory of Nyssa's letter to Peter and Peter's reply, printed before Book I
#: of Against Eunomius (the first 12 paragraphs of ``viii.i``).
_NYSS_PETER = ("viii.i.i", "viii.i.ii")
#: The Commonitory's chapters XXIX-XXXIII: the recapitulation that is all that
#: survives of Vincent's second Commonitory.
_VINC_RECAP = ("iii.xxx", "iii.xxxi", "iii.xxxii", "iii.xxxiii", "iii.xxxiv")
#: Jerome's prefaces that NPNF translates (in full or in part), as works of
#: their own: div3 → (slug, title, date, date range).  The others are the
#: editor's summaries and stay in ``jerome-prefaces``.
_JER_PREFACES = (
    ("vii.ii.viii", "preface-to-the-four-gospels", "Preface to the Four Gospels (to Pope Damasus)",
     383, (383, 384)),
    ("vii.iii.iv", "preface-to-samuel-and-kings",
     "Preface to the Books of Samuel and Kings (Prologus galeatus)", 391, (390, 392)),
    ("vii.iii.viii", "preface-to-job", "Preface to Job (from the Hebrew)", 392, (392, 393)),
    ("vii.iii.x", "preface-to-the-books-of-solomon",
     "Preface to the Books of Solomon (from the Hebrew)", 393, (393, 394)),
    ("vii.iii.xiii", "preface-to-daniel", "Preface to Daniel", 392, (391, 393)),
)

_WORKS: tuple[_WorkSpec, ...] = (
    # ================================================================ NPNF1
    # ---------------------------------------------------------------- npnf101
    _aug("npnf101", "confessions", "The Confessions", 398, (397, 401), "Conf",
         P("vi", "Confessions"), conf="established"),
    _aug("npnf101", "letters", "Letters (with letters addressed to Augustine)", None,
         (386, 430), "Ep", P("vii", "Letters of St. Augustin")),
    # ---------------------------------------------------------------- npnf102
    _aug("npnf102", "city-of-god", "The City of God", 420, (413, 426), "CivDei",
         P("iv", "City of God"), conf="established"),
    _aug("npnf102", "on-christian-doctrine", "On Christian Doctrine", 397, (396, 427),
         "DocChr", P("v", "On Christian Doctrine"), conf="established"),
    # ---------------------------------------------------------------- npnf103
    _aug("npnf103", "on-the-trinity", "On the Holy Trinity", 417, (399, 422), "Trin",
         P("iv.i", "Holy Trinity"), conf="established"),
    _aug("npnf103", "enchiridion", "The Enchiridion", 422, (421, 423), "Ench",
         P("iv.ii", "Enchiridion"), conf="established"),
    _aug("npnf103", "catechising-the-uninstructed", "On the Catechising of the Uninstructed",
         400, (399, 405), "CatRud", P("iv.iii", "Catechising")),
    _aug("npnf103", "faith-and-the-creed", "A Treatise on Faith and the Creed", 393,
         (393, 393), "FidSymb", P("iv.iv", "Faith and the Creed"), conf="established"),
    _aug("npnf103", "faith-of-things-not-seen", "Concerning Faith of Things Not Seen", 400,
         (399, 420), "FidInvis", P("iv.v", "Things Not Seen")),
    _aug("npnf103", "profit-of-believing", "On the Profit of Believing", 391, (391, 392),
         "UtilCred", P("iv.vi", "Profit of Believing")),
    _aug("npnf103", "on-the-creed", "On the Creed: A Sermon to the Catechumens", 395,
         (393, 425), "Symb", P("iv.vii", "On the Creed"), conf="uncertain"),
    _aug("npnf103", "on-continence", "On Continence", 395, (394, 420), "Cont",
         P("v.i", "On Continence"), conf="uncertain"),
    _aug("npnf103", "good-of-marriage", "On the Good of Marriage", 401, (400, 401),
         "BonConj", P("v.ii", "Good of Marriage")),
    _aug("npnf103", "holy-virginity", "Of Holy Virginity", 401, (400, 401), "Virg",
         P("v.iii", "Holy Virginity")),
    _aug("npnf103", "good-of-widowhood", "On the Good of Widowhood", 414, (413, 414),
         "BonVid", P("v.iv", "Widowhood")),
    _aug("npnf103", "on-lying", "On Lying", 395, (394, 395), "Mend", P("v.v", "On Lying")),
    _aug("npnf103", "against-lying", "Against Lying", 420, (419, 420), "CMend",
         P("v.vi", "Against Lying")),
    _aug("npnf103", "work-of-monks", "Of the Work of Monks", 401, (400, 401), "OpMon",
         P("v.vii", "Work of Monks")),
    _aug("npnf103", "on-patience", "On Patience", 418, (417, 418), "Pat",
         P("v.viii", "On Patience"), conf="uncertain"),
    _aug("npnf103", "care-for-the-dead", "On Care to Be Had for the Dead", 422, (421, 424),
         "CuraMort", P("v.ix", "Care to Be Had for the Dead")),
    # ---------------------------------------------------------------- npnf104
    _aug("npnf104", "morals-of-the-catholic-church", "On the Morals of the Catholic Church",
         388, (387, 389), "MorEccl", P("iv.iv", "Morals of the Catholic Church")),
    _aug("npnf104", "morals-of-the-manichaeans", "On the Morals of the Manichaeans",
         388, (387, 389), "MorMan", P("iv.v", "Morals of the Manich")),
    _aug("npnf104", "two-souls", "On Two Souls, Against the Manichaeans", 392, (391, 392),
         "DuabAn", P("iv.vi", "Two Souls")),
    _aug("npnf104", "disputation-against-fortunatus",
         "Acts or Disputation Against Fortunatus the Manichaean", 392, (392, 392), "Fort",
         P("iv.vii", "Fortunatus"), conf="established"),
    _aug("npnf104", "against-the-fundamental-epistle",
         "Against the Epistle of Manichaeus Called Fundamental", 397, (396, 397), "CEpFund",
         P("iv.viii", "Fundamental")),
    _aug("npnf104", "reply-to-faustus", "Reply to Faustus the Manichaean", 400, (397, 400),
         "CFaust", P("iv.ix", "Reply to Faustus")),
    _aug("npnf104", "nature-of-good", "Concerning the Nature of Good, Against the Manichaeans",
         405, (399, 405), "NatBon", P("iv.x", "Nature of Good")),
    _aug("npnf104", "on-baptism-against-the-donatists", "On Baptism, Against the Donatists",
         400, (400, 401), "Bapt", P("v.iv", "On Baptism")),
    _aug("npnf104", "answer-to-petilian", "Answer to the Letters of Petilian, the Donatist",
         401, (400, 403), "CLitPet", P("v.v", "Petilian")),
    _aug("npnf104", "correction-of-the-donatists",
         "The Correction of the Donatists (Letter 185)", 417, (417, 417), "Ep185",
         P("v.vi", "Correction of the Donatists")),
    # ---------------------------------------------------------------- npnf105
    _aug("npnf105", "merits-and-forgiveness-of-sins",
         "On the Merits and Forgiveness of Sins, and on the Baptism of Infants", 412,
         (411, 412), "PeccMer", P("x", "Merits and Forgiveness"), conf="established"),
    _aug("npnf105", "spirit-and-the-letter", "On the Spirit and the Letter", 412, (412, 413),
         "SpLit", P("xi", "Spirit and the Letter"), conf="established"),
    _aug("npnf105", "nature-and-grace", "On Nature and Grace", 415, (413, 415), "NatGrat",
         P("xii", "Nature and Grace")),
    _aug("npnf105", "perfection-in-righteousness",
         "Concerning Man's Perfection in Righteousness", 415, (415, 416), "PerfJust",
         P("xiii", "Perfection in Righteousness")),
    _aug("npnf105", "proceedings-of-pelagius", "On the Proceedings of Pelagius", 417,
         (416, 417), "GestPel", P("xiv", "Proceedings of Pelagius"), conf="established"),
    _aug("npnf105", "grace-of-christ-and-original-sin",
         "On the Grace of Christ, and on Original Sin", 418, (418, 418), "GratChr",
         P("xv", "Grace of Christ"), conf="established"),
    _aug("npnf105", "marriage-and-concupiscence", "On Marriage and Concupiscence", 419,
         (418, 421), "NuptConc", P("xvi", "Marriage and Concupiscence")),
    _aug("npnf105", "soul-and-its-origin", "On the Soul and its Origin", 420, (419, 421),
         "AnOrig", P("xvii", "Soul and its Origin")),
    _aug("npnf105", "against-two-letters-of-the-pelagians",
         "Against Two Letters of the Pelagians", 421, (420, 421), "CDuasEp",
         P("xviii", "Two Letters of the Pelagians")),
    _aug("npnf105", "grace-and-free-will", "On Grace and Free Will", 426, (426, 427),
         "GratLib", P("xix", "Grace and Free Will"), conf="established"),
    _aug("npnf105", "rebuke-and-grace", "On Rebuke and Grace", 427, (426, 427), "CorrGrat",
         P("xx", "Rebuke and Grace"), conf="established"),
    _aug("npnf105", "predestination-of-the-saints", "On the Predestination of the Saints",
         429, (428, 429), "PraedSanct", P("xxi.ii", "Book I"), conf="established"),
    _aug("npnf105", "gift-of-perseverance", "On the Gift of Perseverance", 429, (428, 429),
         "DonPers", P("xxi.iii", "Gift of Perseverance"), conf="established"),
    # ---------------------------------------------------------------- npnf106
    _aug("npnf106", "sermon-on-the-mount", "Our Lord's Sermon on the Mount", 394, (393, 396),
         "SermDom", P("v", "Sermon on the Mount")),
    _aug("npnf106", "harmony-of-the-gospels", "The Harmony of the Gospels", 400, (399, 405),
         "ConsEv", P("vi", "Harmony of the Gospels")),
    _aug("npnf106", "sermons-on-new-testament-lessons",
         "Sermons on Selected Lessons of the New Testament", None, (391, 430), "SermNT",
         P("vii", "Sermons on Selected Lessons")),
    # ---------------------------------------------------------------- npnf107
    _aug("npnf107", "tractates-on-john", "Tractates on the Gospel of John", 416, (406, 420),
         "TractJn", P("iii", "Gospel According to St. John")),
    _aug("npnf107", "homilies-on-first-john", "Ten Homilies on the First Epistle of John",
         407, (406, 416), "Tract1Jn", P("iv", "First Epistle of John")),
    _aug("npnf107", "soliloquies", "Soliloquies", 387, (386, 387), "Solil",
         P("v", "Soliloquies"), conf="established"),
    # ---------------------------------------------------------------- npnf108
    _aug("npnf108", "expositions-on-the-psalms", "Expositions on the Book of Psalms", 415,
         (392, 422), "EnPs", P("ii", "Psalms")),
    # ---------------------------------------------------------------- npnf109
    _chrys("npnf109", "on-the-priesthood", "Treatise Concerning the Christian Priesthood",
           386, (381, 391), "Sac", P("iv", "Priesthood")),
    _chrys("npnf109", "exhortation-to-theodore", "An Exhortation to Theodore After His Fall",
           370, (368, 378), "Theod", P("v", "Theodore")),
    _chrys("npnf109", "letter-to-a-young-widow", "Letter to a Young Widow", 380, (380, 381),
           "Vid", P("vi", "Young Widow")),
    _chrys("npnf109", "homilies-on-ignatius-and-babylas", "Homilies on S. Ignatius and S. Babylas",
           387, (386, 398), "IgnBab", P("vii", "Ignatius and S. Babylas")),
    _chrys("npnf109", "homily-on-lowliness-of-mind",
           "Homily Concerning Lowliness of Mind, and on Philippians i. 18", 390, (386, 398),
           "Humil", P("viii", "Lowliness of Mind")),
    _chrys("npnf109", "instructions-to-catechumens", "Instructions to Catechumens", 388,
           (386, 398), "Catech", P("ix", "Catechumens")),
    _chrys("npnf109", "homilies-on-the-power-of-demons",
           "Three Homilies Concerning the Power of Demons", 388, (386, 398), "Diab",
           P("x", "Power of Demons")),
    _chrys("npnf109", "homily-on-father-if-it-be-possible",
           "Homily on Matt. xxvi. 39, 'Father, If It Be Possible', against Marcionists and "
           "Manichaeans", 390, (386, 398), "Patr", P("xi", "Father If It Be Possible")),
    _chrys("npnf109", "homily-on-the-paralytic",
           "Homily on the Paralytic Let Down Through the Roof", 390, (386, 398), "Paral",
           P("xii", "Paralytic")),
    _chrys("npnf109", "homily-to-those-absent-from-the-assembly",
           "Homily to Those Who Had Not Attended the Assembly, and on 'If Thine Enemy Hunger'",
           388, (386, 398), "Inim", P("xiii", "Not Attended the Assembly")),
    _chrys("npnf109", "homily-against-publishing-errors",
           "Homily Against Publishing the Errors of the Brethren", 387, (386, 398), "Anath",
           P("xiv", "Publishing the Errors")),
    _chrys("npnf109", "homilies-on-eutropius", "Two Homilies on Eutropius", 399, (399, 399),
           "Eutrop", P("xv", "Eutropius"), conf="established"),
    _chrys("npnf109", "no-one-can-harm-the-man-who-does-not-injure-himself",
           "A Treatise to Prove that No One Can Harm the Man Who Does Not Injure Himself",
           406, (404, 407), "Laed", P("xvi", "No One Can Harm")),
    _chrys("npnf109", "letters-to-olympias", "Letters to Olympias", 405, (404, 407), "EpOlymp",
           P("xvii", "Olympias")),
    W("npnf109", "chrysostom-correspondence-with-innocent",
      "Correspondence of St. Chrysostom with Innocent, Bishop of Rome", _CHRYS, 405,
      (404, 407), "approximate", "greek", "Chrys.EpInnoc",
      P("xviii", "Bishop of Rome")),
    _chrys("npnf109", "homilies-on-the-statues", "Homilies on the Statues to the People of Antioch",
           387, (387, 387), "Stat", P("xix", "Statues"), conf="established"),
    # ---------------------------------------------------------------- npnf110-114
    _chrys("npnf110", "homilies-on-matthew", "Homilies on the Gospel of Matthew (Homilies I–XLIV)",
           390, (386, 398), "HomMatt",
           P("iii", "Homilies of St. John Chrysostom", skip=_MATT_PG58)),
    _chrys("npnf110", "homilies-on-matthew-45-90",
           "Homilies on the Gospel of Matthew (Homilies XLV–XC)", 390, (386, 398), "HomMatt",
           P("iii", "Homilies of St. John Chrysostom", keep=_MATT_PG58)),
    _chrys("npnf111", "homilies-on-acts", "Homilies on the Acts of the Apostles", 400,
           (400, 401), "HomAct", P("vi", "Acts of the Apostles")),
    _chrys("npnf111", "homilies-on-romans", "Homilies on the Epistle to the Romans", 391,
           (386, 398), "HomRom", P("vii", "Romans")),
    _chrys("npnf112", "homilies-on-first-corinthians", "Homilies on First Corinthians", 392,
           (386, 398), "Hom1Cor", P("iv", "First Corinthians")),
    _chrys("npnf112", "homilies-on-second-corinthians", "Homilies on Second Corinthians", 392,
           (386, 398), "Hom2Cor", P("v", "Second Corinthians")),
    _chrys("npnf113", "commentary-on-galatians", "Commentary on Galatians", 395, (386, 398),
           "CommGal", P("iii.iii", "Galatians")),
    _chrys("npnf113", "homilies-on-ephesians", "Homilies on Ephesians", 395, (386, 398),
           "HomEph", P("iii.iv", "Ephesians")),
    _chrys("npnf113", "homilies-on-philippians", "Homilies on Philippians", 400, (398, 404),
           "HomPhil", P("iv.iii", "Philippians")),
    _chrys("npnf113", "homilies-on-colossians", "Homilies on Colossians", 400, (398, 404),
           "HomCol", P("iv.iv", "Colossians")),
    _chrys("npnf113", "homilies-on-first-thessalonians", "Homilies on First Thessalonians",
           400, (398, 404), "Hom1Thess", P("iv.v", "First Thessalonians")),
    _chrys("npnf113", "homilies-on-second-thessalonians", "Homilies on Second Thessalonians",
           400, (398, 404), "Hom2Thess", P("iv.vi", "2 Thessalonians")),
    _chrys("npnf113", "homilies-on-first-timothy", "Homilies on First Timothy", 392, (386, 398),
           "Hom1Tim", P("v.iii", "1 Timothy")),
    _chrys("npnf113", "homilies-on-second-timothy", "Homilies on Second Timothy", 392,
           (386, 398), "Hom2Tim", P("v.iv", "2 Timothy")),
    _chrys("npnf113", "homilies-on-titus", "Homilies on Titus", 392, (386, 398), "HomTit",
           P("v.v", "Titus")),
    _chrys("npnf113", "homilies-on-philemon", "Homilies on Philemon", 392, (386, 398),
           "HomPhlm", P("v.vi", "Philemon")),
    _chrys("npnf114", "homilies-on-john", "Homilies on the Gospel of John", 391, (386, 398),
           "HomJn", P("iv", "Gospel of St. John")),
    _chrys("npnf114", "homilies-on-hebrews", "Homilies on the Epistle to the Hebrews", 403,
           (402, 404), "HomHeb", P("v", "Hebrews")),

    # ================================================================ NPNF2
    # ---------------------------------------------------------------- npnf201
    W("npnf201", "eusebius-church-history", "The Church History (Historia Ecclesiastica)",
      "Eusebius of Caesarea", 324, (313, 326), "established", "greek", "Euseb.HE",
      *(P(d, f"Book {b}", str(i)) for i, (d, b) in enumerate((
          ("iii.vi", "I"), ("iii.vii", "II"), ("iii.viii", "III"), ("iii.ix", "IV"),
          ("iii.x", "V"), ("iii.xi", "VI"), ("iii.xii", "VII"), ("iii.xiii", "VIII"),
          ("iii.xv", "IX"), ("iii.xvi", "X")), start=1))),
    W("npnf201", "eusebius-martyrs-of-palestine", "The Martyrs of Palestine",
      "Eusebius of Caesarea", 311, (311, 313), "approximate", "greek", "Euseb.MartPal",
      P("iii.xiv", "Martyrs of Palestine")),
    W("npnf201", "eusebius-life-of-constantine", "The Life of Constantine",
      "Eusebius of Caesarea", 339, (337, 340), "approximate", "greek", "Euseb.VitConst",
      P("iv.vi", "Life of Constantine")),
    W("npnf201", "constantine-oration-to-the-assembly-of-the-saints",
      "The Oration of Constantine to the Assembly of the Saints", "Constantine the Great",
      325, (314, 330), "uncertain", "greek", "Const.OrSanct",
      P("iv.vii", "Oration of Constantine")),
    W("npnf201", "eusebius-oration-in-praise-of-constantine",
      "Oration in Praise of Constantine (Tricennial Oration)", "Eusebius of Caesarea",
      336, (335, 336), "established", "greek", "Euseb.LaudConst",
      P("iv.viii", "Oration of Eusebius")),
    # ---------------------------------------------------------------- npnf202
    W("npnf202", "socrates-ecclesiastical-history", "The Ecclesiastical History",
      "Socrates Scholasticus", 440, (439, 443), "approximate", "greek", "Socr.HE",
      *(P(d, f"Book {b}", str(i)) for i, (d, b) in enumerate((
          ("ii.iv", "I"), ("ii.v", "II"), ("ii.vi", "III"), ("ii.vii", "IV"),
          ("ii.viii", "V"), ("ii.ix", "VI"), ("ii.x", "VII")), start=1))),
    W("npnf202", "sozomen-ecclesiastical-history", "The Ecclesiastical History", "Sozomen",
      445, (439, 450), "approximate", "greek", "Sozom.HE",
      P("iii.v", "Address to the Emperor Theodosius", "0"),
      *(P(d, f"Book {b}", str(i)) for i, (d, b) in enumerate((
          ("iii.vi", "I"), ("iii.vii", "II"), ("iii.viii", "III"), ("iii.ix", "IV"),
          ("iii.x", "V"), ("iii.xi", "VI"), ("iii.xii", "VII"), ("iii.xiii", "VIII"),
          ("iii.xiv", "IX")), start=1))),
    # ---------------------------------------------------------------- npnf203
    W("npnf203", "cyril-twelve-anathemas", "The Twelve Anathemas Against Nestorius",
      "Cyril of Alexandria", 430, (430, 430), "established", "greek", "CyrAlex.Anath",
      P("iv.vi", "Anathemas of Cyril")),
    W("npnf203", "theodoret-counter-statements", "Counter-Statements to Cyril's Anathemas",
      "Theodoret of Cyrrhus", 431, (430, 431), "approximate", "greek", "Theodoret.CAnath",
      P("iv.vii", "Counter-statements")),
    W("npnf203", "theodoret-ecclesiastical-history", "The Ecclesiastical History",
      "Theodoret of Cyrrhus", 449, (444, 450), "approximate", "greek", "Theodoret.HE",
      P("iv.viii", "Ecclesiastical History of Theodoret")),
    W("npnf203", "theodoret-eranistes", "Dialogues: The 'Eranistes' or 'Polymorphus'",
      "Theodoret of Cyrrhus", 447, (447, 448), "approximate", "greek", "Theodoret.Eran",
      P("iv.ix", "Eranistes")),
    W("npnf203", "theodoret-letters", "Letters", "Theodoret of Cyrrhus", None, (423, 457),
      "approximate", "greek", "Theodoret.Ep", P("iv.x", "Letters of the Blessed Theodoret")),
    W("npnf203", "jerome-lives-of-illustrious-men", "Lives of Illustrious Men (De Viris Illustribus)",
      _JER, 392, (392, 393), "established", "latin", "Jer.VirIll",
      P("v.iii", "Jerome. Lives of Illustrious Men")),
    W("npnf203", "gennadius-lives-of-illustrious-men",
      "Lives of Illustrious Men (continuation of Jerome)", "Gennadius of Marseilles", 480,
      (467, 496), "approximate", "latin", "Gennad.VirIll",
      P("v.iv", "Gennadius. Lives of Illustrious Men")),
    W("npnf203", "rufinus-prefaces-to-translations",
      "Prefaces and Perorations to his Translations (Benedictions of the Patriarchs, "
      "Pamphilus, Peri Archon, Recognitions, Sayings of Xystus, Eusebius, Origen)", _RUF,
      402, (397, 410), "approximate", "latin", "Ruf.Praef",
      P("vi.iii", "Benedictions of the Twelve Patriarchs", "BenPatr1"),
      P("vi.iv", "Preface to Book II", "BenPatr2"),
      P("vi.v", "Pamphilus' Defence of Origen", "Pamph"),
      P("vi.vii", "Preface to the Translations of Origen", "Princ1"),
      P("vi.viii", "Preface to Book III", "Princ3"),
      P("vi.xiv", "Recognitions", "Recog"),
      P("vi.xv", "Sayings of Xystus", "Xyst"),
      P("vi.xvi", "Ecclesiastical History", "HE"),
      P("vi.xvii", "Psalms 36", "OrigPs"),
      P("vi.xviii", "Epistle to the", "OrigRom"),
      P("vi.xix", "Peroration", "OrigRomPer"),
      P("vi.xx", "Homilies on Numbers", "OrigNum")),
    W("npnf203", "rufinus-on-the-falsification-of-origen",
      "Epilogue to Pamphilus' Apology for Origen, or On the Falsification of the Books of "
      "Origen", _RUF, 397, (397, 398), "approximate", "latin", "Ruf.Adult",
      P("vi.vi", "Epilogue to Pamphilus")),
    W("npnf203", "rufinus-apology-to-anastasius", "Apology in Defence of Himself, Addressed "
      "to Anastasius", _RUF, 400, (400, 401), "approximate", "latin", "Ruf.ApolAnast",
      P("vi.ix", "Rufinus' Apology in Defence of Himself")),
    W("npnf203", "anastasius-letter-to-john-of-jerusalem",
      "Letter to John, Bishop of Jerusalem, Concerning Rufinus", "Anastasius I of Rome",
      401, (400, 401), "approximate", "latin", "Anast.EpJoh",
      P("vi.x", "Letter of Anastasius")),
    W("npnf203", "rufinus-apology-against-jerome",
      "Apology, Addressed to Apronianus, in Reply to Jerome", _RUF, 401, (400, 401),
      "approximate", "latin", "Ruf.ApolHier", P("vi.xi", "Apology of Rufinus")),
    W("npnf203", "jerome-apology-against-rufinus", "Apology Against the Books of Rufinus",
      _JER, 402, (401, 402), "approximate", "latin", "Jer.CRuf",
      P("vi.xii", "Jerome's Apology")),
    W("npnf203", "rufinus-commentary-on-the-apostles-creed",
      "A Commentary on the Apostles' Creed", _RUF, 404, (400, 410), "approximate", "latin",
      "Ruf.Symb", P("vi.xiii", "Apostles' Creed")),
    # ---------------------------------------------------------------- npnf204
    _ath("against-the-heathen", "Against the Heathen (Contra Gentes)", 318, (318, 337),
         "Gent", P("vi", "Against the Heathen")),
    _ath("on-the-incarnation", "On the Incarnation of the Word", 318, (318, 337), "Inc",
         P("vii", "Incarnation of the Word")),
    W("npnf204", "alexander-deposition-of-arius",
      "Deposition of Arius, and Encyclical Letter of Alexander", "Alexander of Alexandria",
      321, (319, 324), "approximate", "greek", "AlexAlex.DepAr",
      P("viii", "Deposition of Arius")),
    W("npnf204", "eusebius-letter-to-his-church", "Letter to the People of his Diocese on "
      "the Council of Nicaea (Epistola Eusebii)", "Eusebius of Caesarea", 325, (325, 325),
      "established", "greek", "Euseb.EpCaes", P("ix", "Letter of Eusebius")),
    _ath("statement-of-faith", "Statement of Faith (Expositio Fidei)", 330, (325, 340), "ExpFid",
         P("x", "Statement of Faith"), conf="uncertain"),
    _ath("on-luke-x-22", "On Luke x. 22 (Illud Omnia)", 335, (330, 341), "IllOmn",
         P("xi", "On Luke x. 22"), conf="uncertain"),
    _ath("encyclical-letter", "Encyclical Letter (Epistola Encyclica)", 339, (339, 339), "EpEnc",
         P("xii", "Encyclical Letter"), conf="established"),
    _ath("defence-against-the-arians", "Defence Against the Arians (Apologia Contra Arianos)",
         357, (349, 357), "ApolSec", P("xiii", "Defence Against the Arians")),
    _ath("de-decretis", "Defence of the Nicene Definition (De Decretis)", 352, (350, 356),
         "Decr", P("xiv", "De Decretis")),
    _ath("de-sententia-dionysii", "Defence of Dionysius (De Sententia Dionysii)", 354,
         (352, 356), "Dion", P("xv", "Defence of Dionysius")),
    _ath("life-of-antony", "Life of Antony (Vita Antonii)", 357, (356, 362), "VitAnt",
         P("xvi", "Life of Antony"), conf="established"),
    _ath("circular-to-the-bishops-of-egypt-and-libya",
         "Circular to the Bishops of Egypt and Libya", 356, (356, 357), "EpAeg",
         P("xvii", "Circular to Bishops of Egypt")),
    _ath("apology-to-constantius", "Apology to the Emperor Constantius", 357, (353, 357),
         "ApolConst", P("xviii", "Apology to the Emperor")),
    _ath("defence-of-his-flight", "Defence of His Flight (Apologia de Fuga)", 357, (357, 358),
         "Fug", P("xix", "Defence of His Flight")),
    _ath("history-of-the-arians", "History of the Arians (Historia Arianorum)", 358,
         (357, 358), "HistAr", P("xx", "Arian History")),
    # One work per discourse (#380); the first keeps the old slug.
    _ath("discourses-against-the-arians", "First Discourse Against the Arians", 340,
         (339, 360), "OratAr", P("xxi", "Against the Arians", keep=("xxi.ii.i",))),
    _ath("second-discourse-against-the-arians", "Second Discourse Against the Arians", 340,
         (339, 360), "OratAr", P("xxi", "Against the Arians", keep=("xxi.ii.iii",))),
    _ath("third-discourse-against-the-arians", "Third Discourse Against the Arians", 340,
         (339, 360), "OratAr", P("xxi", "Against the Arians", keep=("xxi.ii.iv",))),
    _ath("fourth-discourse-against-the-arians",
         "Fourth Discourse Against the Arians (of doubtful authenticity)", 340, (339, 360),
         "OratAr", P("xxi", "Against the Arians", keep=("xxi.ii.vi",))),
    _ath("de-synodis", "On the Councils of Ariminum and Seleucia (De Synodis)", 359,
         (359, 361), "Syn", P("xxii", "De Synodis")),
    _ath("tome-to-the-antiochenes", "Synodal Letter to the People of Antioch "
         "(Tomus ad Antiochenos)", 362, (362, 362), "Tom", P("xxiii", "Tomus ad Antiochenos"),
         conf="established"),
    _ath("letter-to-the-bishops-of-africa", "Synodal Letter to the Bishops of Africa "
         "(Ad Afros)", 369, (367, 369), "Afr", P("xxiv", "Bishops of Africa")),
    W("npnf204", "historia-acephala", "The Historia Acephala (History of Athanasius)", None,
      390, (373, 420), "uncertain", "greek", "HistAceph", P("xxv.ii", "Historia Acephala")),
    W("npnf204", "festal-index", "The Index to the Festal Letters (Chronicon Athanasianum)",
      None, 390, (373, 420), "uncertain", "greek", "IndFest", P("xxv.iii.ii", "Index")),
    _ath("festal-letters", "Festal Letters", None, (329, 373), "EpFest",
         P("xxv.iii.iii", "Festal Letters")),
    _ath("personal-letters", "Personal Letters (Letters XLVI–XLVII, L–LI, LXIV)", None,
         (335, 373), "Ep",
         P("xxv.iii.iv", "Personal Letters", skip=(
             *(div for div, *_ in _ATH_LETTERS), _ATH_JOVIAN, *_ATH_ORSISIUS))),
    *(_ath(slug, title, date, rng, prefix, P("xxv.iii.iv", "Personal Letters", keep=(div,)))
      for div, slug, title, date, rng, prefix in _ATH_LETTERS),
    _ath("letter-56-to-jovian", "Letter LVI: To the Emperor Jovian (with Jovian's letter)",
         363, (363, 363), "EpJov",
         P("xxv.iii.iv", "Personal Letters", keep=(_ATH_JOVIAN,), drop_trailing=9),
         conf="established"),
    # The appendix to Letter LVI keeps its refs (``Ath.EpJov.9``-``17``).
    _ath("petitions-of-the-arians-to-jovian", "Petitions of the Arians to the Emperor Jovian "
         "(appendix to Letter LVI)", 363, (363, 364), "EpJov",
         P("xxv.iii.iv", "Personal Letters", keep=(_ATH_JOVIAN,), drop_leading=9)),
    _ath("letters-57-58-to-orsisius", "Letters LVII–LVIII: To Orsisius", 364, (363, 364),
         "EpOrs", P("xxv.iii.iv", "Personal Letters", keep=_ATH_ORSISIUS)),
    # ---------------------------------------------------------------- npnf205
    W("npnf205", "gregory-of-nyssa-letter-to-peter",
      "Letter to his Brother Peter, with Peter's Reply (prefatory to Against Eunomius)", _NYSS,
      382, (380, 384), "approximate", "greek", "GregNyss.Eun",
      P("viii.i", "Against Eunomius", keep=_NYSS_PETER)),
    W("npnf205", "gregory-of-nyssa-against-eunomius", "Against Eunomius", _NYSS, 382,
      (380, 384), "approximate", "greek", "GregNyss.Eun",
      P("viii.i", "Against Eunomius", drop_leading=12)),
    W("npnf205", "gregory-of-nyssa-answer-to-eunomius-second-book",
      "Answer to Eunomius' Second Book", _NYSS, 383, (382, 384), "approximate", "greek",
      "GregNyss.RefEun", P("viii.ii", "Second Book")),
    W("npnf205", "gregory-of-nyssa-on-the-holy-spirit",
      "On the Holy Spirit, Against the Macedonians", _NYSS, 381, (380, 381), "approximate",
      "greek", "GregNyss.Spir", P("viii.iii", "On the Holy Spirit")),
    W("npnf205", "gregory-of-nyssa-on-the-holy-trinity",
      "On the Holy Trinity, and of the Godhead of the Holy Spirit (to Eustathius)", _NYSS,
      380, (375, 385), "uncertain", "greek", "GregNyss.Trin", P("viii.iv", "Holy Trinity")),
    W("npnf205", "gregory-of-nyssa-not-three-gods", "On 'Not Three Gods' (to Ablabius)",
      _NYSS, 385, (375, 394), "uncertain", "greek", "GregNyss.Abl",
      P("viii.v", "Not Three Gods")),
    W("npnf205", "gregory-of-nyssa-on-the-faith", "On the Faith (to Simplicius)", _NYSS,
      380, (375, 394), "uncertain", "greek", "GregNyss.Fid", P("viii.vi", "On the Faith")),
    W("npnf205", "gregory-of-nyssa-on-virginity", "On Virginity", _NYSS, 371, (370, 378),
      "approximate", "greek", "GregNyss.Virg", P("ix.ii", "On Virginity")),
    W("npnf205", "gregory-of-nyssa-on-infants-early-deaths", "On Infants' Early Deaths",
      _NYSS, 385, (380, 394), "uncertain", "greek", "GregNyss.Infant",
      P("ix.iii", "Infants")),
    W("npnf205", "gregory-of-nyssa-on-pilgrimages", "On Pilgrimages (Letter 2)", _NYSS,
      381, (380, 385), "uncertain", "greek", "GregNyss.Peregr", P("ix.iv", "Pilgrimages")),
    W("npnf205", "gregory-of-nyssa-on-the-making-of-man", "On the Making of Man", _NYSS,
      379, (379, 380), "approximate", "greek", "GregNyss.HomOpif",
      P("x.ii", "Making of Man")),
    W("npnf205", "gregory-of-nyssa-on-the-soul-and-the-resurrection",
      "On the Soul and the Resurrection", _NYSS, 380, (379, 381), "approximate", "greek",
      "GregNyss.AnRes", P("x.iii", "Soul and the Resurrection")),
    W("npnf205", "gregory-of-nyssa-great-catechism", "The Great Catechism (Oratio Catechetica)",
      _NYSS, 385, (383, 387), "approximate", "greek", "GregNyss.OrCat",
      P("xi.ii", "Great Catechism")),
    W("npnf205", "gregory-of-nyssa-funeral-oration-on-meletius", "Funeral Oration on Meletius",
      _NYSS, 381, (381, 381), "established", "greek", "GregNyss.Melet",
      P("xii.ii", "Meletius")),
    W("npnf205", "gregory-of-nyssa-on-the-baptism-of-christ",
      "On the Baptism of Christ (Sermon for the Day of Lights)", _NYSS, 383, (379, 394),
      "uncertain", "greek", "GregNyss.Bapt", P("xii.iii", "Baptism of Christ")),
    W("npnf205", "gregory-of-nyssa-letters", "Letters", _NYSS, None, (370, 394),
      "approximate", "greek", "GregNyss.Ep", P("xiii", "Letters")),
    # ---------------------------------------------------------------- npnf206
    W("npnf206", "jerome-letters", "Letters (with letters addressed to Jerome)", _JER, None,
      (370, 419), "approximate", "latin", "Jer.Ep", P("v", "Letters of St. Jerome")),
    W("npnf206", "jerome-life-of-paul-the-hermit", "The Life of Paulus the First Hermit", _JER,
      376, (374, 379), "approximate", "latin", "Jer.VitPaul", P("vi.i", "Paulus the First Hermit")),
    W("npnf206", "jerome-life-of-hilarion", "The Life of S. Hilarion", _JER, 390, (386, 391),
      "approximate", "latin", "Jer.VitHil", P("vi.ii", "Hilarion")),
    W("npnf206", "jerome-life-of-malchus", "The Life of Malchus, the Captive Monk", _JER, 391,
      (386, 392), "approximate", "latin", "Jer.VitMalch", P("vi.iii", "Malchus")),
    W("npnf206", "jerome-dialogue-against-the-luciferians", "The Dialogue Against the "
      "Luciferians", _JER, 379, (378, 382), "approximate", "latin", "Jer.Lucif",
      P("vi.iv", "Luciferians")),
    W("npnf206", "jerome-against-helvidius", "The Perpetual Virginity of Blessed Mary "
      "(Against Helvidius)", _JER, 383, (382, 384), "approximate", "latin", "Jer.Helv",
      P("vi.v", "Perpetual Virginity")),
    W("npnf206", "jerome-against-jovinianus", "Against Jovinianus", _JER, 393, (393, 393),
      "established", "latin", "Jer.Jov", P("vi.vi", "Jovinianus")),
    W("npnf206", "jerome-against-vigilantius", "Against Vigilantius", _JER, 406, (406, 406),
      "established", "latin", "Jer.Vigil", P("vi.vii", "Vigilantius")),
    W("npnf206", "jerome-against-john-of-jerusalem", "To Pammachius Against John of Jerusalem",
      _JER, 397, (396, 397), "approximate", "latin", "Jer.CJoh",
      P("vi.viii", "John of Jerusalem")),
    W("npnf206", "jerome-against-the-pelagians", "Dialogue Against the Pelagians", _JER, 415,
      (415, 415), "established", "latin", "Jer.Pelag", P("vi.ix", "Against the Pelagians")),
    W("npnf206", "jerome-prefaces", "Prefaces (to his Early Works, the Vulgate Old Testament, "
      "and the Commentaries)", _JER, None, (379, 415), "approximate", "latin", "Jer.Praef",
      P("vii", "Prefaces", skip=tuple(div for div, *_ in _JER_PREFACES))),
    *(W("npnf206", f"jerome-{slug}", title, _JER, date, rng, "approximate", "latin",
        "Jer.Praef", P("vii", "Prefaces", keep=(div,)))
      for div, slug, title, date, rng in _JER_PREFACES),
    # ---------------------------------------------------------------- npnf207
    W("npnf207", "cyril-of-jerusalem-procatechesis", "The Procatechesis (Prologue to the "
      "Catechetical Lectures)", "Cyril of Jerusalem", 350, (348, 351), "approximate", "greek",
      "CyrHier.Cat", P("ii.iv", "Procatechesis", "0")),
    W("npnf207", "cyril-of-jerusalem-catechetical-lectures",
      "The Catechetical Lectures (Lectures I–XVIII)", "Cyril of Jerusalem",
      350, (348, 351), "approximate", "greek", "CyrHier.Cat",
      *(P(f"ii.{r}", "", str(n)) for n, r in enumerate((
          "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv", "xvi",
          "xvii", "xviii", "xix", "xx", "xxi", "xxii"), start=1))),
    W("npnf207", "cyril-of-jerusalem-mystagogical-lectures",
      "The Mystagogical Lectures (Lectures XIX–XXIII)", "Cyril of Jerusalem", 380, (350, 390),
      "uncertain", "greek", "CyrHier.Myst",
      *(P(f"ii.{r}", "Mysteries", str(n)) for n, r in enumerate((
          "xxiii", "xxiv", "xxv", "xxvi", "xxvii"), start=1))),
    *(W("npnf207", f"gregory-nazianzen-oration-{num:02d}", title, _NAZ, date,
        (date - 1, date + 1), "approximate", "greek", f"GregNaz.Or{num}", P(div, check))
      for div, check, num, title, date in _NAZ_ORATIONS),
    W("npnf207", "gregory-nazianzen-letters-on-the-apollinarian-controversy",
      "Letters on the Apollinarian Controversy (to Cledonius and Nectarius)", _NAZ, 382,
      (381, 387), "approximate", "greek", "GregNaz.EpApoll",
      P("iv.ii", "Apollinarian Controversy")),
    W("npnf207", "gregory-nazianzen-correspondence-with-basil",
      "Correspondence with Saint Basil the Great", _NAZ, None, (358, 378), "approximate",
      "greek", "GregNaz.EpBas", P("iv.iii", "Correspondence with Saint Basil")),
    W("npnf207", "gregory-nazianzen-miscellaneous-letters", "Miscellaneous Letters", _NAZ,
      None, (359, 390), "approximate", "greek", "GregNaz.Ep", P("iv.iv", "Miscellaneous")),
    # ---------------------------------------------------------------- npnf208
    W("npnf208", "basil-on-the-holy-spirit", "On the Holy Spirit (De Spiritu Sancto)",
      "Basil of Caesarea", 375, (374, 375), "established", "greek", "Bas.SpiritSanct",
      P("vii", "De Spiritu Sancto")),
    W("npnf208", "basil-hexaemeron", "The Hexaemeron", "Basil of Caesarea", 378, (370, 378),
      "approximate", "greek", "Bas.Hex", P("viii", "Hexæmeron")),
    W("npnf208", "basil-letters", "Letters (with letters addressed to Basil)",
      "Basil of Caesarea", None, (357, 378), "approximate", "greek", "Bas.Ep",
      P("ix", "The Letters")),
    # ---------------------------------------------------------------- npnf209
    W("npnf209", "hilary-de-synodis", "On the Councils (De Synodis)", "Hilary of Poitiers",
      359, (358, 359), "established", "latin", "Hil.Syn", P("ii.iv", "De Synodis")),
    W("npnf209", "hilary-on-the-trinity", "On the Trinity (De Trinitate)", "Hilary of Poitiers",
      359, (356, 360), "approximate", "latin", "Hil.Trin", P("ii.v", "De Trinitate")),
    W("npnf209", "hilary-homilies-on-psalms", "Homilies on Psalms I, LIII, CXXX",
      "Hilary of Poitiers", 365, (360, 367), "approximate", "latin", "Hil.Ps",
      P("ii.vi", "Homilies on Psalms")),
    W("npnf209", "john-of-damascus-exposition-of-the-orthodox-faith",
      "An Exact Exposition of the Orthodox Faith (De Fide Orthodoxa)", "John of Damascus",
      743, (730, 749), "approximate", "greek", "JohnDam.FidOrt",
      P("iii.iv", "Exposition of the Orthodox Faith")),
    # ---------------------------------------------------------------- npnf210
    W("npnf210", "ambrose-on-the-duties-of-the-clergy", "On the Duties of the Clergy "
      "(De Officiis)", _AMB, 390, (388, 391), "approximate", "latin", "Ambr.Off",
      P("iv.i", "Duties of the Clergy")),
    W("npnf210", "ambrose-on-the-holy-spirit", "On the Holy Spirit", _AMB, 381, (381, 381),
      "established", "latin", "Ambr.Spir", P("iv.ii", "On the Holy Spirit")),
    W("npnf210", "ambrose-on-the-decease-of-satyrus", "On the Decease of His Brother Satyrus",
      _AMB, 378, (375, 379), "approximate", "latin", "Ambr.ExcSat",
      P("iv.iii", "Satyrus")),
    W("npnf210", "ambrose-exposition-of-the-christian-faith", "Exposition of the Christian "
      "Faith (De Fide)", _AMB, 380, (378, 380), "approximate", "latin", "Ambr.Fid",
      P("iv.iv", "Christian Faith")),
    W("npnf210", "ambrose-on-the-mysteries", "On the Mysteries", _AMB, 390, (387, 391),
      "approximate", "latin", "Ambr.Myst", P("iv.v", "On the Mysteries")),
    W("npnf210", "ambrose-concerning-repentance", "Concerning Repentance", _AMB, 389,
      (384, 394), "approximate", "latin", "Ambr.Paen", P("iv.vi", "Repentance")),
    W("npnf210", "ambrose-concerning-virgins", "Concerning Virgins", _AMB, 377, (377, 377),
      "established", "latin", "Ambr.Virg", P("iv.vii", "Concerning Virgins")),
    W("npnf210", "ambrose-concerning-widows", "Concerning Widows", _AMB, 377, (377, 378),
      "approximate", "latin", "Ambr.Vid", P("iv.viii", "Concerning Widows")),
    W("npnf210", "symmachus-memorial-on-the-altar-of-victory",
      "Memorial on the Altar of Victory (Relatio III)", "Quintus Aurelius Symmachus", 384,
      (384, 384), "established", "latin", "Symm.Rel3",
      P("v.i", "Memorial of Symmachus", "1"), P("v.iii", "Memorial of Symmachus", "2")),
    W("npnf210", "ambrose-selected-letters", "Selected Letters", _AMB, None, (384, 396),
      "approximate", "latin", "Ambr.Ep",
      *(P(f"v.{r}", "", r) for r in (
          "ii", "iv", "v", "vi", "viii", "ix", "x", "xi", "xii", "xiii", "xiv", "xv"))),
    W("npnf210", "ambrose-sermon-against-auxentius",
      "Sermon Against Auxentius on the Giving Up of the Basilicas", _AMB, 386, (386, 386),
      "established", "latin", "Ambr.Aux", P("v.vii", "Auxentius")),
    # ---------------------------------------------------------------- npnf211
    W("npnf211", "sulpicius-severus-life-of-st-martin", "On the Life of St. Martin",
      "Sulpicius Severus", 397, (396, 397), "approximate", "latin", "SulpSev.VitMart",
      P("ii.ii", "Life of St. Martin")),
    W("npnf211", "sulpicius-severus-letters", "Letters", "Sulpicius Severus", 398, (397, 400),
      "approximate", "latin", "SulpSev.Ep", P("ii.iii", "Letters of Sulpitius")),
    W("npnf211", "sulpicius-severus-dialogues", "Dialogues", "Sulpicius Severus", 404,
      (403, 406), "approximate", "latin", "SulpSev.Dial", P("ii.iv", "Dialogues")),
    W("npnf211", "pseudo-sulpicius-severus-doubtful-letters", "Doubtful Letters",
      "Pseudo-Sulpicius Severus", None, (400, 600), "uncertain", "latin", "PsSulpSev.Ep",
      P("ii.v", "Doubtful Letters")),
    W("npnf211", "sulpicius-severus-sacred-history", "The Sacred History (Chronicle)",
      "Sulpicius Severus", 403, (400, 404), "approximate", "latin", "SulpSev.Chron",
      P("ii.vi", "Sacred History")),
    W("npnf211", "vincent-of-lerins-commonitory", "The Commonitory (Chapters I–XXVIII)",
      "Vincent of Lérins", 434, (434, 434), "established", "latin", "Vinc.Comm",
      P("iii", "Commonitory", skip=_VINC_RECAP)),
    W("npnf211", "vincent-of-lerins-commonitory-recapitulation",
      "The Commonitory, Chapters XXIX–XXXIII (the Recapitulation of the Second Commonitory)",
      "Vincent of Lérins", 434, (434, 434), "established", "latin", "Vinc.Comm",
      P("iii", "Commonitory", keep=_VINC_RECAP)),
    W("npnf211", "cassian-institutes", "The Institutes of the Coenobia", "John Cassian",
      420, (419, 426), "approximate", "latin", "CassJohn.Inst",
      P("iv.ii", "Preface", "0"), P("iv.iii", "Institutes", "1")),
    W("npnf211", "cassian-conferences", "The Conferences", "John Cassian", 426, (420, 429),
      "approximate", "latin", "CassJohn.Coll",
      P("iv.iv", "Part I.", "1"), P("iv.v", "Part II.", "2"), P("iv.vi", "Part III.", "3")),
    W("npnf211", "cassian-on-the-incarnation", "On the Incarnation of the Lord, Against "
      "Nestorius", "John Cassian", 430, (429, 430), "established", "latin", "CassJohn.Inc",
      P("iv.vii", "Incarnation")),
    # ---------------------------------------------------------------- npnf212-213
    W("npnf212", "leo-letters", "Letters", "Leo the Great", None, (440, 461), "approximate",
      "latin", "Leo.Ep", P("ii.iv", "Letters")),
    W("npnf212", "leo-sermons", "Sermons", "Leo the Great", None, (440, 461), "approximate",
      "latin", "Leo.Serm", P("ii.v", "Sermons")),
    W("npnf212", "gregory-the-great-pastoral-rule", "The Book of Pastoral Rule",
      "Gregory the Great", 590, (590, 591), "established", "latin", "GregMag.RegPast",
      P("iii.iv", "Pastoral Rule")),
    W("npnf212", "gregory-the-great-register-books-1-8",
      "Register of the Epistles (Books I–VIII)", "Gregory the Great", None, (590, 598),
      "established", "latin", "GregMag.Reg", P("iii.v", "Register of the Epistles")),
    W("npnf213", "gregory-the-great-register-books-9-14",
      "Register of the Epistles (Books IX–XIV)", "Gregory the Great", None, (598, 604),
      "established", "latin", "GregMag.Reg",
      *(P(f"ii.{r}", f"Book {b}", b) for r, b in (
          ("v", "IX"), ("vi", "X"), ("vii", "XI"), ("viii", "XII"), ("ix", "XIII"),
          ("x", "XIV")))),
    W("npnf213", "ephrem-nisibene-hymns", "The Nisibene Hymns (Carmina Nisibena)",
      "Ephrem the Syrian", 363, (350, 373), "approximate", "syriac", "Eph.CNis",
      P("iii.iv", "Nisibene Hymns")),
    W("npnf213", "ephrem-hymns-on-the-nativity", "Nineteen Hymns on the Nativity of Christ "
      "in the Flesh", "Ephrem the Syrian", 363, (350, 373), "approximate", "syriac",
      "Eph.HymNat", P("iii.v", "Nativity")),
    W("npnf213", "ephrem-hymns-for-the-epiphany", "Fifteen Hymns for the Feast of the Epiphany",
      "Ephrem the Syrian", 365, (350, 450), "uncertain", "syriac", "Eph.HymEpiph",
      P("iii.vi", "Epiphany")),
    W("npnf213", "ephrem-the-pearl", "The Pearl: Seven Hymns on the Faith",
      "Ephrem the Syrian", 360, (350, 373), "approximate", "syriac", "Eph.Marg",
      P("iii.vii", "The Pearl")),
    W("npnf213", "ephrem-three-homilies", "Three Homilies", "Ephrem the Syrian", 365,
      (350, 373), "uncertain", "syriac", "Eph.Hom", P("iii.viii", "Three Homilies")),
    W("npnf213", "aphrahat-select-demonstrations", "Select Demonstrations",
      "Aphrahat the Persian Sage", 340, (337, 345), "established", "syriac", "Aphrahat.Dem",
      P("iii.ix", "Aphrahat")),
    # ---------------------------------------------------------------- npnf214
    # Appendix: canons and canonical epistles not of conciliar origin.
    W("npnf214", "apostolic-canons", "The Canons of the Holy Apostles (Apostolic Canons)",
      None, 380, (375, 400), "approximate", "greek", "CanApost",
      P("xvii.iv", "Canons of the Holy"), genre="council"),
    W("npnf214", "dionysius-of-alexandria-letter-to-basilides",
      "Canonical Letter to Basilides", "Dionysius of Alexandria", 260, (247, 264),
      "approximate", "greek", "DionAlex.Basil", P("xvii.v", "Basilides")),
    W("npnf214", "peter-of-alexandria-canons", "The Canons (from the Sermon on Penitence)",
      "Peter of Alexandria", 306, (306, 306), "established", "greek", "PetrAlex.Can",
      P("xvii.vi", "Peter, Archbishop of Alexandria")),
    W("npnf214", "gregory-thaumaturgus-canonical-epistle", "Canonical Epistle",
      "Gregory Thaumaturgus", 258, (254, 262), "approximate", "greek", "GregThaum.EpCan",
      P("xvii.vii", "Canonical Epistle of St. Gregory")),
    # The three canonical letters as works of their own (#315).
    W("npnf214", "athanasius-letter-to-ammus", "Canonical Epistle to the Monk Ammus", _ATH,
      354, (354, 356), "approximate", "greek", "Ath.EpAmun", P("xvii.viii", "Monk Ammus")),
    W("npnf214", "athanasius-canonical-epistles", "Festal Letter XXXIX (on the Canon)", _ATH,
      367, (367, 367), "established", "greek", "Ath.EpCan", P("xvii.ix", "XXXIX", "Fest39")),
    W("npnf214", "athanasius-letter-to-rufinianus", "Canonical Epistle to Rufinianus", _ATH,
      362, (362, 363), "approximate", "greek", "Ath.EpRuf", P("xvii.x", "Ruffinian")),
    W("npnf214", "basil-canonical-epistles", "Canonical Epistles and Canonical Extracts",
      "Basil of Caesarea", 375, (370, 378), "approximate", "greek", "Bas.EpCan",
      *(P(f"xvii.{r}", "", r) for r in (
          "xi", "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx"))),
    W("npnf214", "gregory-of-nyssa-canonical-epistle-to-letoius",
      "Canonical Epistle to Letoius", _NYSS, 390, (383, 394), "approximate", "greek",
      "GregNyss.Let", P("xvii.xxi", "Letoïus")),
    W("npnf214", "gregory-nazianzen-verses-on-the-canon",
      "Verses on the Genuine Books of Scripture", _NAZ, 385, (380, 390), "uncertain",
      "greek", "GregNaz.Carm", P("xvii.xxii", "Metre Poems")),
    W("npnf214", "amphilochius-iambics-to-seleucus", "Iambics to Seleucus (on the Canon)",
      "Amphilochius of Iconium", 385, (375, 394), "uncertain", "greek", "Amphil.Sel",
      P("xvii.xxiii", "Amphilochius")),
    W("npnf214", "timothy-of-alexandria-canonical-answers", "Canonical Answers",
      "Timothy of Alexandria", 381, (380, 385), "approximate", "greek", "TimAlex.Resp",
      P("xvii.xxiv", "Timothy")),
    W("npnf214", "theophilus-of-alexandria-canonical-writings",
      "Canonical Writings (Prosphonesis, Commonitory to Ammon, Letters to Agatho and "
      "Menas, On the Cathari)", "Theophilus of Alexandria", 395, (385, 412), "approximate",
      "greek", "TheophAlex.Can",
      *(P(f"xvii.{r}", "", r) for r in ("xxv", "xxvi", "xxvii", "xxviii", "xxix"))),
    W("npnf214", "cyril-of-alexandria-canonical-epistles", "Canonical Epistles (to Domnus; "
      "to the Bishops of Libya and Pentapolis)", "Cyril of Alexandria", 430, (412, 444),
      "approximate", "greek", "CyrAlex.EpCan",
      P("xvii.xxx", "Cyril", "Domn"), P("xvii.xxxi", "Libya", "Lib")),
    W("npnf214", "gennadius-encyclical-letter", "Encyclical Letter Against Simony",
      "Gennadius I of Constantinople", 459, (458, 471), "approximate", "greek",
      "GennadConst.Enc", P("xvii.xxxii", "Gennadius")),
)


# ---------------------------------------------------------------------------
# Translation linkage: slug → work_id of the original-language Work in the
# corpus (First1KGreek, PTA, Perseus, OGLT PL, OGPG).  Matched by author + title,
# then checked by hand against a passage of the original; unsure cases are
# left out (see _UNLINKED).
# ---------------------------------------------------------------------------

_F1K = "first1k/{}/1st1K-grc1"
_AUG_PL = "oglt-pl/augustinus/{}"
_JER_PL = "oglt-pl/hieronymus/{}"
_AMB_PL = "oglt-pl/ambrosius/{}"

_PG51_HOMILIES = "ogpg/vol-051/in-loca-novi-testamenti"
_PG52_OPUSCULA = "ogpg/vol-052/de-motibus-constantinopolitanis"
_PG52_LETTERS = "ogpg/vol-052/epistulae"

#: Originals in OGPG (see the note where ``_ORIGINALS`` includes this table).
_PG_ORIGINALS: dict[str, str] = {
    # NPNF1 vol. 9: Chrysostom's treatises and homilies
    "chrysostom-exhortation-to-theodore": "ogpg/vol-047/ad-theodorum-lapsum",
    # PG 48 prints both tractates to the widow; NPNF translates the first.
    "chrysostom-letter-to-a-young-widow": "ogpg/vol-048/ad-viduam-juniorem",
    "chrysostom-on-the-priesthood": "ogpg/vol-048/de-sacerdotio",
    "chrysostom-homilies-on-the-power-of-demons": "ogpg/vol-049/de-diabolo-tentatore",
    "chrysostom-homilies-on-the-statues": "ogpg/vol-049/de-statuis",
    "chrysostom-instructions-to-catechumens": "ogpg/vol-049/catecheses-ad-illuminandos",
    # In S. Ignatium and De S. Babyla are among PG 50's Sermones panegyrici.
    "chrysostom-homilies-on-ignatius-and-babylas": "ogpg/vol-050/sermones-panegyrici",
    # Five of the Homiliae XXV in quaedam loca Novi Testamenti (PG 51).
    "chrysostom-homily-on-father-if-it-be-possible": _PG51_HOMILIES,
    "chrysostom-homily-on-the-paralytic": _PG51_HOMILIES,
    "chrysostom-homily-to-those-absent-from-the-assembly": _PG51_HOMILIES,
    "chrysostom-homily-on-lowliness-of-mind": _PG51_HOMILIES,
    "chrysostom-homily-against-publishing-errors": _PG51_HOMILIES,
    # In Eutropium and Quod nemo laeditur are among PG 52's Opuscula de
    # motibus Constantinopolitanis.
    "chrysostom-homilies-on-eutropius": _PG52_OPUSCULA,
    "chrysostom-no-one-can-harm-the-man-who-does-not-injure-himself": _PG52_OPUSCULA,
    # Both are part of PG 52's letter collection (Innocent's replies too).
    "chrysostom-letters-to-olympias": _PG52_LETTERS,
    "chrysostom-correspondence-with-innocent": _PG52_LETTERS,
    # NPNF1 vols. 10-14: Chrysostom's homily series.  Migne prints the
    # Matthew homilies over PG 57 (I-XLIV) and PG 58 (XLV-XC).
    "chrysostom-homilies-on-matthew": "ogpg/vol-057/in-matthaeum-1",
    "chrysostom-homilies-on-matthew-45-90": "ogpg/vol-058/in-matthaeum-2",
    "chrysostom-homilies-on-john": "ogpg/vol-059/in-joannem",
    "chrysostom-homilies-on-acts": "ogpg/vol-060/in-acta",
    "chrysostom-homilies-on-first-corinthians": "ogpg/vol-061/in-1-corinthios",
    "chrysostom-homilies-on-second-corinthians": "ogpg/vol-061/in-2-corinthios",
    "chrysostom-homilies-on-ephesians": "ogpg/vol-062/in-ephesios",
    "chrysostom-homilies-on-philippians": "ogpg/vol-062/in-philippenses",
    "chrysostom-homilies-on-first-thessalonians": "ogpg/vol-062/in-1-thessalonicenses",
    "chrysostom-homilies-on-second-thessalonians": "ogpg/vol-062/in-2-thessalonicenses",
    "chrysostom-homilies-on-first-timothy": "ogpg/vol-062/in-1-timotheum",
    "chrysostom-homilies-on-hebrews": "ogpg/vol-063/in-hebraeos",
    # NPNF2 vol. 3: Theodoret; Cyril's anathemas close his third letter to
    # Nestorius (Ep. 17).
    "theodoret-eranistes": "ogpg/vol-083/eranistes",
    "theodoret-letters": "ogpg/vol-083/epistulae",
    "cyril-twelve-anathemas": "ogpg/vol-077/epistula-17",
    # NPNF2 vol. 4: Athanasius (the works PTA does not have)
    "athanasius-circular-to-the-bishops-of-egypt-and-libya": "ogpg/vol-025/ad-episcopos-aegypti",
    "athanasius-defence-against-the-arians": "ogpg/vol-025/apologia-contra-arianos",
    "athanasius-defence-of-his-flight": "ogpg/vol-025/apologia-de-fuga",
    "athanasius-encyclical-letter": "ogpg/vol-025/epistula-encyclica",
    "athanasius-history-of-the-arians": "ogpg/vol-025/historia-arianorum",
    "athanasius-on-luke-x-22": "ogpg/vol-025/in-illud-omnia",
    # OGPG files it as Pseudo-Athanasius; same Expositio fidei.
    "athanasius-statement-of-faith": "ogpg/vol-025/expositio-fidei",
    "athanasius-de-synodis": "ogpg/vol-026/de-synodis",
    "athanasius-life-of-antony": "ogpg/vol-026/vita-antonii",
    # Personal letters (#380).  PG 26 prints both letters to Orsisius as one
    # Work, and the letter to Rufinianus as ad-rufinianum (whose last lines
    # OGPG files under ad-luciferum).
    "athanasius-letter-48-to-amun": "ogpg/vol-026/ad-amunem",
    "athanasius-letter-52-first-to-monks": "ogpg/vol-025/ad-monachos",
    "athanasius-letter-53-second-to-monks": "ogpg/vol-026/ad-monachos",
    "athanasius-letter-54-to-serapion-on-the-death-of-arius": "ogpg/vol-025/de-morte-arii",
    "athanasius-letter-55-to-rufinianus": "ogpg/vol-026/ad-rufinianum",
    "athanasius-letters-57-58-to-orsisius": "ogpg/vol-026/ad-orsisium",
    "athanasius-letter-59-to-epictetus": "ogpg/vol-026/ad-epictetum",
    "athanasius-letter-60-to-adelphius": "ogpg/vol-026/ad-adelphium",
    "athanasius-letter-61-to-maximus": "ogpg/vol-026/ad-maximum",
    # NPNF2 vol. 5: Gregory of Nyssa.  PG 45's Contra Eunomium libri XII
    # includes the answer to Eunomius' second book.
    "gregory-of-nyssa-against-eunomius": "ogpg/vol-045/contra-eunomium",
    "gregory-of-nyssa-answer-to-eunomius-second-book": "ogpg/vol-045/contra-eunomium",
    "gregory-of-nyssa-letter-to-peter": "ogpg/vol-045/ad-petrum",
    "gregory-of-nyssa-on-the-holy-spirit": "ogpg/vol-045/adversus-macedonianos",
    "gregory-of-nyssa-not-three-gods": "ogpg/vol-045/ad-ablabium",
    "gregory-of-nyssa-on-the-faith": "ogpg/vol-045/ad-simplicium",
    "gregory-of-nyssa-great-catechism": "ogpg/vol-045/oratio-catechetica",
    "gregory-of-nyssa-on-the-making-of-man": "ogpg/vol-044/de-opificio-hominis",
    "gregory-of-nyssa-on-the-soul-and-the-resurrection": "ogpg/vol-046/de-anima-et-resurrectione",
    "gregory-of-nyssa-on-virginity": "ogpg/vol-046/de-virginitate",
    "gregory-of-nyssa-on-infants-early-deaths": "ogpg/vol-046/de-infantibus",
    "gregory-of-nyssa-on-the-baptism-of-christ": "ogpg/vol-046/in-baptismum-christi",
    "gregory-of-nyssa-funeral-oration-on-meletius": "ogpg/vol-046/in-meletium",
    # On Pilgrimages is Ep. 2 of the PG 46 letters.
    "gregory-of-nyssa-letters": "ogpg/vol-046/epistulae",
    "gregory-of-nyssa-on-pilgrimages": "ogpg/vol-046/epistulae",
    # NPNF2 vol. 7: Cyril of Jerusalem.
    "cyril-of-jerusalem-procatechesis": "ogpg/vol-033/procatechesis",
    "cyril-of-jerusalem-catechetical-lectures": "ogpg/vol-033/catecheses",
    "cyril-of-jerusalem-mystagogical-lectures": "ogpg/vol-033/catecheses-mystagogicae",
    # NPNF2 vol. 7: Gregory Nazianzen (Orations 27-31 are linked to First1K above)
    **{f"gregory-nazianzen-oration-{n:02d}": f"ogpg/vol-{35 if n < 27 else 36:03d}/oratio-{n}"
       for n in (1, 2, 3, 7, 8, 12, 16, 18, 21, 33, 34, 37, 38, 39, 40, 41, 42, 43, 45)},
    # The three NPNF letter groups are selections from the PG 37 letters.
    "gregory-nazianzen-correspondence-with-basil": "ogpg/vol-037/epistulae",
    "gregory-nazianzen-letters-on-the-apollinarian-controversy": "ogpg/vol-037/epistulae",
    "gregory-nazianzen-miscellaneous-letters": "ogpg/vol-037/epistulae",
    # NPNF2 vol. 8: Basil
    "basil-hexaemeron": "ogpg/vol-029/in-hexaemeron",
    "basil-on-the-holy-spirit": "ogpg/vol-032/de-spiritu-sancto",
    # NPNF2 vol. 9: John of Damascus
    "john-of-damascus-exposition-of-the-orthodox-faith": "ogpg/vol-094/expositio-fidei",
    # NPNF2 vol. 14: canonical epistles.  NPNF prints most of these abridged
    # (Johnson's summaries), so they are renderings of part of the original.
    "dionysius-of-alexandria-letter-to-basilides": "ogpg/vol-010/dionysius-alexandrinus",
    "gregory-thaumaturgus-canonical-epistle": "ogpg/vol-010/thaumaturgus-epistula-canonica",
    "peter-of-alexandria-canons": "ogpg/vol-018/petrus-alexandrinus",
    # The poem on the canon is Carmen I.1.12 of the Carmina dogmatica.
    "gregory-nazianzen-verses-on-the-canon": "ogpg/vol-037/carmina-dogmatica",
    "gregory-of-nyssa-canonical-epistle-to-letoius": "ogpg/vol-045/epistula-canonica",
    "theophilus-of-alexandria-canonical-writings": "ogpg/vol-065/theophilus-alexandrinus",
    # The letter to Domnus is among PG 77's Epistulae.
    "cyril-of-alexandria-canonical-epistles": "ogpg/vol-077/epistulae",
}

_ORIGINALS: dict[str, str] = {
    # NPNF1: Augustine (OGLT PL)
    "augustine-on-christian-doctrine": _AUG_PL.format("pl34_0_s."),
    "augustine-on-the-trinity": _AUG_PL.format("pl42_14_s."),
    "augustine-enchiridion": _AUG_PL.format("pl40_5_s."),
    "augustine-catechising-the-uninstructed": _AUG_PL.format("pl40_7_s."),
    "augustine-faith-of-things-not-seen": _AUG_PL.format("pl40_4_s."),
    "augustine-on-the-creed": _AUG_PL.format("pl40_8_s."),
    # PL prints the two books on morals as one work.
    "augustine-morals-of-the-catholic-church": _AUG_PL.format("pl32_6_s."),
    "augustine-morals-of-the-manichaeans": _AUG_PL.format("pl32_6_s."),
    "augustine-perfection-in-righteousness": _AUG_PL.format("pl44_0_s."),
    "augustine-proceedings-of-pelagius": _AUG_PL.format("pl44_1_s."),
    "augustine-grace-of-christ-and-original-sin": _AUG_PL.format("pl44_2_s."),
    "augustine-marriage-and-concupiscence": _AUG_PL.format("pl44_4_s."),
    "augustine-grace-and-free-will": _AUG_PL.format("pl44_8_s."),
    "augustine-rebuke-and-grace": _AUG_PL.format("pl44_11_s."),
    "augustine-predestination-of-the-saints": _AUG_PL.format("pl44_14_s."),
    "augustine-gift-of-perseverance": _AUG_PL.format("pl45_0_s."),
    "augustine-sermon-on-the-mount": _AUG_PL.format("pl34_3_s."),
    "augustine-tractates-on-john": _AUG_PL.format("pl35_3_s."),
    "augustine-homilies-on-first-john": _AUG_PL.format("pl35_4_s."),
    "augustine-soliloquies": _AUG_PL.format("pl32_0_s."),
    # Only the PL 36 file of the Enarrationes is in the corpus.
    "augustine-expositions-on-the-psalms": _AUG_PL.format("pl36_0_san"),
    # Sermons 51-147 (Benedictine numbering), all in PL 38's first class of
    # sermons (De Scripturis, Sermons 1-183).
    "augustine-sermons-on-new-testament-lessons": _AUG_PL.format("pl38_0_s."),
    # NPNF1: Chrysostom (PTA)
    "chrysostom-homilies-on-colossians": "pta/pta0002/pta161/pta-grc1",
    # NPNF2 vol. 1-3: historians (First1KGreek), Jerome/Rufinus/Gennadius (OGLT)
    "eusebius-church-history": _F1K.format("tlg2018/tlg002"),
    "eusebius-martyrs-of-palestine": _F1K.format("tlg2018/tlg003"),
    "eusebius-life-of-constantine": _F1K.format("tlg2018/tlg020"),
    "constantine-oration-to-the-assembly-of-the-saints": _F1K.format("tlg2018/tlg021"),
    "eusebius-oration-in-praise-of-constantine": _F1K.format("tlg2018/tlg022"),
    "socrates-ecclesiastical-history": _F1K.format("tlg2057/tlg002"),
    "sozomen-ecclesiastical-history": _F1K.format("tlg2048/tlg001"),
    "theodoret-ecclesiastical-history": _F1K.format("tlg4089/tlg003"),
    "jerome-lives-of-illustrious-men": _JER_PL.format("pl23_21_unknown"),
    "gennadius-lives-of-illustrious-men": "oglt-pl/gennadius-massiliensis/pl58_25_li",
    "rufinus-apology-to-anastasius": "oglt-pl/rufinus-aquileiensis/pl21_6_apo",
    "anastasius-letter-to-john-of-jerusalem": "oglt-pl/anastasius-i/pl21_7_epi",
    "rufinus-apology-against-jerome": "oglt-pl/rufinus-aquileiensis/pl21_5_ruf",
    "jerome-apology-against-rufinus": _JER_PL.format("pl23_17_unknown"),
    "rufinus-commentary-on-the-apostles-creed": "oglt-pl/rufinus-aquileiensis/pl21_2_com",
    # NPNF2 vol. 4: Athanasius (PTA, Athanasius Werke)
    "athanasius-against-the-heathen": "pta/pta0022/pta001/pta-grc1",
    "athanasius-on-the-incarnation": "pta/pta0022/pta002/pta-grc1",
    "athanasius-de-decretis": "pta/pta0022/pta003/pta-grc1",
    "athanasius-de-sententia-dionysii": "pta/pta0022/pta004/pta-grc1",
    "athanasius-apology-to-constantius": "pta/pta0022/pta010/pta-grc1",
    "athanasius-tome-to-the-antiochenes": "pta/pta0022/pta015/pta-grc1",
    # The four discourses (#380).  OGPG PG 26 prints them as one Work.
    "athanasius-discourses-against-the-arians": _F1K.format("tlg2035/tlg130"),
    "athanasius-second-discourse-against-the-arians": _F1K.format("tlg2035/tlg131"),
    "athanasius-third-discourse-against-the-arians": _F1K.format("tlg2035/tlg132"),
    "athanasius-fourth-discourse-against-the-arians": _F1K.format("tlg2035/tlg117"),
    # Personal letters with a PTA edition (#380).  PTA's Petitiones Arianorum
    # are the appendix NPNF prints after Letter LVI.
    "athanasius-letter-49-to-dracontius": "pta/pta0022/pta013/pta-grc1",
    "athanasius-letter-56-to-jovian": "pta/pta0022/pta016/pta-grc1",
    "athanasius-petitions-of-the-arians-to-jovian": "pta/pta0022/pta017/pta-grc1",
    "athanasius-letter-62-to-john-and-antiochus": "pta/pta0022/pta011/pta-grc1",
    "athanasius-letter-63-to-palladius": "pta/pta0022/pta012/pta-grc1",
    "athanasius-letter-to-ammus": "ogpg/vol-026/ad-amunem",
    "athanasius-letter-to-rufinianus": "ogpg/vol-026/ad-rufinianum",
    "athanasius-letter-to-the-bishops-of-africa": "pta/pta0022/pta014/pta-grc1",
    # Urkunde 4 (Opitz): Alexander's letters deposing Arius.
    "alexander-deposition-of-arius": "pta/pta0100/pta002/pta-grc1",
    # NPNF2 vol. 6: Jerome (OGLT)
    "jerome-letters": _JER_PL.format("pl22_0_san"),
    "jerome-life-of-paul-the-hermit": _JER_PL.format("pl23_0_vita"),
    "jerome-life-of-hilarion": _JER_PL.format("pl23_1_vita"),
    "jerome-life-of-malchus": _JER_PL.format("pl23_2_unknown"),
    "jerome-dialogue-against-the-luciferians": _JER_PL.format("pl23_12_s.eusebiihieronymi"),
    "jerome-against-helvidius": _JER_PL.format("pl23_13_unknown"),
    "jerome-against-jovinianus": _JER_PL.format("pl23_14_s.eusebiihieronymi"),
    "jerome-against-vigilantius": _JER_PL.format("pl23_15_s.eusebiihieronymi"),
    "jerome-against-john-of-jerusalem": _JER_PL.format("pl23_16_unknown"),
    "jerome-against-the-pelagians": _JER_PL.format("pl23_19_s.eusebiihieronymi"),
    # Prefaces NPNF translates (#380); some only in part.
    "jerome-preface-to-the-four-gospels": _JER_PL.format("pl29_11_s."),
    "jerome-preface-to-samuel-and-kings": _JER_PL.format("pl28_9_"),
    "jerome-preface-to-job": _JER_PL.format("pl28_16_unknown"),
    "jerome-preface-to-the-books-of-solomon": _JER_PL.format("pl28_18_unknown"),
    "jerome-preface-to-daniel": _JER_PL.format("pl28_21_"),
    # NPNF2 vol. 7: Gregory Nazianzen's Theological Orations (First1KGreek)
    **{f"gregory-nazianzen-oration-{n}": _F1K.format(f"tlg2022/tlg0{t:02d}")
       for n, t in (("27", 7), ("28", 8), ("29", 9), ("30", 10), ("31", 11))},
    # NPNF2 vol. 8: Basil's letters (Perseus)
    "basil-letters": "perseus/tlg2040/tlg004/perseus-grc2",
    # NPNF2 vol. 9: Hilary (OGLT); the homilies are a selection of the Tractatus.
    "hilary-de-synodis": "oglt-pl/hilarius-pictaviensis/pl10_2_457",
    "hilary-on-the-trinity": "oglt-pl/hilarius-pictaviensis/pl10_0_san",
    "hilary-homilies-on-psalms": "oglt-pl/hilarius-pictaviensis/pl9_10_san",
    # NPNF2 vol. 10: Ambrose (OGLT)
    "ambrose-on-the-duties-of-the-clergy": _AMB_PL.format("pl16_0_san"),
    "ambrose-on-the-holy-spirit": _AMB_PL.format("pl16_11_sa"),
    "ambrose-on-the-decease-of-satyrus": _AMB_PL.format("pl16_21_sa"),
    "ambrose-exposition-of-the-christian-faith": _AMB_PL.format("pl16_10_sa"),
    "ambrose-on-the-mysteries": _AMB_PL.format("pl16_7_san"),
    "ambrose-concerning-repentance": _AMB_PL.format("pl16_9_san"),
    "ambrose-concerning-virgins": _AMB_PL.format("pl16_1_san"),
    "ambrose-concerning-widows": _AMB_PL.format("pl16_2_san"),
    # NPNF2 vol. 11-13 (OGLT)
    "vincent-of-lerins-commonitory": "oglt-pl/vincentius-lirinensis/pl50_7_unk",
    "vincent-of-lerins-commonitory-recapitulation": "oglt-pl/vincentius-lirinensis/pl50_8_sec",
    "leo-letters": "oglt-pl/leo-i-magnus/pl54_3_san",
    "leo-sermons": "oglt-pl/leo-i-magnus/pl54_0_ser",
    "gregory-the-great-pastoral-rule": "oglt-pl/gregorius-i-magnus/pl77_0_san",
    # Both NPNF volumes translate a selection of the one PL Registrum.
    "gregory-the-great-register-books-1-8": "oglt-pl/gregorius-i-magnus/pl77_9_",
    "gregory-the-great-register-books-9-14": "oglt-pl/gregorius-i-magnus/pl77_9_",
    # NPNF2 vol. 10: the selected letters (Epp. 17-63), the Sermon against
    # Auxentius (printed after Ep. 21) and Symmachus's Relatio III (printed
    # after Ep. 17) are all in PL 16's first class of Ambrose's letters.
    "ambrose-selected-letters": _AMB_PL.format("pl16_19_sa"),
    "ambrose-sermon-against-auxentius": _AMB_PL.format("pl16_19_sa"),
    "symmachus-memorial-on-the-altar-of-victory": _AMB_PL.format("pl16_19_sa"),
    # NPNF2 vol. 14: Basil's canonical epistles (Epp. 188, 199, 217) belong to
    # the same Perseus letter collection as basil-letters.
    "basil-canonical-epistles": "perseus/tlg2040/tlg004/perseus-grc2",
    # -- Open Patrologia Graeca (OGPG): OCR of Migne's Greek columns, one Work
    # per text (``scripts/ingest/data/ogpg_index.csv``).  Used only where no
    # critical edition of the text is in the corpus, and only split works
    # (``ogpg/vol-NNN/{slug}``), never a volume's ``other`` remainder.  Where
    # the Migne Work holds more than the translation, the comment says so.
    **_PG_ORIGINALS,
}

#: Plausible originals deliberately *not* linked (slug → reason).
_UNLINKED: dict[str, str] = {
    "athanasius-canonical-epistles": "Festal 39's Greek is inside OGPG PG 26's Epistulae festales",
    "athanasius-personal-letters": (
        "the letters left in it (Sardica, Lucifer, Diodorus) have no original in the corpus"),
    "athanasius-festal-letters": "survive in Syriac; OGPG PG 26 has only a Greek fragment",
    "eusebius-letter-to-his-church": "Opitz Urk. 22 is not among the PTA Dokumente in corpus",
    "rufinus-prefaces-to-translations": "prefaces scattered across several PL works",
    "jerome-prefaces": (
        "the prefaces left in it are mostly the editor's summaries, or in commentaries"),
    "gregory-of-nyssa-on-the-holy-trinity": "printed as Basil's Ep. 189, not as a work of Gregory",
    "apostolic-canons": "not inside OGPG PG 1's Constitutiones apostolicae (which ends at 8.46)",
    "amphilochius-iambics-to-seleucus": "the Iambi are not in OGPG PG 39's Amphilochius",
    "gennadius-encyclical-letter": "not found in the OCR of OGPG PG 85's Gennadius",
    "timothy-of-alexandria-canonical-answers": "OGPG prints it in a two-author Work (PG 33)",
    "theodoret-counter-statements": (
        "quoted in Cyril's Apologia contra Theodoretum, not a split OGPG PG 76 Work"),
}

_WORKS = link_originals(_WORKS, _ORIGINALS)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one JSON file per ``_WORKS`` row (see ``_ccel_works.ingest_table``)."""
    return ingest_table(output_dir, SOURCE_ID, _WORKS, force=force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
