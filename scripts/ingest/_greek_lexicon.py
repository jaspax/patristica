"""
Greek word-form lexicon and OCR-quality scoring.

The lexicon is a list of *inflected* Ancient Greek word forms harvested from
the clean (edited, non-OCR or OCR-corrected) Greek text already in this
corpus.  It is used to score OCR output (Open Patrologia Graeca): the fraction
of a paragraph's words that are real Greek forms is a strong garbage detector.

Why self-built rather than Morpheus/Diorisis: no extra licence to track, no
extra download, and the forms are normalised exactly the way the scorer
normalises OCR tokens.

Sources (``data/normalized``, language ``grc`` only):

* ``patristic/first1k``  — First1KGreek (CC-BY-SA 4.0)
* ``patristic/pta``      — Patristic Text Archive (CC-BY-SA 4.0)
* ``patristic/perseus``  — Perseus canonical-greekLit (CC-BY-SA 4.0)
* ``scripture/sblgnt``   — SBL Greek New Testament (CC-BY 4.0)
* ``scripture/pta-lxx``  — PTA Septuagint (CC-BY-SA 4.0)

Rahlfs LXX (CC-BY-NC-SA) is deliberately excluded so the derived list carries
no non-commercial restriction.  ``patristic/ogpg`` (the OCR being scored) is of
course excluded too.

Token normalisation (shared by building and scoring, see ``normalize_token``):
NFD → drop all combining marks (accents, breathings, iota subscript, diaeresis)
→ lowercase → fold letter variants (final/lunate sigma → σ, ϐ → β, ϑ → θ, …)
→ drop apostrophes/coronis.  Accent-insensitive matching is intentional: OCR
gets accents wrong far more often than base letters, and Migne's typography
(grave accents, ϐ) differs from the critical editions.

The cached artefact is ``scripts/ingest/data/greek_wordforms.tsv.gz``
(``form<TAB>count``, most frequent first).  Rebuild with::

    uv run python -m scripts.ingest._greek_lexicon --build
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from tqdm import tqdm

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
LEXICON_PATH = Path(__file__).resolve().parent / "data" / "greek_wordforms.tsv.gz"
DEFAULT_NORMALIZED_DIR = _REPO_ROOT / "data" / "normalized"

LEXICON_SOURCES: tuple[str, ...] = (
    "patristic/first1k",
    "patristic/pta",
    "patristic/perseus",
    "scripture/sblgnt",
    "scripture/pta-lxx",
)

# Forms seen fewer times than this in the clean corpus are not trusted:
# hapaxes there include residual OCR errors of First1KGreek.
DEFAULT_MIN_COUNT = 2

_LETTER_FOLD = str.maketrans({
    "ς": "σ", "ϲ": "σ", "Ϲ": "σ",
    "ϐ": "β", "ϑ": "θ", "ϕ": "φ", "ϰ": "κ", "ϱ": "ρ", "ϖ": "π", "ϗ": "και",
    "ϛ": "στ",
})


def _is_greek_letter(c: str) -> bool:
    cp = ord(c)
    return (0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF) and c.isalpha()


def normalize_token(token: str) -> str:
    """Return the accent-less, lowercase, letter-folded form of a token.

    Every non-letter character (punctuation, digits, apostrophes, superscript
    note numbers) is dropped; letters of any script are kept, so a mixed
    Greek/Latin OCR token stays mixed.
    """
    nfd = unicodedata.normalize("NFD", token)
    out = "".join(
        c for c in nfd
        if unicodedata.category(c) != "Mn" and c.isalpha()
    )
    return out.lower().translate(_LETTER_FOLD)


def tokens(text: str) -> list[str]:
    """Whitespace tokens normalised with ``normalize_token``; empties dropped."""
    out = []
    for raw in text.split():
        form = normalize_token(raw)
        if form:
            out.append(form)
    return out


def is_greek_form(form: str) -> bool:
    """True if every letter of a normalised form is Greek."""
    return bool(form) and all(_is_greek_letter(c) for c in form)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LexScore:
    """Dictionary score of one paragraph.

    ``score`` = known Greek words / all words, where "all words" counts every
    token containing a letter: Greek tokens, Latin tokens and mixed-script
    tokens.  Latin and mixed tokens can never be known, so a Greek/Latin
    column-boundary mash-up scores low even if its Greek fragments are real.
    """

    known: int
    greek: int
    foreign: int

    @property
    def total(self) -> int:
        return self.greek + self.foreign

    @property
    def score(self) -> float:
        return self.known / self.total if self.total else 0.0


def score_text(text: str, lexicon: frozenset[str]) -> LexScore:
    """Score ``text`` against a set of normalised Greek forms."""
    known = greek = foreign = 0
    for form in tokens(text):
        if is_greek_form(form):
            greek += 1
            if form in lexicon:
                known += 1
        else:
            foreign += 1
    return LexScore(known=known, greek=greek, foreign=foreign)


# ---------------------------------------------------------------------------
# Building / loading the lexicon
# ---------------------------------------------------------------------------

def build_counts(normalized_dir: Path, sources: tuple[str, ...] = LEXICON_SOURCES) -> Counter[str]:
    """Count normalised Greek forms over the ``grc`` chunks of ``sources``."""
    counts: Counter[str] = Counter()
    files = [
        p for src in sources
        for p in sorted((normalized_dir / src).rglob("*.json"))
        if not p.name.startswith("_")
    ]
    if not files:
        raise FileNotFoundError(f"No normalized files for {sources} under {normalized_dir}")
    for path in tqdm(files, desc="greek lexicon"):
        chunks = json.loads(path.read_text(encoding="utf-8"))
        for chunk in chunks:
            if chunk.get("language") != "grc":
                continue
            counts.update(f for f in tokens(chunk["text"]) if is_greek_form(f))
    return counts


def write_lexicon(counts: Counter[str], path: Path = LEXICON_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{form}\t{n}" for form, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
    header = (
        "# Greek word forms (accent-less, lowercase, folded; see _greek_lexicon.py)\n"
        f"# sources: {', '.join(LEXICON_SOURCES)} (data/normalized, grc chunks)\n"
        "# licences of sources: CC-BY-SA 4.0 / CC-BY 4.0\n"
    )
    data = (header + "\n".join(lines) + "\n").encode("utf-8")
    # mtime=0 → byte-identical output for identical input (idempotent rebuilds)
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(data)
    log.info("Wrote %d forms → %s", len(counts), path)


def read_counts(path: Path = LEXICON_PATH) -> Counter[str]:
    if not path.exists():
        raise FileNotFoundError(
            f"Greek lexicon {path} missing; build it with "
            "`uv run python -m scripts.ingest._greek_lexicon --build`"
        )
    counts: Counter[str] = Counter()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            form, _, n = line.rstrip("\n").partition("\t")
            counts[form] = int(n)
    return counts


@lru_cache(maxsize=4)
def load_lexicon(path: Path = LEXICON_PATH, min_count: int = DEFAULT_MIN_COUNT) -> frozenset[str]:
    """Load the cached lexicon as a frozenset of forms seen ≥ ``min_count`` times."""
    return frozenset(f for f, n in read_counts(path).items() if n >= min_count)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Build the Greek word-form lexicon.")
    parser.add_argument("--build", action="store_true", help="(re)build the cached lexicon")
    parser.add_argument("--normalized-dir", type=Path, default=DEFAULT_NORMALIZED_DIR)
    parser.add_argument("--output", type=Path, default=LEXICON_PATH)
    args = parser.parse_args()
    if args.build:
        write_lexicon(build_counts(args.normalized_dir), args.output)
    counts = read_counts(args.output)
    log.info("%d forms total; %d with count ≥ %d",
             len(counts), sum(1 for n in counts.values() if n >= DEFAULT_MIN_COUNT),
             DEFAULT_MIN_COUNT)


if __name__ == "__main__":
    main()
