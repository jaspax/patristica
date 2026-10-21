"""Tests for scripts.align (#179): loading members, idempotent runs, the store on disk."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from patristica import alignment_store as store  # noqa: E402
from patristica import embeddings as emb  # noqa: E402
from patristica import translations as tr  # noqa: E402
from scripts import align  # noqa: E402

DIMS = 32
RUN = emb.EmbeddingRun(model="voyage/voyage-4-large", dims=DIMS, input_type="document",
                       date="2026-10-17", script="tests")
PROV = tr.Provenance(model="gpt-6.1-sol", prompt_version="v1", date="2026-10-14", script="tests")
VERSES = 6


def meaning(k: int) -> np.ndarray:
    v = np.random.default_rng(1000 + k).normal(size=DIMS)
    return v / np.linalg.norm(v)


def write_corpus(root: Path, shift_gez: bool = False) -> tuple[Path, Path, Path]:
    """KJV, OSHB and Ge'ez Genesis 1:1–6, and a Greek work with its English translation."""
    norm, trans, vecs_dir = root / "normalized", root / "translations", root / "embeddings"
    works = {
        "kjv/gen": ("eng", "scripture", None, [f"Gen.1.{v}" for v in range(1, VERSES + 1)]),
        "oshb/gen": ("hbo", "scripture", None, [f"Gen.1.{v}" for v in range(1, VERSES + 1)]),
        "gez/gen": ("gez", "scripture", None, [f"Gen.1.{v}" for v in range(1, VERSES + 1)]),
        "first1k/tlg9999/tlg001/1st1K-grc1": ("grc", "patristic", None,
                                             ["1.1", "1.2", "1.3", "1.4"]),
        "anf-works/x": ("eng", "patristic", "first1k/tlg9999/tlg001/1st1K-grc1",
                        ["X.1", "X.2", "X.3"]),
    }
    entries = []
    for wid, (lang, genre, of, refs) in works.items():
        path = f"{wid}.json"
        entries.append({"path": path, "work": {
            "work_id": wid, "source_id": wid.split("/")[0], "title": wid, "author": None,
            "author_ids": [], "genre": genre, "language": lang, "license": "public_domain",
            "date_composed": 100, "date_range": [100, 100], "date_confidence": "approximate",
            "tradition": None, "edition": None, "provenance_url": None, "translation_of": of}})
        chunks, rows, vecs = [], [], []
        tw = tr.WorkTranslations(work_id=wid, source_path=path, source_language=lang)
        rng = np.random.default_rng(len(wid))
        for u, ref in enumerate(refs):
            text = f"{wid} unit {ref} text"
            cid = f"{wid}#{ref}"
            chunks.append({"chunk_id": cid, "work_id": wid, "canonical_ref": ref,
                           "language": lang, "text": text, "chunk_index": u})
            k = u
            if wid == "anf-works/x":  # three units for the Greek's four: X.2 = 1.2 + 1.3
                k = [0, 1, 3][u]
            m = meaning(k)
            if wid == "anf-works/x" and u == 1:
                m = meaning(1) + meaning(2)
            if shift_gez and wid == "gez/gen":
                m = meaning(min(u + 1, VERSES - 1))
            v = m / np.linalg.norm(m) + 0.15 / np.sqrt(DIMS) * rng.normal(size=DIMS)
            if lang == "gez":
                english = f"translation of {ref}"
                tw.put(tr.ChunkTranslation(chunk_id=cid, source_sha256=tr.text_sha(text),
                                           provenance=PROV.key, group_size=1, text=english), PROV)
                rows.append(emb.Row(cid, emb.KIND_TEXT, tr.text_sha(text), RUN.key))
                vecs.append(rng.normal(size=DIMS))  # the Ge'ez text vector is noise
                rows.append(emb.Row(cid, emb.KIND_TRANSLATION, tr.text_sha(english), RUN.key))
            else:
                rows.append(emb.Row(cid, emb.KIND_TEXT, tr.text_sha(text), RUN.key))
            vecs.append(v)
        (norm / path).parent.mkdir(parents=True, exist_ok=True)
        (norm / path).write_text(json.dumps(chunks), encoding="utf-8")
        tr.save(trans, tw, chunks)
        emb.save(vecs_dir, emb.WorkEmbeddings(wid, path, {RUN.key: RUN}, rows,
                                              np.asarray(vecs, dtype=np.float16)))
    (norm / "_works.jsonl").write_text("".join(json.dumps(e) + "\n" for e in entries))
    return norm, trans, vecs_dir


def jobs(root: Path, norm: Path, trans: Path, vecs: Path, **kw) -> list[align.Job]:
    """The jobs ``scripts.align`` runs: unpublishable works are left out of each group."""
    entries = align.load_works(norm)
    by_id = {e["work"]["work_id"]: e
             for e in align.select(entries, [], [], include_unpublishable=False)}
    groups = align.version_groups(entries)
    return [align.Job(g, [by_id[w] for w in mem if w in by_id], norm, trans, vecs,
                      root / "alignments",
                      kw.get("force", False), kw.get("dry_run", False), "2026-10-19")
            for g, mem in groups.items()]


