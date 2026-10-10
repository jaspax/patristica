"""
Patrologia Graeca volume → contents table, used by ``ogpg.py`` for Work titles,
authors and dates.

Source: the volume list in the English Wikipedia article "Patrologia Graeca"
(revision fetched 2026-10-10; it follows the Cavallera 1912 index), with
author dates from standard patrologies.  Each entry lists the volume's authors
in Migne's order; the first is the principal author used when a short label is
needed.

Dates: ``date_composed`` is the principal author's floruit/death year;
``date_range`` spans *every* listed author, so hybrid volumes (e.g. PG 3–4,
Pseudo-Dionysius with George Pachymeres' 14th-century paraphrase) are
honest about their later content.  A volume is excluded only when all of its
contents fall after the collection period (``patristica.period.work_in_period``);
straddling volumes are kept and flagged ``out_of_period`` by date.

The OGL repos also contain a few mislabeled scans and duplicate bindings;
those are listed in ``EXCLUDED_REPOS`` with the reason.
"""

from __future__ import annotations

from typing import NamedTuple

from patristica.models import DateConfidence


class PGVolume(NamedTuple):
    authors: tuple[str, ...]
    date_composed: int | None
    date_range: tuple[int, int]
    date_confidence: DateConfidence = "approximate"
    note: str | None = None


def _v(authors: str, composed: int | None, lo: int, hi: int,
       conf: DateConfidence = "approximate", note: str | None = None) -> PGVolume:
    return PGVolume(tuple(a.strip() for a in authors.split(";")), composed, (lo, hi), conf, note)


_ORIGEN = _v("Origen", 240, 210, 254, "established")
_EUSEBIUS = _v("Eusebius of Caesarea", 325, 300, 340, "established")
_ATHANASIUS = _v("Athanasius of Alexandria", 350, 325, 373, "established",
                 "includes spuria (PG 28)")
_BASIL = _v("Basil of Caesarea", 370, 357, 379, "established")
_NAZIANZEN = _v("Gregory of Nazianzus; Basil the Minor", 380, 360, 960, "approximate",
                "with the 10th-century scholia of Basil the Minor")
_EPIPHANIUS = _v("Epiphanius of Salamis", 376, 374, 403, "established")
_NYSSA = _v("Gregory of Nyssa", 380, 370, 395, "established")
_CHRYSOSTOM = _v("John Chrysostom", 395, 386, 407, "established",
                 "includes Chrysostomic spuria")
_CYRIL_ALEX = _v("Cyril of Alexandria", 425, 412, 444, "established")
_THEODORET = _v("Theodoret of Cyrrhus", 440, 420, 466, "established")
_PROCOPIUS_GAZA = _v("Procopius of Gaza", 520, 500, 530, "established")
_DAMASCENE = _v("John of Damascus", 730, 700, 754, "established")
_PHOTIUS = _v("Photius of Constantinople", 870, 858, 893, "established")
_CONST_PORPH = _v("Constantine VII Porphyrogenitus", 950, 913, 959, "established")
_METAPHRASTES = _v("Symeon Metaphrastes", 980, 960, 1000, "approximate")
_THEOPHYLACT = _v("Theophylact of Ohrid", 1090, 1078, 1107, "approximate")
_ZIGABENUS = _v("Euthymius Zigabenus", 1110, 1100, 1120, "approximate")
_BALSAMON = _v("Theodore Balsamon", 1180, 1170, 1195, "approximate")
_PALAMAS_150 = _v("Constantine Harmenopoulos; Macarius Chrysocephalus; John XIV Kalekas; "
                  "Theophanes of Nicaea; Nicholas Cabasilas; Gregory Palamas",
                  1350, 1300, 1390)

