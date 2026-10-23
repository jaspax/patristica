"""The author index (#82): ``patristica/data/authors.csv``, ``author_strings.csv``
and ``patristica.authors``."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from patristica.authors import (
    AUTHORS_PATH,
    AuthorDate,
    AuthorIndexError,
    UnknownAuthorError,
    apply_author_date_range,
    apply_author_ids,
    author_index,
    build_index,
    load_authors,
    parse_author_date,
    resolve_author,
    work_author_date_range,
)
from patristica.models import Work
from patristica.period import AUTHOR_BORN_BEFORE
from patristica.textfold import fold
from scripts.normalize import normalize_all

WORKS_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "normalized" / "_works.jsonl"

HEADER = "author_id,name,aliases,birth,death,floruit,tradition,external_ids,pseudo_of,note\n"
STRINGS_HEADER = "source_string,author_ids,reason\n"


def _manifest_works() -> list[dict]:
    if not WORKS_MANIFEST.exists():
        pytest.skip("normalized corpus not present")
    return [
        json.loads(line)["work"]
        for line in WORKS_MANIFEST.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _index(tmp_path: Path, authors: str, strings: str = ""):
    a = tmp_path / "authors.csv"
    s = tmp_path / "author_strings.csv"
    a.write_text("# comment\n" + HEADER + authors, encoding="utf-8")
    s.write_text(STRINGS_HEADER + strings, encoding="utf-8")
    return build_index(a, s)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("354", AuthorDate(354, 354, "established")),
        ("c. 347", AuthorDate(347, 347, "approximate")),
        ("350?", AuthorDate(350, 350, "uncertain")),
        ("340/345", AuthorDate(340, 345, "established")),
        ("c. 296/298", AuthorDate(296, 298, "approximate")),
        ("850/1250?", AuthorDate(850, 1250, "uncertain")),
        ("c. -20", AuthorDate(-20, -20, "approximate")),
    ],
)
def test_parse_author_date(value: str, expected: AuthorDate) -> None:
    assert parse_author_date(value) == expected


def test_parse_author_date_empty_and_bad() -> None:
    assert parse_author_date("") is None
    for bad in ("fl. 380", "380-395", "395/380", "c.380"):
        with pytest.raises(AuthorIndexError):
            parse_author_date(bad)


# ---------------------------------------------------------------------------
# Loading and resolving (synthetic index)
# ---------------------------------------------------------------------------

AUTHORS = (
    "augustine-of-hippo,Augustine of Hippo,Augustinus|Aurelius Augustinus,354,430,,latin,,,\n"
    "jerome,Jerome,\"Hieronymus|Jerome, Saint\",c. 347,420,,latin,stoa0162,,\n"
    "pseudo-augustine,Pseudo-Augustine,Pseudo-Augustinus,,,,latin,,augustine-of-hippo,\n"
    "late-author,Late Author,,1030?,1090,,greek,,,\n"
    "known-late,Known Late,,1040,1100,,greek,,,\n"
    "flourished,Flourished Early,,,,c. 500/520,greek,,,\n"
    "flourished-late,Flourished Late,,,,1020/1060,greek,,,\n"
)


@pytest.fixture()
def index(tmp_path: Path):
    return _index(
        tmp_path,
        AUTHORS,
        "Anonymus,,anonymous work\n"
        "Augustinus et Hieronymus,augustine-of-hippo|jerome,joint letter\n",
    )


def test_resolve_alias_and_name(index) -> None:
    assert index.resolve("Augustinus") == ["augustine-of-hippo"]
    assert index.resolve("Augustine of Hippo") == ["augustine-of-hippo"]
    # Folded: case, punctuation, Latin i/j u/v spellings.
    assert index.resolve("AVRELIVS  AVGVSTINVS") == ["augustine-of-hippo"]
    assert index.resolve("Jerome Saint") == ["jerome"]


def test_resolve_anonymous(index) -> None:
    assert index.resolve(None) == []
    assert index.resolve("  ") == []
    assert index.resolve("Anonymus") == []


def test_resolve_list_strings(index) -> None:
    assert index.resolve("Jerome; Augustinus") == ["jerome", "augustine-of-hippo"]
    assert index.resolve("Jerome; anonymous") == ["jerome"]
    assert index.resolve("Jerome; Augustinus; others") == ["jerome", "augustine-of-hippo"]
    assert index.resolve("Hieronymus et al.") == ["jerome"]
    assert index.resolve("Augustinus et Hieronymus") == ["augustine-of-hippo", "jerome"]
    assert index.resolve("Jerome; Jerome, Saint") == ["jerome"]  # deduplicated


def test_resolve_unknown_raises(index) -> None:
    with pytest.raises(UnknownAuthorError, match="Ambrosius"):
        index.resolve("Ambrosius")
    with pytest.raises(UnknownAuthorError, match="Ambrosius"):
        index.resolve("Jerome; Ambrosius")


def test_period_birth_year(index) -> None:
    a = index.authors
    assert a["augustine-of-hippo"].period_birth_year == 354
    assert a["pseudo-augustine"].period_birth_year is None
    # Floruit before 1025: certainly born before its end.
    assert a["flourished"].period_birth_year == 520
    # Floruit reaching past 1025: birth unknown.
    assert a["flourished-late"].period_birth_year is None
    # An uncertain late birth year is no evidence for exclusion.
    assert a["late-author"].period_birth_year is None
    assert a["known-late"].period_birth_year == 1040


def test_activity_range(index) -> None:
    a = index.authors
    assert a["flourished"].activity_range == (500, 520)  # the floruit
    assert a["augustine-of-hippo"].activity_range == (374, 430)  # birth + 20 .. death
    assert a["jerome"].activity_range == (367, 420)  # c. 347: the earliest birth
    assert a["pseudo-augustine"].activity_range is None
    assert index.activity_range(["jerome", "augustine-of-hippo"]) == (367, 430)  # the span
    assert index.activity_range(["jerome", "pseudo-augustine"]) is None  # one unknown
    assert index.activity_range([]) is None


def test_birth_year_of_a_work(index) -> None:
    assert index.birth_year([]) is None
    assert index.birth_year(["jerome", "augustine-of-hippo"]) == 354  # the youngest
    assert index.birth_year(["jerome", "pseudo-augustine"]) is None  # one unknown


@pytest.mark.parametrize(
    ("authors", "strings", "message"),
    [
        ("a,A,,,,,,,,\na,B,,,,,,,,\n", "", "listed twice"),
        ("Bad_Id,A,,,,,,,,\n", "", "slug"),
        ("a,,,,,,,,,\n", "", "no name"),
        ("a,A,,,,,martian,,,\n", "", "unknown tradition"),
        ("a,A,,400,300,,,,,\n", "", "death before birth"),
        ("a,A,,fl. 400,,,,,,\n", "", "unparseable date"),
        ("a,A,,,,,,,b,\n", "", "pseudo_of 'b' is unknown"),
        ("a,A,X,,,,,,,\nb,B,x,,,,,,,\n", "", "belongs to both"),
        ("a,A,X,,,,,,,\n", "X,a,dup\n", "also an alias"),
        ("a,A,,,,,,,,\n", "Y,b,who\n", "unknown author ids"),
        ("a,A,,,,,,,,\n", "Y,a,\n", "no reason"),
        ("a,A,,,,,,,,\n", "Y,a,r\ny,a,r\n", "collides"),
    ],
)
def test_malformed_index(tmp_path: Path, authors: str, strings: str, message: str) -> None:
    with pytest.raises(AuthorIndexError, match=message):
        _index(tmp_path, authors, strings)


# ---------------------------------------------------------------------------
# The repository's index
# ---------------------------------------------------------------------------

def test_repo_index_loads() -> None:
    idx = author_index()
    assert len(idx.authors) > 500
    assert list(load_authors(AUTHORS_PATH)) == sorted(idx.authors), "keep authors.csv sorted by id"


def test_external_ids_are_well_formed() -> None:
    bad = {
        aid: a.external_ids
        for aid, a in author_index().authors.items()
        if any(not re.fullmatch(r"(tlg|stoa|phi|pta)\d{4}", x) for x in a.external_ids)
    }
    assert not bad


def test_external_ids_are_unique() -> None:
    seen: dict[str, str] = {}
    dupes = []
    for aid, a in author_index().authors.items():
        for x in a.external_ids:
            if x in seen:
                dupes.append((x, seen[x], aid))
            seen[x] = aid
    assert not dupes


def test_pseudonymous_authors_have_no_dates_of_their_own_birth() -> None:
    """A pseudonym has no birth year; its works are judged by their own dates."""
    idx = author_index()
    for a in idx.authors.values():
        if a.pseudo_of is not None:
            assert a.birth is None and a.death is None, a.author_id
            assert idx.authors[a.pseudo_of].pseudo_of is None, a.author_id


@pytest.mark.parametrize(
    ("source", "ids"),
    [
        ("Augustinus", ["augustine-of-hippo"]),
        ("Augustine of Hippo", ["augustine-of-hippo"]),
        ("Hieronymus", ["jerome"]),
        ("Jerome, Saint", ["jerome"]),
        ("Irenaeus, Saint, Bishop of Lyon", ["irenaeus-of-lyon"]),
        ("Cyrill of Alexandria", ["cyril-of-alexandria"]),
        ("Joannes Chrysostomus", ["john-chrysostom"]),
        ("Pseudo-Chrysostom", ["pseudo-john-chrysostom"]),
        ("Anonymus (Pseudo-John Chrysostom)", ["pseudo-john-chrysostom"]),
        ("Basil, Saint, Bishop of Caesarea", ["basil-of-caesarea"]),
        ("Evagrius, Scholasticus", ["evagrius-scholasticus"]),
        ("John of Scythopolis; Maximus the Confessor",
         ["john-of-scythopolis", "maximus-the-confessor"]),
        ("John Geometres; Cosmas Vestitor; anonymous", ["john-geometres", "cosmas-vestitor"]),
        ("Cyprianus Tolonensis et alii", ["cyprian-of-toulon"]),
        ("Anonymus", []),
        ("Concilium Romanum", []),
        ("Georgios Violakis", []),  # modern editor of the Typikon
        (None, []),
    ],
)
def test_repo_examples(source: str | None, ids: list[str]) -> None:
    assert resolve_author(source) == ids


def test_pseudo_of_links() -> None:
    authors = author_index().authors
    assert authors["pseudo-john-chrysostom"].pseudo_of == "john-chrysostom"
    assert authors["pseudo-dionysius-the-areopagite"].pseudo_of == "dionysius-the-areopagite"


def test_every_corpus_author_resolves() -> None:
    unresolved = {}
    for w in _manifest_works():
        try:
            resolve_author(w.get("author"))
        except UnknownAuthorError:
            unresolved[w.get("author")] = w["work_id"]
    assert not unresolved, (
        f"add these to patristica/data/authors.csv (aliases) or author_strings.csv: {unresolved}"
    )


def test_manifest_carries_author_ids() -> None:
    """_works.jsonl was regenerated after the author index last changed."""
    stale = {
        w["work_id"]: (w.get("author_ids"), resolve_author(w.get("author")))
        for w in _manifest_works()
        if w.get("author_ids") != resolve_author(w.get("author"))
    }
    assert not stale, f"re-run scripts.normalize: {dict(list(stale.items())[:10])}"


def test_aliases_do_not_collide_across_authors() -> None:
    # build_index raises on a collision; check names too, against the folded form.
    seen: dict[str, str] = {}
    for a in author_index().authors.values():
        for alias in {fold(x) for x in (a.name, *a.aliases)}:
            assert seen.setdefault(alias, a.author_id) == a.author_id, alias


def test_no_corpus_author_is_born_after_the_period() -> None:
    late = {
        a.author_id: a.birth
        for a in author_index().authors.values()
        if (y := a.period_birth_year) is not None and y >= AUTHOR_BORN_BEFORE
    }
    assert not late


# ---------------------------------------------------------------------------
# Work model and normalize
# ---------------------------------------------------------------------------

def test_work_author_ids_default() -> None:
    w = Work(work_id="x/y", source_id="x", title="T", genre="patristic", language="lat")
    assert w.author_ids == []


def test_apply_author_ids() -> None:
    work = {"work_id": "x/y", "author": "Augustinus"}
    out = apply_author_ids(work)
    assert out == {**work, "author_ids": ["augustine-of-hippo"]}
    assert work == {"work_id": "x/y", "author": "Augustinus"}  # not mutated
    assert apply_author_ids(out) is out
    with pytest.raises(UnknownAuthorError):
        apply_author_ids({"work_id": "x/y", "author": "Nobody Whatsoever"})


def _write_raw(raw: Path, rel: str, work: dict) -> Path:
    path = raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"work": work, "paragraphs": [{"ref": "W.1", "text": "Some text."}]}
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


def _work(work_id: str, author: str | None, date: int) -> dict:
    return {
        "work_id": work_id, "source_id": "src", "title": "T", "genre": "patristic",
        "language": "lat", "author": author, "date_composed": date,
        "date_range": [date - 10, date + 10],
    }


@pytest.mark.parametrize(
    ("author", "flagged"),
    [
        ("Petrus Damiani", False),  # born 1007: in period although dated after 1050
        (None, True),  # anonymous: the date decides
        ("Pseudo-Augustinus", True),  # a pseudonym has no birth year
    ],
)
def test_normalize_uses_author_birth_year(
    tmp_path: Path, author: str | None, flagged: bool
) -> None:
    raw, norm = tmp_path / "raw", tmp_path / "normalized"
    _write_raw(raw, "src/w.json", _work("src/w", author, 1060))
    normalize_all(raw, norm)
    chunks = json.loads((norm / "src" / "w.json").read_text(encoding="utf-8"))
    assert {c["out_of_period"] for c in chunks} == {flagged}
    entry = json.loads((norm / "_works.jsonl").read_text(encoding="utf-8"))
    assert entry["work"]["author_ids"] == resolve_author(author)


def test_normalize_rejects_unknown_author(tmp_path: Path) -> None:
    raw, norm = tmp_path / "raw", tmp_path / "normalized"
    _write_raw(raw, "src/w.json", _work("src/w", "Nobody Whatsoever", 400))
    with pytest.raises(UnknownAuthorError, match="Nobody Whatsoever"):
        normalize_all(raw, norm)


# ---------------------------------------------------------------------------
# Author dates for undated works (#151)
# ---------------------------------------------------------------------------

def test_work_author_date_range() -> None:
    undated = {"work_id": "x/y", "author_ids": ["augustine-of-hippo"]}
    assert work_author_date_range(undated) == (374, 430)
    # A date of the work's own wins, even a single year or a range alone.
    assert work_author_date_range({**undated, "date_composed": 400}) is None
    assert work_author_date_range({**undated, "date_range": [390, 400]}) is None
    assert work_author_date_range({**undated, "author_ids": []}) is None
    assert work_author_date_range({**undated, "author_ids": ["pseudo-augustine"]}) is None


def test_apply_author_date_range() -> None:
    work = {"work_id": "x/y", "author_ids": ["augustine-of-hippo"], "date_range": None,
            "date_composed": None}
    out = apply_author_date_range(work)
    assert out == {**work, "author_date_range": [374, 430]}
    assert "author_date_range" not in work  # not mutated
    assert apply_author_date_range(out) is out
    # A work that gets a date of its own loses the derived one; others never get the key.
    dated = {**out, "date_range": [390, 400], "date_composed": 395}
    assert "author_date_range" not in apply_author_date_range(dated)
    plain = {"work_id": "x/z", "author_ids": []}
    assert apply_author_date_range(plain) is plain


def test_manifest_carries_author_date_range() -> None:
    """_works.jsonl was regenerated after the author dates last changed (#151)."""
    stale = {}
    for w in _manifest_works():
        want = work_author_date_range(w)
        have = w.get("author_date_range")
        if (list(want) if want else None) != have:
            stale[w["work_id"]] = (have, want)
    assert not stale, f"re-run scripts.normalize: {dict(list(stale.items())[:10])}"


@pytest.mark.parametrize(
    ("author", "expected"),
    [
        ("Augustinus", [374, 430]),
        (None, None),  # anonymous
        ("Pseudo-Augustinus", None),  # a pseudonym has no dates
    ],
)
def test_normalize_gives_undated_works_their_author_dates(
    tmp_path: Path, author: str | None, expected: list[int] | None
) -> None:
    """The range goes into _works.jsonl only: the chunks keep no date and the
    period rule is unchanged."""
    raw, norm = tmp_path / "raw", tmp_path / "normalized"
    work = {**_work("src/w", author, 0), "date_composed": None, "date_range": None}
    _write_raw(raw, "src/w.json", work)
    normalize_all(raw, norm)
    entry = json.loads((norm / "_works.jsonl").read_text(encoding="utf-8"))["work"]
    assert entry.get("author_date_range") == expected
    assert (entry["date_range"], entry["date_composed"]) == (None, None)
    chunks = json.loads((norm / "src" / "w.json").read_text(encoding="utf-8"))
    assert {(c["date_range"], c["date_composed"], c["out_of_period"]) for c in chunks} \
        == {(None, None, False)}
    if expected is None:
        assert "author_date_range" not in entry
