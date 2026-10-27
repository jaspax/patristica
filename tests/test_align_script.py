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
                      kw.get("force", False), kw.get("dry_run", False), "2026-10-19",
                      kw.get("allow_missing_vectors", False), kw.get("code_current", True))
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
    allow = {"allow_missing_vectors": True}
    outcome = {j.group: align.run_job(j)[1]
               for j in jobs(tmp_path, norm, trans, vecs, dry_run=True, **allow)}
    assert outcome == {"book:gen": "deleted", "first1k/tlg9999/tlg001/1st1K-grc1": "deleted"}
    assert patristic.exists() and scripture.exists()  # a dry run deletes nothing
    for job in jobs(tmp_path, norm, trans, vecs, **allow):
        align.run_job(job)
    assert not patristic.exists() and not scripture.exists()
    assert store.load(tmp_path / "alignments", "book:gen") is None
    assert {align.run_job(j)[1] for j in jobs(tmp_path, norm, trans, vecs, **allow)} == {
        "skipped"}


def test_member_without_vectors_is_left_out(tmp_path: Path) -> None:
    norm, trans, vecs = write_corpus(tmp_path)
    (vecs / "oshb" / "gen.npz").unlink()
    for job in jobs(tmp_path, norm, trans, vecs, allow_missing_vectors=True):
        align.run_job(job)
    a = store.load(tmp_path / "alignments", "book:gen")
    assert a is not None and set(a.members) == {"kjv/gen", "gez/gen"}


# ---------------------------------------------------------------------------
# Staleness (#130): missing vectors, code changes, the fingerprint file
# ---------------------------------------------------------------------------


def test_member_without_vectors_is_refused(tmp_path: Path) -> None:
    norm, trans, vecs = write_corpus(tmp_path)
    for job in jobs(tmp_path, norm, trans, vecs):
        align.run_job(job)
    path = tmp_path / "alignments" / "book" / "gen.json"
    before = path.read_text()
    (vecs / "oshb" / "gen.npz").unlink()
    outcome = {j.group: align.run_job(j)[1] for j in jobs(tmp_path, norm, trans, vecs)}
    assert outcome["book:gen"] == f"refused: oshb/gen {VERSES}"
    assert outcome["first1k/tlg9999/tlg001/1st1K-grc1"] == "unchanged"
    assert path.read_text() == before


def test_changed_text_without_a_new_vector_is_refused(tmp_path: Path) -> None:
    """A re-normalized unit whose vector is for its old text counts as missing."""
    norm, trans, vecs = write_corpus(tmp_path)
    chunks = json.loads((norm / "kjv/gen.json").read_text())
    chunks[2]["text"] = "a corrected verse text"
    (norm / "kjv/gen.json").write_text(json.dumps(chunks))
    outcome = {j.group: align.run_job(j)[1] for j in jobs(tmp_path, norm, trans, vecs)}
    assert outcome["book:gen"] == "refused: kjv/gen 1"


def test_short_units_need_no_vector(tmp_path: Path) -> None:
    """Units embed leaves out (under MIN_CHARS) don't make a group refused."""
    norm, trans, vecs = write_corpus(tmp_path)
    chunks = json.loads((norm / "kjv/gen.json").read_text())
    chunks.append({**chunks[-1], "chunk_id": "kjv/gen#Gen.1.7", "canonical_ref": "Gen.1.7",
                   "text": "Selah", "chunk_index": len(chunks)})
    (norm / "kjv/gen.json").write_text(json.dumps(chunks))
    outcome = {j.group: align.run_job(j)[1] for j in jobs(tmp_path, norm, trans, vecs)}
    assert outcome["book:gen"] == "aligned"


