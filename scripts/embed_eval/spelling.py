"""
Spelling sensitivity of the embedder for Church Slavonic (#336).

``fold()`` only reaches keyword search; ``scripts.embed`` embeds the stored
spelling. Slavonic witnesses spell one word many ways, so this measures how
far Voyage treats those spellings as the same text, in two test sets built
from ``data/normalized``:

- **Minimal pairs** (``pairs``): about 50 Gospel verses of Codex Marianus,
  each rewritten in one spelling class at a time (``VARIANTS``: yers dropped
  or merged, ѣ/е/ꙗ, і/ꙇ/и, оу/ѹ/у, titla expanded, superscripts inline, marks
  dropped, modern Russian orthography, ``fold()``). Each variant is scored by
  its cosine to the original and by the rank of the original among all of
  Marianus's verses when the variant is the query. Baselines: the next verse
  of the same witness, the same verse in Zographensis and Assemanianus, and
  the SBLGNT Greek of the verse against its unaccented, unpunctuated form.
- **Cross-witness retrieval** (``witness``): for each verse of one Gospel
  codex (Marianus, Zographensis, Assemanianus, Savvina kniga), the rank of the
  same verse (org versification) among all verses of another codex, as R@1,
  R@5 and MRR, with both sides as stored and with both sides ``fold()``-ed.

Every text is embedded as a document (``input_type=document``), as stored
vectors are, through the eval's SQLite cache, so a rerun costs nothing and
texts shared with ``scripts.embed_eval.run`` over ``data/eval/chu`` are paid
for once.

Usage::

    python -m scripts.embed_eval.spelling estimate        # texts, tokens, $ not yet cached
    python -m scripts.embed_eval.spelling run --pay       # paid: embeds what is missing
    python -m scripts.embed_eval.spelling pairs --show 3  # print a few variants (free)
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from patristica import editorial
from patristica.textfold import fold
from patristica.versification import to_org_ref

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

DEFAULT_NORMALIZED = Path("data/normalized")
DEFAULT_OUT = Path("data/eval/chu")
MODEL = "voyage/voyage-4-large"
PRICE_PER_MTOK = 0.12  # voyage-4-large list price, as in scripts.embed

WITNESSES: tuple[str, ...] = ("ccmh-marianus", "ccmh-zographensis", "ccmh-assemanianus",
                              "ccmh-savvina")
GOSPELS: tuple[str, ...] = ("Matt", "Mark", "Luke", "John")
GREEK = "sblgnt"

# --- spelling variants ------------------------------------------------------------

TITLO = "\u0483"
# Combining marks of Church Slavonic text other than superscript letters: titlo,
# palatalization mark, breathings, pokrytie, accents, kamora, breve, diaeresis.
_MARK_RE = re.compile("[\u0300-\u036f\u0483-\u0489]")
_SUPERSCRIPT = {
    0x2DE0: "б", 0x2DE1: "в", 0x2DE2: "г", 0x2DE3: "д", 0x2DE4: "ж", 0x2DE5: "з",
    0x2DE6: "к", 0x2DE7: "л", 0x2DE8: "м", 0x2DE9: "н", 0x2DEA: "о", 0x2DEB: "п",
    0x2DEC: "р", 0x2DED: "с", 0x2DEE: "т", 0x2DEF: "х", 0x2DF0: "ц", 0x2DF1: "ч",
    0x2DF2: "ш", 0x2DF3: "щ", 0x2DF4: "ѳ", 0x2DF5: "ст", 0x2DF6: "а", 0x2DF7: "е",
    0x2DF8: "ꙉ", 0x2DF9: "ꙋ", 0x2DFA: "ѣ", 0x2DFB: "ю", 0x2DFC: "ꙗ", 0x2DFD: "ѧ",
    0x2DFE: "ѫ", 0x2DFF: "ѭ",
    0xA674: "є", 0xA675: "і", 0xA676: "ї", 0xA677: "у", 0xA678: "ъ", 0xA679: "ы",
    0xA67A: "ь", 0xA67B: "ѡ", 0xA69E: "ф", 0xA69F: "ѥ",
}
_SUPERSCRIPT_RE = re.compile("[" + "".join(map(chr, _SUPERSCRIPT)) + "]")
_LETTER_MARKS = "\u0300-\u036f\u0483-\u0489\u2de0-\u2dff\ua674-\ua67d\ua69e\ua69f"
_VOWELS = "аеиоуыюяѣѧѫъьꙿіїꙇѥꙗѩѭꙑѹꙋѡ"
_PAEROK = "ꙿⸯ"
_WORD_RE = re.compile(rf"[\w{_LETTER_MARKS}{_PAEROK}]+")


def _cased(table: dict[str, str]) -> dict[int, str]:
    """A translate table for *table* and its upper-case pairs."""
    out = {ord(k): v for k, v in table.items()}
    for k, v in table.items():
        if k.upper() != k and len(k) == 1:
            out.setdefault(ord(k.upper()), v[:1].upper() + v[1:])
    return out


def _words(text: str, fn: Callable[[str], str]) -> str:
    """Apply *fn* to every word of *text*, leaving spaces and punctuation alone."""
    return _WORD_RE.sub(lambda m: fn(m.group()) or m.group(), text)


def _bare(word: str) -> str:
    """*word* lowercased, superscripts inline, marks dropped."""
    return _MARK_RE.sub("", superscripts_inline(word)).lower()


# Nomina sacra and other words written under a titlo, as prefix rules on the
# word without its marks (longest first). The result spells the word out as an
# OCS edition would; an inflected ending is kept as it is (гл҃ахѫ → глаголахѫ).
# A single letter under a titlo is a numeral and is left alone.
_TITLA: tuple[tuple[str, str], ...] = tuple(sorted({
    "гл": "глагол", "исв": "исоусов",
    "ис": "исоус", "іс": "исоус", "ꙇс": "исоус", "їс": "исоус",
    "сн": "сꙑн", "гн": "господин", "гв": "господев", "г": "господ",
    "бж": "бож", "бг": "бог", "б": "бог", "дх": "доух", "дш": "доуш",
    "отц": "отьц", "оц": "отьц", "оч": "отьч",
    "члвчск": "чловѣчьск", "члчск": "чловѣчьск", "члвч": "чловѣч",
    "члск": "чловѣчьск", "чск": "чловѣчьск",
    "члвк": "чловѣк", "члк": "чловѣк", "чк": "чловѣк",
    "хс": "христос", "х": "христ", "ст": "свѧт",
    "нбс": "небес", "небс": "небес", "нб": "неб",
    "мт": "матер", "срдц": "сръдьц", "крст": "крьст", "прк": "пророк",
    "аꙉл": "аньгел", "епп": "епископ",
    "цркв": "цръкв", "цсрств": "цѣсарств", "цср": "цѣсар", "цѣср": "цѣсар",
    "црств": "цѣсарств", "цр": "цѣсар",
}.items(), key=lambda kv: -len(kv[0])))


def titla_expanded(text: str) -> str:
    """Spell out the words written under a titlo (бг҃ъ → богъ, гл҃а → глагола)."""
    def expand(word: str) -> str:
        if TITLO not in word:
            return word
        bare = _bare(word)
        if len(bare) <= 1:
            return word
        for abbr, full in _TITLA:
            if bare.startswith(abbr):
                out = full + bare[len(abbr):]
                return out[:1].upper() + out[1:] if word[:1].isupper() else out
        return word
    return _words(text, expand)


def superscripts_inline(text: str) -> str:
    """Write superscript letters on the line (хрⷭ҇тъ → хрс҇тъ)."""
    return _SUPERSCRIPT_RE.sub(lambda m: _SUPERSCRIPT[ord(m.group())], text)


def marks_dropped(text: str) -> str:
    """Drop titla, breathings and accents, superscripts inline: what a keyboard gives."""
    return _MARK_RE.sub("", superscripts_inline(text))


def yer_final_dropped(text: str) -> str:
    """Drop word-final yers (богъ → бог), keeping one-letter words."""
    def drop(word: str) -> str:
        out = re.sub(f"[ъьЪЬ][{_LETTER_MARKS}]*$", "", word)
        return out if _bare(out) else word
    return _words(text, drop)


def yer_merged(text: str) -> str:
    """Write the front yer as the back yer (дьнь → дънъ)."""
    return text.translate(_cased({"ь": "ъ"}))


def yers_dropped(text: str) -> str:
    """Drop every yer and paerok (кръстъ → крст, въ → в), keeping one-letter words."""
    def drop(word: str) -> str:
        out = re.sub(f"[ъьЪЬ{_PAEROK}]", "", word)
        return out if _bare(out) else word
    return _words(text, drop)


def _yat_by_position(text: str, after_consonant: str, initial: str) -> str:
    # ѣ at a word start or after a vowel (marks in between don't count).
    def repl(m: re.Match[str]) -> str:
        start, ch = m.start(), m.group()
        j = start - 1
        while j >= 0 and re.match(f"[{_LETTER_MARKS}]", text[j]):
            j -= 1
        prev = text[j] if j >= 0 else " "
        at_start = not (prev.isalpha() or prev in _PAEROK)
        out = initial if at_start or prev.lower() in _VOWELS else after_consonant
        return out.upper() if ch.isupper() else out
    return re.sub("[ѣѢ]", repl, text)


def yat_cyrillic(text: str) -> str:
    """ѣ as a Cyrillic witness writes it: ꙗ at a word start or after a vowel, else ѣ."""
    return _yat_by_position(text, "ѣ", "ꙗ")


def yat_modern(text: str) -> str:
    """ѣ as modern Russian spells the sound: я at a word start or after a vowel
    (Glagolitic Ⱑ is *ja* there: ѣко → яко), else е (тѣло → тело)."""
    return _yat_by_position(text, "е", "я")


def i_merged(text: str) -> str:
    """і, ї, ꙇ as и."""
    return text.translate(_cased({"і": "и", "ї": "и", "ꙇ": "и"}))


_OU_RE = re.compile(f"([оО])([{_LETTER_MARKS}]*)у")


def u_ligature(text: str) -> str:
    """The digraph оу as the ligature ѹ (оубо → ѹбо)."""
    return _OU_RE.sub(lambda m: ("Ѹ" if m.group(1) == "О" else "ѹ") + m.group(2), text)


def u_plain(text: str) -> str:
    """оу, ѹ and ꙋ as у (оубо → убо)."""
    t = _OU_RE.sub(lambda m: ("У" if m.group(1) == "О" else "у") + m.group(2), text)
    return t.translate(_cased({"ѹ": "у", "ꙋ": "у"}))


def iotated_plain(text: str) -> str:
    """The iotated letters as modern glyphs or uniotated: ꙗ → я, ѥ → е, ѩ → ѧ, ѭ → ѫ."""
    return text.translate(_cased({"ꙗ": "я", "ѥ": "е", "ѩ": "ѧ", "ѭ": "ѫ"}))


_MODERN_LETTERS = _cased({
    "ѣ": "е", "і": "и", "ї": "и", "ꙇ": "и", "ѵ": "и", "ꙑ": "ы",
    "ѫ": "у", "ѭ": "ю", "ѧ": "я", "ꙙ": "я", "ѩ": "я", "ꙗ": "я", "ѥ": "е", "є": "е",
    "ѕ": "з", "ꙁ": "з", "ꙃ": "з", "ѡ": "о", "ѻ": "о", "ꙍ": "о", "ѿ": "от",
    "ѳ": "ф", "ѯ": "кс", "ѱ": "пс", "ꙉ": "г", "ѹ": "у", "ꙋ": "у",
    "ꙿ": "", "ⸯ": "",
})


def modern(text: str) -> str:
    """The text in modern Russian orthography, approximately: titla spelled out, no
    marks, modern letters (ѣ → е/я, ѫ → у, ѧ → я, …), шт → щ, оу → у, ъі → ы, no
    ъ, and ь only at a word end. Vocalized yers (дьнь → день) are not modelled."""
    t = yat_modern(marks_dropped(titla_expanded(text)))
    t = re.sub("ъи|ъі", "ы", u_plain(t))
    t = t.translate(_MODERN_LETTERS).replace("шт", "щ").replace("Шт", "Щ")

    def yers(word: str) -> str:
        out = re.sub("[ъЪ]", "", re.sub("[ьЬ](?!$)", "", word))
        return out or word
    return _words(t, yers)


def folded(text: str) -> str:
    """``fold()``: what the keyword index stores (also the candidate embedding form)."""
    return fold(text)


#: Spelling classes, each a function of the original text.
VARIANTS: dict[str, Callable[[str], str]] = {
    "yer_final_dropped": yer_final_dropped,
    "yer_merged": yer_merged,
    "yers_dropped": yers_dropped,
    "yat_cyrillic": yat_cyrillic,
    "yat_modern": yat_modern,
    "i_merged": i_merged,
    "u_ligature": u_ligature,
    "u_plain": u_plain,
    "iotated_plain": iotated_plain,
    "titla_expanded": titla_expanded,
    "superscripts_inline": superscripts_inline,
    "marks_dropped": marks_dropped,
    "modern": modern,
    "folded": folded,
}

# --- test sets --------------------------------------------------------------------


@dataclass(frozen=True)
class Unit:
    chunk_id: str
    source_id: str
    org_ref: str
    text: str


def load_units(normalized_dir: Path, source_id: str, books: Iterable[str] = GOSPELS,
               min_chars: int = 10) -> list[Unit]:
    """The verses of a Scripture source in book order, as embedded (editorial material out)."""
    out: list[Unit] = []
    for book in books:
        path = normalized_dir / source_id / f"{book}.json"
        if not path.exists():
            continue
        for chunk in json.loads(path.read_text(encoding="utf-8")):
            text = editorial.source_text(chunk)
            if len(text.strip()) >= min_chars:
                out.append(Unit(chunk["chunk_id"], source_id,
                                to_org_ref(source_id, chunk["canonical_ref"]), text))
    return out


def pick_sentences(units: list[Unit], n: int = 50, seed: int = 0,
                   min_chars: int = 60, max_chars: int = 250) -> list[int]:
    """Indexes of *n* verses that most spelling classes change, sampled deterministically.

    A verse qualifies when it has a titlo, ѣ, і or ꙇ, оу and a yer, has a next
    verse in the same book, and is 60–250 characters long.
    """
    def ok(i: int) -> bool:
        t = units[i].text
        nxt = units[i + 1] if i + 1 < len(units) else None
        return (min_chars <= len(t) <= max_chars and TITLO in t and "ѣ" in t
                and ("і" in t or "ꙇ" in t) and "оу" in t and ("ь" in t or "ъ" in t)
                and nxt is not None
                and nxt.org_ref.split(".")[0] == units[i].org_ref.split(".")[0])
    pool = [i for i in range(len(units)) if ok(i)]
    return sorted(random.Random(seed).sample(pool, min(n, len(pool))))


def pair_rows(units: list[Unit], picked: list[int], others: dict[str, list[Unit]],
              greek: list[Unit]) -> list[dict]:
    """The minimal-pair rows: ``{sid, kind, a, b}``, cosine(a, b) to be measured.

    *kind* is a spelling class, or a baseline: ``adjacent`` (the next verse),
    ``witness:{source}`` (the same verse in another codex), ``grc_unaccented``
    (SBLGNT unaccented, lowercase, unpunctuated) and ``grc_adjacent``. A
    variant equal to its original is left out (the class doesn't occur there).
    """
    from scripts.embed_eval.queries import perturb

    by_ref = {src: {u.org_ref: u for u in us} for src, us in others.items()}
    grc = {u.org_ref: i for i, u in enumerate(greek)}
    rows = []
    for i in picked:
        u = units[i]
        for kind, fn in VARIANTS.items():
            v = fn(u.text)
            if v != u.text:
                rows.append({"sid": u.chunk_id, "kind": kind, "a": u.text, "b": v})
        rows.append({"sid": u.chunk_id, "kind": "adjacent", "a": u.text, "b": units[i + 1].text})
        for src, refs in by_ref.items():
            if o := refs.get(u.org_ref):
                rows.append({"sid": u.chunk_id, "kind": f"witness:{src}", "a": u.text, "b": o.text})
        if (g := grc.get(u.org_ref)) is not None:
            gt = greek[g].text
            rows.append({"sid": u.chunk_id, "kind": "grc_unaccented", "a": gt,
                         "b": perturb(gt, "grc", random.Random(0))})
            if g + 1 < len(greek):
                rows.append({"sid": u.chunk_id, "kind": "grc_adjacent", "a": gt,
                             "b": greek[g + 1].text})
    return rows


def witness_pairs(units: dict[str, list[Unit]]) -> list[tuple[str, str]]:
    """Ordered (query witness, searched witness) pairs."""
    return [(a, b) for a in units for b in units if a != b]


def rank_of(sims: np.ndarray, relevant: Iterable[int]) -> int:
    """1-based rank of the best relevant column in a row of similarities."""
    import numpy as np

    best = max(sims[j] for j in relevant)
    return int(np.sum(sims > best)) + 1


def witness_scores(vecs: dict[str, np.ndarray], units: dict[str, list[Unit]]) -> list[dict]:
    """R@1, R@5 and MRR of finding each verse of one witness among another's verses."""
    out = []
    for a, b in witness_pairs(units):
        refs_b: dict[str, list[int]] = defaultdict(list)
        for j, u in enumerate(units[b]):
            refs_b[u.org_ref].append(j)
        qs = [(i, refs_b[u.org_ref]) for i, u in enumerate(units[a]) if u.org_ref in refs_b]
        if not qs:
            continue
        sims = vecs[a][[i for i, _ in qs]] @ vecs[b].T
        ranks = [rank_of(sims[k], rel) for k, (_, rel) in enumerate(qs)]
        out.append({"query": a, "searched": b, "n": len(ranks),
                    "R@1": sum(r == 1 for r in ranks) / len(ranks),
                    "R@5": sum(r <= 5 for r in ranks) / len(ranks),
                    "MRR": sum(1 / r for r in ranks) / len(ranks)})
    return out


# --- embedding, cost ------------------------------------------------------------


def cache_path(out_dir: Path) -> Path:
    return out_dir / "embeddings" / f"{MODEL.replace('/', '__')}.sqlite"


def needed_texts(normalized_dir: Path) -> dict[str, list[str]]:
    """Every text the run embeds, by part (``pairs``, ``witness``, ``witness_folded``)."""
    units = {w: load_units(normalized_dir, w) for w in WITNESSES}
    greek = load_units(normalized_dir, GREEK)
    mar = units[WITNESSES[0]]
    rows = pair_rows(mar, pick_sentences(mar), {w: units[w] for w in WITNESSES[1:3]}, greek)
    witness = [u.text for us in units.values() for u in us]
    return {
        "pairs": [t for r in rows for t in (r["a"], r["b"])],
        "witness": witness,
        "witness_folded": [fold(t) for t in witness],
    }


def uncached(texts: Iterable[str], cache: Path) -> list[str]:
    """The distinct *texts* that have no document vector in the cache yet."""
    import hashlib
    import sqlite3

    distinct = sorted(set(texts))
    if not cache.exists():
        return distinct
    db = sqlite3.connect(cache)
    have = {h for (h,) in db.execute("SELECT h FROM emb WHERE kind = 'document'")}
    return [t for t in distinct if hashlib.sha256(t.encode()).hexdigest() not in have]


def estimate(parts: dict[str, list[str]], cache: Path) -> dict:
    """Texts and cl100k tokens still to embed, per part (each text counted once) and in all."""
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    seen: set[str] = set()
    out: dict = {"parts": {}}
    for name, texts in parts.items():
        todo = [t for t in uncached(texts, cache) if t not in seen]
        seen.update(todo)
        tokens = sum(len(enc.encode(t)) for t in todo)
        out["parts"][name] = {"texts": len(todo), "cl100k_tokens": tokens}
    total = sum(p["cl100k_tokens"] for p in out["parts"].values())
    out["total"] = {"texts": len(seen), "cl100k_tokens": total,
                    "usd_list_price": round(total / 1e6 * PRICE_PER_MTOK, 4)}
    return out


def _embedder(out_dir: Path):  # noqa: ANN202 (eval-only helper)
    from scripts.embed_eval.embedders import CachedEmbedder, get_embedder

    return CachedEmbedder(get_embedder(MODEL), cache_path(out_dir))


def _unit(vecs: np.ndarray) -> np.ndarray:
    import numpy as np

    v = np.asarray(vecs, dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def run(normalized_dir: Path, out_dir: Path) -> dict:
    """Embed what is missing (paid) and score both test sets."""
    import numpy as np

    emb = _embedder(out_dir)
    units = {w: load_units(normalized_dir, w) for w in WITNESSES}
    greek = load_units(normalized_dir, GREEK)
    mar = units[WITNESSES[0]]
    picked = pick_sentences(mar)
    rows = pair_rows(mar, picked, {w: units[w] for w in WITNESSES[1:3]}, greek)

    raw = {w: _unit(emb.embed_documents([u.text for u in us])) for w, us in units.items()}
    fld = {w: _unit(emb.embed_documents([fold(u.text) for u in us])) for w, us in units.items()}

    # Minimal pairs: cosine to the original, and the original's rank among all of
    # Marianus's verses (doc–doc) with the variant as the query.
    a = _unit(emb.embed_documents([r["a"] for r in rows]))
    b = _unit(emb.embed_documents([r["b"] for r in rows]))
    cos = np.sum(a * b, axis=1)
    mar_index = {u.chunk_id: i for i, u in enumerate(mar)}
    by_kind: dict[str, list[tuple[float, int | None]]] = defaultdict(list)
    for r, c, vb in zip(rows, cos, b, strict=True):
        rank = None
        if not r["kind"].startswith("grc"):
            rank = rank_of(raw[WITNESSES[0]] @ vb, [mar_index[r["sid"]]])
        by_kind[r["kind"]].append((float(c), rank))
    pairs = {}
    for kind, vals in by_kind.items():
        cs = sorted(c for c, _ in vals)
        ranks = [r for _, r in vals if r is not None]
        pairs[kind] = {"n": len(cs), "mean": float(np.mean(cs)), "min": cs[0],
                       "median": cs[len(cs) // 2],
                       **({"R@1": sum(r == 1 for r in ranks) / len(ranks)} if ranks else {})}
    result = {
        "model": MODEL, "sentences": len(picked),
        "pairs": pairs,
        "witness": witness_scores(raw, units),
        "witness_folded": witness_scores(fld, units),
        "tokens_used": getattr(emb.inner, "tokens_used", None),
    }
    (out_dir / "spelling.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result


def markdown(result: dict) -> str:
    lines = ["### Minimal pairs (cosine to the original; R@1: the original is the nearest "
             "Marianus verse)", "", "| class | n | mean | median | min | R@1 |",
             "|---|---:|---:|---:|---:|---:|"]
    for kind, s in result["pairs"].items():
        r1 = f"{s['R@1']:.2f}" if "R@1" in s else "–"
        lines.append(f"| {kind} | {s['n']} | {s['mean']:.3f} | {s['median']:.3f} | "
                     f"{s['min']:.3f} | {r1} |")
    for part in ("witness", "witness_folded"):
        lines += ["", f"### Cross-witness retrieval ({part})", "",
                  "| query → searched | n | R@1 | R@5 | MRR |", "|---|---:|---:|---:|---:|"]
        for s in result[part]:
            q, t = s["query"].removeprefix("ccmh-"), s["searched"].removeprefix("ccmh-")
            lines.append(f"| {q} → {t} | {s['n']} | {s['R@1']:.2f} | {s['R@5']:.2f} | "
                         f"{s['MRR']:.2f} |")
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=("estimate", "run", "pairs"))
    p.add_argument("--normalized-dir", type=Path, default=DEFAULT_NORMALIZED)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    p.add_argument("--pay", action="store_true", help="run: allow paid Voyage requests")
    p.add_argument("--show", type=int, default=2, help="pairs: sentences to print")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "pairs":
        mar = load_units(args.normalized_dir, WITNESSES[0])
        for i in pick_sentences(mar)[:args.show]:
            print(f"# {mar[i].chunk_id}\n{'original':>20}  {mar[i].text}")
            for kind, fn in VARIANTS.items():
                print(f"{kind:>20}  {fn(mar[i].text)}")
        return
    if args.command == "estimate":
        est = estimate(needed_texts(args.normalized_dir), cache_path(args.out_dir))
        print(json.dumps(est, indent=2))
        return
    if not args.pay:
        raise SystemExit("run sends paid Voyage requests: pass --pay (owner's approval first)")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(markdown(run(args.normalized_dir, args.out_dir)))


if __name__ == "__main__":
    main()
