"""Word flags on Kraken's output: which words are likely misread (#720, after #164).

Per word, five signals, combined by a logistic model fitted on the eval set's
dev pages (data/flagger_fit.json):

  uni       max surprisal of its characters under #164's script-aware unigram
  tri       max conditional surprisal under #164's character trigram
  acc_oov   not in #164's accent-sensitive word list
  fold_oov  not in _greek_lexicon's accent-folded word forms
  conf      1 - Kraken's word confidence

The n-gram models are trained from the clean Greek reference editions in
data/normalized (`python -m scripts.ocr flags-train`, cached under
data/cache/ocr/flagger.pkl). Measured on the eval test pages: AUC 0.91; the
r95 point flags 70% of words and catches 96% of Kraken's wrong words.
"""

from __future__ import annotations

import json
import pickle
import unicodedata
from functools import lru_cache
from pathlib import Path

import numpy as np

from scripts.ingest._greek_lexicon import is_greek_form, load_lexicon, normalize_token
from scripts.ocr import ngram
from scripts.ocr.alto import Line

REPO_ROOT = Path(__file__).resolve().parents[2]
FIT = Path(__file__).resolve().parent / "data" / "flagger_fit.json"
MODEL = REPO_ROOT / "data" / "cache" / "ocr" / "flagger.pkl"
REFERENCE = ("sblgnt", "lxx-rahlfs", "pta", "pta-lxx", "perseus")
FEATURES = ("uni", "tri", "acc_oov", "fold_oov", "conf")


def train(normalized: Path, out: Path = MODEL) -> int:
    """Train #164's unigram, trigram and accent word list on the reference editions."""
    texts = []
    for line in (normalized / "_works.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        w = rec["work"]
        if w["source_id"] in REFERENCE and w["language"] == "grc":
            for c in json.loads((normalized / rec["path"]).read_text(encoding="utf-8")):
                texts.append(" ".join(unicodedata.normalize("NFC", c["text"]).split()))
    prepped = [ngram.prep(t, "grc") for t in texts]
    models = {"uni": ngram.ScriptUnigram(prepped, "grc"), "tri": ngram.CharNgram(prepped, 3),
              "acc": ngram.AccentLexicon(texts)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pickle.dumps(models))
    return len(texts)


@lru_cache(maxsize=1)
def _models(path: Path = MODEL) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run `python -m scripts.ocr flags-train` first")
    return pickle.loads(path.read_bytes())


@lru_cache(maxsize=1)
def _lexicon() -> frozenset[str]:
    return load_lexicon()


@lru_cache(maxsize=1)
def fit() -> dict:
    return json.loads(FIT.read_text(encoding="utf-8"))


def features(word: str, conf: float, models: dict | None = None,
             lexicon: frozenset[str] | None = None) -> list[float]:
    m = models if models is not None else _models()
    lex = lexicon if lexicon is not None else _lexicon()
    p = ngram.prep(word, "grc")
    uni = max(m["uni"].surprisals(p), default=0.0) if p else 0.0
    tri = max(m["tri"].surprisals(p), default=0.0) if p else 0.0
    letters = "".join(c for c in word if c.isalpha() or unicodedata.category(c) == "Mn")
    greek = len(letters) >= 2 and is_greek_form(normalize_token(letters))
    acc_oov = float(greek and ngram.accent_key(letters) not in m["acc"].words)
    fold_oov = float(greek and normalize_token(letters) not in lex)
    return [uni, tri, acc_oov, fold_oov, 1.0 - conf]


def score(X: np.ndarray, params: dict | None = None) -> np.ndarray:
    """Probability that each word (row of features) is misread."""
    f = params or fit()
    Z = (X - np.array(f["mu"])) / np.array(f["sd"])
    return 1 / (1 + np.exp(-(Z @ np.array(f["w"]) + f["b"])))


def flag_lines(lines: list[Line], point: str = "r95", **kw) -> list[list[bool]]:
    """Per line, per word: flagged at the operating point (r80, r90 or r95)."""
    thr = fit()["thresholds"][point]
    out = []
    for ln in lines:
        X = np.array([features(w.text, w.conf, **kw) for w in ln.words])
        out.append(list(score(X) >= thr))
    return out
