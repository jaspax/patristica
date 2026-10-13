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
    "coptic-nt": "Sahidic Coptic New Testament",
    "gez": "Ge'ez Bible (Ethiopian canon)",
    "kjv": "King James Version",
    "lxx-rahlfs": "Septuagint (Rahlfs)",
    "oshb": "Open Scriptures Hebrew Bible",
    "pta-lxx": "Septuagint (Patristic Text Archive)",
    "pta-peshitta": "Peshitta Old Testament (Patristic Text Archive)",
    "sblgnt": "SBL Greek New Testament",
    "web": "World English Bible",
    "wulfila": "Gothic Bible (Wulfila)",
    # Patristic
    "anf-works": "Ante-Nicene Fathers",
    "patristic/apostolic-constitutions": "Apostolic Constitutions (Ante-Nicene Fathers)",
    "patristic/coptic-scriptorium": "Coptic Scriptorium",
    "patristic/didache": "Didache (Ante-Nicene Fathers)",
    "patristic/first1k": "First Thousand Years of Greek",
    "npnf-works": "Nicene and Post-Nicene Fathers",
    "oglt-pl": "Patrologia Latina (Open Greek and Latin)",
    "patristic/ogpg": "Patrologia Graeca (Open Greek and Latin)",
    "perseus": "Perseus Digital Library",
    "pta": "Patristic Text Archive",
    "patristic/syriac-documents": "Ancient Syriac Documents (Ante-Nicene Fathers)",
    # Liturgical
    "liturgical/adai-mari": "Liturgy of Addai and Mari (Ante-Nicene Fathers)",
    "liturgical/armenian-liturgy": "Armenian Liturgy (Issaverdens)",
    "liturgical/cantus": "CANTUS Database",
    "liturgical/cursus": "CURSUS Project",
    "liturgical/gallican": "Gallican Liturgy",
    "liturgical/gez-anaphoras": "Anaphoras of the Ethiopic Liturgy",
    "liturgical/goarch-basil": "Liturgy of St Basil (GOA Digital Chant Stand)",
    "liturgical/goarch-chrysostom": "Liturgy of St John Chrysostom (GOA Digital Chant Stand)",
    "liturgical/hudra": "Hudra (East Syriac)",
    "liturgical/mark-liturgy": "Liturgy of St Mark (Ante-Nicene Fathers)",
    "liturgical/mozarabic": "Mozarabic Liturgy (Férotin)",
    "liturgical/serapion": "Prayer-Book of Sarapion",
    "liturgical/syriac-james": "Syriac Liturgy of St James (Ante-Nicene Fathers)",
    "liturgical/typikon": "Typikon (Violakis)",
    # Councils
    "councils/ecumenical": "Ecumenical and Local Councils (Nicene and Post-Nicene Fathers)",
}


def source_label(source_id: str) -> str:
    """Return the readable label for *source_id*, or the id itself if unknown."""
    return SOURCE_LABELS.get(source_id, source_id)
