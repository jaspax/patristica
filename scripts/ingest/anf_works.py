"""
Ingestor for properly attributed works carved out of the CCEL Ante-Nicene Fathers.

Source: CCEL Ante-Nicene Fathers Vols. 1–9 (Roberts–Donaldson–Coxe, 1885–1897)
        https://ccel.org/ccel/s/schaff/anf{01..09}.xml
License: Public domain
Language: eng

The generic ``ccel_anf`` ingestor emits one Work per ThML ``<div1>``, using a
fuzzy heading heuristic for the author.  In most ANF volumes that heuristic
fails (headings such as "Title Page.", "Apologetic.", "Irenæus") or a div1
lumps several distinct authors and works together (the Ignatian corpus with
its spurious letters, "Remains of the Second and Third Centuries", the New
Testament Apocrypha, ...).  This module re-emits those texts as one Work per
distinct work with correct author, title, date, tradition and genre, driven by
the ``_WORKS`` table below.

Every div taken here is registered in ``_ccel_common.EXCLUDED_DIVS`` (value
``"anf-works"``) so the text is not in the corpus twice; the
editors' apparatus (prefaces, introductory notices, elucidations) is
registered there as ``"non-text: editorial"``.  With both in place the generic
``ccel_anf`` ingestor produces no Works at all.  Extraction mechanics (refs,
nested editorial divs, output layout) are in ``_ccel_works``.

Output: ``data/raw/anf-works/{volume}/{slug}.json``; work_id
``anf-works/{slug}``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from patristica.models import Work
from scripts.ingest._ccel_works import (  # noqa: F401  (re-exported for tests)
    P,
    W,
    _editorial_ids,
    _index_ids,
    _split_commentary,
    _WorkSpec,
    extract_work,
    ingest_table,
    link_originals,
)

from scripts.ingest._printed_verses import rechunk

log = logging.getLogger(__name__)

SOURCE_ID = "anf-works"

_TERT = "Tertullian"
_PS_TERT = "Pseudo-Tertullian"
_CYPR = "Cyprian of Carthage"
_ORIG = "Origen of Alexandria"
_HIPPO = "Hippolytus of Rome"
_PS_CLEM = "Pseudo-Clement of Rome"
_METH = "Methodius of Olympus"


# ---------------------------------------------------------------------------
# Works nested inside another work's div (#381).  ANF prints a few texts as a
# sub-div of a larger one: Ad Donatum as Cyprian's "Epistle I", the Epitome as
# an eighth "book" of the Divine Institutes, Clement's fragments after the
# Stromata.  Both rows read the outer div; the outer row drops the nested
# text's paragraphs (``_without``) and the nested row keeps only them under
# a ref prefix of its own (``_only``), so the outer work keeps its refs.
# ---------------------------------------------------------------------------

_Paras = list[dict]


def _under(ref: str, prefix: str) -> bool:
    return ref == prefix or ref.startswith(prefix + ".")


def _without(prefix: str, keep_root: bool = False) -> Callable[[_Paras], _Paras]:
    """Drop the paragraphs under *prefix* (all but the one at *prefix* itself
    when *keep_root*: the outer work's own heading printed in the nested div)."""
    def drop(paras: _Paras) -> _Paras:
        out = [p for p in paras
               if not _under(p["ref"], prefix) or (keep_root and p["ref"] == prefix)]
        if len(out) == len(paras):
            raise RuntimeError(f"No paragraphs under {prefix!r} to drop")
        return out
    return drop


def _only(
    prefix: str, renamed: str, drop_root: bool = False,
    editorial: Callable[[str], str | None] = lambda ref: None,
) -> Callable[[_Paras], _Paras]:
    """Keep the paragraphs under *prefix* (in this row's own refs: its
    ``ref_prefix`` plus the nested div's number), with *prefix* renamed to *renamed*.

    *editorial* maps a renamed ref to the editorial kind of that whole unit
    (``patristica.editorial``, #236), or ``None``.
    """
    def keep(paras: _Paras) -> _Paras:
        out: _Paras = []
        for p in paras:
            if not _under(p["ref"], prefix) or (drop_root and p["ref"] == prefix):
                continue
            ref = renamed + p["ref"][len(prefix):]
            unit: dict = {"ref": ref, "text": p["text"]}
            kind = editorial(ref)
            if kind:
                unit["editorial"] = [[0, len(p["text"]), kind]]
            out.append(unit)
        if not out:
            raise RuntimeError(f"No paragraphs under {prefix!r}")
        return out
    return keep


def _marks(kinds: dict[str, str]) -> Callable[[str], str | None]:
    return kinds.get


#: ANF's apparatus inside the nested texts: headings and the translator's notes.
_DONATUS_EDITORIAL = _marks({
    "Cypr.Don.2": "heading",   # "Epistle I." (the Oxford numbering)
    "Cypr.Don.3": "title",     # "To Donatus."
    "Cypr.Don.4": "note",      # the translator's "Argument.—…"
})
_EPITOME_EDITORIAL = _marks({"Lact.Epit": "title"})  # "Addressed to His Brother Pentadius."
_CLEMENT_FRAGMENTS_EDITORIAL = _marks({
    "Clem.Frag": "note",  # "[Translated by Rev. William Wilson, M.A.]"
    # Wilson's note on the Instructor passage in Cramer's catena, its list of
    # readings, and Coxe's closing note on the Adumbrations.
    **{f"Clem.Frag.{n}": "note" for n in range(174, 198)},
})

_WORKS: tuple[_WorkSpec, ...] = (
    # ------------------------------------------------------------------ ANF01
    W("anf01", "first-clement", "The First Epistle of Clement to the Corinthians",
      "Clement of Rome", 96, (95, 97), "established", "greek", "1Clem",
      P("ii.ii", "First Epistle to the Corinthians")),
    W("anf01", "polycarp-epistle-to-the-philippians", "The Epistle of Polycarp to the Philippians",
      "Polycarp of Smyrna", 135, (110, 140), "approximate", "greek", "Pol.Phil",
      P("iv.ii", "Epistle to the Philippians")),
    *(W("anf01", f"ignatius-{slug}",
        f"The Epistle of Ignatius {to} (shorter and longer recensions)",
        "Ignatius of Antioch", 107, (105, 115), "approximate", "greek", f"Ign.{abbr}",
        P(div, check))
      for slug, to, abbr, div, check in (
          ("to-the-ephesians", "to the Ephesians", "Eph", "v.ii", "Epistle to the Ephesians"),
          ("to-the-magnesians", "to the Magnesians", "Magn", "v.iii", "Magnesians"),
          ("to-the-trallians", "to the Trallians", "Trall", "v.iv", "Trallians"),
          ("to-the-romans", "to the Romans", "Rom", "v.v", "Epistle to the Romans"),
          ("to-the-philadelphians", "to the Philadelphians", "Phld", "v.vi", "Philadelphians"),
          ("to-the-smyrnaeans", "to the Smyrnaeans", "Smyrn", "v.vii", "Smyrn"),
          ("to-polycarp", "to Polycarp", "Pol", "v.viii", "Epistle to Polycarp"))),
    W("anf01", "ignatius-syriac-recension",
      "The Epistles of Ignatius: Syriac Recension (to Polycarp, the Ephesians, the Romans)",
      "Ignatius of Antioch", 107, (105, 115), "approximate", "syriac", "Ign.Syr",
      P("v.x", "Syriac Version", "Pol"), P("v.xi", "Syriac Version", "Eph"),
      P("v.xii", "Syriac Version", "Rom")),
    W("anf01", "epistle-to-diognetus", "The Epistle to Diognetus", None,
      150, (130, 200), "uncertain", "greek", "DiogNet",
      P("iii.ii", "Epistle to Diognetus")),
    W("anf01", "martyrdom-of-polycarp",
      "The Martyrdom of Polycarp (Encyclical Epistle of the Church at Smyrna)", None,
      156, (155, 160), "approximate", "greek", "MartPol",
      P("iv.iv", "Martyrdom of Polycarp")),
    W("anf01", "pseudo-ignatian-epistles",
      "Spurious Epistles of Ignatius (Tarsians, Antiochians, Hero, Philippians, "
      "Maria of Cassobelae, Mary at Neapolis)",
      "Pseudo-Ignatius", 375, (360, 400), "approximate", "greek", "PsIgn",
      P("v.xiv", "Tarsians", "Tars"), P("v.xv", "Antiochians", "Ant"),
      P("v.xvi", "Hero", "Her"), P("v.xvii", "Philippians", "Phil"),
      P("v.xviii", "Maria of Cassobel", "MarIgn"), P("v.xix", "Mary at Neapolis", "Mar")),
    W("anf01", "ignatius-latin-correspondence",
      "Latin Correspondence of Ignatius with St. John and the Virgin Mary (spurious)",
      "Pseudo-Ignatius", None, (800, 1150), "uncertain", "latin", "PsIgnLat",
      P("v.xx", "First Epistle to St John", "Jn1"),
      P("v.xxi", "Second Epistle to St John", "Jn2"),
      P("v.xxii", "Epistle to Mary the Virgin", "Mar"),
      P("v.xxiii", "Epistle from Mary the Virgin", "MarIgn")),
    W("anf01", "martyrdom-of-ignatius", "The Martyrdom of Ignatius", None,
      400, (350, 500), "uncertain", "greek", "MartIgn",
      P("v.xxv", "Martyrdom of Ignatius")),
    W("anf01", "epistle-of-barnabas", "The Epistle of Barnabas", "Pseudo-Barnabas",
      130, (70, 135), "approximate", "greek", "Barn",
      P("vi.ii", "Epistle of Barnabas")),
    W("anf01", "papias-fragments", "Fragments of Papias", "Papias of Hierapolis",
      120, (100, 130), "approximate", "greek", "Papias",
      P("vii.ii", "Fragments")),
    W("anf01", "pseudo-justin-discourse-to-the-greeks", "Discourse to the Greeks",
      "Pseudo-Justin", 200, (150, 300), "uncertain", "greek", "PsJust.OrGr",
      P("viii.v", "Discourse to the Greeks")),
    W("anf01", "pseudo-justin-hortatory-address", "Hortatory Address to the Greeks",
      "Pseudo-Justin", 260, (220, 300), "uncertain", "greek", "PsJust.Coh",
      P("viii.vi", "Hortatory Address")),
    W("anf01", "pseudo-justin-sole-government-of-god", "On the Sole Government of God",
      "Pseudo-Justin", 200, (150, 300), "uncertain", "greek", "PsJust.Mon",
      P("viii.vii", "Sole Government of God")),
    W("anf01", "justin-first-apology", "The First Apology", "Justin Martyr",
      155, (150, 160), "established", "greek", "Just.1Apol", P("viii.ii", "First Apology")),
    W("anf01", "justin-second-apology", "The Second Apology", "Justin Martyr",
      157, (153, 161), "approximate", "greek", "Just.2Apol", P("viii.iii", "Second Apology")),
    W("anf01", "justin-dialogue-with-trypho", "Dialogue with Trypho, a Jew", "Justin Martyr",
      160, (155, 165), "approximate", "greek", "Just.Dial", P("viii.iv", "Dialogue with Trypho")),
    W("anf01", "justin-on-the-resurrection", "Fragments of the Lost Work on the Resurrection",
      "Justin Martyr", 160, (150, 200), "uncertain", "greek", "Just.Res",
      P("viii.viii", "On the Resurrection")),
    W("anf01", "justin-other-fragments", "Other Fragments from the Lost Writings of Justin",
      "Justin Martyr", 160, (150, 165), "uncertain", "greek", "Just.Frag",
      P("viii.ix", "Other Fragments")),
    W("anf01", "martyrdom-of-justin",
      "The Martyrdom of the Holy Martyrs Justin, Chariton, Charites, Paeon, and Liberianus",
      None, 170, (165, 200), "approximate", "greek", "MartJust",
      P("viii.xi", "Martyrdom of Justin")),
    W("anf01", "irenaeus-against-heresies", "Against Heresies (Adversus Haereses)",
      "Irenaeus of Lyon", 180, (175, 189), "approximate", "greek", "Iren.Haer",
      P("ix.ii", "Book I", "1"), P("ix.iii", "Book II", "2"), P("ix.iv", "Book III", "3"),
      P("ix.vi", "Book IV", "4"), P("ix.vii", "Book V", "5")),
    W("anf01", "irenaeus-fragments", "Fragments from the Lost Writings of Irenaeus",
      "Irenaeus of Lyon", 185, (170, 202), "uncertain", "greek", "Iren.Frag",
      P("ix.viii", "Fragments")),

    # ------------------------------------------------------------------ ANF02
    W("anf02", "shepherd-of-hermas", "The Shepherd of Hermas (Visions, Commandments, Similitudes)",
      "Hermas", 140, (100, 160), "approximate", "greek", "Herm",
      P("ii.ii", "Visions", "Vis"), P("ii.iii", "Commandments", "Mand"),
      P("ii.iv", "Similitudes", "Sim")),
    W("anf02", "tatian-address-to-the-greeks", "Address to the Greeks (Oratio ad Graecos)",
      "Tatian", 170, (165, 175), "approximate", "greek", "Tat.OrGr",
      P("iii.ii", "Address to the Greeks")),
    W("anf02", "tatian-fragments", "Fragments of Tatian", "Tatian",
      170, (160, 180), "uncertain", "greek", "Tat.Frag", P("iii.iii", "Fragments")),
    W("anf02", "theophilus-to-autolycus", "To Autolycus", "Theophilus of Antioch",
      181, (180, 185), "approximate", "greek", "Theoph.Autol",
      P("iv.ii", "Theophilus to Autolycus")),
    W("anf02", "athenagoras-plea-for-the-christians", "A Plea for the Christians (Legatio)",
      "Athenagoras of Athens", 177, (176, 180), "approximate", "greek", "Athen.Leg",
      P("v.ii", "Plea for the Christians")),
    W("anf02", "athenagoras-resurrection-of-the-dead", "On the Resurrection of the Dead",
      "Athenagoras of Athens", 180, (177, 250), "uncertain", "greek", "Athen.Res",
      P("v.iii", "Resurrection of the Dead")),
    W("anf02", "clement-exhortation-to-the-heathen", "Exhortation to the Heathen (Protrepticus)",
      "Clement of Alexandria", 195, (190, 200), "approximate", "greek", "Clem.Protr",
      P("vi.ii", "Exhortation to the Heathen")),
    W("anf02", "clement-the-instructor", "The Instructor (Paedagogus)",
      "Clement of Alexandria", 198, (190, 205), "approximate", "greek", "Clem.Paid",
      P("vi.iii", "Instructor")),
    W("anf02", "clement-stromata", "The Stromata, or Miscellanies",
      "Clement of Alexandria", 202, (198, 215), "approximate", "greek", "Clem.Strom",
      P("vi.iv", "Stromata"), rechunk=_without("Clem.Strom.9")),  # clement-fragments
    W("anf02", "clement-who-is-the-rich-man", "Who is the Rich Man that Shall be Saved?",
      "Clement of Alexandria", 200, (190, 210), "approximate", "greek", "Clem.QDS",
      P("vi.v", "Rich Man")),

    # ------------------------------------------------------------------ ANF03
    W("anf03", "tertullian-apology", "Apology (Apologeticum)", _TERT,
      197, (196, 198), "established", "latin", "Tert.Apol", P("iv.iii", "Apology")),
    W("anf03", "tertullian-on-idolatry", "On Idolatry", _TERT,
      203, (198, 211), "approximate", "latin", "Tert.Idol", P("iv.iv", "On Idolatry")),
    W("anf03", "tertullian-de-spectaculis", "The Shows (De Spectaculis)", _TERT,
      198, (196, 202), "approximate", "latin", "Tert.Spect", P("iv.v", "De Spectaculis")),
    W("anf03", "tertullian-de-corona", "The Chaplet (De Corona)", _TERT,
      211, (211, 212), "approximate", "latin", "Tert.Cor", P("iv.vi", "De Corona")),
    W("anf03", "tertullian-to-scapula", "To Scapula", _TERT,
      212, (212, 213), "approximate", "latin", "Tert.Scap", P("iv.vii", "To Scapula")),
    W("anf03", "tertullian-ad-nationes", "Ad Nationes", _TERT,
      197, (196, 198), "approximate", "latin", "Tert.Nat", P("iv.viii", "Ad Nationes")),
    W("anf03", "tertullian-answer-to-the-jews", "An Answer to the Jews", _TERT,
      200, (195, 210), "approximate", "latin", "Tert.AdvJud",
      P("iv.ix", "Answer to the Jews")),
    W("anf03", "tertullian-souls-testimony", "The Soul's Testimony", _TERT,
      198, (197, 200), "approximate", "latin", "Tert.TestAn",
      P("iv.x", "Soul's Testimony")),
    W("anf03", "tertullian-on-the-soul", "A Treatise on the Soul (De Anima)", _TERT,
      210, (208, 212), "approximate", "latin", "Tert.An",
      P("iv.xi", "Treatise on the Soul")),
    W("anf03", "tertullian-prescription-against-heretics",
      "The Prescription Against Heretics", _TERT,
      200, (198, 203), "approximate", "latin", "Tert.PraescHaer",
      P("v.iii", "Prescription Against Heretics")),
    W("anf03", "tertullian-against-marcion", "The Five Books Against Marcion", _TERT,
      208, (207, 212), "approximate", "latin", "Tert.Marc",
      P("v.iv", "Against Marcion")),
    W("anf03", "tertullian-against-hermogenes", "Against Hermogenes", _TERT,
      205, (200, 206), "approximate", "latin", "Tert.Herm",
      P("v.v", "Against Hermogenes")),
    W("anf03", "tertullian-against-the-valentinians", "Against the Valentinians", _TERT,
      207, (206, 210), "approximate", "latin", "Tert.Val",
      P("v.vi", "Against the Valentinians")),
    W("anf03", "tertullian-on-the-flesh-of-christ", "On the Flesh of Christ", _TERT,
      207, (206, 208), "approximate", "latin", "Tert.CarnChr",
      P("v.vii", "Flesh of Christ")),
    W("anf03", "tertullian-resurrection-of-the-flesh",
      "On the Resurrection of the Flesh", _TERT,
      208, (208, 212), "approximate", "latin", "Tert.Res",
      P("v.viii", "Resurrection of the Flesh")),
    W("anf03", "tertullian-against-praxeas", "Against Praxeas", _TERT,
      213, (210, 217), "approximate", "latin", "Tert.Prax",
      P("v.ix", "Against Praxeas")),
    W("anf03", "tertullian-scorpiace", "Scorpiace", _TERT,
      211, (203, 213), "approximate", "latin", "Tert.Scorp", P("v.x", "Scorpiace")),
    W("anf03", "pseudo-tertullian-against-all-heresies", "Against All Heresies",
      _PS_TERT, 240, (220, 260), "uncertain", "latin", "PsTert.Haer",
      P("v.xi", "Against All Heresies")),
    W("anf03", "tertullian-on-repentance", "On Repentance", _TERT,
      203, (198, 206), "approximate", "latin", "Tert.Paen", P("vi.ii", "On Repentance")),
    W("anf03", "tertullian-on-baptism", "On Baptism", _TERT,
      198, (196, 206), "approximate", "latin", "Tert.Bapt", P("vi.iii", "On Baptism")),
    W("anf03", "tertullian-on-prayer", "On Prayer", _TERT,
      200, (198, 204), "approximate", "latin", "Tert.Orat", P("vi.iv", "On Prayer")),
    W("anf03", "tertullian-ad-martyras", "To the Martyrs (Ad Martyras)", _TERT,
      197, (197, 203), "approximate", "latin", "Tert.Mart", P("vi.v", "Ad Martyras")),
    W("anf03", "passion-of-perpetua-and-felicitas",
      "The Passion of the Holy Martyrs Perpetua and Felicitas", None,
      203, (203, 210), "approximate", "latin", "PassPerp",
      P("vi.vi", "Perpetua and Felicitas")),
    W("anf03", "tertullian-of-patience", "Of Patience", _TERT,
      202, (200, 206), "approximate", "latin", "Tert.Pat", P("vi.vii", "On Patience")),

    # ------------------------------------------------------------------ ANF04
    W("anf04", "tertullian-on-the-pallium", "On the Pallium", _TERT,
      209, (205, 211), "approximate", "latin", "Tert.Pall", P("iii.ii", "On the Pallium")),
    W("anf04", "tertullian-apparel-of-women", "On the Apparel of Women", _TERT,
      202, (197, 206), "approximate", "latin", "Tert.CultFem",
      P("iii.iii", "Apparel of Women")),
    W("anf04", "tertullian-veiling-of-virgins", "On the Veiling of Virgins", _TERT,
      207, (206, 213), "approximate", "latin", "Tert.VirgVel",
      P("iii.iv", "Veiling of Virgins")),
    W("anf04", "tertullian-to-his-wife", "To His Wife", _TERT,
      202, (200, 206), "approximate", "latin", "Tert.Ux", P("iii.v", "To His Wife")),
    W("anf04", "tertullian-exhortation-to-chastity", "On Exhortation to Chastity", _TERT,
      208, (204, 212), "approximate", "latin", "Tert.ExhCast",
      P("iii.vi", "Exhortation to Chastity")),
    W("anf04", "tertullian-on-monogamy", "On Monogamy", _TERT,
      213, (210, 217), "approximate", "latin", "Tert.Monog", P("iii.vii", "On Monogamy")),
    W("anf04", "tertullian-on-modesty", "On Modesty", _TERT,
      217, (210, 220), "approximate", "latin", "Tert.Pud", P("iii.viii", "On Modesty")),
    W("anf04", "tertullian-on-fasting", "On Fasting", _TERT,
      213, (210, 220), "approximate", "latin", "Tert.Jejun", P("iii.ix", "On Fasting")),
    W("anf04", "tertullian-de-fuga", "Flight in Persecution (De Fuga in Persecutione)",
      _TERT, 208, (203, 212), "approximate", "latin", "Tert.Fug",
      P("iii.x", "De Fuga")),
    W("anf04", "pseudo-tertullian-strain-of-jonah", "A Strain of Jonah the Prophet",
      _PS_TERT, 450, (350, 550), "uncertain", "latin", "PsTert.Jon",
      P("iii.xi.i", "Jonah")),
    W("anf04", "pseudo-tertullian-strain-of-sodom", "A Strain of Sodom",
      _PS_TERT, 450, (350, 550), "uncertain", "latin", "PsTert.Sod",
      P("iii.xi.ii", "Sodom")),
    W("anf04", "pseudo-tertullian-genesis", "Genesis (verse paraphrase)",
      _PS_TERT, 425, (350, 550), "uncertain", "latin", "PsTert.Gen",
      P("iii.xi.iii", "Genesis")),
    W("anf04", "pseudo-tertullian-judgment-of-the-lord",
      "A Strain of the Judgment of the Lord",
      _PS_TERT, 450, (350, 550), "uncertain", "latin", "PsTert.Jud",
      P("iii.xi.iv", "Judgment of the Lord")),
    W("anf04", "pseudo-tertullian-reply-to-marcion",
      "Five Books in Reply to Marcion (Carmen adversus Marcionitas)",
      _PS_TERT, 425, (350, 500), "uncertain", "latin", "PsTert.CarmMarc",
      P("iii.xi.v", "Reply to Marcion")),
    W("anf04", "minucius-felix-octavius", "The Octavius", "Minucius Felix",
      200, (160, 250), "uncertain", "latin", "MinFel.Oct",
      P("iv.iii", "Octavius")),
    W("anf04", "commodian-instructions", "The Instructions of Commodianus", "Commodian",
      250, (240, 460), "uncertain", "latin", "Commod.Instr",
      P("v.ii", "Instructions of Commodianus")),
    W("anf04", "rufinus-prologue-to-de-principiis",
      "Prologue to his Translation of Origen's De Principiis", "Rufinus of Aquileia",
      398, (397, 398), "established", "latin", "Ruf.PrologPrinc",
      P("vi.iv", "Prologue of Rufinus")),
    W("anf04", "origen-de-principiis", "De Principiis (On First Principles)", _ORIG,
      225, (220, 230), "approximate", "greek", "Orig.Princ",
      P("vi.v", "De Principiis")),
    W("anf04", "africanus-letter-to-origen",
      "A Letter to Origen from Africanus About the History of Susanna",
      "Julius Africanus", 240, (238, 245), "approximate", "greek", "Afric.EpOrig",
      P("vi.vi", "Letter to Origen from Africanus")),
    W("anf04", "origen-letter-to-africanus", "A Letter from Origen to Africanus", _ORIG,
      240, (238, 245), "approximate", "greek", "Orig.EpAfric",
      P("vi.vii", "Origen to Africanus")),
    W("anf04", "origen-letter-to-gregory", "A Letter from Origen to Gregory", _ORIG,
      238, (235, 240), "approximate", "greek", "Orig.EpGreg",
      P("vi.viii", "Origen to Gregory")),
    W("anf04", "origen-against-celsus", "Against Celsus (Contra Celsum)", _ORIG,
      248, (246, 250), "established", "greek", "Orig.CelsCont",
      P("vi.ix", "Against Celsus")),

    # ------------------------------------------------------------------ ANF05
    W("anf05", "hippolytus-refutation-of-all-heresies",
      "The Refutation of All Heresies", _HIPPO,
      225, (222, 235), "approximate", "greek", "Hippo.Haer",
      P("iii.iii", "Refutation of All Heresies")),
    W("anf05", "hippolytus-exegetical-fragments", "Exegetical Works and Fragments",
      _HIPPO, 215, (200, 235), "uncertain", "greek", "Hippo.Exeg",
      P("iii.iv.i", "Exegetical")),
    # Part II, "Dogmatical and Historical", one work per treatise (#315): each is a
    # separate OGPG PG 10 work; the fragments of homilies and other writings stay together.
    W("anf05", "hippolytus-christ-and-antichrist", "Treatise on Christ and Antichrist",
      _HIPPO, 202, (200, 210), "approximate", "greek", "Hippo.Antichr",
      P("iii.iv.ii.i", "Christ and Antichrist")),
    W("anf05", "hippolytus-against-the-jews", "Expository Treatise Against the Jews",
      _HIPPO, 215, (200, 235), "uncertain", "greek", "Hippo.Jud",
      P("iii.iv.ii.ii", "Against the Jews")),
    W("anf05", "hippolytus-against-plato", "Against Plato, on the Cause of the Universe",
      _HIPPO, 215, (200, 235), "uncertain", "greek", "Hippo.Plat",
      P("iii.iv.ii.iii", "Against Plato")),
    W("anf05", "hippolytus-against-noetus", "Against the Heresy of One Noetus",
      _HIPPO, 220, (200, 235), "approximate", "greek", "Hippo.Noet",
      P("iii.iv.ii.iv", "Noetus")),
    W("anf05", "pseudo-hippolytus-against-beron-and-helix", "Against Beron and Helix (fragments)",
      "Pseudo-Hippolytus", None, (600, 900), "uncertain", "greek", "PsHippo.Beron",
      P("iii.iv.ii.v", "Beron")),
    W("anf05", "pseudo-hippolytus-on-the-theophany", "The Discourse on the Holy Theophany",
      "Pseudo-Hippolytus", None, (300, 600), "uncertain", "greek", "PsHippo.Theoph",
      P("iii.iv.ii.vi", "Theophany")),
    W("anf05", "hippolytus-fragments-of-discourses",
      "Fragments of Discourses or Homilies, and from Other Writings",
      _HIPPO, 215, (200, 235), "uncertain", "greek", "Hippo.DogmFrag",
      P("iii.iv.ii.vii", "Fragments of Discourses", "Disc"),
      P("iii.iv.ii.viii", "Other Writings", "Other"), P("iii.iv.ii.ix", "Elucidation", "Eluc")),
    W("anf05", "pseudo-hippolytus-end-of-the-world",
      "Discourse on the End of the World, and on Antichrist",
      "Pseudo-Hippolytus", None, (500, 1000), "uncertain", "greek", "PsHippo.Consumm",
      P("iii.v.i", "discourse by the most blessed Hippolytus")),
    W("anf05", "pseudo-hippolytus-twelve-and-seventy-apostles",
      "On the Twelve Apostles and On the Seventy Apostles",
      "Pseudo-Hippolytus", None, (500, 1000), "uncertain", "greek", "PsHippo.Apost",
      P("iii.v.ii", "Twelve Apostles", "12"), P("iii.v.iii", "Seventy Apostles", "70")),
    W("anf05", "canons-of-hippolytus",
      "Canons of Hippolytus (Heads of the Canons of Abulides; Canons of the Church "
      "of Alexandria)", None, 338, (336, 400), "uncertain", "greek", "CanHippo",
      P("iii.v.iv", "Canons of Abulide", "Heads"),
      P("iii.v.v", "Canons of the Church of Alexandria", "Can")),
    W("anf05", "pontius-life-of-cyprian", "The Life and Passion of Cyprian",
      "Pontius the Deacon", 259, (258, 262), "approximate", "latin", "Pont.VitCypr",
      P("iv.iii", "Life and Passion of Cyprian")),
    W("anf05", "cyprian-epistles", "The Epistles of Cyprian (with letters to him)", _CYPR,
      253, (249, 258), "approximate", "latin", "Cypr.Ep",
      P("iv.iv", "Epistles of Cyprian"),
      rechunk=_without("Cypr.Ep.I", keep_root=True)),  # cyprian-to-donatus
    W("anf05", "cyprian-unity-of-the-church", "On the Unity of the Church", _CYPR,
      251, (249, 253), "established", "latin", "Cypr.Unit",
      P("iv.v.i", "Unity of the Church")),
    W("anf05", "cyprian-dress-of-virgins", "On the Dress of Virgins", _CYPR,
      249, (248, 249), "approximate", "latin", "Cypr.HabVirg",
      P("iv.v.ii", "Dress of Virgins")),
    W("anf05", "cyprian-on-the-lapsed", "On the Lapsed", _CYPR,
      251, (249, 253), "established", "latin", "Cypr.Laps", P("iv.v.iii", "Lapsed")),
    W("anf05", "cyprian-lords-prayer", "On the Lord's Prayer", _CYPR,
      252, (251, 252), "approximate", "latin", "Cypr.DomOr",
      P("iv.v.iv", "Lord's Prayer")),
    W("anf05", "cyprian-to-demetrianus", "An Address to Demetrianus", _CYPR,
      252, (252, 253), "approximate", "latin", "Cypr.Demetr",
      P("iv.v.v", "Demetrianus")),
    W("anf05", "cyprian-vanity-of-idols", "On the Vanity of Idols", _CYPR,
      247, (246, 248), "uncertain", "latin", "Cypr.Idol",
      P("iv.v.vi", "Vanity of Idols")),
    W("anf05", "cyprian-on-the-mortality", "On the Mortality", _CYPR,
      252, (252, 254), "approximate", "latin", "Cypr.Mort", P("iv.v.vii", "Mortality")),
    W("anf05", "cyprian-works-and-alms", "On Works and Alms", _CYPR,
      253, (252, 254), "approximate", "latin", "Cypr.OpEl",
      P("iv.v.viii", "Works and Alms")),
    W("anf05", "cyprian-advantage-of-patience", "On the Advantage of Patience", _CYPR,
      256, (256, 256), "approximate", "latin", "Cypr.BonPat",
      P("iv.v.ix", "Advantage of Patience")),
    W("anf05", "cyprian-jealousy-and-envy", "On Jealousy and Envy", _CYPR,
      256, (256, 257), "approximate", "latin", "Cypr.Zel",
      P("iv.v.x", "Jealousy and Envy")),
    W("anf05", "cyprian-exhortation-to-martyrdom",
      "Exhortation to Martyrdom, Addressed to Fortunatus", _CYPR,
      257, (250, 257), "approximate", "latin", "Cypr.Fort",
      P("iv.v.xi", "Exhortation to Martyrdom")),
    W("anf05", "cyprian-testimonies", "Three Books of Testimonies Against the Jews", _CYPR,
      249, (248, 250), "approximate", "latin", "Cypr.Test",
      P("iv.v.xii", "Testimonies")),
    W("anf05", "seventh-council-of-carthage",
      "The Seventh Council of Carthage under Cyprian, Concerning the Baptism of Heretics",
      None, 256, (256, 256), "established", "latin", "Carth256",
      P("iv.vi", "Seventh Council of Carthage"), genre="council"),
    W("anf05", "novatian-on-the-public-shows",
      "On the Public Shows (De Spectaculis; transmitted among Cyprian's works)",
      "Novatian", 252, (250, 257), "uncertain", "latin", "Novat.Spect",
      P("iv.vii.ii", "Public Shows")),
    W("anf05", "pseudo-cyprian-glory-of-martyrdom", "On the Glory of Martyrdom",
      "Pseudo-Cyprian", 253, (250, 260), "uncertain", "latin", "PsCypr.LaudMart",
      P("iv.vii.iii", "Glory of Martyrdom")),
    W("anf05", "novatian-on-chastity",
      "Of the Discipline and Advantage of Chastity (De Bono Pudicitiae; transmitted "
      "among Cyprian's works)", "Novatian", 252, (250, 257), "uncertain", "latin",
      "Novat.Pud", P("iv.vii.iv", "Chastity")),
    W("anf05", "pseudo-cyprian-exhortation-to-repentance", "Exhortation to Repentance",
      "Pseudo-Cyprian", 300, (250, 450), "uncertain", "latin", "PsCypr.ExhPaen",
      P("iv.vii.v", "Exhortation to Repentance")),
    W("anf05", "caius-fragments", "Fragments of Caius (Dialogue against Proclus)",
      "Caius of Rome", 205, (199, 217), "approximate", "greek", "Caius.Procl",
      P("v.iii.i", "Against Proclus")),
    W("anf05", "against-the-heresy-of-artemon",
      "Against the Heresy of Artemon (the 'Little Labyrinth')", None,
      230, (210, 250), "uncertain", "greek", "LittleLab",
      P("v.iii.ii", "Artemon")),
    W("anf05", "muratorian-fragment", "The Muratorian Canon", None,
      190, (170, 400), "uncertain", "latin", "MuratFrag",
      P("v.iii.iii", "Canon Muratorianus")),
    W("anf05", "novatian-on-the-trinity", "A Treatise Concerning the Trinity", "Novatian",
      245, (240, 250), "approximate", "latin", "Novat.Trin",
      P("vi.iii", "Concerning the Trinity")),
    W("anf05", "novatian-on-the-jewish-meats", "On the Jewish Meats", "Novatian",
      252, (250, 257), "approximate", "latin", "Novat.Cib",
      P("vi.iv", "Jewish Meats")),
    W("anf05", "anonymous-against-novatian",
      "A Treatise Against the Heretic Novatian by an Anonymous Bishop", None,
      255, (253, 258), "uncertain", "latin", "AdNovat",
      P("vii.iii.ii", "Against the Heretic Novatian")),
    W("anf05", "anonymous-on-rebaptism", "A Treatise on Re-Baptism by an Anonymous Writer",
      None, 256, (255, 258), "approximate", "latin", "Rebapt",
      P("vii.iv.ii", "Re-Baptism")),
    W("anf05", "acts-and-records-baptism-of-heretics",
      "Acts and Records of the Controversy About the Baptism of Heretics (Roman synod under "
      "Stephen, from the Libellus Synodicus; Carthaginian councils)", None,
      256, (253, 900), "uncertain", "latin", "BaptHaerActa",
      P("vii.ii", "Baptism of Heretics"), genre="council"),

    # ------------------------------------------------------------------ ANF06
    W("anf06", "gregory-thaumaturgus-declaration-of-faith", "A Declaration of Faith",
      "Gregory Thaumaturgus", 262, (255, 270), "uncertain", "greek", "GregThaum.Fid",
      P("iii.iii.i", "Declaration of Faith")),
    W("anf06", "gregory-thaumaturgus-metaphrase-of-ecclesiastes",
      "A Metaphrase of the Book of Ecclesiastes", "Gregory Thaumaturgus",
      250, (240, 270), "uncertain", "greek", "GregThaum.MetEccl",
      P("iii.iii.ii", "Ecclesiastes")),
    W("anf06", "gregory-thaumaturgus-canonical-epistle", "Canonical Epistle",
      "Gregory Thaumaturgus", 258, (254, 262), "approximate", "greek", "GregThaum.EpCan",
      P("iii.iii.iii", "Canonical Epistle")),
    W("anf06", "gregory-thaumaturgus-panegyric-to-origen",
      "The Oration and Panegyric Addressed to Origen", "Gregory Thaumaturgus",
      238, (238, 239), "approximate", "greek", "GregThaum.PanOrig",
      P("iii.iii.iv", "Panegyric")),
    # The "Dubious or Spurious Writings" as three works (#315): the two that are
    # separate OGPG PG 10 works, and the rest (PG 10's Opuscula dubia).
    W("anf06", "pseudo-gregory-thaumaturgus-sectional-confession",
      "A Sectional Confession of Faith (Kata meros pistis)",
      "Pseudo-Gregory Thaumaturgus", None, (350, 390), "uncertain", "greek",
      "PsGregThaum.Conf", P("iii.iv.i", "Sectional Confession")),
    W("anf06", "pseudo-gregory-thaumaturgus-twelve-topics", "Twelve Topics on the Faith",
      "Pseudo-Gregory Thaumaturgus", None, (350, 500), "uncertain", "greek",
      "PsGregThaum.Top", P("iii.iv.iii", "Twelve Topics")),
    W("anf06", "pseudo-gregory-thaumaturgus-dubious-writings",
      "Dubious or Spurious Writings attributed to Gregory Thaumaturgus "
      "(On the Trinity, On the Soul, Homilies, On All the Saints, On Matthew)",
      "Pseudo-Gregory Thaumaturgus", None, (300, 700), "uncertain", "greek",
      "PsGregThaum", P("iii.iv.ii", "On the Trinity", "Trin"),
      P("iii.iv.iv", "Subject of the Soul", "Anim"), P("iii.iv.v", "Four Homilies", "Hom"),
      P("iii.iv.vi", "All the Saints", "Sanct"), P("iii.iv.vii", "Matthew", "Matt")),
    W("anf06", "dionysius-of-alexandria-fragments",
      "Extant Fragments: Works and Epistles", "Dionysius of Alexandria",
      255, (247, 264), "approximate", "greek", "DionAlex.Frag",
      P("iv.iii", "Extant Fragments")),
    W("anf06", "dionysius-of-alexandria-exegetical-fragments", "Exegetical Fragments",
      "Dionysius of Alexandria", 255, (247, 264), "uncertain", "greek", "DionAlex.Exeg",
      P("iv.iv", "Exegetical Fragments")),
    W("anf06", "africanus-epistle-to-aristides", "The Epistle to Aristides",
      "Julius Africanus", 225, (220, 240), "approximate", "greek", "Afric.EpArist",
      P("v.iii", "Epistle to Aristides")),
    W("anf06", "narrative-of-events-in-persia",
      "Narrative of Events Happening in Persia on the Birth of Christ",
      "Pseudo-Julius Africanus", 500, (450, 650), "uncertain", "greek", "PsAfric.Pers",
      P("v.iv", "Events Happening in Persia")),
    W("anf06", "africanus-chronography",
      "The Extant Fragments of the Five Books of the Chronography", "Julius Africanus",
      221, (221, 222), "approximate", "greek", "Afric.Chron",
      P("v.v", "Chronography")),
    W("anf06", "passion-of-symphorosa", "The Passion of St. Symphorosa and Her Seven Sons",
      None, 400, (300, 600), "uncertain", "latin", "PassSymph",
      P("v.vi", "Symphorosa")),
    W("anf06", "anatolius-paschal-canon", "The Paschal Canon", "Anatolius of Laodicea",
      277, (270, 650), "uncertain", "greek", "Anat.Pasch",
      P("vi.iii.ii", "Paschal Canon")),
    W("anf06", "anatolius-arithmetic", "Fragments of the Books on Arithmetic",
      "Anatolius of Laodicea", 275, (265, 283), "approximate", "greek", "Anat.Arith",
      P("vi.iii.iii", "Arithmetic")),
    W("anf06", "alexander-of-jerusalem-epistles", "From the Epistles of Alexander",
      "Alexander of Jerusalem", 225, (212, 250), "approximate", "greek", "AlexHier.Ep",
      P("vi.iv.ii", "Epistles of Alexander")),
    W("anf06", "theognostus-hypotyposes", "From His Seven Books of Hypotyposes",
      "Theognostus of Alexandria", 270, (250, 282), "approximate", "greek", "Theogn.Hyp",
      P("vi.v.ii", "Hypotyposes")),
    W("anf06", "pierius-fragment", "A Fragment on the First Epistle to the Corinthians",
      "Pierius of Alexandria", 290, (275, 309), "approximate", "greek", "Pier",
      P("vi.vi.ii", "Fragment of a Work of Pierius")),
    W("anf06", "photius-on-pierius", "Bibliotheca, Codex 119 (on the writings of Pierius)",
      "Photius of Constantinople", 855, (845, 870), "approximate", "greek", "Phot.Bibl119",
      P("vi.vi.iii", "Writings of Pierius")),
    W("anf06", "pseudo-theonas-epistle-to-lucianus",
      "The Epistle of Theonas to Lucianus, the Chief Chamberlain (17th-century forgery)",
      "Jérôme Vignier (as Pseudo-Theonas of Alexandria)", 1650, (1630, 1661),
      "approximate", "latin", "PsTheonas",
      P("vi.vii.ii", "Lucianus")),
    W("anf06", "phileas-epistle-to-thmuis", "Fragments of the Epistle to the People of Thmuis",
      "Phileas of Thmuis", 306, (303, 307), "approximate", "greek", "Phil.Thm",
      P("vi.viii.ii", "People of Thmuis")),
    W("anf06", "phileas-epistle-to-meletius",
      "Epistle of Phileas, Hesychius, Pachomius and Theodorus to Meletius",
      "Phileas of Thmuis", 306, (305, 307), "approximate", "latin", "Phil.Melet",
      P("vi.viii.iii", "Meletius")),
    W("anf06", "pseudo-pamphilus-exposition-of-acts",
      "An Exposition of the Chapters of the Acts of the Apostles (Euthalian apparatus)",
      "Pseudo-Pamphilus", 450, (350, 500), "uncertain", "greek", "PsPamph.ActCap",
      P("vi.ix.ii", "Acts of the Apostles")),
    W("anf06", "malchion-synod-of-antioch",
      "Epistle of the Synod of Antioch against Paul of Samosata, and Acts of the "
      "Disputation (written by Malchion)", "Malchion", 268, (268, 269), "established",
      "greek", "Antioch268",
      P("vi.x.ii", "Epistle Written by Malchion", "Ep"),
      P("vi.x.iii", "Fragments Apparently", "EpFrag"),
      P("vi.x.iv", "Acts of the Disputation", "Disp"),
      P("vi.x.v", "Point in the Same Disputation", "Disp2"),
      genre="council"),
    W("anf06", "acts-of-archelaus", "The Acts of the Disputation with the Heresiarch Manes "
      "(Acta Archelai)", "Hegemonius", 340, (330, 348), "approximate", "greek",
      "Hegem.ActArch",
      P("vii.iii", "Disputation with the Heresiarch Manes", "1"),
      P("vii.iv", "Fragment of the Same Disputation", "2")),
    W("anf06", "alexander-of-lycopolis-manichaeans", "Of the Manichaeans",
      "Alexander of Lycopolis", 300, (277, 310), "approximate", "greek", "AlexLyc.Manich",
      P("viii.iii", "Manich")),
    W("anf06", "acts-of-peter-of-alexandria", "The Genuine Acts of Peter of Alexandria",
      None, 400, (311, 600), "uncertain", "greek", "ActPetrAlex",
      P("ix.iii", "Genuine Acts of Peter")),
    W("anf06", "peter-of-alexandria-canonical-epistle", "The Canonical Epistle (Canons)",
      "Peter of Alexandria", 306, (306, 306), "established", "greek", "PetrAlex.EpCan",
      P("ix.iv", "Canonical Epistle"), split="canons"),
    W("anf06", "balsamon-zonaras-on-peter-of-alexandria",
      "Commentaries on the Canonical Epistle of Peter of Alexandria",
      "Theodore Balsamon and John Zonaras", 1170, (1159, 1195), "approximate", "greek",
      "BalsZon.PetrAlex",
      P("ix.iv", "Canonical Epistle"), split="commentary"),
    W("anf06", "peter-of-alexandria-fragments", "Fragments from the Writings of Peter",
      "Peter of Alexandria", 305, (300, 311), "uncertain", "greek", "PetrAlex.Frag",
      P("ix.vi", "Fragments from the Writings of Peter")),
    W("anf06", "alexander-of-alexandria-epistles",
      "Epistles on the Arian Heresy and the Deposition of Arius",
      "Alexander of Alexandria", 322, (319, 328), "approximate", "greek", "AlexAlex.Ep",
      P("x.iii", "Epistles on the Arian Heresy")),
    W("anf06", "methodius-banquet-of-the-ten-virgins",
      "The Banquet of the Ten Virgins; or Concerning Chastity", _METH,
      290, (270, 311), "approximate", "greek", "Meth.Symp",
      P("xi.iii", "Banquet of the Ten Virgins")),
    W("anf06", "methodius-concerning-free-will", "Concerning Free-Will", _METH,
      290, (270, 311), "approximate", "greek", "Meth.Lib",
      P("xi.iv", "Free-Will")),
    W("anf06", "methodius-discourse-on-the-resurrection",
      "From the Discourse on the Resurrection", _METH,
      300, (290, 311), "approximate", "greek", "Meth.Res",
      P("xi.v", "Discourse on the Resurrection")),
    W("anf06", "methodius-fragments", "Fragments of Methodius", _METH,
      300, (270, 311), "uncertain", "greek", "Meth.Frag",
      P("xi.vi", "Fragments", "1"), P("xi.x", "Cross and Passion", "2"),
      P("xi.xi", "Other Fragments", "3"), P("xi.xii", "Two Fragments", "4")),
    W("anf06", "pseudo-methodius-simeon-and-anna",
      "Oration Concerning Simeon and Anna", "Pseudo-Methodius",
      500, (400, 700), "uncertain", "greek", "PsMeth.Sym",
      P("xi.viii", "Simeon and Anna")),
    W("anf06", "pseudo-methodius-oration-on-the-palms", "Oration on the Palms",
      "Pseudo-Methodius", 500, (400, 700), "uncertain", "greek", "PsMeth.Palm",
      P("xi.ix", "Oration on the Palms")),
    W("anf06", "arnobius-against-the-heathen",
      "The Seven Books Against the Heathen (Adversus Gentes)", "Arnobius of Sicca",
      300, (297, 310), "approximate", "latin", "Arnob.Nat",
      P("xii.iii", "Against the Heathen")),

    # ------------------------------------------------------------------ ANF07
    W("anf07", "lactantius-divine-institutes", "The Divine Institutes", "Lactantius",
      311, (303, 313), "approximate", "latin", "Lact.Inst", P("iii.ii", "Divine Institutes"),
      rechunk=_without("Lact.Inst.8")),  # lactantius-epitome
    W("anf07", "lactantius-anger-of-god", "A Treatise on the Anger of God", "Lactantius",
      314, (313, 316), "approximate", "latin", "Lact.Ira", P("iii.iii", "Anger of God")),
    W("anf07", "lactantius-workmanship-of-god", "On the Workmanship of God, or the Formation of Man",
      "Lactantius", 304, (303, 305), "approximate", "latin", "Lact.Opif",
      P("iii.iv", "Workmanship of God")),
    W("anf07", "lactantius-deaths-of-the-persecutors",
      "Of the Manner in Which the Persecutors Died", "Lactantius",
      315, (313, 316), "approximate", "latin", "Lact.Mort", P("iii.v", "Persecutors Died")),
    W("anf07", "lactantius-fragments", "Fragments of Lactantius", "Lactantius",
      310, (290, 325), "uncertain", "latin", "Lact.Frag", P("iii.vi", "Fragments")),
    W("anf07", "venantius-on-easter", "On Easter (De Pascha)", "Venantius Fortunatus",
      570, (560, 600), "approximate", "latin", "VenFort.Pasch",
      P("iv.i", "On Easter", drop_trailing=1)),
    W("anf07", "anonymous-against-the-montanists",
      "Against the Montanists (fragments; ascribed by the ANF editor to Asterius Urbanus)",
      None, 192, (190, 195), "approximate", "greek", "AntiMont",
      P("v.ii", "Asterius Urbanus", drop_trailing=1)),
    W("anf07", "victorinus-on-the-creation-of-the-world", "On the Creation of the World",
      "Victorinus of Pettau", 290, (260, 304), "approximate", "latin", "Victorin.Fabr",
      P("vi.i", "Creation of the World")),
    W("anf07", "victorinus-commentary-on-the-apocalypse",
      "Commentary on the Apocalypse of the Blessed John", "Victorinus of Pettau",
      290, (260, 304), "approximate", "latin", "Victorin.Apoc",
      P("vi.ii", "Apocalypse")),
    W("anf07", "dionysius-of-rome-against-the-sabellians", "Against the Sabellians",
      "Dionysius of Rome", 262, (259, 268), "approximate", "greek", "DionRom.Sabell",
      P("vii.ii", "Against the Sabellians")),
    W("anf07", "second-clement", "An Ancient Homily, Commonly Styled the Second Epistle "
      "of Clement", "Pseudo-Clement (2 Clement)", 140, (100, 160), "uncertain", "greek",
      "2Clem", P("x.iii", "The Homily")),
    W("anf07", "nicene-creed", "The Nicene Creed (Nicaea 325; Constantinople 381)", None,
      325, (325, 381), "established", "greek", "Nicaea1.Creed",
      P("xi", "Nicene Creed"), genre="council"),

    # ------------------------------------------------------------------ ANF08
    W("anf08", "testaments-of-the-twelve-patriarchs",
      "The Testaments of the Twelve Patriarchs", None,
      150, (-100, 200), "uncertain", "greek", "TestXII",
      P("iii.iii", "Reuben", "Reub"), P("iii.iv", "Simeon", "Sim"),
      P("iii.v", "Levi", "Levi"), P("iii.vi", "Judah", "Jud"),
      P("iii.vii", "Issachar", "Iss"), P("iii.viii", "Zebulun", "Zeb"),
      P("iii.ix", "Dan", "Dan"), P("iii.x", "Naphtali", "Naph"),
      P("iii.xi", "Gad", "Gad"), P("iii.xii", "Asher", "Ash"),
      P("iii.xiii", "Joseph", "Jos"), P("iii.xiv", "Benjamin", "Benj")),
    W("anf08", "clement-excerpts-of-theodotus", "Excerpts of Theodotus",
      "Clement of Alexandria", 200, (190, 215), "approximate", "greek", "Clem.ExcTheod",
      P("iv.iii", "Excerpts of Theodotus")),
    W("anf08", "pseudo-clement-epistles-on-virginity", "Two Epistles Concerning Virginity",
      _PS_CLEM, 250, (200, 300), "uncertain", "greek", "PsClem.Virg",
      P("v.iii", "First Epistle of the Blessed Clement", "1"),
      P("v.iv", "Second Epistle of the Same Clement", "2")),
    W("anf08", "pseudo-clementine-recognitions", "The Recognitions of Clement", _PS_CLEM,
      350, (320, 380), "approximate", "greek", "PsClem.Recog",
      P("vi.iii", "Recognitions")),
    W("anf08", "pseudo-clementine-homilies", "The Clementine Homilies", _PS_CLEM,
      330, (300, 380), "approximate", "greek", "PsClem.Hom",
      P("vi.iv", "Clementine Homilies")),
    # New Testament Apocrypha (ANF08 div1 vii)
    W("anf08", "protevangelium-of-james", "The Protevangelium of James", None,
      150, (140, 200), "approximate", "greek", "ProtJas",
      P("vii.iv", "Protevangelium")),
    W("anf08", "gospel-of-pseudo-matthew", "The Gospel of Pseudo-Matthew", None,
      650, (600, 800), "uncertain", "latin", "PsMt",
      P("vii.v", "Pseudo-Matthew")),
    W("anf08", "gospel-of-the-nativity-of-mary", "The Gospel of the Nativity of Mary",
      None, 850, (800, 1000), "uncertain", "latin", "NatMar",
      P("vii.vi", "Nativity of Mary")),
    W("anf08", "history-of-joseph-the-carpenter", "The History of Joseph the Carpenter",
      None, 500, (400, 700), "uncertain", "coptic", "HistJos",
      P("vii.vii", "Joseph the Carpenter")),
    W("anf08", "infancy-gospel-of-thomas",
      "The Gospel of Thomas (Infancy Gospel; First Greek, Second Greek and Latin Forms)",
      None, 175, (140, 400), "uncertain", "greek", "InfThom",
      P("vii.viii", "First Greek Form", "GrA"), P("vii.ix", "Second Greek Form", "GrB"),
      P("vii.x", "Latin Form", "Lat")),
    W("anf08", "arabic-gospel-of-the-infancy", "The Arabic Gospel of the Infancy of the Saviour",
      None, 600, (500, 800), "uncertain", "syriac", "ArabInf",
      P("vii.xi", "Arabic Gospel")),
    W("anf08", "gospel-of-nicodemus",
      "The Gospel of Nicodemus (Acts of Pilate and Descent of Christ into Hell; "
      "Greek and Latin Forms)", None, 425, (350, 600), "uncertain", "greek", "EvNicod",
      P("vii.xii", "Acts of Pilate:  First Greek", "ActGrA"),
      P("vii.xiii", "Acts of Pilate:  Second Greek", "ActGrB"),
      P("vii.xiv", "Descent of Christ into Hell", "DescGr"),
      P("vii.xv", "Acts of Pilate:  Latin", "ActLat"),
      P("vii.xvi", "Descent into Hell:  Latin", "DescLatA"),
      P("vii.xvii", "Descent into Hell:  Latin", "DescLatB")),
    W("anf08", "letter-of-pontius-pilate", "The Letter of Pontius Pilate to the Roman Emperor",
      None, 300, (150, 450), "uncertain", "greek", "EpPil",
      P("vii.xviii", "Letter of Pontius Pilate")),
    W("anf08", "report-of-pilate", "The Report of Pilate the Procurator (Anaphora Pilati; "
      "two Greek forms)", None, 400, (350, 500), "uncertain", "greek", "AnaphPil",
      P("vii.xix", "Report of Pilate", "A"), P("vii.xx", "Report of Pilate", "B")),
    W("anf08", "giving-up-of-pontius-pilate", "The Giving Up of Pontius Pilate (Paradosis "
      "Pilati)", None, 450, (400, 550), "uncertain", "greek", "ParadPil",
      P("vii.xxi", "Giving Up of Pontius Pilate")),
    W("anf08", "death-of-pilate", "The Death of Pilate, Who Condemned Jesus (Mors Pilati)",
      None, 700, (500, 1000), "uncertain", "latin", "MorsPil",
      P("vii.xxii", "Death of Pilate")),
    W("anf08", "narrative-of-joseph-of-arimathea", "The Narrative of Joseph of Arimathaea",
      None, 600, (450, 900), "uncertain", "greek", "NarrJos",
      P("vii.xxiii", "Narrative of Joseph")),
    W("anf08", "avenging-of-the-saviour", "The Avenging of the Saviour (Vindicta Salvatoris)",
      None, 700, (600, 850), "uncertain", "latin", "VindSalv",
      P("vii.xxiv", "Avenging of the Saviour")),
    W("anf08", "acts-of-peter-and-paul", "Acts of the Holy Apostles Peter and Paul", None,
      500, (400, 600), "uncertain", "greek", "ActPetPaul",
      P("vii.xxv", "Peter and Paul")),
    W("anf08", "acts-of-paul-and-thecla", "Acts of Paul and Thecla", None,
      170, (160, 190), "approximate", "greek", "ActPaulThec",
      P("vii.xxvi", "Paul and Thecla")),
    W("anf08", "acts-of-barnabas", "The Acts of Barnabas", None,
      500, (450, 550), "uncertain", "greek", "ActBarn",
      P("vii.xxvii", "Acts of Barnabus")),
    W("anf08", "acts-of-philip", "The Acts of Philip", None,
      400, (350, 450), "uncertain", "greek", "ActPhil",
      P("vii.xxviii", "Acts of Philip")),
    W("anf08", "acts-and-martyrdom-of-andrew", "Acts and Martyrdom of the Holy Apostle Andrew",
      None, 450, (400, 550), "uncertain", "greek", "ActAndr",
      P("vii.xxix", "Apostle Andrew")),
    W("anf08", "acts-of-andrew-and-matthias", "Acts of Andrew and Matthias", None,
      450, (400, 550), "uncertain", "greek", "ActAndrMatt",
      P("vii.xxx", "Andrew and Matthias")),
    W("anf08", "acts-of-peter-and-andrew", "Acts of Peter and Andrew", None,
      600, (500, 800), "uncertain", "greek", "ActPetAndr",
      P("vii.xxxi", "Peter and Andrew")),
    W("anf08", "acts-and-martyrdom-of-matthew", "Acts and Martyrdom of St. Matthew the Apostle",
      None, 550, (450, 700), "uncertain", "greek", "ActMatt",
      P("vii.xxxii", "Matthew the Apostle")),
    W("anf08", "acts-of-thomas", "Acts of the Holy Apostle Thomas, with the Consummation "
      "of Thomas", None, 225, (200, 250), "approximate", "syriac", "ActThom",
      P("vii.xxxiii", "Apostle Thomas", "Acts"), P("vii.xxxiv", "Consummation", "Cons")),
    W("anf08", "martyrdom-of-bartholomew",
      "Martyrdom of the Holy and Glorious Apostle Bartholomew", None,
      550, (450, 700), "uncertain", "greek", "MartBarth",
      P("vii.xxxv", "Bartholomew")),
    W("anf08", "acts-of-thaddaeus", "Acts of the Holy Apostle Thaddaeus", None,
      550, (450, 700), "uncertain", "greek", "ActThad",
      P("vii.xxxvi", "Thadd")),
    W("anf08", "acts-of-john-the-theologian",
      "Acts of the Holy Apostle and Evangelist John the Theologian", None,
      450, (400, 550), "uncertain", "greek", "ActJn",
      P("vii.xxxvii", "John the Theologian")),
    W("anf08", "revelation-of-moses", "Revelation of Moses (Greek Life of Adam and Eve)",
      None, 200, (100, 400), "uncertain", "greek", "ApocMos",
      P("vii.xxxviii", "Revelation of Moses")),
    W("anf08", "revelation-of-esdras", "Revelation of Esdras (Greek Apocalypse of Ezra)",
      None, 600, (150, 850), "uncertain", "greek", "ApocEsd",
      P("vii.xxxix", "Revelation of Esdras")),
    W("anf08", "revelation-of-paul", "Revelation of Paul (Apocalypse of Paul, Greek)", None,
      400, (388, 450), "approximate", "greek", "ApocPaulGr",
      P("vii.xl", "Revelation of Paul")),
    W("anf08", "revelation-of-john", "Revelation of John (Apocryphal Apocalypse of John)",
      None, 600, (400, 900), "uncertain", "greek", "ApocJnApocr",
      P("vii.xli", "Revelation of John")),
    W("anf08", "falling-asleep-of-mary",
      "The Book of John Concerning the Falling Asleep of Mary", None,
      500, (450, 600), "uncertain", "greek", "DormMar",
      P("vii.xlii", "Falling Asleep of Mary")),
    W("anf08", "passing-of-mary", "The Passing of Mary (First and Second Latin Forms)", None,
      550, (450, 700), "uncertain", "latin", "TransMar",
      P("vii.xliii", "First Latin Form", "A"), P("vii.xliv", "Second Latin Form", "B")),
    W("anf08", "pseudo-isidorian-decretals",
      "The Decretals (Pseudo-Isidorian Epistles and Decrees of Zephyrinus, Callistus, "
      "Urban I, Pontianus, Anterus and Fabian)", "Pseudo-Isidore", 850, (847, 857),
      "approximate", "latin", "PsIsid.Decr",
      P("viii.iii", "Zephyrinus", "Zeph"), P("viii.iv", "Callistus", "Call"),
      P("viii.v", "Urban", "Urb"), P("viii.vi", "Pontianus", "Pont"),
      P("viii.vii", "Anterus", "Ant"), P("viii.viii", "Epistles of Pope Fabian", "Fab"),
      P("viii.ix", "Decrees of Fabian", "FabDecr")),
    # Remains of the Second and Third Centuries (ANF08 div1 x)
    W("anf08", "quadratus-apology-fragment", "Fragment of the Apology", "Quadratus of Athens",
      125, (124, 129), "approximate", "greek", "Quadr", P("x.iii", "Quadratus")),
    W("anf08", "aristo-of-pella-fragments", "Fragments (Disputation of Jason and Papiscus)",
      "Aristo of Pella", 140, (135, 175), "uncertain", "greek", "Aristo",
      P("x.iv", "Aristo of Pella")),
    W("anf08", "pseudo-melito-syriac-apology",
      "A Discourse in the Presence of Antoninus Caesar (Syriac 'Apology of Melito')",
      "Pseudo-Melito", 200, (170, 250), "uncertain", "syriac", "PsMelito.Apol",
      P("x.v.ii", "Presence of Antoninus")),
    W("anf08", "melito-fragments", "Fragments of Melito", "Melito of Sardis",
      170, (160, 180), "approximate", "greek", "Melito.Frag",
      *(P(f"x.v.{n}", t, str(i)) for i, (n, t) in enumerate((
          ("iii", "Soul and Body"), ("iv", "Cross"), ("v", "On Faith"), ("vi", "Part V"),
          ("vii", "Part VI"), ("viii", "Passover"), ("ix", "Apology"), ("x", "Same Apology"),
          ("xi", "Extracts"), ("xii", "Catena on Genesis"), ("xiii", "Scholia"),
          ("xiv", "Nature of Christ"), ("xv", "Lord's Passion")), start=1))),
    W("anf08", "pseudo-melito-clavis", "The Key (Clavis Scripturae), ascribed to Melito",
      "Pseudo-Melito", None, (600, 1000), "uncertain", "latin", "PsMelito.Clavis",
      P("x.v.xvi", "The Key")),
    W("anf08", "hegesippus-fragments",
      "Fragments from the Five Books of Commentaries on the Acts of the Church",
      "Hegesippus", 180, (165, 185), "approximate", "greek", "Heges",
      P("x.vi.ii", "Five Books of Commentaries")),
    W("anf08", "dionysius-of-corinth-fragments", "Fragments of the Epistles",
      "Dionysius of Corinth", 170, (165, 175), "approximate", "greek", "DionCor",
      P("x.vii", "Dionysius, Bishop of Corinth")),
    W("anf08", "rhodon-fragments", "Fragments", "Rhodon",
      190, (180, 200), "approximate", "greek", "Rhodon", P("x.viii", "Rhodon")),
    W("anf08", "methodius-concerning-matter",
      "Concerning Matter (ascribed by Eusebius to Maximus of Jerusalem; from Methodius, "
      "On Free-Will)", _METH, 290, (185, 311), "uncertain", "greek", "Meth.Mat",
      P("x.ix", "Maximus, Bishop of Jerusalem")),
    W("anf08", "claudius-apollinaris-fragments", "Fragments", "Claudius Apollinaris",
      172, (165, 180), "approximate", "greek", "ApollinHier",
      P("x.x", "Claudius Apollinaris")),
    W("anf08", "polycrates-of-ephesus-epistle", "Epistle to Victor and the Roman Church",
      "Polycrates of Ephesus", 190, (189, 198), "approximate", "greek", "Polycr",
      P("x.xi", "Polycrates")),
    W("anf08", "theophilus-of-caesarea-fragment", "Fragment on the Paschal Question",
      "Theophilus of Caesarea", 195, (190, 200), "uncertain", "greek", "TheophCaes",
      P("x.xii", "Theophilus, Bishop of C")),
    W("anf08", "serapion-of-antioch-fragments", "Fragments", "Serapion of Antioch",
      200, (190, 211), "approximate", "greek", "Serap",
      P("x.xiii", "Serapion")),
    W("anf08", "apollonius-against-the-montanists", "Fragments against the Montanists",
      "Apollonius (anti-Montanist)", 197, (190, 210), "approximate", "greek", "Apollon",
      P("x.xiv", "Apollonius")),
    W("anf08", "pantaenus-fragments", "Fragments", "Pantaenus",
      190, (180, 200), "uncertain", "greek", "Pantaen", P("x.xv", "Pant")),
    W("anf08", "letter-of-the-churches-of-vienne-and-lyons",
      "The Letter of the Churches of Vienne and Lyons to the Churches of Asia and Phrygia",
      None, 177, (177, 178), "established", "greek", "EpLugd",
      P("x.xvi", "Pseud-Iren", drop_leading=5)),

    # ------------------------------------------------------------------ ANF09
    W("anf09", "gospel-of-peter", "The Gospel According to Peter", None,
      150, (100, 190), "uncertain", "greek", "EvPetr",
      P("iii.ii", "Gospel According to Peter")),
    W("anf09", "apocalypse-of-peter", "The Apocalypse of Peter", None,
      135, (100, 150), "approximate", "greek", "ApocPetr",
      P("v.ii", "Apocalypse of Peter", "1"), P("v.iii", "Fragments", "2"),
      # #122: part 1 is printed in verses 1–33 (no verse 2), several per paragraph.
      rechunk=lambda paras: rechunk(
          paras, lambda ref: "ApocPetr.1" if ref.startswith("ApocPetr.1.") else None,
          restart=False, max_gap=2)),
    W("anf09", "vision-of-paul", "The Vision of Paul (Apocalypse of Paul)", None,
      400, (388, 450), "approximate", "greek", "ApocPaul",
      P("vi.ii", "Vision of Paul")),
    W("anf09", "apocalypse-of-the-virgin",
      "The Apocalypse of the Holy Mother of God Concerning the Chastisements", None,
      900, (800, 1000), "uncertain", "greek", "ApocVirg",
      P("vii.ii", "Holy Mother of God")),
    W("anf09", "apocalypse-of-sedrach", "The Apocalypse of Sedrach", None,
      500, (200, 1000), "uncertain", "greek", "ApocSedr",
      P("viii.ii", "Apocalypse of Sedrach")),
    W("anf09", "testament-of-abraham", "The Testament of Abraham", None,
      100, (50, 150), "uncertain", "greek", "TestAbr",
      P("ix.iii", "Testament of Abraham")),
    W("anf09", "acts-of-xanthippe-and-polyxena",
      "Life and Conduct of the Holy Women, Xanthippe, Polyxena, and Rebecca", None,
      250, (200, 300), "uncertain", "greek", "ActXanth",
      P("x.ii", "Xanthippe")),
    W("anf09", "narrative-of-zosimus",
      "The Narrative of Zosimus Concerning the Life of the Blessed", None,
      400, (100, 600), "uncertain", "greek", "NarrZos",
      P("xi.ii", "Narrative of Zosimus")),
    W("anf09", "tatian-diatessaron", "The Diatessaron (Arabic version)", "Tatian",
      170, (160, 175), "approximate", "syriac", "Tat.Diat", P("iv.iii", "Diatessaron")),
    W("anf09", "first-clement-anf09", "The First Epistle of Clement to the Corinthians",
      "Clement of Rome", 96, (95, 97), "established", "greek", "1Clem",
      P("xii.iv", "First Epistle of Clement")),
    W("anf09", "second-clement-anf09", "The Second Epistle of Clement",
      "Pseudo-Clement (2 Clement)", 140, (100, 160), "uncertain", "greek", "2Clem",
      P("xii.vi", "Second Epistle of Clement")),
    W("anf09", "apology-of-aristides", "The Apology of Aristides the Philosopher "
      "(Greek from Barlaam and Josaphat; Syriac)", "Aristides of Athens",
      125, (117, 138), "approximate", "greek", "Aristid.Apol",
      P("xiii.iii", "Barlaam and Josaphat", "Gr"), P("xiii.iv", "from the Syriac", "Syr")),
    W("anf09", "passion-of-the-scillitan-martyrs", "The Passion of the Scillitan Martyrs",
      None, 180, (180, 180), "established", "latin", "PassScill",
      P("xiv.iii", "Scillitan")),
    W("anf09", "origen-letter-to-gregory-anf09", "Letter of Origen to Gregory", _ORIG,
      238, (235, 240), "approximate", "greek", "Orig.EpGreg",
      P("xv.ii", "Letter of Origen to Gregory")),
    W("anf09", "origen-commentary-on-john", "Commentary on the Gospel of John", _ORIG,
      230, (225, 240), "approximate", "greek", "Orig.CommJn",
      P("xv.iii", "Commentary on the Gospel of John")),
    W("anf09", "origen-commentary-on-matthew", "Commentary on the Gospel of Matthew", _ORIG,
      246, (244, 249), "approximate", "greek", "Orig.CommMt",
      P("xvi.ii", "Commentary on Matthew")),

    # -------------------------------------------- nested in another row's div
    # (#381; see ``_only`` above)
    W("anf02", "clement-fragments",
      "Fragments (Adumbrations on the Catholic Epistles; from the Catenae, the "
      "Hypotyposes and the Florilegia)", "Clement of Alexandria",
      200, (190, 215), "uncertain", "greek", "Clem.Frag",
      P("vi.iv", "Stromata"),
      rechunk=_only("Clem.Frag.9", "Clem.Frag", editorial=_CLEMENT_FRAGMENTS_EDITORIAL)),
    W("anf05", "cyprian-to-donatus", "To Donatus (Ad Donatum; ANF Epistle I)", _CYPR,
      246, (245, 248), "approximate", "latin", "Cypr.Don",
      P("iv.iv", "Epistles of Cyprian"),
      rechunk=_only("Cypr.Don.I", "Cypr.Don", drop_root=True, editorial=_DONATUS_EDITORIAL)),
    W("anf07", "lactantius-epitome", "The Epitome of the Divine Institutes", "Lactantius",
      314, (313, 317), "approximate", "latin", "Lact.Epit",
      P("iii.ii", "Divine Institutes"),
      rechunk=_only("Lact.Epit.8", "Lact.Epit", editorial=_EPITOME_EDITORIAL)),
)


# ---------------------------------------------------------------------------
# Translation linkage: slug → work_id of the original-language Work in the
# corpus (First1KGreek, PTA, Perseus, OGLT PL, OGPG).  Matched by author + title,
# then checked by hand against a passage of the original; unsure cases are
# left out (see _UNLINKED).
# ---------------------------------------------------------------------------

_F1K = "first1k/{}/1st1K-grc1"
_TERT_LAT = "perseus/stoa0275/{}/opp-lat1"

_ORIGINALS: dict[str, str] = {
    # ANF01
    "first-clement": _F1K.format("tlg1271/tlg001"),
    "polycarp-epistle-to-the-philippians": _F1K.format("tlg1622/tlg001"),
    # Each letter is one part of the seven-letter collection; the CCEL text
    # prints the longer (interpolated) recension alongside.
    **{f"ignatius-{s}": _F1K.format("tlg1443/tlg001") for s in (
        "to-the-ephesians", "to-the-magnesians", "to-the-trallians", "to-the-romans",
        "to-the-philadelphians", "to-the-smyrnaeans", "to-polycarp")},
    "pseudo-ignatian-epistles": _F1K.format("tlg1443/tlg002"),
    "martyrdom-of-polycarp": _F1K.format("tlg1484/tlg001"),
    "epistle-to-diognetus": _F1K.format("tlg0646/tlg004"),
    "epistle-of-barnabas": "first1k/tlg1216/tlg001/opp-grc1",
    "justin-first-apology": _F1K.format("tlg0645/tlg001"),
    "justin-second-apology": "first1k/tlg0645/tlg002/perseus-grc2",
    "justin-dialogue-with-trypho": "first1k/tlg0645/tlg003/perseus-grc2",
    "irenaeus-against-heresies": _F1K.format("tlg1447/tlg001"),
    # ANF02
    "shepherd-of-hermas": _F1K.format("tlg1419/tlg001"),
    "tatian-address-to-the-greeks": "first1k/tlg1766/tlg001/perseus-grc1",
    "theophilus-to-autolycus": "first1k/tlg1725/tlg001/perseus-grc1",
    "athenagoras-plea-for-the-christians": "first1k/tlg1205/tlg001/perseus-grc1",
    "athenagoras-resurrection-of-the-dead": "first1k/tlg1205/tlg002/perseus-grc1",
    "clement-exhortation-to-the-heathen": _F1K.format("tlg0555/tlg001"),
    "clement-the-instructor": _F1K.format("tlg0555/tlg002"),
    "clement-stromata": "perseus/tlg0555/tlg004/perseus-grc2",
    "clement-who-is-the-rich-man": _F1K.format("tlg0555/tlg006"),
    # ANF03-04: Tertullian (Perseus / Open Greek and Latin)
    **{f"tertullian-{s}": _TERT_LAT.format(n) for s, n in (
        ("on-idolatry", "stoa017"), ("de-corona", "stoa013"), ("to-scapula", "stoa003"),
        ("ad-nationes", "stoa002"), ("answer-to-the-jews", "stoa005"),
        ("souls-testimony", "stoa028"), ("on-the-soul", "stoa010"),
        ("prescription-against-heretics", "stoa024"), ("against-marcion", "stoa006"),
        ("against-hermogenes", "stoa004"), ("against-the-valentinians", "stoa008"),
        ("on-the-flesh-of-christ", "stoa012"), ("resurrection-of-the-flesh", "stoa026"),
        ("against-praxeas", "stoa007"), ("scorpiace", "stoa030"),
        ("on-repentance", "stoa021"), ("on-baptism", "stoa011"), ("on-prayer", "stoa020"),
        ("ad-martyras", "stoa001"), ("of-patience", "stoa023"),
        ("on-the-pallium", "stoa022"), ("apparel-of-women", "stoa014"),
        ("veiling-of-virgins", "stoa029"), ("exhortation-to-chastity", "stoa015"),
        ("on-monogamy", "stoa019"), ("on-modesty", "stoa025"), ("on-fasting", "stoa018"),
        ("de-fuga", "stoa016"))},
    "tertullian-apology": "perseus/stoa0275/stoa009/perseus-lat2",
    "tertullian-de-spectaculis": "perseus/stoa0275/stoa027/perseus-lat2",
    # Perseus files Ad Uxorem under stoa0276 ("Pseudo-Tertullian"); same text.
    "tertullian-to-his-wife": "perseus/stoa0276/stoa002/opp-lat1",
    "passion-of-perpetua-and-felicitas": "oglt-pl/anonymus/pl3_0_pass",
    "minucius-felix-octavius": "perseus/stoa0203/stoa001/perseus-lat2",
    "commodian-instructions": "oglt-pl/commodianus/pl5_13_com",
    "origen-against-celsus": "first1k/tlg2042/tlg001/perseus-grc1",
    "origen-letter-to-africanus": _F1K.format("tlg2042/tlg045"),
    # ANF05
    "hippolytus-refutation-of-all-heresies": "first1k/tlg2115/tlg060/opp-grc1",
    "pontius-life-of-cyprian": "oglt-pl/pontius-diaconus/pl3_37_unk",
    "seventh-council-of-carthage": "oglt-pl/concilia-carthaginiensia/pl3_24_ann",
    "caius-fragments": _F1K.format("tlg0572/tlg001"),
    "muratorian-fragment": "oglt-pl/anonymus/pl3_1_unkn",
    "novatian-on-the-trinity": "oglt-pl/novatianus/pl3_8_nova",
    "novatian-on-the-jewish-meats": "oglt-pl/novatianus/pl3_9_nova",
    "anonymous-against-novatian": "oglt-pl/pseudo-cyprian/pl3_36_ano",
    "anonymous-on-rebaptism": "oglt-pl/pseudo-cyprian/pl3_34_ano",
    # ANF06
    # The Greek survives only in fragments (via Epiphanius); same work.
    "acts-of-archelaus": _F1K.format("stoa0146d/stoa001"),
    "methodius-banquet-of-the-ten-virgins": "first1k/tlg2959/tlg001/opp-grc1",
    "methodius-concerning-free-will": "first1k/tlg2959/tlg002/opp-grc1",
    # ANF07
    "venantius-on-easter": "oglt-pl/venantius-fortunatus/pl7_1_vena",
    "anonymous-against-the-montanists": _F1K.format("tlg1131/tlg001"),
    "second-clement": _F1K.format("tlg1271/tlg002"),
    # ANF08
    "clement-excerpts-of-theodotus": _F1K.format("tlg0555/tlg007"),
    "pseudo-clement-epistles-on-virginity": _F1K.format("tlg1271/tlg010"),
    "pseudo-clementine-homilies": _F1K.format("tlg1271/tlg006"),
    "acts-of-thomas": _F1K.format("tlg2038/tlg001"),
    "acts-of-philip": _F1K.format("tlg2948/tlg001"),
    "acts-of-barnabas": _F1K.format("tlg2949/tlg001"),
    "dionysius-of-corinth-fragments": _F1K.format("tlg1329/tlg001"),
    "polycrates-of-ephesus-epistle": _F1K.format("tlg1626/tlg001"),
    # ANF09
    "first-clement-anf09": _F1K.format("tlg1271/tlg001"),
    "second-clement-anf09": _F1K.format("tlg1271/tlg002"),
    # The ANF prints both recensions (Version I and II); linked to Recension A.
    "testament-of-abraham": _F1K.format("tlg1701/tlg001"),
    "origen-commentary-on-john": _F1K.format("tlg2042/tlg005"),
    # ANF08: the Little Labyrinth is section 2 of First1KGreek's Gaius
    # fragments (from Eusebius HE 5.28), with caius-fragments' text.
    "against-the-heresy-of-artemon": _F1K.format("tlg0572/tlg001"),
    # ANF08: Eusebius HE 5.1-3 (the same edition as npnf-works/eusebius-church-history).
    "letter-of-the-churches-of-vienne-and-lyons": _F1K.format("tlg2018/tlg002"),
    # ANF08: the ANF text is the opening (John at Rome and Patmos) and the
    # Metastasis of Bonnet's Acta Joannis, which First1KGreek prints in full.
    "acts-of-john-the-theologian": _F1K.format("tlg0317/tlg001"),
    # -- Open Patrologia Graeca (OGPG): OCR of Migne's Greek columns, one Work
    # per text (``scripts/ingest/data/ogpg_index.csv``).  Used only where no
    # critical edition of the text is in the corpus, and only split works
    # (``ogpg/vol-NNN/{slug}``), never a volume's ``other`` remainder.  Where
    # the Migne Work holds more than the translation, the comment says so.
    # ANF01
    "martyrdom-of-ignatius": "ogpg/vol-005/martyrium-ignatii",
    "papias-fragments": "ogpg/vol-005/papias-fragmenta",
    "martyrdom-of-justin": "ogpg/vol-006/martyrium-justini",
    "pseudo-justin-discourse-to-the-greeks": "ogpg/vol-006/oratio-ad-graecos",
    "pseudo-justin-hortatory-address": "ogpg/vol-006/cohortatio-ad-graecos",
    "pseudo-justin-sole-government-of-god": "ogpg/vol-006/de-monarchia",
    # PG 6 prints the De resurrectione fragments with Justin's other fragments.
    "justin-on-the-resurrection": "ogpg/vol-006/fragmenta-justini",
    "justin-other-fragments": "ogpg/vol-006/fragmenta-justini",
    # Massuet's Greek fragments, which the ANF numbering follows.
    "irenaeus-fragments": "ogpg/vol-007/fragmenta",
    # ANF05: Migne's Fragmenta exegetica cover the ANF collection.
    "hippolytus-exegetical-fragments": "ogpg/vol-010/hippolytus-exegetica",
    # PG 10, cols. 903-950 (#149).
    "pseudo-hippolytus-end-of-the-world": "ogpg/vol-010/de-consummatione-mundi",
    "pseudo-gregory-thaumaturgus-sectional-confession": "ogpg/vol-010/kata-meros-pistis",
    "pseudo-gregory-thaumaturgus-twelve-topics": "ogpg/vol-010/capitula-de-fide",
    "pseudo-gregory-thaumaturgus-dubious-writings": "ogpg/vol-010/thaumaturgus-dubia",
    "hippolytus-christ-and-antichrist": "ogpg/vol-010/de-christo-et-antichristo",
    "hippolytus-against-the-jews": "ogpg/vol-010/adversus-judaeos",
    "hippolytus-against-plato": "ogpg/vol-010/adversus-graecos",
    "hippolytus-against-noetus": "ogpg/vol-010/contra-noetum",
    "pseudo-hippolytus-against-beron-and-helix": "ogpg/vol-010/adversus-beronem",
    "pseudo-hippolytus-on-the-theophany": "ogpg/vol-010/in-theophaniam",
    "pseudo-hippolytus-twelve-and-seventy-apostles": "ogpg/vol-010/de-apostolis",
    # ANF06
    "gregory-thaumaturgus-declaration-of-faith": "ogpg/vol-010/thaumaturgus-expositio-fidei",
    "gregory-thaumaturgus-metaphrase-of-ecclesiastes": "ogpg/vol-010/thaumaturgus-metaphrasis",
    # PG prints the epistle with Balsamon's and Zonaras's commentary.
    "gregory-thaumaturgus-canonical-epistle": "ogpg/vol-010/thaumaturgus-epistula-canonica",
    "gregory-thaumaturgus-panegyric-to-origen": "ogpg/vol-010/thaumaturgus-panegyricus",
    "dionysius-of-alexandria-fragments": "ogpg/vol-010/dionysius-alexandrinus",
    "dionysius-of-alexandria-exegetical-fragments": "ogpg/vol-010/dionysius-commentaria",
    # PG 10's Julius Africanus Work holds both the Chronography fragments and
    # the Epistle to Aristides; the Letter to Origen is a Work of its own (PG 11).
    "africanus-chronography": "ogpg/vol-010/julius-africanus",
    "africanus-epistle-to-aristides": "ogpg/vol-010/julius-africanus",
    "africanus-letter-to-origen": "ogpg/vol-011/africanus-epistula-ad-originem",
    "narrative-of-events-in-persia": "ogpg/vol-010/narratio-de-rebus-persicis",
    "malchion-synod-of-antioch": "ogpg/vol-010/malchion-epistula",
    "pseudo-pamphilus-exposition-of-acts": "ogpg/vol-010/pamphilus-expositio",
    # PG 18 prints the letters as one Work (PTA has only Urk. 4).
    "alexander-of-alexandria-epistles": "ogpg/vol-018/alexander-alexandrinus",
    "alexander-of-lycopolis-manichaeans": "ogpg/vol-018/alexander-lycopolitanus",
    # PG 18's Peter of Alexandria holds the canonical epistle and the fragments.
    "peter-of-alexandria-canonical-epistle": "ogpg/vol-018/petrus-alexandrinus",
    "peter-of-alexandria-fragments": "ogpg/vol-018/petrus-alexandrinus",
    # PG 18's Methodius "Excerpta ac orationes" holds both texts.
    "methodius-discourse-on-the-resurrection": "ogpg/vol-018/methodius-opera-varia",
    "pseudo-methodius-simeon-and-anna": "ogpg/vol-018/methodius-opera-varia",
    # ANF08: Melito's Greek fragments only (the ANF also translates Syriac ones).
    "melito-fragments": "ogpg/vol-005/melito-fragmenta",
    "testaments-of-the-twelve-patriarchs": "ogpg/vol-002/testamenta-xii-patriarcharum",
    # ANF09: First1KGreek has the letter only inside the Philocalia.
    "origen-letter-to-gregory": "ogpg/vol-011/epistula-ad-gregorium",
    "origen-letter-to-gregory-anf09": "ogpg/vol-011/epistula-ad-gregorium",
    # PG 13 prints the extant Greek books (10-17) as one Work; the ANF
    # translates books 10-14 (First1KGreek splits them over two Works).
    "origen-commentary-on-matthew": "ogpg/vol-013/commentarii-in-matthaeum",
    # ANF06: Bibliotheca cod. 119 (PG 103, col. 399), inside the Work for
    # codd. 1-249.
    "photius-on-pierius": "ogpg/vol-103/bibliotheca-1",
    # ANF07: PL 7's Fragmenta holds fragments I-IV and the poem on the Passion;
    # the ANF also prints the Phoenix, which it lacks.
    "lactantius-fragments": "oglt-pl/lactantius/pl7_0_lact",
    # ANF08: the letter of the presbyters and deacons of Achaia (PG 2, cols.
    # 1217-1248); the Work opens with short notices on Andrew (cols. 1191-1197).
    "acts-and-martyrdom-of-andrew": "ogpg/vol-002/de-martyrio-andreae",
    # ANF05: PL 47 prints Cyprian's De dominica oratione among works ascribed
    # to Augustine ("Opusculum I sive liber de oratione"); attributed to Cyprian (#184).
    "cyprian-lords-prayer": "oglt-pl/cyprianus-carthaginensis/pl47_0_unk",
    # ANF06: the "Logos eis ta baia" (PG 18, p. 293 of the OCR), inside the
    # Work that also holds Simeon and Anna.
    "pseudo-methodius-oration-on-the-palms": "ogpg/vol-018/methodius-opera-varia",
    # ANF08: the Latin Liber de nativitate Mariae, with its pseudo-Jerome
    # preface, inside PL 30's mantissa of works ascribed to Jerome.
    "gospel-of-the-nativity-of-mary": "oglt-pl/pseudo-hieronymus/pl30_0_-nativitas",
    # -- Nested works (#381), each checked against the original's text.
    # ANF Epistle I is Ad Donatum (16 sections in both); CSEL 3.1 prints it as a
    # treatise, so it is not part of the Epistulae that cyprian-epistles translates.
    "cyprian-to-donatus": "csel/stoa0104a/stoa001/opp-lat1",
    # The whole Epitome (preface and 68 chapters; ANF keeps the old chapter
    # numbers, I-LXXIII with a gap).
    "lactantius-epitome": "csel/stoa0171/stoa008/opp-lat1",
    # The same collection as Migne's PG 9 Fragmenta (cols. 729-774), in its
    # order: the Latin Adumbrations (which the OGPG OCR lacks), the catena and
    # Hypotyposes fragments, the florilegia, and the Instructor passage from
    # Cramer's catena that ANF describes instead of translating.
    "clement-fragments": "ogpg/vol-009/fragmenta",
}

#: Plausible originals deliberately *not* linked (slug → reason).
_UNLINKED: dict[str, str] = {
    "ignatius-syriac-recension": "Syriac abridgement; no Syriac original in corpus",
    "methodius-fragments": "spread over several first1k fragment works",
    "methodius-concerning-matter": "an extract of first1k tlg2959.tlg002 (De libero arbitrio)",
    "cyprian-epistles": "OGLT has only five individual letters, not the collection",
    "apology-of-aristides": "Greek survives only inside Barlaam and Josaphat (perseus tlg2934.tlg066)",
    "origen-de-principiis": "translates Rufinus's Latin; OGPG PG 11 has only the Greek fragments",
    "hippolytus-fragments-of-discourses": "fragments of several homilies and writings",
    "passion-of-symphorosa": "Latin passio; not in the OCR of OGPG PG 10's julius-africanus",
    "dionysius-of-rome-against-the-sabellians": (
        "Greek only inside Athanasius, De decretis 26; OGLT pl5 prints a Latin version"),
    "acts-and-records-baptism-of-heretics": "several OGLT PL 3 council Works (Rome, Carthage)",
    "pseudo-clementine-recognitions": "Rufinus's Latin is not in the corpus; the Homilies differ",
    "ignatius-latin-correspondence": "Latin letters; the corpus has only Greek recensions",
    "gospel-of-nicodemus": "translates the Greek and Latin forms; the corpus has a Coptic one",
    # Quoted inside another author's work (Eusebius HE), which would group
    # them with that author's works.
    "apollonius-against-the-montanists": "only quoted in Eusebius HE 5.18",
    "phileas-epistle-to-thmuis": "only quoted in Eusebius HE 8.10",
    # OGPG prints these in Works of several authors (PG 5 Fragmenta saeculi
    # II; PG 10 Alexandrina fragmenta), which would group unrelated works.
    **{s: "only in a multi-author OGPG Work" for s in (
        "hegesippus-fragments", "aristo-of-pella-fragments", "quadratus-apology-fragment",
        "pantaenus-fragments", "rhodon-fragments", "serapion-of-antioch-fragments",
        "alexander-of-jerusalem-epistles", "anatolius-arithmetic", "theognostus-hypotyposes",
        "pierius-fragment")},
}

_WORKS = link_originals(_WORKS, _ORIGINALS)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one JSON file per ``_WORKS`` row (see ``_ccel_works.ingest_table``)."""
    return ingest_table(output_dir, SOURCE_ID, _WORKS, force=force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
