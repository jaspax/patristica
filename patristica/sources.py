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
    "clementine": "Clementine Vulgate",
    "coptic-nt": "Sahidic Coptic Bible",
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
    "coptic-scriptorium": "Coptic Scriptorium",
    "csel": "Corpus Scriptorum Ecclesiasticorum Latinorum (Open Greek and Latin)",
    "didache": "Didache (Ante-Nicene Fathers)",
    "first1k": "First Thousand Years of Greek",
    "npnf-works": "Nicene and Post-Nicene Fathers",
    "oglt-pl": "Patrologia Latina (Open Greek and Latin)",
    "ogpg": "Patrologia Graeca (Open Greek and Latin)",
    "perseus": "Perseus Digital Library",
    "pta": "Patristic Text Archive",
    "syriac-documents": "Ancient Syriac Documents (Ante-Nicene Fathers)",
    # Liturgical
    "adai-mari": "Liturgy of Addai and Mari (Ante-Nicene Fathers)",
    "armenian-liturgy": "Armenian Liturgy (Issaverdens)",
    "cantus": "CANTUS Database",
    "cursus": "CURSUS Project",
    "gallican": "Gallican Liturgy",
    "gez-anaphoras": "Anaphoras of the Ethiopic Liturgy",
    "goarch-basil": "Liturgy of St Basil (GOA Digital Chant Stand)",
    "goarch-chrysostom": "Liturgy of St John Chrysostom (GOA Digital Chant Stand)",
    "hudra": "Hudra (East Syriac)",
    "mark-liturgy": "Liturgy of St Mark (Ante-Nicene Fathers)",
    "mozarabic": "Mozarabic Liturgy (Férotin)",
    "serapion": "Prayer-Book of Sarapion",
    "syriac-james": "Syriac Liturgy of St James (Ante-Nicene Fathers)",
    "typikon": "Typikon (Violakis)",
    # Councils
    "ecumenical": "Ecumenical and Local Councils (Nicene and Post-Nicene Fathers)",
    "wikisource-canons": "Holy Canons, Greek (Wikisource)",
}


def source_label(source_id: str) -> str:
    """Return the readable label for *source_id*, or the id itself if unknown."""
    return SOURCE_LABELS.get(source_id, source_id)