PG_VOLUMES: dict[int, PGVolume] = {
    # --- Pre-Nicene -------------------------------------------------------
    1: _v("Clement of Rome", 96, 90, 400, note="with Pseudo-Clementine writings"),
    2: _v("Clement of Rome; Epistle of Barnabas; Hermas; Epistle to Diognetus; "
          "Testaments of the Twelve Patriarchs", 100, 90, 250),
    3: _v("Pseudo-Dionysius the Areopagite; Maximus the Confessor; George Pachymeres",
          500, 480, 1310, note="Pachymeres' paraphrase is 14th-century"),
    4: _v("Pseudo-Dionysius the Areopagite; Maximus the Confessor; George Pachymeres",
          500, 480, 1310, note="scholia and paraphrase; Pachymeres is 14th-century"),
    5: _v("Ignatius of Antioch; Polycarp of Smyrna; Melito of Sardis; Papias of Hierapolis; "
          "Apollonius of Ephesus", 110, 100, 200),
    6: _v("Justin Martyr; Tatian; Athenagoras of Athens; Theophilus of Antioch; Hermias",
          155, 150, 250),
    7: _v("Irenaeus of Lyons", 180, 175, 202, "established"),
    8: _v("Clement of Alexandria", 200, 190, 215, "established"),
    9: _v("Clement of Alexandria", 200, 190, 215, "established"),
    10: _v("Gregory Thaumaturgus; Pope Zephyrinus; Sextus Julius Africanus; Pope Urban I; "
           "Hippolytus of Rome; Theognostus of Alexandria", 230, 200, 270),
    **{n: _ORIGEN for n in range(11, 18)},
    18: _v("Methodius of Olympus; Alexander of Lycopolis; Peter of Alexandria; "
           "Theodore of Heraclea", 300, 270, 360),
    # --- 4th century ------------------------------------------------------
    **{n: _EUSEBIUS for n in range(19, 25)},
    **{n: _ATHANASIUS for n in range(25, 29)},
    **{n: _BASIL for n in range(29, 33)},
    33: _v("Cyril of Jerusalem; Apollinaris of Laodicea; Diodore of Tarsus; "
           "Peter II of Alexandria; Timothy of Alexandria; Isaac the ex-Jew", 350, 348, 390),
    34: _v("Macarius of Egypt; Macarius of Alexandria", 390, 350, 450),
    **{n: _NAZIANZEN for n in range(35, 38)},
    38: _v("Gregory of Nazianzus; Caesarius of Nazianzus", 385, 360, 560,
           note="Pseudo-Caesarius' Dialogues are 6th-century"),
    39: _v("Didymus the Blind; Amphilochius of Iconium; Nectarius of Constantinople",
           380, 360, 400),
    40: _v("Anthony the Great; Pachomius; Serapion of Thmuis; Isaiah the Abbot; Orsisius; "
           "Theodore the Abbot; Asterius of Amasea; Nemesius of Emesa; Hieronymus Graecus; "
           "Serapion of Antioch; Philo of Carpasia; Evagrius Ponticus", 380, 300, 500),
    41: _EPIPHANIUS,
    42: _EPIPHANIUS,
    43: _v("Epiphanius of Salamis; Nonnus of Panopolis", 400, 370, 470),
    **{n: _NYSSA for n in range(44, 47)},
    # --- 5th century ------------------------------------------------------
    **{n: _CHRYSOSTOM for n in range(47, 65)},
    65: _v("Severian of Gabala; Theophilus of Alexandria; Palladius of Helenopolis; "
           "Philostorgius; Atticus of Constantinople; Proclus of Constantinople; "
           "Flavian of Constantinople; Mark the Hermit; Diadochus of Photice; Mark the Deacon",
           420, 385, 470),
    66: _v("Theodore of Mopsuestia; Synesius of Cyrene; Arsenius the Great", 410, 380, 450),
    67: _v("Socrates Scholasticus; Sozomen", 440, 439, 450, "established"),
    **{n: _CYRIL_ALEX for n in range(68, 77)},
    77: _v("Cyril of Alexandria; Theodotus of Ancyra; Paul of Emesa; Acacius of Beroea; "
           "John of Antioch; Memnon of Ephesus; Acacius of Melitene; Rabbula of Edessa; "
           "Firmus of Caesarea; Amphilochius of Side", 431, 412, 460),
    78: _v("Isidore of Pelusium", 420, 390, 440),
    79: _v("Nilus of Sinai; Hyperechius", 420, 390, 450),
    **{n: _THEODORET for n in range(80, 85)},
    85: _v("Basil of Seleucia; Euthalius the Deacon; John of Carpathus; Aeneas of Gaza; "
           "Zacharias Rhetor; Gelasius of Cyzicus; Theotimus; Ammonius; Andrew of Samosata; "
           "Gennadius of Constantinople; Candidus Isaurus; Antipater of Bostra; "
           "Dalmatius of Cyzicus; Timothy of Berytus; Eustathius of Berytus", 460, 430, 680),
    # --- 6th century (86 is bound in two parts; see PG_PARTS) --------------
    86: _v("Timothy of Constantinople; John Maxentius; Theodore Lector; Leontius of Byzantium; "
           "Evagrius Scholasticus; Eulogius of Alexandria", 550, 500, 700),
    # --- 7th century (87 is bound in three parts) --------------------------
    87: _v("Procopius of Gaza; John Moschus; Sophronius of Jerusalem", 520, 500, 640),
    88: _v("Cosmas Indicopleustes; Constantine the Deacon; John Climacus; Agathias; "
           "Gregory of Antioch; John IV the Faster; Dorotheus of Gaza", 580, 540, 650),
    89: _v("Anastasius Sinaita; Anastasius I of Antioch; Anastasius the Abbot; "
           "Anastasius IV of Antioch; Antiochus of Saba", 680, 560, 700),
    90: _v("Maximus the Confessor", 640, 610, 662, "established"),
    91: _v("Maximus the Confessor; Thalassius the Abbot; Theodore of Raithu", 640, 600, 662),
    92: _v("Chronicon Paschale; George of Pisidia", 630, 610, 640),
    93: _v("Olympiodorus the Deacon; Hesychius; Leontius of Neapolis; Leontius of Damascus",
           600, 450, 900, "uncertain"),
    # --- 8th century ------------------------------------------------------
    94: _DAMASCENE,
    95: _DAMASCENE,
    96: _v("John of Damascus; John of Nicaea; John VI of Constantinople; John of Euboea",
           730, 700, 760),
    97: _v("John Malalas; Andrew of Crete; Elias of Crete; Theodore Abu Qurrah", 700, 530, 1120,
           note="Elias of Crete's commentary is 12th-century"),
    98: _v("Germanus I of Constantinople; Cosmas of Maiuma; Gregory of Agrigento; "
           "Pantaleon the Deacon; Epiphanius of Catania; Tarasius of Constantinople",
           730, 590, 810),
    99: _v("Theodore the Studite", 810, 790, 826, "established"),
    # --- 9th century ------------------------------------------------------
    100: _v("Nicephorus I of Constantinople; Stephen the Deacon; Gregory of Decapolis; "
            "Christopher of Alexandria; Methodius I of Constantinople", 820, 800, 850),
    101: _PHOTIUS,
    102: _PHOTIUS,
    103: _PHOTIUS,
    104: _v("Photius of Constantinople; Peter of Sicily; Peter of Argos; Bartholomew of Edessa",
            870, 850, 930),
    105: _v("Nicetas David Paphlagon; Nicetas Byzantius; Theognostus the Monk; "
            "Joseph the Hymnographer", 880, 840, 920),
    # --- 10th century -----------------------------------------------------
    106: _v("Joseppus; Nicephorus the Philosopher; Andrew of Caesarea; Arethas of Caesarea; "
            "John Geometres; Cosmas Vestitor; Leo the Patrician; Athanasius of Corinth",
            900, 550, 1000),
    107: _v("Leo VI the Wise", 900, 886, 912, "established"),
    108: _v("Theophanes the Confessor; Leo Grammaticus; Anastasius Bibliothecarius",
            815, 810, 1013),
    109: _v("Theophanes Continuatus", 960, 950, 1000),
    110: _v("George the Monk (Hamartolos)", 870, 866, 970),
    111: _v("Nicholas I Mystikos; Basil of Neopatras; Basil the Minor; Gregory of Caesarea; "
            "Joseph Genesius; Moses bar Kepha; Theodore Daphnopates; Eutychius of Alexandria",
            920, 900, 970),
    112: _CONST_PORPH,
    113: _v("Constantine VII Porphyrogenitus; Nikon the Metanoeite; Theodosius the Deacon",
            950, 913, 998),
    114: _METAPHRASTES,
    115: _METAPHRASTES,
    116: _METAPHRASTES,
    117: _v("Basil II; Nicephorus II Phocas; Leo the Deacon; Hippolytus of Thebes; "
            "John Georgides; Ignatius the Deacon; Nilus the Eparch; Suda", 990, 900, 1050),
    118: _v("Pseudo-Oecumenius", 990, 900, 1000, "uncertain"),
    119: _v("Pseudo-Oecumenius; various canonists (Jus Graeco-Romanum)", 990, 900, 1150,
            "uncertain", note="canon-law collection runs into the 12th century"),
    # --- 11th century -----------------------------------------------------
    120: _v("Nicetas Stethatos; Michael Cerularius; Leo of Ohrid; Symeon the New Theologian; "
            "John Mauropous; John Xiphilinus", 1040, 1000, 1080,
            note="authors on both sides of the period boundary; not separable"),
    121: _v("George Cedrenus", 1060, 1057, 1100),
    122: _v("George Cedrenus; Michael Psellos", 1060, 1057, 1100),
    **{n: _THEOPHYLACT for n in range(123, 127)},
    # --- 12th century -----------------------------------------------------
    127: _v("Nicephorus Bryennios; Constantine Manasses; Nicholas III of Constantinople; "
            "Philip the Solitary", 1100, 1060, 1150),
    128: _ZIGABENUS,
    129: _ZIGABENUS,
    130: _ZIGABENUS,
    131: _v("Euthymius Zigabenus; Anna Comnena", 1110, 1100, 1150),
    132: _v("Theophanes Kerameus; Nilus Doxapatres; John IV of Antioch; John II Komnenos",
            1130, 1100, 1150),
    133: _v("Alexius Aristenus; Luke Chrysoberges; John Kinnamos; Manuel I Komnenos; "
            "Theodore Prodromos", 1150, 1100, 1190),
    134: _v("John Zonaras", 1130, 1120, 1160),
    135: _v("John Zonaras; George II Xiphilinus; Isaac II Angelos; Neophytos the Recluse; "
            "Eustathius of Thessalonica", 1150, 1120, 1200),
    136: _v("Eustathius of Thessalonica; Antonius Melissa", 1180, 1100, 1195),
    # --- 13th century -----------------------------------------------------
    137: _BALSAMON,
    138: _BALSAMON,
    139: _v("Isidore of Thessalonica; Nicetas of Maroneia; John of Kitros; Mark III of Alexandria; "
            "Joel the Chronographer; Nicetas Choniates", 1200, 1130, 1220),
    140: _v("Nicetas Choniates; Michael Choniates; Germanus II of Constantinople; "
            "Theodore I Laskaris; George Acropolites; Nicephorus Chumnus", 1220, 1180, 1330),
    141: _v("John Bekkos; Constantine Meliteniotes; George Metochites", 1280, 1270, 1310),
    142: _v("Gregory II of Cyprus; Athanasius I of Constantinople; Nicephorus Blemmydes",
            1280, 1230, 1310),
    # --- 14th century -----------------------------------------------------
    143: _v("Ephraim the Chronographer; Theoleptus of Philadelphia; George Pachymeres",
            1310, 1300, 1330),
    144: _v("George Pachymeres; Theodore Metochites; Matthew Blastares", 1320, 1300, 1350),
    145: _v("Matthew Blastares; Thomas Magister; Nicephorus Callistus Xanthopoulos",
            1330, 1300, 1350),
    146: _v("Nicephorus Callistus Xanthopoulos", 1320, 1310, 1335),
    147: _v("Nicephorus Callistus Xanthopoulos; Callistus and Ignatius Xanthopoulos; "
            "Callistus I of Constantinople; Maximus Planudes", 1330, 1290, 1400),
    148: _v("Nicephorus Gregoras", 1350, 1330, 1360),
    149: _v("Nicephorus Gregoras; Nilus Cabasilas; Theodore of Melitene; George Lapithes",
            1350, 1330, 1365),
    150: _PALAMAS_150,
    151: _v("Gregory Palamas; Gregory Akindynos; Barlaam of Seminara", 1340, 1330, 1359,
            "established"),
    152: _v("Manuel Kalekas; John Kyparissiotes; Matthew Kantakouzenos; "
            "Patriarchal acts of Constantinople", 1370, 1320, 1410),
    153: _v("John VI Kantakouzenos", 1370, 1350, 1383),
    154: _v("John VI Kantakouzenos; Philotheus of Selymbria; Demetrius Kydones; "
            "Maximus Chrysoberges", 1370, 1350, 1400),
    # --- 15th century -----------------------------------------------------
    155: _v("Symeon of Thessalonica", 1420, 1410, 1429),
    156: _v("Manuel Chrysoloras; John Kananos; Manuel II Palaiologos; John Anagnostes; "
            "George Sphrantzes", 1420, 1390, 1480),
    157: _v("Pseudo-Kodinos; Doukas", 1460, 1350, 1470),
    158: _v("Michael Glykas; John of Adrianople; Isaias of Cyprus; John Argyropoulos; "
            "Joseph II of Constantinople; Bartholomew of Iano", 1430, 1150, 1480),
    159: _v("Laonikos Chalkokondyles; Leonard of Chios; Isidore of Kiev; Joseph of Methone",
            1460, 1430, 1490),
    160: _v("Gregory III Mammas; Gennadius Scholarius; George Gemistos Plethon; "
            "Matthew Camariotes; Mark of Ephesus; Pope Nicholas V", 1450, 1420, 1490),
    161: _v("Bessarion; George of Trebizond; Constantine Lascaris; Theodore Gaza; "
            "Andronikos Kallistos", 1460, 1430, 1490),
}

