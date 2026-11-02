"""Human-readable labels for ingestion sources (``Work.source_id``).

``source_id`` is an internal identifier; anything shown to users (the library
browser, the licence page) uses these labels instead.  Every source in
``data/normalized/_works.jsonl`` must have an entry — enforced by
``tests/test_export_library.py``.
"""

from __future__ import annotations

SOURCE_LABELS: dict[str, str] = {
    # Scripture
    "armenian": "Classical Armenian Bible (Zohrab)",
    "asv": "American Standard Version",
    "ccmh-assemanianus": "Codex Assemanianus (Old Church Slavonic, CCMH)",
    "ccmh-marianus": "Codex Marianus (Old Church Slavonic, CCMH)",
    "ccmh-savvina": "Savvina kniga (Old Church Slavonic, CCMH)",
    "ccmh-zographensis": "Codex Zographensis (Old Church Slavonic, CCMH)",
    "clementine": "Clementine Vulgate",
    "coptic-nt": "Sahidic Coptic Bible",
    "demetrius-psalter": "Psalter of Demetrius (Sinai, Glagolitic)",
    "gez": "Ge'ez Bible (Ethiopian canon)",
    "kjv": "King James Version",
    "lxx-rahlfs": "Septuagint (Rahlfs)",
    "oshb": "Open Scriptures Hebrew Bible",
    "pta-lxx": "Septuagint (Patristic Text Archive)",
    "pta-peshitta": "Peshitta (Patristic Text Archive)",
    "sblgnt": "SBL Greek New Testament",
    "web": "World English Bible",
    "wulfila": "Gothic Bible (Wulfila)",
    # Patristic
    "anf-works": "Ante-Nicene Fathers",
    "apostolic-constitutions": "Apostolic Constitutions (Ante-Nicene Fathers)",
    "aspr": "Anglo-Saxon Poetic Records (Old English; Oxford Text Archive)",
    "ccmh": "Corpus Cyrillo-Methodianum Helsingiense",
    "ccmh-supr": "Codex Suprasliensis (CCMH)",
    "titus-hagiography": "Old Georgian Hagiography (TITUS)",
    "coptic-scriptorium": "Coptic Scriptorium",
    "coptic-scriptorium-eng": "Coptic Scriptorium (English translations)",
    "celt": "CELT, Corpus of Electronic Texts (Old Irish)",
    "csel": "Corpus Scriptorum Ecclesiasticorum Latinorum (Open Greek and Latin)",
    "didache": "Didache (Ante-Nicene Fathers)",
    "dsc": "Digital Syriac Corpus",
    "evetts-hop-eng": "History of the Patriarchs of Alexandria (Evetts, Patrologia Orientalis)",
    "first1k": "First Thousand Years of Greek",
    "first1k-eng": "First Thousand Years of Greek (English translations)",
    "npnf-works": "Nicene and Post-Nicene Fathers",
    "ocp": "Online Critical Pseudepigrapha",
    "oglt-pl": "Patrologia Latina (Open Greek and Latin)",
    "ogpg": "Patrologia Graeca (Open Greek and Latin)",
    "openiti": "OpenITI (Open Islamicate Texts Initiative)",
    "perseus": "Perseus Digital Library",
    "perseus-eng": "Perseus Digital Library (English translations)",
    "pta": "Patristic Text Archive",
    "pta-eng": "Patristic Text Archive (English translations)",
    "pearse-arabic": "Christian Arabic texts (Roger Pearse, tertullian.org)",
    "pearse-arabic-eng": "Christian Arabic texts (Roger Pearse, tertullian.org; English translations)",
    "titus-chronicles": "Georgian Chronicle, vol. I (Old Georgian, TITUS)",
    "titus-shatberdi": "Shatberdi Codex (Old Georgian, TITUS)",
    "titus-translations": "Old Georgian translations of the Fathers (TITUS)",
    "torot": "TOROT (Old Church Slavonic Treebank)",
    "rea": "Referenzkorpus Altdeutsch (ReA 1.2: Old High German and Old Saxon)",
    "wikisource-apocrypha": "Apocrypha, Greek (Wikisource)",
    "wikisource-oge": "Old Georgian texts (Georgian Wikisource)",
    "syriac-documents": "Ancient Syriac Documents (Ante-Nicene Fathers)",
    "wb-glosses": "Würzburg Glosses on Paul (Old Irish; Doyle, Thesaurus Palaeohibernicus)",
    "wb-glosses-eng": "Würzburg Glosses on Paul (Stokes and Strachan's English, Thesaurus Palaeohibernicus)",
    "aelfric-ch": "Ælfric, Catholic Homilies I (Old English; Thorpe 1844, Project Gutenberg)",
    "aelfric-ch-eng": "Ælfric, Catholic Homilies I (Thorpe's English, 1844, Project Gutenberg)",
    # Liturgical
    "adai-mari": "Liturgy of Addai and Mari (Ante-Nicene Fathers)",
    "armenian-liturgy": "Armenian Liturgy (Issaverdens)",
    "cantus": "CANTUS Database",
    "cursus": "CURSUS Project",
    "gallican": "Gallican Liturgy",
    "gez-anaphoras": "Anaphoras of the Ethiopic Liturgy",
    "glosscorpus": "Gloss Corpus (Moran, Galway)",
    "goarch-basil": "Liturgy of St Basil (GOA Digital Chant Stand)",
    "goarch-chrysostom": "Liturgy of St John Chrysostom (GOA Digital Chant Stand)",
    "hudra": "Hudra (East Syriac)",
    "mark-liturgy": "Liturgy of St Mark (Ante-Nicene Fathers)",
    "mozarabic": "Mozarabic Liturgy (Férotin)",
    "serapion": "Prayer-Book of Sarapion",
    "syriac-james": "Syriac Liturgy of St James (Ante-Nicene Fathers)",
    "titus-liturgy": "Old Georgian Liturgies (TITUS)",
    "typikon": "Typikon (Violakis)",
    # Councils
    "ecumenical": "Ecumenical and Local Councils (Nicene and Post-Nicene Fathers)",
    "wikisource-canons": "Holy Canons, Greek (Wikisource)",
    # Derived sources
    "mt-eng": "Patristica machine translations (English)",
    # Old Georgian Bible and lectionaries from TITUS (#515)
    "titus-khanmeti-gospels": "Khanmeti Gospels, palimpsest A-89/A-844 (Old Georgian, TITUS)",
    "titus-adishi": "Adishi Gospels (Old Georgian, TITUS)",
    "titus-preathonite-gospels": "Pre-Athonite Gospels (Old Georgian, TITUS)",
    "titus-athonite-gospels": "Athonite Gospels of George the Athonite (Old Georgian, TITUS)",
    "titus-acts-sinai": "Acts, oldest redaction (Old Georgian, TITUS)",
    "titus-acts-ab": "Acts, redactions A and B (Old Georgian, TITUS)",
    "titus-paul-ab": "Pauline Epistles, redaction AB (Old Georgian, TITUS)",
    "titus-paul-cd": "Pauline Epistles, redaction CD (Old Georgian, TITUS)",
    "titus-catholic-a1": "Catholic Epistles, redaction A1 (Old Georgian, TITUS)",
    "titus-catholic-b": "Catholic Epistles, redaction B (Old Georgian, TITUS)",
    "titus-catholic-g": "Catholic Epistles, redaction G (Old Georgian, TITUS)",
    "titus-catholic-d": "Catholic Epistles, redaction D (Old Georgian, TITUS)",
    "titus-apocalypse": "Apocalypse of Euthymius the Athonite (Old Georgian, TITUS)",
    "titus-oshki": "Oshki and Jerusalem Old Testament (Old Georgian, TITUS)",
    "titus-psalter-a": "Psalms and Odes, redaction A (Old Georgian, TITUS)",
    "titus-paris-lectionary": "Paris Lectionary (Old Georgian, TITUS)",
    "titus-khanmeti-lectionary": "Khanmeti Lectionary (Old Georgian, TITUS)",
}

#: Sources whose works are machine translations made by Patristica
#: (``patristica.machine_translation``, #422): labelled as such, never embedded
#: for search, and not stamped by an ingestor (``scripts.machine_translate``
#: writes their raw files).
MACHINE_TRANSLATION_SOURCES: frozenset[str] = frozenset({"mt-eng"})


def source_label(source_id: str) -> str:
    """Return the readable label for *source_id*, or the id itself if unknown."""
    return SOURCE_LABELS.get(source_id, source_id)