def test_editorial_units_need_no_vector(tmp_path: Path) -> None:
    """A wholly editorial unit (#236) gets no vector from embed, like a short one."""
    norm, trans, vecs = write_corpus(tmp_path)
    chunks = json.loads((norm / "kjv/gen.json").read_text())
    title = "The First Book of Moses, called Genesis"
    chunks.append({**chunks[-1], "chunk_id": "kjv/gen#Gen.1.7", "canonical_ref": "Gen.1.7",
                   "text": title, "chunk_index": len(chunks),
                   "editorial": [[0, len(title), "title"]]})
    (norm / "kjv/gen.json").write_text(json.dumps(chunks))
    outcome = {j.group: align.run_job(j)[1] for j in jobs(tmp_path, norm, trans, vecs)}
    assert outcome["book:gen"] == "aligned"


def test_marking_a_span_needs_a_new_vector(tmp_path: Path) -> None:
    """A vector embeds a unit's source text: marking a span in it makes the vector stale."""
    norm, trans, vecs = write_corpus(tmp_path)
    chunks = json.loads((norm / "kjv/gen.json").read_text())
    chunks[2]["editorial"] = [[0, 2, "note"]]
    (norm / "kjv/gen.json").write_text(json.dumps(chunks))
    outcome = {j.group: align.run_job(j)[1] for j in jobs(tmp_path, norm, trans, vecs)}
    assert outcome["book:gen"] == "refused: kjv/gen 1"


def test_code_change_realigns_but_keeps_unchanged_files(tmp_path: Path) -> None:
    norm, trans, vecs = write_corpus(tmp_path)
    for job in jobs(tmp_path, norm, trans, vecs):
        align.run_job(job)
    path = tmp_path / "alignments" / "book" / "gen.json"
    before = path.read_text()
    later = [align.Job(**{**vars(j), "today": "2026-11-01"})
             for j in jobs(tmp_path, norm, trans, vecs, code_current=False)]
    assert {align.run_job(j)[1] for j in later} == {"unchanged"}
    assert path.read_text() == before  # same result: the old run date stays


def run_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, norm: Path, trans: Path,
             vecs: Path, *extra: str) -> None:
    monkeypatch.setattr("sys.argv", [
        "align", "--input-dir", str(norm), "--translations-dir", str(trans),
        "--embeddings-dir", str(vecs), "--output-dir", str(tmp_path / "alignments"),
        "--jobs", "1", *extra])
    align.main()


GREEK = "first1k/tlg9999/tlg001/1st1K-grc1"


def test_full_run_records_code_and_groups(tmp_path: Path, monkeypatch) -> None:
    norm, trans, vecs = write_corpus(tmp_path)
    monkeypatch.setattr(align, "align_code_hash", lambda: "code-1")
    run_main(monkeypatch, tmp_path, norm, trans, vecs)
    fp = align.read_fingerprint(tmp_path / "alignments")
    assert fp["align"] == {"code": "code-1"}
    assert sorted(fp["groups"]) == ["book:gen", GREEK]
    assert fp["groups"]["book:gen"]["members"] == ["gez/gen", "kjv/gen", "oshb/gen"]
    assert "keys" in fp["groups"]["book:gen"] and "keys" not in fp["groups"][GREEK]
    assert align.check_groups(norm, tmp_path / "alignments") == {}
    assert [p.name for p, _ in store.iter_store(tmp_path / "alignments")] == [
        "gen.json", "1st1K-grc1.json"]  # the fingerprint file is not an alignment

    # Genesis keeps only one member with vectors: recorded as skipped.
    (vecs / "oshb" / "gen.npz").unlink()
    (vecs / "gez" / "gen.npz").unlink()
    run_main(monkeypatch, tmp_path, norm, trans, vecs, "--allow-missing-vectors")
    record = align.read_fingerprint(tmp_path / "alignments")["groups"]["book:gen"]
    assert record["skipped"] == align.NO_VECTORS
    assert align.check_groups(norm, tmp_path / "alignments") == {}  # a skip isn't stale


