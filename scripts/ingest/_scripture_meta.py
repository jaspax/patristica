"""
Shared metadata for canonical scripture books.

Provides OSIS abbreviations, full titles, date ranges, and ordered book lists
used by all scripture ingestor modules.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Ordered book lists
# ---------------------------------------------------------------------------

#: OSIS abbreviations for the 39 MT Old Testament books, in canonical order.
OT_BOOKS: list[str] = [
    "Gen", "Exod", "Lev", "Num", "Deut",
    "Josh", "Judg", "Ruth", "1Sam", "2Sam",
    "1Kgs", "2Kgs", "1Chr", "2Chr", "Ezra",
    "Neh", "Esth", "Job", "Ps", "Prov",
    "Eccl", "Song", "Isa", "Jer", "Lam",
    "Ezek", "Dan", "Hos", "Joel", "Amos",
    "Obad", "Jonah", "Mic", "Nah", "Hab",
    "Zeph", "Hag", "Zech", "Mal",
]

#: OSIS abbreviations for the 27 NT books, in canonical order.
NT_BOOKS: list[str] = [
    "Matt", "Mark", "Luke", "John", "Acts",
    "Rom", "1Cor", "2Cor", "Gal", "Eph",
    "Phil", "Col", "1Thess", "2Thess", "1Tim",
    "2Tim", "Titus", "Phlm", "Heb", "Jas",
    "1Pet", "2Pet", "1John", "2John", "3John",
    "Jude", "Rev",
]

#: OSIS abbreviations for the 7 Deuterocanonical books (Catholic/Orthodox canon).
DEUTEROCANON_BOOKS: list[str] = [
    "Tob", "Jdt", "1Macc", "2Macc", "Wis", "Sir", "Bar",
]

#: Books in the Ethiopic Orthodox canon not present in the Catholic Deuterocanon.
#: Includes both classic pseudepigrapha and Ethiopian-specific compositions.
ETHIOPIC_EXTRA_BOOKS: list[str] = [
    "1En",   # 1 Enoch
    "Jub",   # Jubilees
    "1Meq",  # 1 Meqabyan (not = 1 Maccabees)
    "2Meq",  # 2 Meqabyan
    "3Meq",  # 3 Meqabyan
    "4Bar",  # 4 Baruch / Paraleipomena of Jeremiah
    "Kings", # Combined Ethiopic Kings (1Sam–2Kgs folded; LXX "1–4 Kingdoms")
    "ApEz",  # Apocalypse of Ezra
    "Lef",   # Lefafa Sedq
    "MysHE", # Mysteries of Heaven and Earth
    "TestLd",# Testament of Our Lord
    "Teach", # Teaching of Mysteries
    "Sinod", # Sinodos
    "KN",    # Kebra Nagast (post-schism composition; flagged)
    "Synax", # Synaxarion (liturgical calendar; flagged)
    "Clem",  # Ethiopic Clement
]

#: Additional books found in the Armenian Apostolic canon (beyond Catholic Deuterocanon).
ARMENIAN_EXTRA_BOOKS: list[str] = [
    "3Macc", # 3 Maccabees (shared with Greek Orthodox)
    "1Esd",  # 1 Esdras (Greek Esdras / 3 Ezra)
    "3Cor",  # 3 Corinthians (apocryphal NT, canonical in Armenian tradition)
]

#: Full set in Protestant canonical order.
PROTESTANT_BOOKS: list[str] = OT_BOOKS + NT_BOOKS

#: Full set including Deuterocanon (Catholic order).
CATHOLIC_BOOKS: list[str] = OT_BOOKS + DEUTEROCANON_BOOKS + NT_BOOKS


# ---------------------------------------------------------------------------
# Full title map  (OSIS abbrev → full English title)
# ---------------------------------------------------------------------------

BOOK_TITLE: dict[str, str] = {
    # OT
    "Gen": "Genesis", "Exod": "Exodus", "Lev": "Leviticus", "Num": "Numbers",
    "Deut": "Deuteronomy", "Josh": "Joshua", "Judg": "Judges", "Ruth": "Ruth",
    "1Sam": "1 Samuel", "2Sam": "2 Samuel", "1Kgs": "1 Kings", "2Kgs": "2 Kings",
    "1Chr": "1 Chronicles", "2Chr": "2 Chronicles", "Ezra": "Ezra",
    "Neh": "Nehemiah", "Esth": "Esther", "Job": "Job", "Ps": "Psalms",
    "Prov": "Proverbs", "Eccl": "Ecclesiastes", "Song": "Song of Songs",
    "Isa": "Isaiah", "Jer": "Jeremiah", "Lam": "Lamentations",
    "Ezek": "Ezekiel", "Dan": "Daniel", "Hos": "Hosea", "Joel": "Joel",
    "Amos": "Amos", "Obad": "Obadiah", "Jonah": "Jonah", "Mic": "Micah",
    "Nah": "Nahum", "Hab": "Habakkuk", "Zeph": "Zephaniah", "Hag": "Haggai",
    "Zech": "Zechariah", "Mal": "Malachi",
    # NT
    "Matt": "Matthew", "Mark": "Mark", "Luke": "Luke", "John": "John",
    "Acts": "Acts", "Rom": "Romans", "1Cor": "1 Corinthians",
    "2Cor": "2 Corinthians", "Gal": "Galatians", "Eph": "Ephesians",
    "Phil": "Philippians", "Col": "Colossians", "1Thess": "1 Thessalonians",
    "2Thess": "2 Thessalonians", "1Tim": "1 Timothy", "2Tim": "2 Timothy",
    "Titus": "Titus", "Phlm": "Philemon", "Heb": "Hebrews", "Jas": "James",
    "1Pet": "1 Peter", "2Pet": "2 Peter", "1John": "1 John",
    "2John": "2 John", "3John": "3 John", "Jude": "Jude", "Rev": "Revelation",
    # Deuterocanon
    "Tob": "Tobit", "Jdt": "Judith", "1Macc": "1 Maccabees",
    "2Macc": "2 Maccabees", "Wis": "Wisdom of Solomon",
    "Sir": "Sirach", "Bar": "Baruch",
    # Ethiopic Orthodox extra books
    "1En": "1 Enoch", "Jub": "Jubilees",
    "1Meq": "1 Meqabyan", "2Meq": "2 Meqabyan", "3Meq": "3 Meqabyan",
    "4Bar": "4 Baruch", "Kings": "Kings",
    "ApEz": "Apocalypse of Ezra", "Lef": "Lefafa Sedq",
    "MysHE": "Mysteries of Heaven and Earth",
    "TestLd": "Testament of Our Lord", "Teach": "Teaching of Mysteries",
    "Sinod": "Sinodos", "KN": "Kebra Nagast", "Synax": "Synaxarion",
    "Clem": "Ethiopic Clement",
    # Armenian extra books
    "3Macc": "3 Maccabees", "3Cor": "3 Corinthians",
    "1Esd": "1 Esdras",
}


# ---------------------------------------------------------------------------
# Date metadata per book  (OSIS abbrev → dict)
# ---------------------------------------------------------------------------
# date_composed: best single estimate (CE, negative = BCE)
# date_range: (earliest, latest) in CE years (negative = BCE)
# date_confidence: "established" | "approximate" | "uncertain"

BOOK_DATES: dict[str, dict] = {
    # Pentateuch — traditional Mosaic authorship debated; scholarly consensus: Persian period
    "Gen":  {"date_composed": -500, "date_range": (-1000, -400), "date_confidence": "uncertain"},
    "Exod": {"date_composed": -500, "date_range": (-1000, -400), "date_confidence": "uncertain"},
    "Lev":  {"date_composed": -500, "date_range": (-600, -400),  "date_confidence": "uncertain"},
    "Num":  {"date_composed": -500, "date_range": (-600, -400),  "date_confidence": "uncertain"},
    "Deut": {"date_composed": -620, "date_range": (-700, -400),  "date_confidence": "approximate"},
    # Historical books
    "Josh": {"date_composed": -600, "date_range": (-900, -400),  "date_confidence": "uncertain"},
    "Judg": {"date_composed": -600, "date_range": (-900, -400),  "date_confidence": "uncertain"},
    "Ruth": {"date_composed": -500, "date_range": (-600, -400),  "date_confidence": "uncertain"},
    "1Sam": {"date_composed": -600, "date_range": (-700, -500),  "date_confidence": "uncertain"},
    "2Sam": {"date_composed": -600, "date_range": (-700, -500),  "date_confidence": "uncertain"},
    "1Kgs": {"date_composed": -600, "date_range": (-700, -550),  "date_confidence": "approximate"},
    "2Kgs": {"date_composed": -560, "date_range": (-620, -550),  "date_confidence": "approximate"},
    "1Chr": {"date_composed": -400, "date_range": (-450, -350),  "date_confidence": "approximate"},
    "2Chr": {"date_composed": -400, "date_range": (-450, -350),  "date_confidence": "approximate"},
    "Ezra": {"date_composed": -400, "date_range": (-450, -350),  "date_confidence": "approximate"},
    "Neh":  {"date_composed": -400, "date_range": (-445, -350),  "date_confidence": "approximate"},
    "Esth": {"date_composed": -400, "date_range": (-500, -300),  "date_confidence": "uncertain"},
    # Wisdom
    "Job":  {"date_composed": -500, "date_range": (-700, -400),  "date_confidence": "uncertain"},
    "Ps":   {"date_composed": -500, "date_range": (-1000, -200), "date_confidence": "uncertain"},
    "Prov": {"date_composed": -500, "date_range": (-700, -400),  "date_confidence": "uncertain"},
    "Eccl": {"date_composed": -250, "date_range": (-350, -180),  "date_confidence": "approximate"},
    "Song": {"date_composed": -500, "date_range": (-700, -400),  "date_confidence": "uncertain"},
    # Major prophets
    "Isa":  {"date_composed": -700, "date_range": (-740, -530),  "date_confidence": "approximate"},
    "Jer":  {"date_composed": -587, "date_range": (-627, -580),  "date_confidence": "approximate"},
    "Lam":  {"date_composed": -586, "date_range": (-587, -580),  "date_confidence": "approximate"},
    "Ezek": {"date_composed": -590, "date_range": (-593, -570),  "date_confidence": "approximate"},
    "Dan":  {"date_composed": -164, "date_range": (-167, -163),  "date_confidence": "approximate"},
    # Minor prophets
    "Hos":  {"date_composed": -750, "date_range": (-780, -725),  "date_confidence": "approximate"},
    "Joel": {"date_composed": -400, "date_range": (-500, -300),  "date_confidence": "uncertain"},
    "Amos": {"date_composed": -760, "date_range": (-760, -750),  "date_confidence": "approximate"},
    "Obad": {"date_composed": -586, "date_range": (-586, -400),  "date_confidence": "uncertain"},
    "Jonah":{"date_composed": -500, "date_range": (-600, -400),  "date_confidence": "uncertain"},
    "Mic":  {"date_composed": -735, "date_range": (-737, -700),  "date_confidence": "approximate"},
    "Nah":  {"date_composed": -620, "date_range": (-663, -612),  "date_confidence": "approximate"},
    "Hab":  {"date_composed": -610, "date_range": (-620, -598),  "date_confidence": "approximate"},
    "Zeph": {"date_composed": -630, "date_range": (-640, -620),  "date_confidence": "approximate"},
    "Hag":  {"date_composed": -520, "date_range": (-520, -519),  "date_confidence": "established"},
    "Zech": {"date_composed": -519, "date_range": (-520, -480),  "date_confidence": "approximate"},
    "Mal":  {"date_composed": -450, "date_range": (-500, -400),  "date_confidence": "approximate"},
    # NT — all well-established 1st century dates
    "Matt": {"date_composed": 80,  "date_range": (70, 100),   "date_confidence": "approximate"},
    "Mark": {"date_composed": 68,  "date_range": (65, 75),    "date_confidence": "approximate"},
    "Luke": {"date_composed": 80,  "date_range": (75, 90),    "date_confidence": "approximate"},
    "John": {"date_composed": 90,  "date_range": (85, 100),   "date_confidence": "approximate"},
    "Acts": {"date_composed": 80,  "date_range": (75, 90),    "date_confidence": "approximate"},
    "Rom":  {"date_composed": 57,  "date_range": (55, 58),    "date_confidence": "established"},
    "1Cor": {"date_composed": 55,  "date_range": (53, 57),    "date_confidence": "established"},
    "2Cor": {"date_composed": 56,  "date_range": (55, 57),    "date_confidence": "established"},
    "Gal":  {"date_composed": 50,  "date_range": (48, 55),    "date_confidence": "approximate"},
    "Eph":  {"date_composed": 62,  "date_range": (58, 90),    "date_confidence": "uncertain"},
    "Phil": {"date_composed": 62,  "date_range": (60, 63),    "date_confidence": "approximate"},
    "Col":  {"date_composed": 62,  "date_range": (58, 80),    "date_confidence": "uncertain"},
    "1Thess":{"date_composed":51,  "date_range": (50, 52),    "date_confidence": "established"},
    "2Thess":{"date_composed":52,  "date_range": (50, 90),    "date_confidence": "uncertain"},
    "1Tim": {"date_composed": 62,  "date_range": (60, 100),   "date_confidence": "uncertain"},
    "2Tim": {"date_composed": 65,  "date_range": (60, 100),   "date_confidence": "uncertain"},
    "Titus":{"date_composed": 63,  "date_range": (60, 100),   "date_confidence": "uncertain"},
    "Phlm": {"date_composed": 62,  "date_range": (60, 63),    "date_confidence": "approximate"},
    "Heb":  {"date_composed": 70,  "date_range": (65, 90),    "date_confidence": "approximate"},
    "Jas":  {"date_composed": 50,  "date_range": (45, 60),    "date_confidence": "uncertain"},
    "1Pet": {"date_composed": 64,  "date_range": (60, 90),    "date_confidence": "uncertain"},
    "2Pet": {"date_composed": 100, "date_range": (80, 120),   "date_confidence": "uncertain"},
    "1John":{"date_composed": 95,  "date_range": (85, 100),   "date_confidence": "approximate"},
    "2John":{"date_composed": 95,  "date_range": (85, 100),   "date_confidence": "approximate"},
    "3John":{"date_composed": 95,  "date_range": (85, 100),   "date_confidence": "approximate"},
    "Jude": {"date_composed": 70,  "date_range": (65, 100),   "date_confidence": "uncertain"},
    "Rev":  {"date_composed": 95,  "date_range": (81, 96),    "date_confidence": "approximate"},
    # Ethiopic Orthodox extra books
    "1En":   {"date_composed": -200, "date_range": (-300, -100), "date_confidence": "approximate"},
    "Jub":   {"date_composed": -155, "date_range": (-170, -140), "date_confidence": "approximate"},
    "1Meq":  {"date_composed": 500,  "date_range": (400, 700),   "date_confidence": "uncertain"},
    "2Meq":  {"date_composed": 500,  "date_range": (400, 700),   "date_confidence": "uncertain"},
    "3Meq":  {"date_composed": 500,  "date_range": (400, 700),   "date_confidence": "uncertain"},
    "4Bar":  {"date_composed": 100,  "date_range": (70, 135),    "date_confidence": "approximate"},
    "Kings": {"date_composed": -600, "date_range": (-900, -550), "date_confidence": "uncertain"},
    "ApEz":  {"date_composed": 100,  "date_range": (70, 218),    "date_confidence": "uncertain"},
    "Lef":   {"date_composed": 500,  "date_range": (400, 800),   "date_confidence": "uncertain"},
    "MysHE": {"date_composed": 500,  "date_range": (400, 800),   "date_confidence": "uncertain"},
    "TestLd":{"date_composed": 400,  "date_range": (350, 600),   "date_confidence": "uncertain"},
    "Teach": {"date_composed": 500,  "date_range": (400, 800),   "date_confidence": "uncertain"},
    "Sinod": {"date_composed": 400,  "date_range": (300, 700),   "date_confidence": "uncertain"},
    # Kebra Nagast: compiled ~13th c. CE from older sources; post-schism composition
    "KN":    {"date_composed": 1250, "date_range": (1200, 1325), "date_confidence": "approximate"},
    "Synax": {"date_composed": 1400, "date_range": (1200, 1500), "date_confidence": "uncertain"},
    "Clem":  {"date_composed": 400,  "date_range": (300, 600),   "date_confidence": "uncertain"},
    # Armenian / Greek Orthodox extra books
    "3Macc": {"date_composed": -100, "date_range": (-130, -70),  "date_confidence": "approximate"},
    "3Cor":  {"date_composed": 160,  "date_range": (150, 250),   "date_confidence": "approximate"},
    "1Esd":  {"date_composed": -200, "date_range": (-400, -100), "date_confidence": "uncertain"},
    # Deuterocanon
    "Tob":  {"date_composed": -200, "date_range": (-300, -100), "date_confidence": "approximate"},
    "Jdt":  {"date_composed": -150, "date_range": (-200, -100), "date_confidence": "approximate"},
    "1Macc":{"date_composed": -100, "date_range": (-135, -63),  "date_confidence": "approximate"},
    "2Macc":{"date_composed": -120, "date_range": (-150, -50),  "date_confidence": "approximate"},
    "Wis":  {"date_composed": -50,  "date_range": (-100, 50),   "date_confidence": "approximate"},
    "Sir":  {"date_composed": -180, "date_range": (-200, -175), "date_confidence": "approximate"},
    "Bar":  {"date_composed": -150, "date_range": (-300, -100), "date_confidence": "uncertain"},
}


# ---------------------------------------------------------------------------
# Full-name → OSIS abbreviation map  (used for CSV sources that give full names)
# ---------------------------------------------------------------------------

FULL_NAME_TO_ABBREV: dict[str, str] = {
    # Standard English full names
    "Genesis": "Gen", "Exodus": "Exod", "Leviticus": "Lev", "Numbers": "Num",
    "Deuteronomy": "Deut", "Joshua": "Josh", "Judges": "Judg", "Ruth": "Ruth",
    "1 Samuel": "1Sam", "2 Samuel": "2Sam", "1 Kings": "1Kgs", "2 Kings": "2Kgs",
    "1 Chronicles": "1Chr", "2 Chronicles": "2Chr", "Ezra": "Ezra",
    "Nehemiah": "Neh", "Esther": "Esth", "Job": "Job", "Psalms": "Ps",
    "Psalm": "Ps", "Proverbs": "Prov", "Ecclesiastes": "Eccl",
    "Song of Solomon": "Song", "Song of Songs": "Song",
    "Isaiah": "Isa", "Jeremiah": "Jer", "Lamentations": "Lam",
    "Ezekiel": "Ezek", "Daniel": "Dan", "Hosea": "Hos", "Joel": "Joel",
    "Amos": "Amos", "Obadiah": "Obad", "Jonah": "Jonah", "Micah": "Mic",
    "Nahum": "Nah", "Habakkuk": "Hab", "Zephaniah": "Zeph", "Haggai": "Hag",
    "Zechariah": "Zech", "Malachi": "Mal",
    "Matthew": "Matt", "Mark": "Mark", "Luke": "Luke", "John": "John",
    "Acts": "Acts", "Romans": "Rom",
    "1 Corinthians": "1Cor", "2 Corinthians": "2Cor",
    "Galatians": "Gal", "Ephesians": "Eph", "Philippians": "Phil",
    "Colossians": "Col", "1 Thessalonians": "1Thess", "2 Thessalonians": "2Thess",
    "1 Timothy": "1Tim", "2 Timothy": "2Tim",
    "Titus": "Titus", "Philemon": "Phlm", "Hebrews": "Heb", "James": "Jas",
    "1 Peter": "1Pet", "2 Peter": "2Pet",
    "1 John": "1John", "2 John": "2John", "3 John": "3John",
    "Jude": "Jude", "Revelation": "Rev",
    # Deuterocanon
    "Tobit": "Tob", "Judith": "Jdt",
    "1 Maccabees": "1Macc", "2 Maccabees": "2Macc",
    "Wisdom of Solomon": "Wis", "Wisdom": "Wis",
    "Sirach": "Sir", "Ecclesiasticus": "Sir",
    "Baruch": "Bar",
    # Ethiopic extra
    "1 Enoch": "1En", "Enoch": "1En",
    "Jubilees": "Jub",
    "1 Meqabyan": "1Meq", "2 Meqabyan": "2Meq", "3 Meqabyan": "3Meq",
    "4 Baruch": "4Bar", "Paraleipomena of Jeremiah": "4Bar",
    "Kings": "Kings",
    "Apocalypse of Ezra": "ApEz",
    "Lefafa Sedq": "Lef",
    "Mysteries of Heaven and Earth": "MysHE",
    "Testament of Our Lord": "TestLd",
    "Teaching of Mysteries": "Teach",
    "Sinodos": "Sinod",
    "Kebra Nagast": "KN",
    "Synaxarion": "Synax",
    "Ethiopic Clement": "Clem",
    # Armenian / Greek Orthodox extra
    "3 Maccabees": "3Macc",
    "3 Corinthians": "3Cor",
    "1 Esdras": "1Esd", "3 Ezra": "1Esd",
}


def book_work_id(source_id: str, abbrev: str) -> str:
    """Return the work_id slug for a given source and book abbreviation.

    E.g. ``book_work_id("scripture/oshb", "Gen")`` → ``"scripture/oshb/gen"``.
    """
    return f"{source_id}/{abbrev.lower()}"
