"""
Shared metadata for patristic authors and works.

Provides author abbreviations, dates, traditions, and work metadata used by
patristic ingestor modules.  The abbreviations are designed to be stable across
sources so that the same canonical_ref can link parallel texts from different
collections (e.g. PTA Greek + CCEL English translation).

Author abbreviation conventions:
  - Use the most widely recognised Latin/English short form
  - Single-word when possible (Ign, Ath, Aug, Bas, etc.)
  - For two authors with the same initial letter: add a disambiguating letter
    (GregNaz vs GregNyss vs GregMag)

Work abbreviation conventions:
  - Abbreviate the Latin title where one exists (Conf, Haer, Strom, etc.)
  - For letters/homilies: Ep{n}, Hom{series}
"""

from __future__ import annotations

from dataclasses import dataclass

from patristica.models import DateConfidence, Language, Tradition


@dataclass(frozen=True)
class AuthorMeta:
    abbrev: str
    full_name: str
    dates: tuple[int, int]          # (birth_year, death_year), approx
    tradition: Tradition
    language: Language              # primary language of composition


@dataclass(frozen=True)
class WorkMeta:
    abbrev: str
    author_abbrev: str
    title: str                      # English title
    date_composed: int | None       # best single estimate (CE)
    date_range: tuple[int, int] | None
    date_confidence: DateConfidence


# ---------------------------------------------------------------------------
# Authors
# ---------------------------------------------------------------------------

