"""Score the hand-labelled sample with each model and report detection rates.

    uv run python -m scripts.ocr_poc.evaluate SAMPLE.jsonl OUT_DIR

Thresholds are fixed on held-out *clean reference* chunks (the FLAG_RATE
quantile), never on the labelled sample.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import sys
from collections.abc import Callable
from pathlib import Path

from scripts.ocr_poc.corpus import chunks, norm
from scripts.ocr_poc.models import AccentLexicon, CharNgram, Lexicon, ScriptUnigram, Unigram, prep

log = logging.getLogger(__name__)

REFERENCE: dict[str, list[str]] = {
    "grc": ["sblgnt", "lxx-rahlfs", "pta", "pta-lxx", "perseus"],
    "lat": ["clementine", "perseus", "pta", "cursus"],
}
# Whole-language corpus, OCR included, for the "self-trained" variant.
EVERYTHING: dict[str, list[str]] = {
    "grc": REFERENCE["grc"] + ["first1k", "ogpg", "typikon", "goarch-basil", "goarch-chrysostom"],
    "lat": REFERENCE["lat"] + ["oglt-pl", "cantus", "mozarabic", "gallican"],
}
FLAG_RATE = 0.02  # share of held-out clean chunks each threshold flags
ERROR_TAGS = set("XLASF")
LABELS = Path(__file__).with_name("labels.txt")


def heldout(cid: str) -> bool:
    return hashlib.md5(cid.encode()).digest()[0] < 13  # ~5%


def load_labels() -> dict[int, set[str]]:
    out = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        i, _, tags = line.partition(":")
        out[int(i)] = set(tags.split())
    return out


def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def quantile(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sample = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8")]
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    labels = load_labels()
    assert len(labels) == len(sample), (len(labels), len(sample))
    gold_ids = {r["chunk_id"] for r in sample}
    for i, r in enumerate(sample):
        r["text"] = norm(r["text"])
        r["tags"] = labels[i]
        r["idx"] = i

    report: dict = {}
    rows: list[dict] = []
    for lang in ("grc", "lat"):
        train, calib = [], []
        for src in REFERENCE[lang]:
            for cid, t in chunks(src, lang):
                if cid in gold_ids:
                    continue
                (calib if heldout(cid) else train).append(t)
        log.info("%s: %d train / %d calibration reference chunks", lang, len(train), len(calib))
        rng = random.Random(1)
        every = [
            t
            for src in EVERYTHING[lang]
            for cid, t in chunks(src, lang)
            if cid not in gold_ids and rng.random() < 0.25
        ]
        log.info("%s: %d chunks (25%% sample) for self-trained models", lang, len(every))

        uni, bi, tri = Unigram(train), CharNgram(train, 2), CharNgram(train, 3)
        lex = Lexicon(train)
        uni_all, bi_all = Unigram(every), CharNgram(every, 2)
        # v2: typography normalized, apparatus masked, casefolded; script-aware unigram.
        train_t = [prep(t, lang) for t in train]
        uni_s, bi_t, tri_t = (
            ScriptUnigram(train_t, lang),
            CharNgram(train_t, 2),
            CharNgram(train_t, 3),
        )
        scorers: dict[str, Callable[[str], float]] = {
            "unigram": uni.score,
            "bigram_max": bi.score,
            "bigram_mean": bi.mean_score,
            "trigram_max": tri.score,
            "trigram_mean": tri.mean_score,
            "lexicon_oov": lex.score,
            "unigram_self": uni_all.score,
            "bigram_max_self": bi_all.score,
            "unigram_script": lambda t: uni_s.score(prep(t, lang)),
            "bigram_typo": lambda t: bi_t.score(prep(t, lang)),
            "trigram_typo": lambda t: tri_t.score(prep(t, lang)),
        }
        if lang == "grc":
            acc = AccentLexicon(train)
            scorers["accent_lexicon_oov"] = acc.score
        calib = [t for t in calib if len(t) >= 20]
        thresholds = {
            name: quantile([f(t) for t in calib], 1 - FLAG_RATE) for name, f in scorers.items()
        }

        # v3: bootstrap. Add the target (OCR) sources' own chunks that pass the
        # v2 round-1 filter, so the model learns their legitimate conventions
        # (citations, numerals, apparatus) but not the junk round 1 catches.
        refs = set(REFERENCE[lang])
        target = [
            (cid, prep(t, lang))
            for src in EVERYTHING[lang]
            if src not in refs
            for cid, t in chunks(src, lang)
            if cid not in gold_ids and rng.random() < 0.25 and len(t) >= 20
        ]
        passing = [
            (cid, t)
            for cid, t in target
            if uni_s.score(t) <= thresholds["unigram_script"]
            and bi_t.score(t) <= thresholds["bigram_typo"]
        ]
        log.info("%s: %d/%d target chunks pass round 1", lang, len(passing), len(target))
        boot_train = train_t + [t for cid, t in passing if not heldout(cid)]
        boot_calib = [prep(t, lang) for t in calib] + [t for cid, t in passing if heldout(cid)]
        uni_b, bi_b, tri_b = (
            ScriptUnigram(boot_train, lang),
            CharNgram(boot_train, 2),
            CharNgram(boot_train, 3),
        )
        boot = {
            "unigram_boot": lambda t: uni_b.score(prep(t, lang)),
            "bigram_boot": lambda t: bi_b.score(prep(t, lang)),
            "trigram_boot": lambda t: tri_b.score(prep(t, lang)),
        }
        for name, f in boot.items():
            thresholds[name] = quantile([f(t) for t in boot_calib], 1 - FLAG_RATE)
        scorers.update(boot)
        log.info("%s thresholds: %s", lang, {k: round(v, 3) for k, v in thresholds.items()})

        gold = [r for r in sample if r["language"] == lang]
        for r in gold:
            r["scores"] = {name: f(r["text"]) for name, f in scorers.items()}
            r["flags"] = {name: r["scores"][name] > thresholds[name] for name in scorers}
            r["why"] = {
                "unigram": uni.explain(r["text"], thresholds["unigram"]),
                "bigram": bi.explain(r["text"], thresholds["bigram_max"]),
                "lexicon": lex.explain(r["text"])[:8],
                "unigram_boot": uni_b.explain(prep(r["text"], lang), thresholds["unigram_boot"]),
                "bigram_boot": bi_b.explain(prep(r["text"], lang), thresholds["bigram_boot"]),
            }
            rows.append(r)
        report[lang] = summarize(gold, list(scorers), thresholds)

    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    with open(out_dir / "scored.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            r = dict(r, tags=sorted(r["tags"]))
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print_report(report)


def summarize(gold: list[dict], names: list[str], thresholds: dict[str, float]) -> dict:
    def is_err(r: dict) -> bool:
        return bool(r["tags"] & ERROR_TAGS)

    groups = {
        "clean": [r for r in gold if not is_err(r)],
        "error": [r for r in gold if is_err(r)],
        "has_X_or_F": [r for r in gold if r["tags"] & set("XF")],
        "inset_only": [r for r in gold if is_err(r) and not r["tags"] & set("XF")],
        "inset_only_L": [r for r in gold if "L" in r["tags"] and not r["tags"] & set("XF")],
        "inset_only_A_noL": [r for r in gold if "A" in r["tags"] and not r["tags"] & set("XFL")],
        "inset_only_S_noLA": [r for r in gold if "S" in r["tags"] and not r["tags"] & set("XFLA")],
    }
    out: dict = {
        "n": {k: len(v) for k, v in groups.items()},
        "thresholds": thresholds,
        "scorers": {},
    }
    combos = {
        "unigram|bigram_max": ("unigram", "bigram_max"),
        "unigram|trigram_max": ("unigram", "trigram_max"),
        "unigram|lexicon_oov": ("unigram", "lexicon_oov"),
        "unigram_script|bigram_typo": ("unigram_script", "bigram_typo"),
        "unigram_boot|bigram_boot": ("unigram_boot", "bigram_boot"),
        "unigram_boot|trigram_boot": ("unigram_boot", "trigram_boot"),
    }
    if "accent_lexicon_oov" in names:
        combos["unigram_boot|bigram_boot|accent_lex"] = (
            "unigram_boot",
            "bigram_boot",
            "accent_lexicon_oov",
        )
    for name in names + list(combos):
        parts = combos.get(name, (name,))

        def flag(r: dict) -> bool:
            return any(r["flags"][p] for p in parts)

        s: dict = {k: _rate(v, flag) for k, v in groups.items()}
        flagged = [r for r in gold if flag(r)]
        s["precision"] = (
            round(sum(is_err(r) for r in flagged) / len(flagged), 3) if flagged else None
        )
        if name in names:
            s["auc_any_error"] = round(
                auc(
                    [r["scores"][name] for r in groups["error"]],
                    [r["scores"][name] for r in groups["clean"]],
                ),
                3,
            )
            s["auc_inset_vs_clean"] = round(
                auc(
                    [r["scores"][name] for r in groups["inset_only"]],
                    [r["scores"][name] for r in groups["clean"]],
                ),
                3,
            )
        # What this scorer adds over the unigram flag alone.
        missed = [r for r in groups["error"] if not r["flags"]["unigram"]]
        s["recall_on_unigram_misses"] = _rate(missed, flag)
        out["scorers"][name] = s
    return out


def _rate(rs: list[dict], flag: Callable[[dict], bool]) -> str:
    k = sum(flag(r) for r in rs)
    return f"{k}/{len(rs)}"


def print_report(report: dict) -> None:
    cols = [
        "clean",
        "has_X_or_F",
        "inset_only",
        "inset_only_L",
        "inset_only_A_noL",
        "inset_only_S_noLA",
        "recall_on_unigram_misses",
        "precision",
        "auc_any_error",
        "auc_inset_vs_clean",
    ]
    for lang, rep in report.items():
        print(f"\n## {lang}  n={rep['n']}")
        print("scorer".ljust(32) + "".join(c[:14].rjust(15) for c in cols))
        for name, s in rep["scorers"].items():
            print(name.ljust(32) + "".join(str(s.get(c, "")).rjust(15) for c in cols))


if __name__ == "__main__":
    main()
