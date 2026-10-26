from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Controlled vocabulary types
# ---------------------------------------------------------------------------

Language = Literal["grc", "lat", "hbo", "syc", "cop", "gez", "hye", "got", "eng"]

Genre = Literal["scripture", "patristic", "liturgical", "council", "apocrypha"]

Tradition = Literal[
    "greek",
    "latin",
    "syriac",
    "ethiopic",
    "coptic",
    "armenian",
    "gothic",
]

DateConfidence = Literal["established", "approximate", "uncertain"]

License = Literal[
    "public_domain",
    "cc-by-4.0",
    "cc-by-sa-4.0",
    "cc-by-nc-sa-4.0",
    "cc-by-nc-4.0",
    "academic-noncommercial",
    "used-with-permission",
    "unknown",
]


# ---------------------------------------------------------------------------
# Work — metadata for a single work
# ---------------------------------------------------------------------------

class Work(BaseModel):
    work_id: str = Field(
        description="Slug uniquely identifying this work, '{source_id}/{local id}', e.g. 'oshb/gen'."
    )
    source_id: str = Field(
        description="Identifies the ingestion source, the collection slug, e.g. 'oshb' or 'first1k'; also the work's directory under data/raw and data/normalized."
    )
    author: str | None = Field(
        default=None,
        description=(
            "Author as the source gives it (provenance; spelling varies by source). "
            "Use author_ids for identity."
        ),
    )
    author_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Canonical author ids from the author index (patristica/authors.py), "
            "resolved from author by scripts.normalize; [] for anonymous works."
        ),
    )
    title: str = Field(description="Title of the work.")

    # Date metadata
    date_composed: int | None = Field(
        default=None,
        description="Best single-year estimate of composition (CE). Negative = BCE.",
    )
    date_range: tuple[int, int] | None = Field(
        default=None,
        description="Inclusive (earliest, latest) composition range in CE years.",
    )
    date_confidence: DateConfidence = Field(default="uncertain")

    # Classification
    genre: Genre
    language: Language
    tradition: Tradition | None = None

    # Licensing & provenance
    license: License = Field(default="unknown")
    provenance_url: str | None = Field(
        default=None,
        description="URL of the source edition or download location.",
    )
    edition: str | None = Field(
        default=None,
        description="Edition or version description, e.g. 'Clementine 1592' or 'NPNF Series 1 Vol. 1'.",
    )

    # Translation linkage.  The work this one was translated from, for every
    # version, not only English: ingestors set it for English translations
    # (#11/#150); patristica.translation_links curates it for the ancient
    # versions (#153), applied by scripts.normalize.  It may chain (Coptic →
    # LXX → Hebrew) and names one designated edition of the source text.
    # (Kept in a comment: editing the description string below would change
    # this module's code hash and with it every ingest stamp, #130.)
    translation_of: str | None = Field(
        default=None,
        description="work_id of the original-language work this is a translation of.",
    )

    # Catalogue identifiers the source records for the work (#178)
    external_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Identifiers the source itself records for the work, as 'KIND:value' "
            "(e.g. 'TLG:tlg4090.tlg096', 'CPG:5200', 'BHG:1234', 'Pinakes-Oeuvre:1956'). "
            "patristica.versions joins works that share a TLG, CPG or BHG id. "
            "Omitted from _works.jsonl when empty."
        ),
    )


# ---------------------------------------------------------------------------
# Chunk — one text unit (verse, paragraph, stanza, canon, etc.)
# ---------------------------------------------------------------------------

class Chunk(BaseModel):
    chunk_id: str = Field(
        description="Unique identifier: '{work_id}#{canonical_ref}' or with a counter suffix."
    )
    work_id: str
    canonical_ref: str = Field(
        description=(
            "Dot-separated canonical reference, e.g. 'Gen.1.1', "
            "'Aug.Conf.1.1.1', 'ByzLit.Chrysostom.Anaphora.3', 'Nicaea1.Canon.7'."
        )
    )
    language: Language
    text: str

    # Position within the work
    chunk_index: int = Field(description="Zero-based sequential position within the work.")

    # Overlap context (for embedding quality)
    context_before: str | None = Field(
        default=None,
        description="Trailing text from the preceding chunk (~50 tokens).",
    )
    context_after: str | None = Field(
        default=None,
        description="Leading text from the following chunk (~50 tokens).",
    )

    # Date metadata (inherited from Work but may be overridden for hybrid texts)
    date_composed: int | None = None
    date_range: tuple[int, int] | None = None
    date_confidence: DateConfidence = "uncertain"
    out_of_period: bool = Field(
        default=False,
        description=(
            "True if this chunk is positively dated after the collection period "
            "(see patristica/period.py); only possible in works kept as hybrids."
        ),
    )

    # Translation linkage
    translation_group_id: str | None = Field(
        default=None,
        description="Shared ID linking parallel chunks across languages for the same passage.",
    )
