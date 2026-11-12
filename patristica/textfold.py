"""
Orthographic folding for near-verbatim text matching.

``fold()`` maps a string to a canonical form so that the same words written
with different orthography compare equal: Greek with or without accents and
breathings, Hebrew with or without points, vocalized or unvocalized Syriac,
Coptic with or without supralinear strokes, the common Latin spelling
variants (u/v, i/j, ae/oe/e, medieval *michi*/*nichil*), and the letters
Church Slavonic witnesses and editions write differently (і/ꙇ/и, оу/ѹ/ꙋ/у,
ѡ/о, ꙑ/ъі/ы, ѥ/є/е, ꙗ/я/ѣ and ѣ/е by position, ѕ/ꙁ/з, ь/ъ and final
yers; see ``_CYRILLIC_LETTERS``), and Arabic with or without harakat, hamza
seats and tatweel, and with dotless or dotted final yāʾ (``_ARABIC_LETTERS``),
and Old Georgian in any of its three scripts and in old or modern spelling
(``_GEORGIAN_LETTERS``, ``_fold_georgian``), and the letters Old English,
Old Saxon and Old High German witnesses write differently (ð/đ/þ, ƀ/b,
ƿ/w, ȝ/g; ``_LATIN_LETTERS``), and the variant characters (異體字) of
Literary Chinese (``_CJK_VARIANTS``).

It is deliberately lossy and language-independent: the same function is
applied to indexed text and to queries, so neither side needs language
detection. Use it for lexical matching only, never for display.
"""

from __future__ import annotations

import re
import unicodedata

# Punctuation that sits *inside* a word and is deleted rather than turned into
# a word break: Armenian emphasis/exclamation/question marks, the Coptic
# morphological divider, and the grave accent some Coptic editions use as a
# word-internal mark.
_IN_WORD_MARKS = dict.fromkeys(map(ord, "՛՜՞⳿`"), None)

# Latin letter-level variants, applied after lowercasing.
#
# Old English, Old Saxon and Old High German (#563) are written in Latin
# letters, and their witnesses and editions write some sounds with different
# letters (measured on Thorpe's Catholic Homilies I and ReA 1.2's Heliand and
# Tatian):
# - ð, þ and đ (crossed d) are one sound: Thorpe writes þæt/ðæt, þurh/ðurh
#   in one edition, the Heliand quað/quađ, uuirðid/uuirđid, dôðe/dôđe. They
#   fold to þ. Not to "th", the older spelling of the same sound: that would
#   make Old English þe/þis and transliterated Gothic þan/þus match English
#   the/this/than/thus.
# - ƀ (barred b) is b: the Heliand writes haƀda/habda, gilôƀon/gilobon.
# - ƿ (wynn) is w and ȝ/ᵹ/ʒ (yogh, insular g, ezh) are g, as the editions
#   print what manuscripts and diplomatic texts write.
# uu is not folded onto w: every OHG and Old Saxon source writes uu
# (uuort, uuas), and folding it would make Latin uua/uus and the OHG uuas
# match English wa/ws/was.
_LATIN_LETTERS = str.maketrans({
    "j": "i", "v": "u", "æ": "e", "œ": "e",
    "ð": "þ", "đ": "þ", "ƀ": "b", "ƿ": "w", "ȝ": "g", "ᵹ": "g", "ʒ": "g",
})
_LATIN_DIGRAPHS = re.compile(r"ae|oe")

# Latin word-level variants (medieval spellings → classical).
_LATIN_WORDS = {"michi": "mihi", "nichil": "nihil"}

# Arabic letter variants (#83), applied after NFKD (which already turns the
# presentation forms into base letters and أ/إ/آ into ا plus a dropped mark).
# Tatweel only stretches a word; alif waṣla is an alif; Egyptian printing
# and many Christian Arabic editions write final yāʾ undotted (الذى = الذي);
# OCR gives the Persian yeh and keheh for yāʾ and kāf. ة/ه is not folded:
# كتابة (writing) and كتابه (his book) are different words.
_ARABIC_LETTERS = str.maketrans({
    "\u0640": None,  # tatweel
    "ٱ": "ا", "ى": "ي", "ی": "ي", "ک": "ك",
})