# Parts of volumes bound separately (repo "Vol.-86.1" etc.).
PG_PARTS: dict[tuple[int, int], PGVolume] = {
    (16, 1): _v("Origen", 240, 210, 254, "established", "Hexapla fragments"),
    (16, 2): _v("Origen", 240, 210, 254, "established", "Hexapla fragments"),
    (16, 3): _v("Origen; Hippolytus of Rome", 240, 210, 254, "approximate",
                "Hexapla fragments and the Philosophumena (Refutatio omnium haeresium), "
                "printed by Migne under Origen's name; now attributed to Hippolytus"),
    (86, 1): _v("Timothy of Constantinople; John Maxentius; Theodore Lector; Procopius of Tyre; "
                "Theodore of Scythopolis; Timothy of Jerusalem; Theodosius of Alexandria; "
                "Eusebius of Alexandria; Eusebius of Emesa; Gregentius of Taphar; "
                "Epiphanius of Constantinople; Isaac of Nineveh; Barsanuphius; Justinian I; "
                "Agapetus the Deacon; Leontius of Byzantium", 530, 340, 700),
    (86, 2): _v("Leontius of Byzantium; Ephraim of Antioch; Paul the Silentiary; "
                "Eutychius of Constantinople; Evagrius Scholasticus; Eulogius of Alexandria; "
                "Simeon Stylites the Younger; Zacharias of Jerusalem; Modestus of Jerusalem",
                580, 530, 640),
    (87, 1): _PROCOPIUS_GAZA,
    (87, 2): _PROCOPIUS_GAZA,
    (87, 3): _v("Procopius of Gaza; John Moschus; Sophronius of Jerusalem; Alexander the Monk",
                600, 500, 640),
}