def _add_work(norm: Path, entry: dict, chunks: list[dict]) -> None:
    (norm / entry["path"]).write_text(json.dumps(chunks), encoding="utf-8")
    with (norm / "_works.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def test_new_member_of_an_existing_group_is_stale(tmp_path: Path, monkeypatch) -> None:
    """Another edition linked into book:gen keeps the group id and its file (#203)."""
    norm, trans, vecs = write_corpus(tmp_path)
    monkeypatch.setattr(align, "align_code_hash", lambda: "code-1")
    run_main(monkeypatch, tmp_path, norm, trans, vecs)
    kjv = next(e for e in align.load_works(norm) if e["work"]["work_id"] == "kjv/gen")
    web = {"path": "web/gen.json", "work": {**kjv["work"], "work_id": "web/gen",
                                            "source_id": "web"}}
    (norm / "web").mkdir()
    chunks = json.loads((norm / kjv["path"]).read_text())
    _add_work(norm, web, [{**c, "chunk_id": c["chunk_id"].replace("kjv/", "web/"),
                           "work_id": "web/gen"} for c in chunks])
    assert align.check_groups(norm, tmp_path / "alignments") == {"book:gen": "members changed"}


def test_versification_change_makes_only_that_book_stale(tmp_path: Path, monkeypatch) -> None:
    """A corrected scheme override moves a book's refs without touching the code hash."""
    norm, trans, vecs = write_corpus(tmp_path)
    monkeypatch.setattr(align, "align_code_hash", lambda: "code-1")
    run_main(monkeypatch, tmp_path, norm, trans, vecs)
    real = align.scripture_keys
    monkeypatch.setattr(align, "scripture_keys", lambda wid, refs: (
        [r + "x" for r in real(wid, refs)] if wid == "gez/gen" else real(wid, refs)))
    assert align.check_groups(norm, tmp_path / "alignments") == {
        "book:gen": "versification changed"}


def test_check_groups_reports_new_and_dropped_groups(tmp_path: Path, monkeypatch) -> None:
    norm, trans, vecs = write_corpus(tmp_path)
    assert align.check_groups(norm, tmp_path / "alignments") == {
        "book:gen": "not aligned", GREEK: "not aligned"}
    monkeypatch.setattr(align, "align_code_hash", lambda: "code-1")
    run_main(monkeypatch, tmp_path, norm, trans, vecs)
    (tmp_path / "alignments" / "book" / "gen.json").unlink()
    _relicense(norm, "anf-works/x", "unknown")  # the Greek group loses its translation
    assert align.check_groups(norm, tmp_path / "alignments") == {
        "book:gen": "no alignment file", GREEK: "no longer a group to align"}


def test_single_publishable_member_without_vectors_is_cleaned_up(tmp_path: Path) -> None:
    """A group licensing leaves with one member reaches the cleanup, not a refusal."""
    norm, trans, vecs = write_corpus(tmp_path)
    for job in jobs(tmp_path, norm, trans, vecs):
        align.run_job(job)
    _relicense(norm, "anf-works/x", "unknown")
    (vecs / "first1k" / "tlg9999" / "tlg001" / "1st1K-grc1.npz").unlink()
    outcome = {j.group: align.run_job(j)[1] for j in jobs(tmp_path, norm, trans, vecs)}
    assert outcome[GREEK] == "deleted"


def test_refusal_exits_nonzero_and_keeps_old_code_hash(tmp_path: Path, monkeypatch) -> None:
    norm, trans, vecs = write_corpus(tmp_path)
    monkeypatch.setattr(align, "align_code_hash", lambda: "code-1")
    run_main(monkeypatch, tmp_path, norm, trans, vecs)
    (vecs / "oshb" / "gen.npz").unlink()
    monkeypatch.setattr(align, "align_code_hash", lambda: "code-2")
    with pytest.raises(SystemExit) as exc:
        run_main(monkeypatch, tmp_path, norm, trans, vecs)
    assert exc.value.code == 1
    assert align.read_fingerprint(tmp_path / "alignments")["align"] == {"code": "code-1"}