# Old Georgian (#222, #511). The stored text keeps its spelling; these rules
# only let old and modern spellings match each other.
#
# Scripts: Asomtavruli and Nuskhuri (the Khutsuri scripts) are the same
# alphabet as Mkhedruli, letter for letter, so any text in them matches the
# Mkhedruli the sources store: casefold turns Asomtavruli into Nuskhuri and
# Mtavruli into Mkhedruli, and Nuskhuri becomes Mkhedruli here (the letters'
# Unicode names differ only by "SMALL"). Khutsuri writes u as the digraph
# ႭჃ/ⴍⴣ, so ოჳ is უ (before the ჳ rule below, so the digraph isn't read as
# ო + ვი; ოუ itself is common and kept: მოუწოდა).
#
# Archaic letters, as modern spelling writes them (measured on the TITUS
# Adishi and pre-Athonite Gospels and Wikisource's Shushanik and Conversion
# of Kartli):
# - ჱ → ე (ძჱ/ძე, ქრისტჱ/ქრისტე, alternating even within one manuscript);
# - ჴ → ხ (ჴელი → ხელი; the witnesses write გულისჴმა/გულისხმა);
# - ჳ → ვ before a vowel (ტყჳე → ტყვე, ჰრქჳან → ჰრქვან), else ვი (თჳსი →
#   თვისი, ღჳნო → ღვინო, სიტყჳსა → სიტყვისა); a witness's უ for ჳ before a
#   vowel (ტყუე) meets it through the უ rule, before a consonant (თუსი)
#   it doesn't;
# - ჲ → ი before a vowel (ესაჲა → ესაია), else dropped (სიტყუაჲ → სიტყუა,
#   რაჲთა → რათა, გალილეაჲსა → გალილეასა). This merges case forms
#   (დედაჲ/დედა, -ისაჲ/-ისა) and a few words (დაჲ "sister"/და "and"), as
#   modern spelling does.
# - უ → ვ between a consonant and ა, ე or ო: Old Georgian writes the
#   consonant v there as უ (ქუეყანა → ქვეყანა, სიტყუა → სიტყვა, თქუენ →
#   თქვენ, დავარღუო → დავარღვო). Not before ი, where უ is mostly the vowel
#   (სიცრუისა), not word-initially (უყო "he did to him" ≠ ვყო "I did"), and
#   not after a vowel (მოუწოდა, დაუდვა). Known merge: შუა "middle" with შვა
#   "begat".
# ჵ (rare) is kept.
_GEORGIAN_ARCHAIC = {ord("ჱ"): "ე", ord("ჴ"): "ხ"}
_GEORGIAN_LETTERS = {
    cp: unicodedata.lookup(unicodedata.name(chr(cp)).replace("SMALL ", "")).translate(
        _GEORGIAN_ARCHAIC
    )
    for cp in range(0x2D00, 0x2D2E)
    if unicodedata.name(chr(cp), "").startswith("GEORGIAN SMALL LETTER")
} | _GEORGIAN_ARCHAIC
_GEORGIAN_DIGRAPH = "ოჳ"
_GEORGIAN_VOWELS = "აეიოუ"
_GEORGIAN_CONSONANTS = "ბგდვზთკლმნპჟრსტფქღყშჩცძწჭხჯჰჶ"
_GEORGIAN_U_VOWELS = "აეო"  # the vowels after which a consonant's უ is v
_GEORGIAN_WE_RE = re.compile(f"ჳ(?=[{_GEORGIAN_VOWELS}])")
_GEORGIAN_HIE_RE = re.compile(f"ჲ(?=[{_GEORGIAN_VOWELS}])")
_GEORGIAN_U_RE = re.compile(f"(?<=[{_GEORGIAN_CONSONANTS}])უ(?=[{_GEORGIAN_U_VOWELS}])")


def _fold_georgian(t: str) -> str:
    """The Old Georgian rules above, on text already folded letter by letter."""
    t = t.replace(_GEORGIAN_DIGRAPH, "უ")
    t = _GEORGIAN_WE_RE.sub("ვ", t).replace("ჳ", "ვი")
    t = _GEORGIAN_HIE_RE.sub("ი", t).replace("ჲ", "")
    return _GEORGIAN_U_RE.sub("ვ", t)


