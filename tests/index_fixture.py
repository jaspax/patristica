"""A tiny corpus on disk (manifest, normalized files, translations, vectors) for
``scripts.build_index`` and the search API tests.

Every vector is a basis direction (``direction``), so a test can aim a query at
one chunk: chunk ``i`` of ``CHUNKS`` has its text vector on axis ``2 * i`` and
its translation vector on axis ``2 * i + 1``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from patristica import embeddings as emb
from patristica import translations as tr

FULL_DIMS = 1024
RUN = emb.EmbeddingRun(model="voyage/voyage-4-large", dims=FULL_DIMS, input_type="document",
                       date="2026-10-17", script="tests")
PROVENANCE = tr.Provenance(model="gpt-6.1-sol", prompt_version="v1", date="2026-10-14",
                           script="tests")

WORKS = {
    "kjv/gen": dict(source_id="kjv", title="Genesis", author=None, author_ids=[],
                    genre="scripture", language="eng", license="public_domain",
                    date_composed=-500, date_range=[-900, -400], tradition=None,
                    edition="King James Version (1769)"),
    "oshb/gen": dict(source_id="oshb", title="Genesis", author=None, author_ids=[],
                     genre="scripture", language="hbo", license="cc-by-4.0",
                     date_composed=-500, date_range=[-900, -400], tradition=None,
                     edition="Open Scriptures Hebrew Bible"),
    "pta/hymns": dict(source_id="pta", title="Hymns on Faith", author="Ephrem",
                      author_ids=["ephrem-the-syrian"], genre="patristic", language="syc",
                      license="cc-by-sa-4.0", date_composed=360, date_range=[350, 373],
                      tradition="syriac", edition="PTA"),
    "unlicensed/secret": dict(source_id="unlicensed", title="Unlicensed", author=None,
                              author_ids=[], genre="liturgical", language="syc", license="unknown",
                              date_composed=1960, date_range=[1960, 1960], tradition="syriac",
                              edition="Unlicensed edition"),
}

# (work_id, ref, text, English translation or None)
CHUNKS = [
    ("kjv/gen", "Gen.1.1", "In the beginning God created the heaven and the earth.", None),
    ("kjv/gen", "Gen.1.2", "And the earth was without form, and void.", None),
    ("oshb/gen", "Gen.1.1", "בְּרֵאשִׁית בָּרָא אֱלֹהִים אֵת הַשָּׁמַיִם וְאֵת הָאָרֶץ", None),
    ("pta/hymns", "Hymn.1.1", "ܗܝܡܢܘܬܐ ܕܝܠܢ ܫܪܝܪܬܐ ܗܝ ܘܡܫܒܚܬܐ", "Our faith is true and glorious."),
    ("pta/hymns", "Hymn.1.2", "ܐ", None),  # too short to embed
    ("unlicensed/secret", "H.1", "ܫܘܒܚܐ ܠܐܠܗܐ ܒܪܘܡܐ ܘܫܠܡܐ", None),
]


def chunk_id(work_id: str, ref: str) -> str:
    return f"{work_id}#{ref}"


def direction(axis: int, dims: int = FULL_DIMS) -> np.ndarray:
    v = np.zeros(dims, dtype=np.float32)
    v[axis] = 1.0
    return v


def axis_of(work_id: str, ref: str, translation: bool = False) -> int:
    i = next(i for i, c in enumerate(CHUNKS) if c[:2] == (work_id, ref))
    return 2 * i + int(translation)


def work_path(work_id: str) -> str:
    return f"{work_id}.json"


def write_corpus(root: Path) -> tuple[Path, Path, Path]:
    """Write the corpus under *root*; return (normalized, translations, embeddings) dirs."""
    norm, trans, store = root / "normalized", root / "translations", root / "embeddings"
    norm.mkdir(parents=True)
    entries = []
    for work_id, meta in WORKS.items():
        work = {"work_id": work_id, "date_confidence": "approximate", "provenance_url": None,
                "translation_of": None, **meta}
        entries.append({"path": work_path(work_id), "work": work})
        chunks = []
        rows: list[emb.Row] = []
        vecs = []
        tw = tr.WorkTranslations(work_id=work_id, source_path=work_path(work_id),
                                 source_language=meta["language"])
        for i, (wid, ref, text, english) in enumerate(CHUNKS):
            if wid != work_id:
                continue
            cid = chunk_id(work_id, ref)
            chunks.append({"chunk_id": cid, "work_id": work_id, "canonical_ref": ref,
                           "language": meta["language"], "text": text,
                           "chunk_index": len(chunks), "context_before": None,
                           "context_after": None, "date_composed": meta["date_composed"],
                           "date_range": meta["date_range"], "date_confidence": "approximate",
                           "out_of_period": False, "translation_group_id": None})
            if len(text) < 10:
                continue
            rows.append(emb.Row(cid, emb.KIND_TEXT, tr.text_sha(text), RUN.key))
            vecs.append(direction(2 * i))
            if english is not None:
                tw.put(tr.ChunkTranslation(chunk_id=cid, source_sha256=tr.text_sha(text),
                                           provenance=PROVENANCE.key, group_size=1,
                                           text=english), PROVENANCE)
                rows.append(emb.Row(cid, emb.KIND_TRANSLATION, tr.text_sha(english), RUN.key))
                vecs.append(direction(2 * i + 1))
        path = norm / work_path(work_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
        tr.save(trans, tw, chunks)
        emb.save(store, emb.WorkEmbeddings(work_id, work_path(work_id), {RUN.key: RUN}, rows,
                                           np.asarray(vecs, dtype=np.float16)))
    (norm / "_works.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")
    return norm, trans, store


def load_corpus(root: Path, url: str) -> None:
    """Write the corpus under *root* and load it into the database at *url*."""
    import psycopg

    from scripts import build_index

    norm, trans, store = write_corpus(root)
    with psycopg.connect(url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
