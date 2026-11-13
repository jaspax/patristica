"""Church Slavonic spelling-sensitivity sets (#336): variants, test sets, one-language eval set."""

import json
from pathlib import Path

import numpy as np
import pytest

from patristica.textfold import fold
from scripts.embed_eval import langset, spelling
from scripts.embed_eval.spelling import Unit


@pytest.mark.parametrize(("fn", "src", "want"), [
    (spelling.yer_final_dropped, "богъ рече. въ домъ", "бог рече. в дом"),
    (spelling.yer_final_dropped, "ъ", "ъ"),  # a one-letter word stays
    (spelling.yer_merged, "дьнь Дьнь", "дънъ Дънъ"),
    (spelling.yers_dropped, "кръстъ вьсѣмъ сꙿвѣтъ", "крст всѣм свѣт"),
    (spelling.yat_cyrillic, "ѣко тѣло моѣ", "ꙗко тѣло моꙗ"),
    (spelling.yat_modern, "ѣко тѣло моѣ Ѣко", "яко тело моя Яко"),
    (spelling.i_merged, "ꙇ і ї Ꙇ", "и и и И"),
    (spelling.u_ligature, "оубо оу̑бо Оубо", "ѹбо ѹ̑бо Ѹбо"),
    (spelling.u_plain, "оубо ѹбо ꙋбо", "убо убо убо"),
    (spelling.iotated_plain, "ꙗко ѥго ѩзꙑкъ ѭже", "яко его ѧзꙑкъ ѫже"),
    (spelling.titla_expanded, "бг҃ъ гл҃а Ис҃ъ в҃", "богъ глагола Исоусъ в҃"),
    (spelling.titla_expanded, "сн҃ъ чл҃чскꙑ", "сꙑнъ чловѣчьскꙑ"),
    (spelling.titla_expanded, "цр҃кве цр҃ь", "цръкве цѣсарь"),
    (spelling.superscripts_inline, "хрⷭ҇тъ", "хрс҇тъ"),
    (spelling.marks_dropped, "хрⷭ҇тъ и҅ гл҃а", "хрстъ и гла"),
])
def test_variants(fn, src, want):
    assert fn(src) == want


def test_modern_orthography():
    assert spelling.modern("ꙇ гл҃а емоу. аште ѣко тѣло") == "и глагола ему. аще яко тело"
    assert spelling.modern("пѫтемь въниди дъва") == "путемь вниди два"
    assert spelling.modern("Ꙇ") == "И"


def test_every_variant_keeps_punctuation_but_folded():
    text = "ꙇ гл҃а емоу. ѣко"
    for name, fn in spelling.VARIANTS.items():
        assert ("." in fn(text)) is (name != "folded"), name
    assert spelling.folded(text) == fold(text)


def _units(n, src="ccmh-marianus", book="Matt"):
    text = "ꙇ гл҃а емоу ѣко оубо въ домъ тѣла твоего и не иди тамо никогда же."
    return [Unit(f"{src}/{book.lower()}#{book}.1.{i}", src, f"{book}.1.{i}", f"{text} {i}")
            for i in range(1, n + 1)]


def test_pick_sentences_is_deterministic_and_needs_a_next_verse():
    units = _units(10)
    picked = spelling.pick_sentences(units, n=5, seed=1)
    assert picked == spelling.pick_sentences(units, n=5, seed=1)
    assert len(picked) == 5 and 9 not in picked  # the last verse has no next one
    assert spelling.pick_sentences(units, n=50) == list(range(9))


