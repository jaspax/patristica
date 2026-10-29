"""
Ingestor for Codex Suprasliensis from the Corpus Cyrillo-Methodianum
Helsingiense (CCMH), one work per text (#333, #29).

Codex Suprasliensis is an 11th-century Cyrillic menaion for March: lives of
the saints of the month and homilies for Holy Week and Easter, translated from
Greek in the late 9th–10th century. It survives in three parts (Ljubljana,
St Petersburg, Warsaw), which CCMH numbers 1–3.

Text: CCMH's ``suprasliensis.txt`` (Severjanov 1904, some places checked
against the BAN facsimile), CC BY 4.0
(https://www.kielipankki.fi/download/ccmh-src/www/suprasliensis.html). Every
line is ``PFFFSLL text``: part, folio, side (1 recto, 2 verso), line. The file
runs in text order: part 1's misbound folio 38 follows folio 88, where its text
belongs. The text is a 7-bit ASCII transliteration, converted to Cyrillic here
(``_LETTERS`` and ``ccmh_to_cyrillic``).

Text boundaries: CCMH has none. They come from TOROT's ``supr.xml`` (the
Syntacticus treebank release, pinned commit ``_TOROT_COMMIT``, itself from
suprasliensis.obdurodon.org): every TOROT token carries its part, folio and
line, so the first token of each TOROT text division gives the line where the
text starts. Only those positions (facts about the manuscript) are taken from
TOROT, never its text, which is CC BY-NC-SA: the published text stays CCMH's
CC BY. TOROT splits the Life of Pionius in two divisions (7123 and 7163);
they are one text here. ``_check_split`` compares every work's words with its
TOROT division and logs at ERROR when they don't match.

Units: one unit per manuscript page, ref ``Supr.{part}.{folio}{side}``
(``Supr.1.12r``); a page shared by two texts is a unit in each. A word
hyphenated across a line or page belongs to the line it starts on. The
manuscript's own headings (``мѣсѧца марта …``) are text. Marginalia (CCMH
sets them after a run of tabs) are marked as editorial notes. Where leaves are
lost at a text's start or end, the unit carries a lacuna marker ``[…]`` marked
as a ``lacuna`` span (#236).

Metadata per text (title, author, genre, BHG/CPG, feast day) is curated in
``scripts/ingest/data/supr_texts.csv``.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from lxml import etree

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._slavonic import glagolitic_to_cyrillic

log = logging.getLogger(__name__)

SOURCE_ID = "ccmh-supr"

CCMH_URL = "https://www.kielipankki.fi/download/ccmh-src/www/suprasliensis.txt"
CCMH_PAGE = "https://www.kielipankki.fi/download/ccmh-src/www/suprasliensis.html"
_TOROT_COMMIT = "525cee4fb40590d7d514376c11acaed1bdd91c15"
TOROT_URL = (
    "https://raw.githubusercontent.com/syntacticus/syntacticus-treebank-data/"
    f"{_TOROT_COMMIT}/torot/supr.xml"
)
_INDEX_CSV = Path(__file__).parent / "data" / "supr_texts.csv"

_EDITION = (
    "Codex Suprasliensis, ed. S. Severjanov (1904), CCMH transliteration "
    "(Corpus Cyrillo-Methodianum Helsingiense, Kielipankki), converted to "
    "Cyrillic; text boundaries from the TOROT/obdurodon text divisions "
    "(Syntacticus treebank data, commit 525cee4)"
)

# Translation of the Greek: late 9th to 10th century (the manuscript is 11th c.).
_DATE_RANGE = (885, 1000)

LACUNA = "[…]"

# ---------------------------------------------------------------------------
# CCMH transliteration → Cyrillic
# ---------------------------------------------------------------------------

# CCMH's table for this codex (the page above). Two-letter sequences first.
_DIGRAPHS: dict[str, str] = {
    "ju": "ю",
    "ja": "ꙗ",  # ja (a ligature or az with a stroke)
    "je": "ѥ",
    "jE": "ѩ",  # iotated small yus
    "jO": "ѭ",  # iotated big yus
}
_LETTERS: dict[str, str] = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е",
    "Z": "ж", "D": "ѕ", "z": "з",
    "i": "и",  # izhe (octal: 8)
    "I": "і",  # i (decimal: 10)
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "r": "р",
    "s": "с", "t": "т",
    "u": "оу",  # u as a digraph
    "U": "ꙋ",   # uk as one letter
    "f": "ф", "x": "х", "w": "ѡ", "q": "щ", "c": "ц", "C": "ч", "S": "ш",
    "&": "ъ", "$": "ь",
    "y": "ы",   # jery (= &I)
    "@": "ѣ",
    "E": "ѧ", "O": "ѫ",
    "X": "ѯ", "P": "ѱ", "T": "ѳ", "Y": "ѵ",
    "j": "ꙗ",  # a bare j (twice in the file) is read as ja
    "G": "г",  # once (moGOStu), a typo
    "2": "ѣ",  # v2ky (once): the shifted key of @
}

# Letters written above the line → combining Cyrillic letters.
_SUPERSCRIPT: dict[str, str] = {
    "б": "ⷠ", "в": "ⷡ", "г": "ⷢ", "д": "ⷣ", "ж": "ⷤ",
    "з": "ⷥ", "к": "ⷦ", "л": "ⷧ", "м": "ⷨ", "н": "ⷩ",
    "о": "ⷪ", "п": "ⷫ", "р": "ⷬ", "с": "ⷭ", "т": "ⷮ",
    "х": "ⷯ", "ц": "ⷰ", "ч": "ⷱ", "ш": "ⷲ", "щ": "ⷳ",
    "ф": "ⷴ", "а": "ⷶ", "е": "ⷷ", "оу": "ⷹ", "ѣ": "ⷺ",
    "ю": "ⷻ", "ꙗ": "ⷼ", "ѧ": "ⷽ", "ѫ": "ⷾ", "ѭ": "ⷿ",
    "и": "ꙵ", "і": "ꙶ", "ъ": "ꙸ", "ы": "ꙹ", "ь": "ꙺ",
}

_TITLO = "҃"
_PALATAL = "҄"  # palatal arc on the preceding consonant
_KAMORA = "̑"   # circumflex (kamora) above the next vowel
_DASIA = "҅"    # spiritus asper
_PSILI = "҆"    # spiritus lenis
_TREMA = "̈"
_PAEROK = "ꙿ"

_PREFIX_MARKS = {"(": _DASIA, ")": _PSILI, '"': _TREMA}
_CONSONANTS = set("bvgdZDzklmnprstfxqcCSG")


def _convert_word(word: str) -> str:
    """One space-free CCMH token → Cyrillic."""
    out: list[str] = []
    # A word written wholly above the line (every letter after "!", e.g.
    # "!p!a!C!e") is an interlinear insertion: its letters are written plainly.
    letters = re.findall(r"j[uaeEO]|[A-Za-z@&$2]", word)
    raised = re.findall(r"!(?:[()\"^']*)(?:j[uaeEO]|[A-Za-z@&$2])", word)
    if len(letters) >= 2 and len(raised) == len(letters):
        word = word.replace("!", "")
    titlo = False
    capital = False
    superscript = False
    marks: list[str] = []
    base_letters = 0
    i = 0
    while i < len(word):
        ch = word[i]
        if ch == "!":
            if base_letters == 0 and not superscript:
                titlo = True
            else:
                superscript = True
            i += 1
            continue
        if ch == "*":
            capital = True
            i += 1
            continue
        if ch in _PREFIX_MARKS:
            marks.append(_PREFIX_MARKS[ch])
            i += 1
            continue
        if ch == "^":
            if i > 0 and word[i - 1] in _CONSONANTS and out:
                out.append(_PALATAL)
            else:
                marks.append(_KAMORA)
            i += 1
            continue
        if ch == "'":
            out.append(_PAEROK)
            superscript = False
            i += 1
            continue
        pair = word[i : i + 2]
        if pair in _DIGRAPHS:
            cyr = _DIGRAPHS[pair]
            i += 2
        elif ch in _LETTERS:
            cyr = _LETTERS[ch]
            i += 1
        else:
            # Punctuation and anything else passes through; a pending "!" or
            # mark before it is dropped.
            if ch not in "´":
                out.append(ch)
            superscript = False
            marks = []
            i += 1
            continue
        if superscript and base_letters > 0:
            out.append(_SUPERSCRIPT.get(cyr, cyr))
        else:
            if capital:
                cyr = cyr[0].upper() + cyr[1:]
            out.append(cyr)
            base_letters += 1
        out.extend(marks)
        marks = []
        capital = False
        superscript = False
    text = "".join(out)
    if titlo:
        text = _place_titlo(text)
    return text


def _place_titlo(word: str) -> str:
    """A titlo over the whole word, written after its second letter (its first
    in a word of one or two letters): ``бг҃ъ``, ``х҃с``."""
    positions = [k for k, c in enumerate(word) if unicodedata.category(c).startswith("L")]
    if not positions:
        return word
    nth = positions[1] if len(positions) >= 3 else positions[0]
    end = nth + 1
    while end < len(word) and unicodedata.category(word[end]) == "Mn":
        end += 1
    return word[:end] + _TITLO + word[end:]


def ccmh_to_cyrillic(text: str) -> str:
    """A run of CCMH transliteration (words and punctuation) → Cyrillic (NFC)."""
    text = _prepare(text)
    words = [_convert_word(w) for w in text.split()]
    out = " ".join(w for w in words if w)
    return unicodedata.normalize("NFC", glagolitic_to_cyrillic(out))


# ---------------------------------------------------------------------------
# CCMH lines → a word stream
# ---------------------------------------------------------------------------

# Marginal notes. CCMH writes text that stands in the margin after a run of
# tabs on the lines beside it; other tab runs are gaps inside a line (a hole or
# a space the scribe left), whose text is ordinary text. The notes, keyed by
# the line they start beside: (the lines whose text after the tabs is the
# note, the note in CCMH transliteration, whole). Checked against TOROT, which
# leaves them out of the text.
_MARGINAL_NOTES: dict[str, tuple[tuple[str, ...], str]] = {
    # "as with one mouth they said": a correction to be read into the text
    "1090102": (("1090102", "1090103"), "jako (edn@mi usty r@SE :"),
    # the scribe Retko's note, written down the margin of fol. 104r
    "1104118": (
        tuple(f"11041{n:02d}" for n in range(18, 30)),
        '!gi pomIlu"I ret&ka amIn',
    ),
    "3002104": (("3002104", "3002105"), "v$s@x&"),  # "all": a correction
    # "on the fig tree, the adulteress and her deceitful speech"
    "3041219": (
        ("3041216", "3041219", "3041220"),
        "(o smok'vi (i (o Zen@ ljubod@(ici . (i (o bes@d@ (je)jE l)$st)$n@ . : .",
    ),
    "3042108": (("3042108",), 'o zmi"I'),  # "on the serpent"
}
_NOTE_LINES = {key: first for first, (keys, _) in _MARGINAL_NOTES.items() for key in keys}


@dataclass
class Word:
    """One word of the CCMH text, on the line it starts on."""

    line: str      # PFFFSLL
    ascii: str     # CCMH transliteration
    cyrillic: str = ""
    note: bool = False  # a marginal note (one Word holding the whole note)


def _prepare(text: str) -> str:
    """Punctuation runs → single marks, ornaments dropped, word-internal
    hyphens joined."""
    text = re.sub(r"\.\s*:\s*\.", " ⁘ ", text)  # four dots in a diamond
    text = text.replace(":.", " ⁖ ")
    text = re.sub(r"(?<=\S)-(?=\S)", "", text)
    return " ".join(w for w in text.split() if not w.isdigit())


# Line numbers with a side digit 3 for 2 (each between lines of the verso).
_LINE_FIXES = {
    "3014301": "3014201",
    "3030302": "3030202",
    "3059319": "3059219",
    "3059320": "3059220",
}


def parse_ccmh(path: Path) -> list[Word]:
    """CCMH's file → its words in text order, each marginal note as one word
    after the last word of the line it starts beside."""
    words: list[Word] = []
    carry: Word | None = None  # a word hyphenated at the end of the last line
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        key, _, body = raw.partition(" ")
        key = _LINE_FIXES.get(key, key)
        if not re.fullmatch(r"[123]\d{3}[12]\d{2}", key):
            raise ValueError(f"unexpected CCMH line number {key!r}")
        if key in _NOTE_LINES:
            body = re.split(r"\t+", body)[0]
        body = body.replace("\t", " ").rstrip()
        hyphen = body.endswith("-")
        tokens = _prepare(body[:-1] if hyphen else body).split()
        if carry is not None and tokens:
            carry.ascii += tokens.pop(0)
            carry = None
        line_words: list[Word] = []
        for t in tokens:
            if not re.search(r"[A-Za-z@&$]", t) and words and not words[-1].note:
                words[-1].ascii += t  # a stop belongs to the word before it
            else:
                line_words.append(Word(key, t))
                words.append(line_words[-1])
        if hyphen and line_words:
            carry = line_words[-1]
        if key in _MARGINAL_NOTES:
            words.append(Word(key, _MARGINAL_NOTES[key][1], note=True))
    for w in words:
        w.cyrillic = ccmh_to_cyrillic(w.ascii)
    return words


# ---------------------------------------------------------------------------
# Text boundaries from TOROT
# ---------------------------------------------------------------------------

def _fold_words(text: str) -> list[str]:
    from patristica.textfold import fold  # noqa: PLC0415 (only for matching)

    return [w for w in fold(text).split() if any(c.isalpha() for c in w)]


@dataclass
class Division:
    """A TOROT text division: its id, title, first line (when TOROT records
    it) and its words, folded."""

    div_id: str
    title: str
    first_line: str | None
    words: list[str]


def parse_torot(path: Path) -> list[Division]:
    divisions: list[Division] = []
    tree = etree.parse(str(path))
    for div in tree.iter("div"):
        first_line = None
        forms: list[str] = []
        for tok in div.iter("token"):
            form = tok.get("form")
            if not form:
                continue
            forms.append(glagolitic_to_cyrillic(form) + (tok.get("presentation-after") or " "))
            ids = tok.get("foreign-ids")
            if len(forms) == 1 and ids:
                d = dict(kv.split("=", 1) for kv in ids.split(",") if "=" in kv)
                folio = d["folio"]
                first_line = d["part"] + folio[:3] + ("1" if folio[3] == "r" else "2") + d["line"]
        # A stop with no space after it would join two words.
        text = re.sub(r"([.·⁘⁛:;])(?=\S)", r"\1 ", "".join(forms))
        divisions.append(Division(div.get("id"), div.findtext("title") or "", first_line,
                                  _fold_words(text)))
    return divisions


def _similar(a: str, b: str) -> bool:
    """Two folded words that are the same word: equal, one a prefix of the
    other, or (four letters or more) one letter apart (жрицем, жрцем)."""
    if a == b:
        return True
    if min(len(a), len(b)) < 3:
        return False
    if a.startswith(b) or b.startswith(a):
        return True
    if min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def _match_score(stream: list[str], pos: int, probe: list[str]) -> int:
    """How many of *probe*'s words follow in order in the stream from *pos*
    (a word may be missing or split on either side: TOROT writes ``к а`` for
    the numeral ``к҃а``)."""
    window = stream[pos : pos + len(probe) + 3]
    score = j = 0
    for word in probe:
        for k in range(j, min(j + 3, len(window))):
            if _similar(window[k], word):
                score += 1
                j = k + 1
                break
    return score


def find_starts(words: list[Word], divisions: list[Division]) -> list[int]:
    """The index in *words* where each division starts, in order. Searched
    near TOROT's first line where it records one, else after the previous
    start."""
    folded = ["" if w.note else ((_fold_words(w.cyrillic) or [""])[0]) for w in words]
    starts: list[int] = []
    low = 0
    for div in divisions:
        if div.first_line is not None:
            near = [i for i in range(low, len(words))
                    if words[i].line[:5] == div.first_line[:5]
                    and abs(int(words[i].line[5:]) - int(div.first_line[5:])) <= 2]
        else:
            near = list(range(low, len(words)))
        # TOROT may open a division with a title of its editors, which CCMH
        # lacks: skip as few of its first words as gives a match.
        start = None
        for skip in range(_MAX_SKIP + 1):
            probe = div.words[skip : skip + _PROBE]
            scored = [(_match_score(folded, i, probe), -i) for i in near
                      if _similar(folded[i], probe[0])]
            # Near TOROT's own line a weaker match will do (numerals, headings).
            if scored and max(scored)[0] >= (_PROBE - 5 if div.first_line else _PROBE - 3):
                start = -max(scored)[1]
                break
        if start is None:
            raise ValueError(f"TOROT division {div.div_id} ({div.title}) not found in CCMH")
        if skip:
            log.info("TOROT %s starts with %d words CCMH lacks (its editors' title?): %s",
                     div.div_id, skip, " ".join(div.words[:skip]))
        starts.append(start)
        low = start + 1
    return starts


_PROBE = 10
_MAX_SKIP = 20


# ---------------------------------------------------------------------------
# Lost leaves
# ---------------------------------------------------------------------------

# Leaves lost from the codex (Birnbaum's foliation map,
# https://suprasliensis.obdurodon.org/foliation.html), by the page they follow
# in CCMH's numbering (PFFFS). The first leaf is lost too (the codex begins in
# the Life of Paul and Juliana) and so is the end (in the Life of Aninas).
_LOST_AFTER = {"10182", "10782", "10842", "10862", "11182", "31502", "31512"}
_LOST_AT_START = True


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SuprText:
    """One text of the codex: a row of ``data/supr_texts.csv``."""

    divs: tuple[str, ...]  # TOROT division ids (Pionius is two)
    slug: str
    title: str
    author: str | None
    genre: str
    external_ids: tuple[str, ...]
    start_line: str | None  # CCMH line where the text starts, where TOROT has none


def load_texts(path: Path = _INDEX_CSV) -> list[SuprText]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    return [
        SuprText(tuple(r["divs"].split()), r["slug"], r["title"], r["author"] or None,
                 r["genre"], tuple(r["external_ids"].split()), r["start_line"] or None)
        for r in rows
    ]


def page_ref(line: str) -> str:
    """The unit ref of the page a CCMH line is on, in the codex's continuous
    foliation (part 2 follows part 1's 118 leaves, part 3 its 16):
    ``Supr.12r``, ``Supr.119r``."""
    folio = int(line[1:4]) + {"1": 0, "2": 118, "3": 134}[line[0]]
    return f"Supr.{folio}{'r' if line[4] == '1' else 'v'}"


def build_units(words: list[Word], lacuna_before: bool, lacuna_after: bool) -> list[dict]:
    """One work's words → raw paragraph records, one per page, with lacunae
    and marginal notes marked as editorial spans."""
    units: list[dict] = []
    current: dict | None = None
    page = None

    def add(token: str, kind: str | None = None) -> None:
        assert current is not None
        text = current["text"]
        glue = "" if not text or (kind is None and not re.search(r"\w", token[:1])) else " "
        start = len(text) + len(glue)
        current["text"] = text + glue + token
        if kind:
            current.setdefault("editorial", []).append([start, start + len(token), kind])

    for k, word in enumerate(words):
        if word.line[:5] != page:
            page = word.line[:5]
            current = {"ref": page_ref(word.line), "text": ""}
            units.append(current)
            if k == 0 and lacuna_before:
                add(LACUNA, "lacuna")
        add(word.cyrillic, "note" if word.note else None)
        nxt = words[k + 1].line[:5] if k + 1 < len(words) else None
        if page in _LOST_AFTER and nxt is not None and nxt != page:
            add(LACUNA, "lacuna")
    if lacuna_after and current is not None:
        add(LACUNA, "lacuna")
    return units


def split_texts(words: list[Word], divisions: list[Division],
                texts: list[SuprText]) -> list[tuple[SuprText, list[Word]]]:
    """The codex's words → one run of words per text."""
    by_id = {d.div_id: d for d in divisions}
    firsts = [by_id[t.divs[0]] for t in texts]
    starts = find_starts(words, firsts)
    for k, t in enumerate(texts):
        if t.start_line is not None:
            starts[k] = next(i for i, w in enumerate(words) if w.line == t.start_line)
    if starts != sorted(starts):
        raise ValueError("Suprasliensis texts out of order")
    ends = starts[1:] + [len(words)]
    out = [(t, words[s:e]) for t, s, e in zip(texts, starts, ends)]
    for t, run in out:
        _check_split(t, run, [by_id[d] for d in t.divs])
    return out


def _check_split(text: SuprText, run: list[Word], divs: list[Division]) -> float:
    """How much of the TOROT division's words this text has (and the
    reverse); logged at ERROR below 0.9, a split gone wrong."""
    from collections import Counter  # noqa: PLC0415

    ours = Counter(w for x in run if not x.note for w in _fold_words(x.cyrillic))
    theirs = Counter(w for d in divs for w in d.words)
    common = sum((ours & theirs).values())
    recall = common / max(sum(theirs.values()), 1)
    precision = common / max(sum(ours.values()), 1)
    level = logging.ERROR if min(recall, precision) < 0.9 else logging.INFO
    log.log(level, "%s: %d words, TOROT %s %d words, overlap %.3f / %.3f", text.slug,
            sum(ours.values()), "+".join(d.div_id for d in divs), sum(theirs.values()),
            recall, precision)
    return min(recall, precision)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download CCMH's Suprasliensis and TOROT's divisions; write one raw JSON
    file per text to ``output_dir/ccmh-supr/``."""
    texts = load_texts()
    out_dir = output_dir / SOURCE_ID
    paths = [out_dir / f"{t.slug}.json" for t in texts]
    if not force and all(p.exists() for p in paths):
        return [Work(**json.loads(p.read_text(encoding="utf-8"))["work"]) for p in paths]

    cache = output_dir / "_cache"
    ccmh = download_file(CCMH_URL, cache / "ccmh" / "suprasliensis.txt", force=force)
    torot = download_file(TOROT_URL, cache / "syntacticus" / _TOROT_COMMIT[:7] / "supr.xml",
                          etag_cache=False)
    words = parse_ccmh(ccmh)
    runs = split_texts(words, parse_torot(torot), texts)

    works: list[Work] = []
    last = len(runs) - 1
    for k, ((text, run), path) in enumerate(zip(runs, paths)):
        first_page = run[0].line[:5]
        before = (k == 0 and _LOST_AT_START) or (
            k > 0 and runs[k - 1][1][-1].line[:5] in _LOST_AFTER
            and runs[k - 1][1][-1].line[:5] != first_page)
        after = run[-1].line[:5] in _LOST_AFTER and (
            k == last or runs[k + 1][1][0].line[:5] != run[-1].line[:5])
        paragraphs = build_units(run, before, after)
        work = Work(
            work_id=f"{SOURCE_ID}/{text.slug}",
            source_id=SOURCE_ID,
            author=text.author,
            title=text.title,
            date_range=_DATE_RANGE,
            date_confidence="approximate",
            genre=text.genre,  # type: ignore[arg-type]
            language="chu",
            tradition="slavonic",
            license="cc-by-4.0",
            provenance_url=CCMH_PAGE,
            edition=f"{_EDITION}; {page_ref(run[0].line)[5:]}–{page_ref(run[-1].line)[5:]}",
            external_ids=list(text.external_ids),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": paragraphs},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)
    log.info("Codex Suprasliensis: %d texts, %d pages", len(works),
             sum(len({w.line[:5] for w in run}) for _, run in runs))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