# Repos that must not be ingested as PG volumes (repo → reason).  Identified
# by sampling page headers and by trigram overlap between volumes' texts
# (M8 audit, 2026-10).
EXCLUDED_REPOS: dict[str, str] = {
    "Vol.-12-13": "Patrologia Latina scan (PL 12–13), mislabeled",
    "Vol.-18-19": "Patrologia Latina scan (PL 18–19), mislabeled",
    "Vol.-20-21": "Patrologia Latina scan (PL 20–21), mislabeled",
    "Vol.-40-41": "Patrologia Latina scan (PL 40–41), mislabeled",
    "Vol.-47-48": "duplicate binding of PG 47–48 (single-volume repos ingested)",
    "Vol.-49-50": "duplicate binding of PG 49–50 (single-volume repos ingested)",
    "Vol.-53-54": "duplicate binding of PG 53–54 (single-volume repos ingested)",
    "Vol.-57-58": "duplicate binding of PG 57–58 (single-volume repos ingested)",
    "Vol.-86": "duplicate scan of PG 86.2; used as an extra scan for Vol.-86.2",
    "Vol.-87": "actually a scan of PG 97; used as an extra scan for Vol.-97",
}

# Extra scans of the same volume that live in another (excluded) repo.
EXTRA_SCAN_REPOS: dict[str, tuple[str, ...]] = {
    "Vol.-86.2": ("Vol.-86",),
    "Vol.-97": ("Vol.-87",),
}


def lookup(vol_nums: list[int], part: int | None = None) -> PGVolume | None:
    """Return the table entry for a repo's volume(s) (merged for combined bindings)."""
    if part is not None and (vol_nums[0], part) in PG_PARTS:
        return PG_PARTS[(vol_nums[0], part)]
    entries = [PG_VOLUMES[n] for n in vol_nums if n in PG_VOLUMES]
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0]
    authors: list[str] = []
    for e in entries:
        authors.extend(a for a in e.authors if a not in authors)
    confs = {e.date_confidence for e in entries}
    conf: DateConfidence = "established" if confs == {"established"} else (
        "uncertain" if "uncertain" in confs else "approximate")
    return PGVolume(
        tuple(authors),
        entries[0].date_composed,
        (min(e.date_range[0] for e in entries), max(e.date_range[1] for e in entries)),
        conf,
        "; ".join(e.note for e in entries if e.note) or None,
    )


def short_authors(authors: tuple[str, ...], limit: int = 3) -> str:
    """'A, B, C et al.' style label from an author tuple."""
    if len(authors) <= limit:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + " et al."