def test_pair_rows_variants_and_baselines():
    mar = _units(3)
    zog = _units(3, "ccmh-zographensis")
    greek = [Unit(f"sblgnt/matt#Matt.1.{i}", "sblgnt", f"Matt.1.{i}", f"Καὶ εἶπεν αὐτῷ, {i}.")
             for i in range(1, 4)]
    rows = spelling.pair_rows(mar, [0], {"ccmh-zographensis": zog}, greek)
    kinds = {r["kind"] for r in rows}
    assert {"adjacent", "witness:ccmh-zographensis", "grc_unaccented", "grc_adjacent",
            "titla_expanded", "modern", "folded"} <= kinds
    assert "superscripts_inline" not in kinds  # no superscript: the variant is the original
    grc = next(r for r in rows if r["kind"] == "grc_unaccented")
    assert grc["b"] == "και ειπεν αυτω 1"
    assert all(r["a"] != r["b"] for r in rows if r["kind"] in spelling.VARIANTS)


def test_witness_scores():
    units = {"a": _units(3, "a"), "b": _units(3, "b")[:2]}
    eye = np.eye(3, dtype=np.float32)
    vecs = {"a": eye, "b": np.stack([eye[1], eye[0]])}  # b's verses in the wrong order
    scores = {(s["query"], s["searched"]): s for s in spelling.witness_scores(vecs, units)}
    ab = scores[("a", "b")]
    assert ab["n"] == 2 and ab["R@1"] == 0.0 and ab["R@5"] == 1.0 and ab["MRR"] == 0.5


def test_estimate_counts_each_text_once(tmp_path):
    est = spelling.estimate({"x": ["богъ", "богъ", "rex"], "y": ["rex", "deus"]},
                            tmp_path / "none.sqlite")
    assert est["parts"]["x"]["texts"] == 2 and est["parts"]["y"]["texts"] == 1
    assert est["total"]["texts"] == 3 and est["total"]["usd_list_price"] >= 0