def test_scripture_uses_translation_vectors_and_refs(tmp_path: Path) -> None:
    norm, trans, vecs = write_corpus(tmp_path)
    for job in jobs(tmp_path, norm, trans, vecs):
        assert align.run_job(job) == (job.group, "aligned")
    a = store.load(tmp_path / "alignments", "book:gen")
    assert a is not None and a.pivot == "kjv/gen"
    assert a.members["gez/gen"].group_of == list(range(VERSES))
    assert a.members["oshb/gen"].group_of == list(range(VERSES))
    text = (tmp_path / "alignments" / "book" / "gen.json").read_text()
    assert '"spans": "++++++"' in text
    assert a.run["params"]["prior"] == align.SCRIPTURE_PRIOR


def test_n_to_m_patristic_pair(tmp_path: Path) -> None:
    norm, trans, vecs = write_corpus(tmp_path)
    for job in jobs(tmp_path, norm, trans, vecs):
        align.run_job(job)
    a = store.load(tmp_path / "alignments", "first1k/tlg9999/tlg001/1st1K-grc1")
    assert a is not None
    groups = a.groups_of()
    eng = {g: s["anf-works/x"] for g, s in groups.items()}
    grc = {g: s["first1k/tlg9999/tlg001/1st1K-grc1"] for g, s in groups.items()}
    assert sorted(zip(grc.values(), eng.values())) == [((0, 1), (0, 1)), ((1, 3), (1, 2)),
                                                       ((3, 4), (2, 3))]


def test_rerun_is_idempotent_and_inputs_trigger_realignment(tmp_path: Path) -> None:
    norm, trans, vecs = write_corpus(tmp_path)
    for job in jobs(tmp_path, norm, trans, vecs):
        align.run_job(job)
    path = tmp_path / "alignments" / "book" / "gen.json"
    before = path.read_text()
    assert all(align.run_job(j)[1] == "unchanged" for j in jobs(tmp_path, norm, trans, vecs))
    # New vectors for the Ge'ez (another run): the book is aligned again; a dry run
    # only reports it.
    write_corpus(tmp_path / "v2", shift_gez=True)
    shard = emb.load(tmp_path / "v2" / "embeddings", "gez/gen.json")
    run2 = RUN.model_copy(update={"date": "2026-10-20"})
    shard.runs = {run2.key: run2}
    shard.rows = [emb.Row(r.chunk_id, r.kind, r.sha, run2.key) for r in shard.rows]
    emb.save(vecs, shard)
    outcome = {j.group: align.run_job(j)[1]
               for j in jobs(tmp_path, norm, trans, vecs, dry_run=True)}
    assert outcome["book:gen"] == "aligned"
    assert outcome["first1k/tlg9999/tlg001/1st1K-grc1"] == "unchanged"
    assert path.read_text() == before
    for j in jobs(tmp_path, norm, trans, vecs):
        align.run_job(j)
    assert path.read_text() != before


def test_scripture_eval_without_vectors_reports_dashes(tmp_path: Path, capsys) -> None:
    """No vectors means no predictions: the report shows dashes, not ZeroDivisionError."""
    import argparse

    from scripts import align_eval

    args = argparse.Namespace(
        input_dir=Path("data/normalized"), translations_dir=Path("data/translations"),
        embeddings_dir=tmp_path / "none", book=["gen"], prior=False, calibrate=True, jobs=1)
    align_eval.scripture(args)
    out = capsys.readouterr().out
    assert "| **all** | – | – | – | – |" in out
    assert "no beads to calibrate on" in out


def _relicense(norm: Path, work_id: str, licence: str) -> None:
    lines = []
    for line in (norm / "_works.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e["work"]["work_id"] == work_id:
            e["work"]["license"] = licence
        lines.append(json.dumps(e))
    (norm / "_works.jsonl").write_text("\n".join(lines) + "\n")


def test_group_without_two_eligible_members_loses_its_file(tmp_path: Path) -> None:
    """A group that falls under two eligible members has its old alignment removed."""
    norm, trans, vecs = write_corpus(tmp_path)
    for job in jobs(tmp_path, norm, trans, vecs):
        align.run_job(job)
    patristic = store.path_for(tmp_path / "alignments", "first1k/tlg9999/tlg001/1st1K-grc1")
    scripture = store.path_for(tmp_path / "alignments", "book:gen")
    assert patristic.exists() and scripture.exists()
    # The English translation becomes unpublishable; Genesis loses all vectors but KJV's.
    _relicense(norm, "anf-works/x", "unknown")
    (vecs / "oshb" / "gen.npz").unlink()
    (vecs / "gez" / "gen.npz").unlink()
    outcome = {j.group: align.run_job(j)[1]
               for j in jobs(tmp_path, norm, trans, vecs, dry_run=True)}
    assert outcome == {"book:gen": "deleted", "first1k/tlg9999/tlg001/1st1K-grc1": "deleted"}
    assert patristic.exists() and scripture.exists()  # a dry run deletes nothing
    for job in jobs(tmp_path, norm, trans, vecs):
        align.run_job(job)
    assert not patristic.exists() and not scripture.exists()
    assert store.load(tmp_path / "alignments", "book:gen") is None
    assert {align.run_job(j)[1] for j in jobs(tmp_path, norm, trans, vecs)} == {"skipped"}


def test_member_without_vectors_is_left_out(tmp_path: Path) -> None:
    norm, trans, vecs = write_corpus(tmp_path)
    (vecs / "oshb" / "gen.npz").unlink()
    for job in jobs(tmp_path, norm, trans, vecs):
        align.run_job(job)
    a = store.load(tmp_path / "alignments", "book:gen")
    assert a is not None and set(a.members) == {"kjv/gen", "gez/gen"}
