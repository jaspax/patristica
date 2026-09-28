"""
Project-scope allowlist for CTS-organised corpora (First1KGreek, Perseus).

Both repos are dominated by classical pagan literature (Plutarch, Galen,
Demosthenes, Cicero, …), and their TEI headers carry no composition dates,
so a date cutoff cannot separate patristic from classical material.  Instead
we keep only textgroups (CTS author IDs) that are Christian or Jewish
religious literature composed before the Great Schism.

Deliberately excluded:
- ``tlg0031`` New Testament, ``tlg0527`` Septuaginta — covered by dedicated
  scripture ingestors (SBLGNT, PTA LXX).
- Christian authors represented only by secular works (Philoponus' Aristotle
  commentaries, Agathias, Ausonius).  Exception: Procopius, kept as a
  counterpoint to hagiographic sources on Justinian's reign.
- Pagan authors writing about Christians (Julian, Celsus via Origen, …) —
  a possible future expansion, out of scope for now.
- Post-schism authors (Theophylact of Ohrid, Zonaras, Anna Comnena, …).
"""

from __future__ import annotations

import re
from pathlib import Path

IN_SCOPE_AUTHOR_IDS: frozenset[str] = frozenset({
    # --- Apostolic Fathers, apologists, early Christian texts ---
    "tlg1311",    # Didache
    "tlg1216",    # Epistle of Barnabas
    "tlg1271",    # Clement of Rome
    "tlg1419",    # Shepherd of Hermas
    "tlg1443",    # Ignatius of Antioch
    "tlg1622",    # Polycarp
    "tlg1484",    # Martyrdom of Polycarp
    "tlg2016",    # Martyrdom of Perpetua and Felicity
    "tlg0645",    # Justin Martyr
    "tlg0646",    # Pseudo-Justin Martyr
    "tlg1205",    # Athenagoras
    "tlg1725",    # Theophilus of Antioch
    "tlg1766",    # Tatian
    "tlg1447",    # Irenaeus
    "tlg1665",    # Presbyters cited by Irenaeus
    "tlg1664",    # Alexandrian presbyters
    "tlg1329",    # Dionysius of Corinth
    "tlg1626",    # Polycrates of Ephesus
    "ogl0001",    # Pinytus of Knossos
    "tlg0572",    # Gaius of Rome
    "tlg1131",    # Anonymous anti-Montanist (Ad Avircium Marcellum)
    # --- Christian apocrypha ---
    "tlg0317",    # Acts of John
    "tlg2038",    # Acts of Thomas
    "tlg2948",    # Acts of Philip
    "tlg2949",    # Acts of Barnabas
    # --- Jewish / Jewish-Christian literature ---
    "tlg0018",    # Philo of Alexandria
    "tlg0526",    # Flavius Josephus
    "tlg1463",    # 1 Enoch (Greek)
    "tlg1701",    # Testament of Abraham
    "tlg1750",    # Lives of the Prophets
    "tlg1551",    # Sibylline Oracles
    # --- Greek Fathers ---
    "tlg0555",    # Clement of Alexandria
    "tlg2042",    # Origen
    "tlg2115",    # Hippolytus
    "tlg2959",    # Methodius of Olympus
    "tlg2018",    # Eusebius of Caesarea
    "tlg2035",    # Athanasius
    "tlg2041",    # Marcellus of Ancyra
    "tlg2040",    # Basil of Caesarea
    "tlg2022",    # Gregory of Nazianzus
    "tlg2021",    # Epiphanius of Salamis
    "tlg4090",    # Cyril of Alexandria
    "tlg4089",    # Theodoret of Cyrus
    "tlg2934",    # John of Damascus
    "tlg4102",    # Catenae on the New Testament
    "stoa0146d",  # Hegemonius (Acta Archelai)
    # --- Church historians and hagiography ---
    "tlg2057",    # Socrates Scholasticus
    "tlg2048",    # Sozomen
    "tlg2058",    # Philostorgius
    "tlg2768",    # Gelasius of Cyzicus
    "tlg2733",    # Evagrius Scholasticus
    "tlg2371",    # Chronicon Paschale
    "tlg2806",    # Mark the Deacon (Life of Porphyry)
    "tlg4029",    # Procopius (secular, but documents the Justinianic Christian milieu)
    # --- Latin Fathers ---
    "stoa0275",   # Tertullian
    "stoa0276",   # Pseudo-Tertullian
    "stoa0203",   # Minucius Felix
    "stoa0162",   # Jerome
    "stoa0058",   # Boethius (theological tractates, Consolation)
})

# Edition suffix at the end of a CTS version string, e.g. "perseus-grc2",
# "1st1K-fre1", "1st1K-eng1b".
_EDITION_LANG_RE = re.compile(r"-([a-z]{3})\d*[a-z]?$", re.IGNORECASE)

_TEXTGROUP_RE = re.compile(r"^(tlg|phi|stoa|ogl|ggm)\d")


def author_id_from_path(xml_path: Path, data_dir: Path) -> str:
    """Return the CTS textgroup ID (first directory under ``data/``)."""
    return xml_path.relative_to(data_dir).parts[0]


def is_in_scope(author_id: str) -> bool:
    return author_id in IN_SCOPE_AUTHOR_IDS


def edition_matches_language(xml_path: Path, lang: str) -> bool:
    """True if the file's edition suffix is *lang* (or ``mul``/unrecognised).

    Rejects translations such as ``-eng1``, ``-fre1``, ``-ger2``, ``-ita1``.
    Multilingual (``mul``) and suffix-less files pass through so the caller's
    ``xml:lang`` check can decide.
    """
    parts = xml_path.stem.split(".")
    if len(parts) < 3:
        return True
    m = _EDITION_LANG_RE.search(parts[2])
    if m is None:
        return True
    code = m.group(1).lower()
    return code == lang or code == "mul"


def prune_out_of_scope(out_root: Path, langs: tuple[str, ...]) -> int:
    """Delete previously written ``{author}/{work}/*.json`` outputs under
    *out_root* that are out of scope or in a language not in *langs*.

    Needed because ingestors skip existing outputs, so files written before
    a scope change would otherwise persist forever.  Returns the count removed.
    """
    removed = 0
    # Only touch textgroup dirs: First1KGreek's output root is also its repo
    # checkout, which has unrelated dirs (data/, split/, save/, …).
    author_dirs = [d for d in out_root.iterdir() if d.is_dir() and _TEXTGROUP_RE.match(d.name)]
    for author_dir in author_dirs:
        in_scope = is_in_scope(author_dir.name)
        for path in sorted(author_dir.glob("*/*.json")):
            if in_scope and any(edition_matches_language(path, lang) for lang in langs):
                continue
            path.unlink()
            removed += 1
        for d in [*author_dir.iterdir(), author_dir]:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
    return removed