def _normalized(tmp_path: Path) -> Path:
    root = tmp_path / "normalized"
    works = [
        ("ccmh-marianus/matt", "ccmh-marianus", "scripture", "ccmh-marianus/Matt.json"),
        ("ccmh-zographensis/matt", "ccmh-zographensis", "scripture",
         "ccmh-zographensis/Matt.json"),
        ("ccmh-supr/vita", "ccmh-supr", "patristic", "ccmh-supr/vita.json"),
        ("sblgnt/matt", "sblgnt", "scripture", "sblgnt/Matt.json"),
        ("web/matt", "web", "scripture", "web/Matt.json"),
    ]
    lines = []
    for wid, src, genre, path in works:
        lang = {"sblgnt": "grc", "web": "eng"}.get(src, "chu")
        # The Slavonic witnesses version like SBLGNT (org); a registered scheme is needed.
        scheme_src = "sblgnt" if src.startswith("ccmh-") and genre == "scripture" else src
        lines.append(json.dumps({"path": path, "work": {
            "work_id": wid, "source_id": scheme_src, "genre": genre, "language": lang}}))
        n = 12 if genre == "scripture" else 30
        chunks = []
        for i in range(n):
            ref = f"Matt.1.{i + 1}" if genre == "scripture" else f"Supr.1r.s{i + 1}"
            text = f"ꙇ гл҃а емоу слово {i} ѣко не бѫдетъ тако въ вѣкъ вѣкоу {wid}"
            chunk = {"chunk_id": f"{wid}#{ref}", "work_id": wid, "canonical_ref": ref,
                     "language": lang, "text": text, "chunk_index": i}
            if i == 0:
                chunk["text"] = "[глава] " + text
                chunk["editorial"] = [[0, 7, "heading"]]
            chunks.append(chunk)
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    (root / "_works.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def test_langset_build(tmp_path):
    root = _normalized(tmp_path)
    out = tmp_path / "eval" / "chu"
    stats = langset.build(root, "chu", out, scripture_per_lang=3, unique_per_lang=4,
                          distractors_per_lang=5, authored_dir=tmp_path, folded=True,
                          subset_dir=tmp_path / "subset")
    rows = [json.loads(line) for line in (out / "corpus.jsonl").open()]
    refs = [c for c in rows if c["role"] == "reference"]
    corpus = [c for c in rows if c["role"] != "reference"]
    assert {c["language"] for c in corpus} == {"chu"}
    # every Scripture target's verse group has its English verse, and only those
    groups = {t["chunk_id"].split("#")[1] for t in stats["targets_list"]
              if t["origin"] == "scripture"}
    assert {c["translation_group_id"] for c in refs} == groups
    assert {c["language"] for c in refs} == {"eng"}
    # the subset tree holds exactly the set's chu chunks, in normalized form
    sub = [json.loads(line) for line in (tmp_path / "subset" / "_works.jsonl").open()]
    kept = [c for r in sub for c in json.loads((tmp_path / "subset" / r["path"]).read_text())]
    assert sorted(c["chunk_id"] for c in kept) == sorted(c["chunk_id"] for c in corpus)
    assert stats["subset_chunks"] == len(corpus)
    assert any("editorial" in c for c in kept)
    assert stats["targets"] == {"chu/scripture": 3, "chu/unique": 4}
    by_id = {c["chunk_id"]: c for c in corpus}
    # Scripture verses are grouped across witnesses by org ref; editorial text is out
    for c in corpus:
        if c["chunk_id"].startswith("ccmh-marianus"):
            assert c["translation_group_id"] == c["chunk_id"].split("#")[1]
        assert not c["text"].startswith("[")
    queries = [json.loads(line) for line in (out / "queries.jsonl").open()]
    modes = {q["mode"] for q in queries}
    assert modes == {"exact", "near", "modern"}
    for q in queries:
        assert q["target_chunk_id"] in by_id
    folded = [json.loads(line) for line in (tmp_path / "eval" / "chu-fold" / "corpus.jsonl").open()]
    assert [c["text"] for c in folded] == [
        fold(c["text"]) if c["language"] == "chu" else c["text"] for c in rows]


def test_eval_languages_are_not_enrolled():
    from patristica.translations import TRANSLATED_LANGUAGES
    from scripts.embed_eval.translate import EVAL_LANGUAGES, LANGUAGE_NAMES, PROMPT_NAMES

    assert not set(EVAL_LANGUAGES) & set(LANGUAGE_NAMES)
    assert not set(EVAL_LANGUAGES) & TRANSLATED_LANGUAGES
    assert set(PROMPT_NAMES) == set(LANGUAGE_NAMES) | set(EVAL_LANGUAGES)
    assert PROMPT_NAMES["chu"] == "Old Church Slavonic"  # enrolled on #336
    assert PROMPT_NAMES["oge"] == "Old Georgian"  # enrolled on #529
    assert PROMPT_NAMES["sga"] == "Old Irish"  # enrolled on #552
    assert PROMPT_NAMES["ang"] == "Old English"  # enrolled on #582


def test_lectionaries_are_not_georgian_only():
    from scripts.embed_eval.select import unique_works

    def work(work_id: str, genre: str) -> dict:
        return {"work_id": work_id, "language": "oge", "genre": genre}

    works = [work("titus-paris-lectionary/lectionarium-hierosolymitanum", "liturgical"),
             work("titus-khanmeti-lectionary/lectionarium-gracense", "liturgical"),
             work("titus-liturgy/liturgy-of-st-james", "liturgical")]
    assert unique_works(works)["oge"] == {"titus-liturgy/liturgy-of-st-james"}


def test_translate_refuses_an_unenrolled_language_in_the_production_store(monkeypatch):
    import scripts.translate as st

    monkeypatch.setattr(st, "PROMPT_NAMES", {**st.PROMPT_NAMES, "xxx": "Test Language"})
    monkeypatch.setattr("sys.argv", ["translate", "--langs", "xxx", "--dry-run"])
    with pytest.raises(SystemExit):
        st.main()


def test_langset_drops_units_embed_skips(tmp_path):
    """A wholly editorial neighbour is empty in source_text: not in the set (#483)."""
    from patristica.embeddings import MIN_CHARS

    root = _normalized(tmp_path)
    path = root / "ccmh-supr/vita.json"
    chunks = json.loads(path.read_text(encoding="utf-8"))
    for c in chunks[1::2]:
        c["text"], c["editorial"] = "[глава]", [[0, 7, "heading"]]
    path.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "eval" / "chu"
    stats = langset.build(root, "chu", out, scripture_per_lang=3, unique_per_lang=4,
                          distractors_per_lang=5, authored_dir=tmp_path,
                          subset_dir=tmp_path / "subset")
    rows = [json.loads(line) for line in (out / "corpus.jsonl").open()]
    assert rows and all(len(c["text"].strip()) >= MIN_CHARS for c in rows)
    assert stats["subset_chunks"] == sum(c["role"] != "reference" for c in rows)


def test_langset_is_deterministic(tmp_path):
    root = _normalized(tmp_path)
    a = langset.build(root, "chu", tmp_path / "a", scripture_per_lang=3, unique_per_lang=4,
                      distractors_per_lang=5, authored_dir=tmp_path)
    b = langset.build(root, "chu", tmp_path / "b", scripture_per_lang=3, unique_per_lang=4,
                      distractors_per_lang=5, authored_dir=tmp_path)
    assert a["targets_list"] == b["targets_list"]
    qa, qb = (tmp_path / d / "queries.jsonl" for d in "ab")
    assert qa.read_text() == qb.read_text()


def test_langset_groups_felire_witnesses_and_needs_no_scripture(tmp_path):
    """Old Irish (#552): no Scripture, and the two Félire editions are one text."""
    from scripts.embed_eval.queries import load_authored

    root = tmp_path / "normalized"
    works = [("celt/felire-oengusso", "liturgical"), ("glosscorpus/felire", "liturgical"),
             ("wb-glosses/rom", "patristic"), ("celt/clocan-binn", "patristic")]
    lines = []
    for wid, genre in works:
        path = f"{wid}.json"
        lines.append(json.dumps({"path": path, "work": {
            "work_id": wid, "source_id": wid.split("/")[0], "genre": genre, "language": "sga"}}))
        chunks = [{"chunk_id": f"{wid}#Fel.Jan.{i}", "work_id": wid,
                   "canonical_ref": f"Fel.Jan.{i}", "language": "sga", "chunk_index": i,
                   "text": f"rann {i} " * (12 if i % 2 else 3) + wid} for i in range(1, 9)]
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(json.dumps(chunks), encoding="utf-8")
    (root / "_works.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp_path / "eval"
    stats = langset.build(root, "sga", out, scripture_per_lang=0, unique_per_lang=8,
                          distractors_per_lang=0, authored_dir=tmp_path, min_target_chars=80)
    assert stats["targets"] == {"sga/unique": 8}
    rows = {c["chunk_id"]: c for c in map(json.loads, (out / "corpus.jsonl").open())}
    targets = [t["chunk_id"] for t in stats["targets_list"]]
    assert all(len(rows[t]["text"]) >= 80 for t in targets)
    felire = [t for t in targets if "felire" in t]
    groups = [rows[t]["translation_group_id"] for t in felire]
    assert felire and len(groups) == len(set(groups))
    assert all(g.startswith("felire:Fel.Jan.") for g in groups)
    assert rows["wb-glosses/rom#Fel.Jan.1"]["translation_group_id"] is None
    # the other edition's quatrain is in the corpus and answers the target's queries
    t = felire[0]
    other = next(c for c in rows if c != t and rows[c]["translation_group_id"] == groups[0])
    (tmp_path / "q.jsonl").write_text(json.dumps({
        "query_id": f"paraphrase:{t}", "mode": "paraphrase", "text": "x", "query_lang": "eng",
        "target_lang": "sga", "origin": "unique", "target_chunk_id": t}) + "\n")
    [q] = load_authored([tmp_path / "q.jsonl"], list(rows.values()))
    assert set(q.relevant_ids) == {t, other}


def test_old_english_pools():
    """#582: the ASPR poems by kind and Ælfric are pools; Thorpe's English is in none."""
    from scripts.embed_eval.select import pool_of

    assert pool_of("ang", "aspr/andreas") == "narrative"
    assert pool_of("ang", "aspr/phoenix") == "exeter"
    assert pool_of("ang", "aspr/wanderer") == "wisdom"
    assert pool_of("ang", "aelfric-ch/ch1-05") == "aelfric"
    assert pool_of("ang", "aspr/creed") is None  # a minor poem: distractor only
    assert pool_of("ang", "aelfric-ch-eng/ch1-05") is None



def test_langset_groups_chinese_editions_by_their_passage_alignment(tmp_path):
    """Literary Chinese (#663): two editions cut differently are paired by the
    alignment store, a hit on either answers, and --all-units keeps short units."""
    from patristica import alignment_store
    from scripts.embed_eval.queries import load_authored

    root, store = tmp_path / "normalized", tmp_path / "alignments"
    text = "大秦景教流行中國碑頌并序粵若常然真寂先先而無元窅然靈虛後後而妙有{}"
    short = "短句甲乙丙丁戊己庚辛壬癸"
    works = {"wikisource-lzh/xian-stele": [text.format(i) for i in range(6)] + [short],
             "cbeta/t2144-jingjiao-stele": [text.format(i) + "。" for i in range(6)]}
    lines = []
    for wid, texts in works.items():
        lines.append(json.dumps({"path": f"{wid}.json", "work": {
            "work_id": wid, "source_id": wid.split("/")[0], "genre": "patristic",
            "language": "lzh"}}))
        chunks = [{"chunk_id": f"{wid}#S.{i}", "work_id": wid, "canonical_ref": f"S.{i}",
                   "language": "lzh", "chunk_index": i, "text": t} for i, t in enumerate(texts)]
        (root / wid).parent.mkdir(parents=True, exist_ok=True)
        (root / f"{wid}.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    (root / "_works.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    ids = {w: [f"{w}#S.{i}" for i in range(len(t))] for w, t in works.items()}
    a = alignment_store.Alignment("cbeta/t2144-jingjiao-stele", "cbeta/t2144-jingjiao-stele",
                                  6, "x", {})
    for w in works:
        # the editions agree on units 0-5; unit 0 is a low-confidence group
        group_of = list(range(6)) + ([-1] if len(ids[w]) == 7 else [])
        a.members[w] = alignment_store.Member(w, len(group_of), "x", group_of,
                                              {g: (3 if g == 0 else 9) for g in range(6)},
                                              alignment_store.ids_sha(ids[w]))
    alignment_store.save(store, a)

    out = tmp_path / "eval"
    stats = langset.build(root, "lzh", out, scripture_per_lang=0, unique_per_lang=3,
                          distractors_per_lang=0, authored_dir=tmp_path, all_units=True,
                          alignments_dir=store)
    rows = {c["chunk_id"]: c for c in map(json.loads, (out / "corpus.jsonl").open())}
    assert len(rows) == 13  # every unit, the short one (under the target minimum) too
    assert all(t["chunk_id"].startswith("wikisource-lzh/") for t in stats["targets_list"])
    assert rows["wikisource-lzh/xian-stele#S.0"]["translation_group_id"] is None  # flagged
    assert rows["wikisource-lzh/xian-stele#S.6"]["translation_group_id"] is None
    g = rows["wikisource-lzh/xian-stele#S.3"]["translation_group_id"]
    assert g.startswith("edition:") and rows["cbeta/t2144-jingjiao-stele#S.3"][
        "translation_group_id"] == g
    t = "wikisource-lzh/xian-stele#S.3"
    (tmp_path / "q.jsonl").write_text(json.dumps({
        "query_id": f"paraphrase:{t}", "mode": "paraphrase", "text": "x", "query_lang": "eng",
        "target_lang": "lzh", "origin": "unique", "target_chunk_id": t}) + "\n")
    [q] = load_authored([tmp_path / "q.jsonl"], list(rows.values()))
    assert set(q.relevant_ids) == {t, "cbeta/t2144-jingjiao-stele#S.3"}