def _fold_georgian_spans(items: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """``_fold_georgian`` on characters with their source spans (after the digraph)."""
    def following(k: int) -> str:
        return items[k + 1][0] if k + 1 < len(items) else ""

    out: list[tuple[str, int, int]] = []
    for k, (c, start, end) in enumerate(items):  # ჳ
        if c == "ჳ":
            if following(k) and following(k) in _GEORGIAN_VOWELS:
                out.append(("ვ", start, end))
            else:
                out += [("ვ", start, end), ("ი", start, end)]
        else:
            out.append((c, start, end))
    items, out = out, []
    for k, (c, start, end) in enumerate(items):  # ჲ
        if c == "ჲ":
            if following(k) and following(k) in _GEORGIAN_VOWELS:
                out.append(("ი", start, end))
        else:
            out.append((c, start, end))
    items, out = out, []
    for k, (c, start, end) in enumerate(items):  # უ between a consonant and a vowel
        if (c == "უ" and k and items[k - 1][0] in _GEORGIAN_CONSONANTS
                and following(k) and following(k) in _GEORGIAN_U_VOWELS):
            c = "ვ"
        out.append((c, start, end))
    return out


# Church Slavonic (#330). Superscript letters (Cyrillic Extended-A/B
# combining letters) are letters of the word written above the line, so they
# become their base letter instead of being dropped as marks: хрⷭ҇тъ → хрстъ.
_CYRILLIC_COMBINING_LETTERS = {
    0x2DE0: "б", 0x2DE1: "в", 0x2DE2: "г", 0x2DE3: "д", 0x2DE4: "ж", 0x2DE5: "з",
    0x2DE6: "к", 0x2DE7: "л", 0x2DE8: "м", 0x2DE9: "н", 0x2DEA: "о", 0x2DEB: "п",
    0x2DEC: "р", 0x2DED: "с", 0x2DEE: "т", 0x2DEF: "х", 0x2DF0: "ц", 0x2DF1: "ч",
    0x2DF2: "ш", 0x2DF3: "щ", 0x2DF4: "ѳ", 0x2DF5: "ст", 0x2DF6: "а", 0x2DF7: "е",
    0x2DF8: "ꙉ", 0x2DF9: "ꙋ", 0x2DFA: "ѣ", 0x2DFB: "ю", 0x2DFC: "ꙗ", 0x2DFD: "ѧ",
    0x2DFE: "ѫ", 0x2DFF: "ѭ",
    0xA674: "є", 0xA675: "і", 0xA676: "ї", 0xA677: "у", 0xA678: "ъ", 0xA679: "ы",
    0xA67A: "ь", 0xA67B: "ѡ", 0xA69E: "ф", 0xA69F: "ѥ",
}

# Cyrillic letter variants, applied after lowercasing: what the OCS witnesses
# and their editions (TOROT, CCMH, Glagolitic transliterations) write
# differently for one sound. Cyrillic manuscripts write iotation of е, а and
# the nasals inconsistently (ꙓ is iotated, so it is я); ѕ/ꙁ/з vary by
# manuscript; ѵ, ѳ, ѯ, ѱ spell Greek loans. ѣ is folded by position below.
_CYRILLIC_LETTERS = str.maketrans({
    # ї is NFKD-decomposed (і + diaeresis) in the text, but the superscript
    # ꙶ (U+A676) becomes ї only after NFKD, so ї is folded here as well.
    "і": "и", "ї": "и", "ꙇ": "и", "ѵ": "и",
    "ѡ": "о", "ѻ": "о", "ѽ": "о", "ꙍ": "о", "ꙩ": "о", "ꙫ": "о", "ꙭ": "о", "ꙮ": "о",
    "ꚙ": "о", "ѿ": "от",
    "ѹ": "у", "ꙋ": "у",
    "ѥ": "е", "є": "е",
    "ꙗ": "я", "ꙓ": "я",
    "ꙑ": "ы",
    "ѕ": "з", "ꙁ": "з", "ꙃ": "з", "ꙅ": "з",
    "ꙙ": "ѧ", "ѩ": "ѧ", "ꙝ": "ѧ", "ѭ": "ѫ",
    "ѳ": "ф", "ѯ": "кс", "ѱ": "пс",
})
# Digraphs, after the letters: оу is one letter (u), ъі/ъи spell ꙑ.
_CYRILLIC_DIGRAPHS = {"оу": "у", "ъи": "ы"}
_CYRILLIC_DIGRAPH_RE = re.compile("|".join(_CYRILLIC_DIGRAPHS))
# Yers, after the digraphs: the front yer ь (and the neutral ꙏ) becomes ъ,
# since witnesses confuse the two; the paerok (ꙿ, ⸯ), which marks an omitted
# yer, is left out. Word-final yers are then left out too (written in OCS,
# not in modern spelling: богъ = бог); word-internal ones are kept.
_CYRILLIC_YERS = {ord("ь"): "ъ", ord("ꙏ"): "ъ"}
_CYRILLIC_FINAL_YERS_RE = re.compile("ъ+(?= |$)")
# Glagolitic has one letter, Ⱑ, for ja (at the start of a word and after a
# vowel) and ě (after a consonant), and its Cyrillic transliterations write ѣ
# for both. So ѣ at a word start or after a vowel folds to я (ѣко = ꙗко =
# яко), and after anything else to е (тѣло = тело). The vowels are those left
# after the other Cyrillic folds (ѹ/оу → у, ꙑ → ы, і → и, ѥ → е, …); ѣ itself
# counts, since it has just become я or е. A yer is a vowel too, and so is
# the paerok that stands for one: the Glagolitic witnesses write братрьѣ,
# марьѣ where Cyrillic ones write братрьꙗ, марьꙗ. So ѣ is folded before the
# paerok is left out.
_CYRILLIC_VOWELS = "аеиоуыюяѣѧѫъꙿⸯ"
_CYRILLIC_YAT_JA_RE = re.compile(f"(?:^|(?<=[ {_CYRILLIC_VOWELS}]))ѣ")
_CYRILLIC_PAEROK = dict.fromkeys(map(ord, "ꙿⸯ"), None)


#: CJK ideographs, as a regex character class body (#648): the radicals, 々 〇
#: and the Hangzhou numerals, the unified ideographs with every extension and
#: the compatibility ideographs. Private-use characters (unencoded ideographs
#: in some sources) are not included: other scripts' sources use them too.
IDEOGRAPHS = ("\u2e80-\u2fdf\u3005\u3007\u3021-\u3029\u3038-\u303b"
              "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0003ffff")
IDEOGRAPH_RE = re.compile(f"[{IDEOGRAPHS}]")

# Literary Chinese variant characters (異體字, #648). The sources keep their
# own characters: zh.wikisource's diplomatic transcriptions write the forms
# of the stone and the manuscripts (㬌 for 景, 夲 for 本, 礼 for 禮), the
# Taishō (CBETA) its own. Each variant here folds to the traditional standard
# form (Taiwan's 教育部 standard where the two traditional forms differ: 眾,
# 啟, 跡), so a quote typed in either matches and the editions align by text.
# The table comes from comparing zh.wikisource with CBETA T2142 (序聽迷詩所經),
# T2143 (the hymn 景教三威蒙度讚 and 尊經) and T2144 (the Xi'an stele), plus
# the "normalized form" CBETA's gaiji declarations give for the characters
# those files use. It is not a simplified → traditional conversion: only
# variants the sources write are here (无 与 国 礼 among them, which are
# also simplified forms). Left out on purpose, since they are words of their
# own: 閒 (間 and 閑), 疋 (匹), 豊 (豐 and 禮's 豊), 祆/祅, and the readings
# where the editions differ (開/關, 元/無, 純/絕, 日/曰, 厏/萬).
_CJK_VARIANTS = str.maketrans({
    "㬌": "景", "衆": "眾", "髙": "高", "㓛": "功", "虗": "虛", "惣": "總", "夲": "本",
    "逺": "遠", "㝎": "定", "啓": "啟", "𦀰": "經", "亰": "京", "𠃵": "乾", "嵗": "歲",
    "䫟": "願", "无": "無", "皷": "鼓", "隟": "隙", "𥪰": "競", "𢫾": "指", "浄": "淨",
    "抅": "拘", "徳": "德", "賔": "賓", "䰟": "魂", "冨": "富", "絶": "絕", "劒": "劍",
    "羣": "群", "俻": "備", "飰": "飯", "㩲": "權", "乗": "乘", "熈": "熙", "宻": "密",
    "礼": "禮", "国": "國", "躭": "耽", "蹔": "暫", "与": "與", "迹": "跡", "𦀸": "浣",
    # CBETA's gaiji, by their normalized form.
    "㗛": "笑", "𬽐": "喪", "𮊵": "羸", "\U00023ACD": "歛", "\U0002DCAB": "灟",
    "\U0002E785": "延",
})


def _is_dropped_mark(ch: str) -> bool:
    # Mn/Me: combining accents, breathings, points, vowel marks, overlines.
    # Cf: zero-width joiners, bidi controls and similar format characters.
    return unicodedata.category(ch) in ("Mn", "Me", "Cf")


def _is_separator(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in ("P", "S", "Z") or ch.isspace()


def fold(text: str) -> str:
    """Return the folded form of *text*: lowercase, unmarked, single-spaced words."""
    t = unicodedata.normalize("NFKD", text).translate(_IN_WORD_MARKS)
    t = t.translate(_CYRILLIC_COMBINING_LETTERS)
    t = "".join(ch for ch in t if not _is_dropped_mark(ch))
    t = t.casefold()  # also maps final sigma (ς) and long s (ſ) to σ / s
    t = "".join(" " if _is_separator(ch) else ch for ch in t)
    t = t.translate(_CJK_VARIANTS)
    t = _LATIN_DIGRAPHS.sub("e", t.translate(_LATIN_LETTERS).translate(_ARABIC_LETTERS))
    t = _fold_georgian(t.translate(_GEORGIAN_LETTERS))
    t = _CYRILLIC_DIGRAPH_RE.sub(
        lambda m: _CYRILLIC_DIGRAPHS[m.group()], t.translate(_CYRILLIC_LETTERS)
    ).translate(_CYRILLIC_YERS)
    t = _CYRILLIC_YAT_JA_RE.sub("я", t).replace("ѣ", "е").translate(_CYRILLIC_PAEROK)
    t = _CYRILLIC_FINAL_YERS_RE.sub("", t)
    return " ".join(_LATIN_WORDS.get(w, w) for w in t.split())


def fold_spans(text: str) -> tuple[str, list[int], list[int]]:
    """``fold(text)``, with the span of *text* each folded character came from.

    Returns ``(folded, starts, ends)``: ``folded[k]`` comes from
    ``text[starts[k]:ends[k]]``. It applies the steps of ``fold`` one
    character at a time, so a match found in the folded text can be shown in
    the original (search highlighting, #143). A space between words spans
    the gap between them, and a replaced word (*michi*) spans the whole word.
    """
    chars: list[tuple[str, int, int]] = []
    for i, ch in enumerate(text):
        nfkd = unicodedata.normalize("NFKD", ch).translate(_IN_WORD_MARKS)
        for d in nfkd.translate(_CYRILLIC_COMBINING_LETTERS):
            if _is_dropped_mark(d):
                continue
            for c in d.casefold():
                if _is_separator(c):
                    chars.append((" ", i, i + 1))
                    continue
                # A Cyrillic letter may become two (ѿ → от).
                c = c.translate(_CJK_VARIANTS)
                c = c.translate(_LATIN_LETTERS).translate(_ARABIC_LETTERS)
                c = c.translate(_GEORGIAN_LETTERS)
                for e in c.translate(_CYRILLIC_LETTERS):
                    chars.append((e, i, i + 1))
    # The digraphs ae/oe, ოჳ and оу/ъи, left to right and not overlapping, as
    # the regexes do (they can't overlap each other: different letters).
    merged: list[tuple[str, int, int]] = []
    k = 0
    while k < len(chars):
        c, start, end = chars[k]
        pair = c + chars[k + 1][0] if k + 1 < len(chars) else ""
        if pair in ("ae", "oe"):
            merged.append(("e", start, chars[k + 1][2]))
            k += 2
        elif pair == _GEORGIAN_DIGRAPH:
            merged.append(("უ", start, chars[k + 1][2]))
            k += 2
        elif pair in _CYRILLIC_DIGRAPHS:
            merged.append((_CYRILLIC_DIGRAPHS[pair], start, chars[k + 1][2]))
            k += 2
        else:
            merged.append((c, start, end))
            k += 1
    merged = _fold_georgian_spans(merged)
    # ь → ъ; ѣ by the folded character before it (a paerok counts); then the
    # paerok is left out.
    cyrillic: list[tuple[str, int, int]] = []
    before = " "
    for c, start, end in merged:
        c = c.translate(_CYRILLIC_YERS)
        if c == "ѣ":
            c = "я" if before in " " + _CYRILLIC_VOWELS else "е"
        before = c
        if c.translate(_CYRILLIC_PAEROK):
            cyrillic.append((c, start, end))
    # Word-final yers: a ъ followed only by ъ up to a space or the end.
    merged = []
    at_end = True
    for item in reversed(cyrillic):
        if item[0] == " ":
            at_end = True
        elif item[0] == "ъ" and at_end:
            continue
        else:
            at_end = False
        merged.append(item)
    merged.reverse()
    words: list[list[tuple[str, int, int]]] = []
    current: list[tuple[str, int, int]] = []
    for item in merged:
        if item[0].isspace():
            if current:
                words.append(current)
                current = []
        else:
            current.append(item)
    if current:
        words.append(current)
    folded: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for n, word in enumerate(words):
        if n:
            folded.append(" ")
            starts.append(ends[-1])
            ends.append(word[0][1])
        spelled = "".join(c for c, _, _ in word)
        if spelled in _LATIN_WORDS:
            word = [(c, word[0][1], word[-1][2]) for c in _LATIN_WORDS[spelled]]
        for c, start, end in word:
            folded.append(c)
            starts.append(start)
            ends.append(end)
    return "".join(folded), starts, ends


def squash(text: str) -> str:
    """Return ``fold(text)`` without spaces, for word-boundary-insensitive containment.

    Coptic editions disagree on word division (bound groups vs. morphemes), so
    "does chunk X contain quote Q?" is checked on squashed strings.
    """
    return fold(text).replace(" ", "")