AUTHORS: dict[str, AuthorMeta] = {a.abbrev: a for a in [
    # --- Apostolic Fathers ---
    AuthorMeta("Ign",       "Ignatius of Antioch",              (35, 107),   "greek",   "grc"),
    AuthorMeta("Pol",       "Polycarp of Smyrna",               (69, 155),   "greek",   "grc"),
    AuthorMeta("Barn",      "Pseudo-Barnabas",                  (70, 132),   "greek",   "grc"),
    AuthorMeta("Herm",      "Hermas",                           (100, 160),  "greek",   "grc"),
    AuthorMeta("Did",       "Didache",                          (50, 120),   "greek",   "grc"),
    AuthorMeta("1Clem",     "Clement of Rome",                  (30, 99),    "greek",   "grc"),
    AuthorMeta("2Clem",     "Pseudo-Clement (2 Clement)",       (100, 160),  "greek",   "grc"),
    AuthorMeta("DiogNet",   "Epistle to Diognetus",             (150, 200),  "greek",   "grc"),

    # --- Greek Apologists ---
    AuthorMeta("Just",      "Justin Martyr",                    (100, 165),  "greek",   "grc"),
    AuthorMeta("Tat",       "Tatian",                           (120, 180),  "greek",   "grc"),
    AuthorMeta("Athen",     "Athenagoras of Athens",            (133, 190),  "greek",   "grc"),
    AuthorMeta("Theoph",    "Theophilus of Antioch",            (120, 185),  "greek",   "grc"),

    # --- Early Church Fathers ---
    AuthorMeta("Iren",      "Irenaeus of Lyon",                 (130, 202),  "greek",   "grc"),
    AuthorMeta("Clem",      "Clement of Alexandria",            (150, 215),  "greek",   "grc"),
    AuthorMeta("Orig",      "Origen of Alexandria",             (184, 253),  "greek",   "grc"),
    AuthorMeta("Tert",      "Tertullian",                       (155, 240),  "latin",   "lat"),
    AuthorMeta("Cypr",      "Cyprian of Carthage",              (200, 258),  "latin",   "lat"),
    AuthorMeta("Hippo",     "Hippolytus of Rome",               (170, 235),  "greek",   "grc"),
    AuthorMeta("Novatian",  "Novatian",                         (200, 258),  "latin",   "lat"),
    AuthorMeta("Euseb",     "Eusebius of Caesarea",             (260, 340),  "greek",   "grc"),
    AuthorMeta("Lact",      "Lactantius",                       (250, 325),  "latin",   "lat"),
    AuthorMeta("Arnob",     "Arnobius of Sicca",                (255, 330),  "latin",   "lat"),

    # --- Nicene and Post-Nicene Fathers (Greek) ---
    AuthorMeta("Ath",       "Athanasius of Alexandria",         (296, 373),  "greek",   "grc"),
    AuthorMeta("Eph",       "Ephrem the Syrian",                (306, 373),  "syriac",  "syc"),
    AuthorMeta("Bas",       "Basil of Caesarea",                (330, 379),  "greek",   "grc"),
    AuthorMeta("GregNaz",   "Gregory of Nazianzus",             (329, 390),  "greek",   "grc"),
    AuthorMeta("GregNyss",  "Gregory of Nyssa",                 (335, 395),  "greek",   "grc"),
    AuthorMeta("Amphil",    "Amphilochius of Iconium",          (340, 395),  "greek",   "grc"),
    AuthorMeta("Chrys",     "John Chrysostom",                  (347, 407),  "greek",   "grc"),
    AuthorMeta("Didym",     "Didymus the Blind",                (313, 398),  "greek",   "grc"),
    AuthorMeta("Epiphan",   "Epiphanius of Salamis",            (310, 403),  "greek",   "grc"),
    AuthorMeta("Thdr",      "Theodore of Mopsuestia",           (350, 428),  "greek",   "grc"),
    AuthorMeta("CyrAlex",   "Cyril of Alexandria",              (376, 444),  "greek",   "grc"),
    AuthorMeta("Nestor",    "Nestorius",                        (381, 451),  "greek",   "grc"),
    AuthorMeta("Proc",      "Proclus of Constantinople",        (390, 446),  "greek",   "grc"),
    AuthorMeta("Theodoret", "Theodoret of Cyrrhus",             (393, 457),  "greek",   "grc"),
    AuthorMeta("Ps-Dion",   "Pseudo-Dionysius the Areopagite",  (490, 530),  "greek",   "grc"),
    AuthorMeta("Maximus",   "Maximus the Confessor",            (580, 662),  "greek",   "grc"),
    AuthorMeta("JohnDam",   "John of Damascus",                 (675, 749),  "greek",   "grc"),
    AuthorMeta("TheodStr",  "Theodore the Studite",             (759, 826),  "greek",   "grc"),
    AuthorMeta("Phot",      "Photius of Constantinople",        (815, 893),  "greek",   "grc"),

    # --- Nicene and Post-Nicene Fathers (Latin) ---
    AuthorMeta("Ambr",      "Ambrose of Milan",                 (340, 397),  "latin",   "lat"),
    AuthorMeta("Jer",       "Jerome",                           (347, 420),  "latin",   "lat"),
    AuthorMeta("Aug",       "Augustine of Hippo",               (354, 430),  "latin",   "lat"),
    AuthorMeta("Pelag",     "Pelagius",                         (354, 420),  "latin",   "lat"),
    AuthorMeta("Ruf",       "Rufinus of Aquileia",              (344, 411),  "latin",   "lat"),
    AuthorMeta("CassJohn",  "John Cassian",                     (360, 435),  "latin",   "lat"),
    AuthorMeta("Leo",       "Leo the Great",                    (400, 461),  "latin",   "lat"),
    AuthorMeta("GregMag",   "Gregory the Great",                (540, 604),  "latin",   "lat"),
    AuthorMeta("Bede",      "Bede the Venerable",               (672, 735),  "latin",   "lat"),
    AuthorMeta("Isid",      "Isidore of Seville",               (560, 636),  "latin",   "lat"),
    AuthorMeta("Boeth",     "Boethius",                         (480, 524),  "latin",   "lat"),
    AuthorMeta("CassInst",  "Cassiodorus",                      (485, 585),  "latin",   "lat"),
    AuthorMeta("Fulgent",   "Fulgentius of Ruspe",              (462, 527),  "latin",   "lat"),

    # --- Syriac Fathers ---
    AuthorMeta("Aphrahat",  "Aphrahat the Persian Sage",        (270, 345),  "syriac",  "syc"),
    AuthorMeta("Narsai",    "Narsai of Nisibis",                (399, 502),  "syriac",  "syc"),
    AuthorMeta("IsaacNin",  "Isaac of Nineveh",                 (613, 700),  "syriac",  "syc"),

    # --- Coptic Fathers ---
    AuthorMeta("Pach",      "Pachomius",                        (292, 348),  "coptic",  "cop"),
    AuthorMeta("Shenoute",  "Shenoute of Atripe",               (347, 465),  "coptic",  "cop"),
]}

# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

WORKS: dict[str, WorkMeta] = {f"{w.author_abbrev}.{w.abbrev}": w for w in [
    # Ignatius of Antioch
    WorkMeta("Eph",         "Ign",      "Epistle to the Ephesians",                 107,  (105, 110),  "established"),
    WorkMeta("Magn",        "Ign",      "Epistle to the Magnesians",                107,  (105, 110),  "established"),
    WorkMeta("Trall",       "Ign",      "Epistle to the Trallians",                 107,  (105, 110),  "established"),
    WorkMeta("Rom",         "Ign",      "Epistle to the Romans",                    107,  (105, 110),  "established"),
    WorkMeta("Phld",        "Ign",      "Epistle to the Philadelphians",            107,  (105, 110),  "established"),
    WorkMeta("Smyrn",       "Ign",      "Epistle to the Smyrnaeans",                107,  (105, 110),  "established"),
    WorkMeta("Pol",         "Ign",      "Epistle to Polycarp",                      107,  (105, 110),  "established"),

    # Justin Martyr
    WorkMeta("1Apol",       "Just",     "First Apology",                            155,  (150, 160),  "established"),
    WorkMeta("2Apol",       "Just",     "Second Apology",                           157,  (153, 161),  "approximate"),
    WorkMeta("Dial",        "Just",     "Dialogue with Trypho",                     160,  (155, 165),  "approximate"),

    # Irenaeus
    WorkMeta("Haer",        "Iren",     "Against Heresies (Adversus Haereses)",     180,  (175, 185),  "established"),
    WorkMeta("Epid",        "Iren",     "Proof of the Apostolic Preaching",         190,  (185, 200),  "approximate"),

    # Clement of Alexandria
    WorkMeta("Protr",       "Clem",     "Protrepticus (Exhortation to the Greeks)", 195,  (190, 200),  "approximate"),
    WorkMeta("Paid",        "Clem",     "Paedagogus (The Instructor)",              198,  (190, 205),  "approximate"),
    WorkMeta("Strom",       "Clem",     "Stromateis",                               202,  (198, 215),  "approximate"),

    # Origen
    WorkMeta("CelsCont",    "Orig",     "Contra Celsum",                            248,  (246, 250),  "established"),
    WorkMeta("Princ",       "Orig",     "De Principiis",                            225,  (220, 230),  "approximate"),
    WorkMeta("CommJn",      "Orig",     "Commentary on John",                       230,  (225, 240),  "approximate"),

    # Tertullian
    WorkMeta("Apol",        "Tert",     "Apologeticum",                             197,  (196, 198),  "established"),
    WorkMeta("PraescHaer",  "Tert",     "De Praescriptione Haereticorum",           200,  (198, 203),  "approximate"),
    WorkMeta("Bapt",        "Tert",     "De Baptismo",                              198,  (196, 206),  "approximate"),

    # Cyprian
    WorkMeta("Unit",        "Cypr",     "De Unitate Ecclesiae",                     251,  (249, 253),  "established"),
    WorkMeta("Laps",        "Cypr",     "De Lapsis",                                251,  (249, 253),  "established"),

    # Eusebius
    WorkMeta("HE",          "Euseb",    "Historia Ecclesiastica",                   313,  (303, 325),  "established"),
    WorkMeta("PE",          "Euseb",    "Praeparatio Evangelica",                   314,  (310, 320),  "approximate"),

    # Athanasius
    WorkMeta("IncVer",      "Ath",      "De Incarnatione Verbi",                    318,  (316, 328),  "approximate"),
    WorkMeta("VitAnt",      "Ath",      "Vita Antonii",                             357,  (355, 362),  "established"),
    WorkMeta("OratAr",      "Ath",      "Orations against the Arians",              339,  (335, 357),  "approximate"),

    # Basil of Caesarea
    WorkMeta("Hex",         "Bas",      "Hexaemeron",                               378,  (376, 379),  "established"),
    WorkMeta("SpiritSanct", "Bas",      "De Spiritu Sancto",                        375,  (374, 376),  "established"),
    WorkMeta("RegFus",      "Bas",      "Regulae Fusius Tractatae",                 358,  (355, 370),  "approximate"),

    # Gregory of Nazianzus
    WorkMeta("Orat",        "GregNaz",  "Theological Orations",                     380,  (379, 381),  "established"),
    WorkMeta("Ep",          "GregNaz",  "Epistles",                                 None, (359, 390),  "approximate"),
    WorkMeta("Poem",        "GregNaz",  "Poems",                                    None, (360, 390),  "approximate"),

    # Gregory of Nyssa
    WorkMeta("VitMoys",     "GregNyss", "Life of Moses",                            390,  (385, 395),  "approximate"),
    WorkMeta("HomOpif",     "GregNyss", "De Hominis Opificio",                      379,  (378, 380),  "established"),
    WorkMeta("VitMacr",     "GregNyss", "Life of Macrina",                          382,  (380, 385),  "approximate"),
    WorkMeta("CommCant",    "GregNyss", "Commentary on the Song of Songs",          394,  (390, 400),  "approximate"),

    # John Chrysostom
    WorkMeta("HomMatt",     "Chrys",    "Homilies on Matthew",                      390,  (386, 398),  "approximate"),
    WorkMeta("HomJn",       "Chrys",    "Homilies on John",                         391,  (388, 398),  "approximate"),
    WorkMeta("Sacerd",      "Chrys",    "De Sacerdotio",                            386,  (384, 390),  "approximate"),
    WorkMeta("HomRom",      "Chrys",    "Homilies on Romans",                       391,  (388, 398),  "approximate"),

    # Cyril of Alexandria
    WorkMeta("CommJn",      "CyrAlex",  "Commentary on John",                       425,  (420, 430),  "approximate"),
    WorkMeta("AnathemaNest","CyrAlex",  "Twelve Anathemas against Nestorius",       430,  (430, 431),  "established"),

    # Augustine
    WorkMeta("Conf",        "Aug",      "Confessiones",                             400,  (397, 401),  "established"),
    WorkMeta("CivDei",      "Aug",      "De Civitate Dei",                          426,  (413, 426),  "established"),
    WorkMeta("Trin",        "Aug",      "De Trinitate",                             420,  (399, 422),  "established"),
    WorkMeta("DocChr",      "Aug",      "De Doctrina Christiana",                   397,  (395, 426),  "established"),
    WorkMeta("EnchDir",     "Aug",      "Enchiridion",                              423,  (421, 423),  "established"),
    WorkMeta("SermMont",    "Aug",      "De Sermone Domini in Monte",               394,  (392, 396),  "approximate"),
    WorkMeta("GrLibArb",    "Aug",      "De Gratia et Libero Arbitrio",             426,  (426, 427),  "established"),

    # Ambrose
    WorkMeta("HexAmb",      "Ambr",     "Hexaemeron",                               389,  (386, 390),  "approximate"),
    WorkMeta("IncDom",      "Ambr",     "De Incarnationis Dominicae Sacramento",    382,  (380, 385),  "approximate"),
    WorkMeta("Spir",        "Ambr",     "De Spiritu Sancto",                        381,  (380, 382),  "established"),

    # Jerome
    WorkMeta("VirIll",      "Jer",      "De Viris Illustribus",                     392,  (391, 393),  "established"),
    WorkMeta("EpJer",       "Jer",      "Letters",                                  None, (370, 419),  "approximate"),

    # Leo the Great
    WorkMeta("Serm",        "Leo",      "Sermons",                                  None, (440, 461),  "approximate"),
    WorkMeta("Ep",          "Leo",      "Letters",                                  None, (440, 461),  "approximate"),
    WorkMeta("TomLeo",      "Leo",      "Tome to Flavian",                          449,  (449, 449),  "established"),

    # Pseudo-Dionysius
    WorkMeta("DivNom",      "Ps-Dion",  "De Divinis Nominibus",                     500,  (490, 520),  "approximate"),
    WorkMeta("CaelHier",    "Ps-Dion",  "De Coelesti Hierarchia",                   500,  (490, 520),  "approximate"),
    WorkMeta("EcclHier",    "Ps-Dion",  "De Ecclesiastica Hierarchia",              500,  (490, 520),  "approximate"),
    WorkMeta("MystTheol",   "Ps-Dion",  "Mystica Theologia",                        500,  (490, 520),  "approximate"),

    # Maximus the Confessor
    WorkMeta("AmbigMax",    "Maximus",  "Ambigua",                                  628,  (625, 640),  "approximate"),
    WorkMeta("MystaMax",    "Maximus",  "Mystagogia",                               628,  (625, 640),  "approximate"),
    WorkMeta("CharMax",     "Maximus",  "Four Centuries on Charity",                626,  (620, 630),  "approximate"),

    # John of Damascus
    WorkMeta("FidOrtJD",    "JohnDam",  "De Fide Orthodoxa",                        730,  (726, 749),  "approximate"),
    WorkMeta("ImgJD",       "JohnDam",  "On the Divine Images",                     726,  (724, 730),  "approximate"),
    WorkMeta("HaerJD",      "JohnDam",  "De Haeresibus",                            743,  (740, 749),  "approximate"),

    # Gregory the Great
    WorkMeta("RegGrMag",    "GregMag",  "Regula Pastoralis",                        590,  (590, 591),  "established"),
    WorkMeta("MorGrMag",    "GregMag",  "Moralia in Job",                           595,  (578, 595),  "established"),
    WorkMeta("HomEzGrMag",  "GregMag",  "Homilies on Ezekiel",                      593,  (590, 594),  "approximate"),
    WorkMeta("HomEvGrMag",  "GregMag",  "Homilies on the Gospels",                  591,  (590, 592),  "established"),
    WorkMeta("DialGrMag",   "GregMag",  "Dialogues",                                593,  (593, 594),  "established"),

    # Aphrahat
    WorkMeta("Dem",         "Aphrahat", "Demonstrations (Taḥwyātā)",               336,  (336, 345),  "established"),

    # Ephrem the Syrian
    WorkMeta("HymParad",    "Eph",      "Hymns on Paradise",                        350,  (345, 360),  "approximate"),
    WorkMeta("HymFast",     "Eph",      "Hymns on Fasting",                         356,  (350, 365),  "approximate"),
    WorkMeta("HymNat",      "Eph",      "Hymns on the Nativity",                    363,  (358, 368),  "approximate"),
    WorkMeta("HymEpiph",    "Eph",      "Hymns on Epiphany",                        363,  (358, 368),  "approximate"),
]}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_author(abbrev: str) -> AuthorMeta | None:
    """Return AuthorMeta for *abbrev*, or ``None`` if not found."""
    return AUTHORS.get(abbrev)


def get_work(author_abbrev: str, work_abbrev: str) -> WorkMeta | None:
    """Return WorkMeta for *author_abbrev*.*work_abbrev*, or ``None``."""
    return WORKS.get(f"{author_abbrev}.{work_abbrev}")


def author_work_id(author_abbrev: str, work_abbrev: str) -> str:
    """Return a slug work_id like ``"augustine/confessions"``.

    Falls back to ``"{abbrev}/{work_abbrev.lower()}"`` if the author is not in
    the metadata table.
    """
    author = AUTHORS.get(author_abbrev)
    if author is None:
        slug_author = author_abbrev.lower()
    else:
        slug_author = author.full_name.lower().replace(" ", "-").replace(".", "")
    slug_work = work_abbrev.lower()
    return f"{slug_author}/{slug_work}"
