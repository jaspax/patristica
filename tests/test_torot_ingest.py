"""TOROT ingestor (#334): token joining, units and editorial spans."""

from pathlib import Path

import pytest
from patristica import editorial
from scripts.ingest import torot

_HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<proiel schema-version="2.1"><source id="{name}" language="chu">
<title>T</title><license>CC BY-NC-SA 4.0</license>
"""


def _tok(form: str, after: str | None = " ", before: str | None = None, cp: str | None = None) -> str:
    attrs = f'form="{form}"'
    if after is not None:
        attrs += f' presentation-after="{after}"'
    if before is not None:
        attrs += f' presentation-before="{before}"'
    if cp is not None:
        attrs += f' citation-part="{cp}"'
    return f"<token {attrs}/>"


def _xml(tmp_path: Path, name: str, divs: list[list[list[str]]], *, lic: str = "CC BY-NC-SA 4.0") -> Path:
    body = "".join(
        "<div><title>English title</title>"
        + "".join("<sentence>" + "".join(s) + '<token empty-token-sort="V"/></sentence>' for s in div)
        + "</div>"
        for div in divs)
    path = tmp_path / f"{name}.xml"
    path.write_text(_HEAD.format(name=name).replace("CC BY-NC-SA 4.0", lic)
                    + body + "</source></proiel>", encoding="utf-8")
    return path


def _marked(unit: dict) -> str:
    text, out, pos = unit["text"], "", 0
    for s, e, k in unit.get("editorial", []):
        out += text[pos:s] + "⟦" + k[0] + ":" + text[s:e] + "⟧"
        pos = e
    return out + text[pos:]


def test_psalter_verses_lacunae_and_supplements(tmp_path: Path) -> None:
    xml = _xml(tmp_path, "psal-sin", [[
        [_tok("Без", cp="2.0"), _tok("напьсаньѣ", ":- ", cp="2.0")],
        [_tok("Въскѫѭ", cp="2.1"), _tok("тъщет.нъімъ", ":-- ", cp="2.1")],
        [_tok("ашѩ", before="......", cp="2.2"), _tok("цр҃і", ": ", cp="2.2")],
        [_tok("оубо", ".", cp="2.3"), _tok("образомъ", "", cp="2.3"), _tok("ѣлъі", " ", cp="2.3"),
         _tok("оукл(о)ни", ".... ", cp="2.3"), _tok("cр҃це", "-.. ", cp="2.3")],
        [_tok("въдо[во]вѫ", ".) ", cp="﻿2.4")],
        [_tok("1850", cp="2.4"), _tok("года", ". ", cp="2.4")],
    ]])
    key, units = torot.parse("psal-sin", xml)
    assert key == "verses"
    got = {u["ref"]: _marked(u) for u in units}
    assert got == {
        "Ps.2.0": "Без напьсаньѣ:-",
        "Ps.2.1": "Въскѫѭ тъщет⟦l:.⟧нъімъ:--",
        "Ps.2.2": "⟦l:......⟧ашѩ цр҃і:",
        # a space after the stop, none inside the word, a Latin c made Cyrillic
        "Ps.2.3": "оубо. образомъѣлъі оукл⟦s:(о)⟧ни⟦l:....⟧ ср҃це-..",
        # the BOM in the citation part is dropped; a sentence with digits is a note
        "Ps.2.4": "въдо⟦n:[во]⟧вѫ.) ⟦n:1850 года.⟧",
    }
    for u in units:
        editorial.check(u["text"], u.get("editorial", []))
    assert editorial.strip(units[1]["text"], editorial.check(units[1]["text"], units[1]["editorial"])) \
        == "Въскѫѭ тъщет нъімъ:--"


def test_kiev_missal_rubrics_and_brackets(tmp_path: Path) -> None:
    xml = _xml(tmp_path, "kiev-mis", [[
        [_tok("ВЪ"), _tok("ДЬНЬ"), _tok("КЛꙆМЕНТА")],
        [_tok("Бъ҃"), _tok("живот[ѣ", "] ")],
        [_tok("тог]о"), _tok("ꙇ", " ... "), _tok("се", ": ")],
        [_tok("НАДЪ"), _tok("ОПЛАТМЬ")],
        [_tok("ПРѢФ[АЦИѢ")],
        [_tok("Д", " ...] ")],
        [_tok("Рованиѧ", ". ")],
    ]])
    key, units = torot.parse("kiev-mis", xml)
    assert key == "paragraphs"
    assert [(u["ref"], _marked(u)) for u in units] == [
        ("KievMis.1", "ВЪ ДЬНЬ КЛꙆМЕНТА"),
        ("KievMis.1.1", "Бъ҃ живот⟦s:[ѣ]⟧ тог⟦s:]⟧о ꙇ ⟦l:...⟧ се:"),
        ("KievMis.1.2", "НАДЪ ОПЛАТМЬ ПРѢФ⟦s:[⟧АЦИѢ Д ⟦l:...⟧⟦s:]⟧"),
        ("KievMis.1.3", "Рованиѧ."),
    ]
    rec = units[1]
    assert editorial.strip(rec["text"], editorial.check(rec["text"], rec["editorial"])) \
        == "Бъ҃ животѣ того ꙇ се:"


def test_prose_heading_is_the_first_sentence(tmp_path: Path) -> None:
    xml = _xml(tmp_path, "chrabr", [[
        [_tok("о"), _tok("писменехь"), _tok("Xрабъра", None)],
        [_tok("Прѣжде", ". ￼"), _tok("ѹбѡ", ". ")],
        [_tok("҃s", ". ")],
    ]])
    _, units = torot.parse("chrabr", xml)
    assert [(u["ref"], u["text"]) for u in units] == [
        ("Chrabr.1", "о писменехь Храбъра"),
        ("Chrabr.1.1", "Прѣжде. ѹбѡ. ҃ѕ."),
    ]


def test_licence_and_language_are_checked(tmp_path: Path) -> None:
    with pytest.raises(torot.TorotFormatError, match="licence"):
        torot.parse("euch", _xml(tmp_path, "euch", [[[_tok("мол")]]], lic="CC BY 4.0"))
    path = _xml(tmp_path, "euch", [[[_tok("мол")]]])
    path.write_text(path.read_text(encoding="utf-8").replace('language="chu"', 'language="orv"'),
                    encoding="utf-8")
    with pytest.raises(torot.TorotFormatError, match="language"):
        torot.parse("euch", path)


def test_works_metadata() -> None:
    for name in torot.WORKS:
        work = torot.make_work(name)
        assert work.language == "chu" and work.tradition == "slavonic"
        assert work.license == "cc-by-nc-sa-4.0"
        assert torot.COMMIT in (work.provenance_url or "")
    assert torot.make_work("psal-sin").work_id == "torot/ps"

