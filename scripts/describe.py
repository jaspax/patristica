"""Write author bios and work descriptions (#795) to ``data/descriptions/``.

See ``patristica/descriptions.py`` for the format. For each author, and for
each version group of works (#178: one description, copied to every member),
the generator

1. searches English Wikipedia and fetches the lead section of the top
   candidates (cached in ``data/cache/wikipedia/``),
2. takes the metadata and, for a work, the opening of its text (an English
   version where there is one), and
3. asks Claude, through a local ``claude -p`` on the Claude subscription (no
   API bill), to pick the candidate article that is about this author or work
   (or none) and to write 50-100 words from those sources.

``MODEL`` is the model every description is written with; new authors and
works use it too. A bake-off on 8 authors and 8 works (#795) chose Sonnet:
equal to Haiku on well-known subjects, but it identified the obscure ones
(a CANTUS manuscript as Hildegard's Dendermonde codex, an Arian fragment as
Opitz's Urkunde 13) where Haiku paraphrased the opening and leaked catalogue
wording.

Runs are resumable: an entry that already has generated text is skipped
(``--redo`` rewrites it), results are saved every few dozen calls, and the
run stops sending when the subscription's five-hour window passes
``--stop-at``.

Usage::

    python -m scripts.describe status                 # what is missing or placeholder
    python -m scripts.describe generate [--authors|--works] [--limit N] [--workers 6]
    python -m scripts.describe generate --id augustine-of-hippo --id book:gen
    python -m scripts.describe placeholder            # lorem ipsum everywhere (layout review)

``--normalized-dir`` points at materialized normalized files (a worktree
has git-lfs pointers; the main checkout has the text).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import subprocess
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from patristica import console, descriptions
from patristica.authors import Author, AuthorDate, author_index
from patristica.descriptions import PLACEHOLDER_MODEL, WIKIPEDIA_PREFIX, Description
from patristica.versions import derive_version_groups

log = logging.getLogger(__name__)

#: The model every bio and description is written with (claude -p --model).
MODEL = "claude-sonnet-5-5"
#: Bump when the prompt changes in a way that should rewrite every entry.
PROMPT_VERSION = "1"

WORKS_MANIFEST = Path("data/normalized/_works.jsonl")
WIKI_CACHE = Path("data/cache/wikipedia")
WIKI_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "PatristicaDescriptions/1.0 (digital library of early Christian texts)"
EXCERPT_WORDS = 250
CANDIDATES = 4

SYSTEM = """\
You write short reference notes for Patristica, a free digital library of \
Scripture and Christian writings of the first millennium (Greek, Latin, Syriac, \
Coptic, Armenian, Ge'ez, Slavonic, Georgian, Arabic, Irish and more). Each note \
appears beside an author's or a work's catalogue facts.

Write one paragraph of plain, neutral, encyclopedic English, 50 to 100 words (never more than 100).
- For a person: who they were, when and where they lived, their role (bishop, \
monk, theologian, poet…), and what they are known for, including major works \
or ideas.
- For a work: what kind of text it is, who wrote it (or to whom it is \
attributed), when, what it is about, and why it matters. The note is shown on \
every language version of the work, so do not describe a particular edition, \
translation or manuscript.
- Rely on the sources given: the Wikipedia extracts, the catalogue facts and \
the opening of the text. Add only what you are certain is standard knowledge. \
Never invent dates, places, titles or attributions. If a date or attribution \
is disputed or unknown, say so. If little is known, write less (down to about \
30 words) rather than pad.
- The catalogue facts come from the library's own index and can be approximate \
or wrong. Where the sources disagree with them, follow the better-supported \
account. Never refer to "the catalogue", "the sources" or "the text provided".
- Do not repeat the heading as a label, address the reader, mention Wikipedia \
or the library, or use bullet points or Markdown.

Also choose the Wikipedia article: the title of the candidate article that is \
about this same person, or this same work (or the collection or series this \
work is one part of, such as a set of homilies). Never choose an article about \
a different person or work with a similar name, or about the author of a work. \
If no candidate fits, answer null."""


class Reply(BaseModel):
    wikipedia_title: str | None = Field(
        description="Exact title of the matching candidate article, or null")
    text: str = Field(description="The note: one paragraph, 50-100 words")


# --- Wikipedia --------------------------------------------------------------


class Wikipedia:
    """Search hits with their lead extracts from the English Wikipedia API,
    cached on disk (``data/cache/wikipedia/``) and paced under Wikimedia's
    rate limits: 10 requests a minute for a client without contact details in
    its User-Agent, 200 with them (``WIKIMEDIA_USER_AGENT``, set by the owner;
    never put the owner's details in code). 429s are retried after their
    Retry-After."""

    def __init__(self, cache: Path = WIKI_CACHE) -> None:
        import httpx

        from patristica.embedders import env_key

        try:
            agent: str | None = env_key("WIKIMEDIA_USER_AGENT")  # environment or .env
        except KeyError:
            agent = None
        self.cache = cache
        self.http = httpx.Client(timeout=30, headers={"User-Agent": agent or USER_AGENT})
        self.interval = 60 / (150 if agent else 9)
        self._lock = threading.Lock()  # one request at a time: be polite
        self._next = 0.0

    def _get(self, params: dict[str, str]) -> dict[str, Any]:
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        path = self.cache / key[:2] / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        with self._lock:
            for attempt in range(8):
                time.sleep(max(0.0, self._next - time.monotonic()))
                r = self.http.get(WIKI_API, params={**params, "format": "json",
                                                    "formatversion": "2"})
                self._next = time.monotonic() + self.interval
                if r.status_code == 200:
                    break
                if attempt == 7 or r.status_code not in (429, 500, 502, 503, 504):
                    r.raise_for_status()
                wait_s = float(r.headers.get("retry-after") or 10 * (attempt + 1))
                log.debug("Wikipedia %s: waiting %.0f s", r.status_code, wait_s)
                self._next = time.monotonic() + wait_s
            data = r.json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def search(self, query: str, limit: int = CANDIDATES) -> list[dict[str, Any]]:
        """The top *limit* hits for *query*, in rank order, with their lead
        extracts: one request (a search generator with ``prop=extracts``)."""
        data = self._get({"action": "query", "generator": "search", "gsrsearch": query,
                          "gsrlimit": str(limit), "prop": "extracts|description",
                          "exintro": "1", "explaintext": "1", "exlimit": "max",
                          "redirects": "1"})
        pages = data.get("query", {}).get("pages", [])
        return sorted(pages, key=lambda p: p.get("index", 0))

    def candidates(self, queries: list[str]) -> list[dict[str, str]]:
        """Lead extracts of the top search hits of *queries*, without duplicates
        or disambiguation pages."""
        out: list[dict[str, str]] = []
        for q in queries:
            for p in self.search(q):
                if (p.get("missing") or not p.get("extract") or is_disambiguation(p)
                        or any(c["title"] == p["title"] for c in out)):
                    continue
                out.append({"title": p["title"], "description": p.get("description", ""),
                            "extract": p["extract"][:1800]})
        return out[:CANDIDATES + 2]


def is_disambiguation(page: dict[str, Any]) -> bool:
    return (page.get("description") == "Topics referred to by the same term"
            or page.get("extract", "").rstrip().endswith("may refer to:"))


def wikipedia_url(title: str) -> str:
    from urllib.parse import quote

    return WIKIPEDIA_PREFIX + quote(title.replace(" ", "_"), safe="_()',-.:!")


# --- Claude -----------------------------------------------------------------


@dataclass
class Usage:
    five_hour: float | None = None
    seven_day: float | None = None


def ask(system: str, user: str, model: str = MODEL) -> tuple[Reply, Usage]:
    """One request through a local ``claude -p`` (no tools, settings or project context)."""
    from scripts.embed_eval.translate import parse_claude_stream

    cmd = ["claude", "-p", "--model", model, "--system-prompt", system,
           "--json-schema", json.dumps(Reply.model_json_schema()),
           "--tools", "", "--setting-sources", "", "--strict-mcp-config",
           "--no-session-persistence", "--verbose", "--output-format", "stream-json"]
    with tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=cwd,
                              timeout=600)
    reply, usage = parse_claude_stream(model, proc.stdout, proc.returncode, proc.stderr, Reply)
    limits = usage.get("limits", {})
    return reply, Usage((limits.get("five_hour") or {}).get("utilization"),
                        (limits.get("seven_day") or {}).get("utilization"))


# --- Subjects ---------------------------------------------------------------


def year(y: int) -> str:
    return f"{-y} BC" if y < 0 else str(y)


def fmt_date(d: AuthorDate | None) -> str | None:
    if d is None:
        return None
    span = year(d.low) if d.low == d.high else f"{year(d.low)}-{year(d.high)}"
    return {"established": span, "approximate": f"c. {span}"}.get(d.confidence, f"{span}?")


@dataclass
class Subject:
    """One generation request: an author, or a version group of works."""

    key: str                 # author id, or the group id
    ids: list[str]           # the entries it fills (the author, or every member)
    heading: str             # what the prompt is about
    facts: list[str]
    queries: list[str]
    #: ``(work_id, normalized file)`` to take the opening of the text from, in order.
    texts: list[tuple[str, Path]] = field(default_factory=list)
    excerpt: str | None = None
    excerpt_source: str | None = None

    def load_excerpt(self) -> None:
        """Read the opening of the first readable text (once, just before the request)."""
        if self.excerpt is not None:
            return
        for work_id, path in self.texts:
            if (text := read_excerpt(path)) is not None:
                self.excerpt, self.excerpt_source = text, work_id
                return

    def prompt(self, candidates: list[dict[str, str]]) -> str:
        parts = [f"# {self.heading}", "", "## Catalogue facts", *[f"- {f}" for f in self.facts]]
        if self.excerpt:
            parts += ["", "## Opening of the text", self.excerpt]
        parts += ["", "## Wikipedia candidates"]
        if not candidates:
            parts.append("(none found)")
        for c in candidates:
            parts += ["", f"### Article title: {c['title']}"]
            if c["description"]:
                parts.append(f"Short description: {c['description']}")
            parts.append(c["extract"])
        return "\n".join(parts)


def author_subjects(works: list[dict[str, Any]]) -> list[Subject]:
    index = author_index().authors
    titles: dict[str, list[str]] = {}
    for w in works:
        for aid in w.get("author_ids") or []:
            if w["language"] == "eng" or len(titles.get(aid, [])) < 3:
                titles.setdefault(aid, []).append(w["title"])
    out = []
    for aid, a in sorted(index.items()):
        out.append(author_subject(a, index, titles.get(aid, [])))
    return out


def author_subject(a: Author, index: dict[str, Author], titles: list[str]) -> Subject:
    facts = [f"Name: {a.name}"]
    if a.aliases:
        facts.append("Also known as: " + "; ".join(a.aliases[:8]))
    for label, d in (("Born", a.birth), ("Died", a.death), ("Active", a.floruit)):
        if (s := fmt_date(d)) is not None:
            facts.append(f"{label}: {s}")
    if a.tradition:
        facts.append(f"Tradition: {a.tradition}")
    if a.pseudo_of:
        real = index.get(a.pseudo_of)
        facts.append("This is a pseudonymous author: works falsely or doubtfully attributed to "
                     f"{real.name if real else a.pseudo_of}. Describe that body of writings.")
    if a.note:
        facts.append(f"Note: {a.note}")
    if titles:
        seen = list(dict.fromkeys(titles))
        facts.append("Works in the library include: " + "; ".join(seen[:6]))
    queries = [a.name] if not a.pseudo_of else [a.name, f"{a.name} pseudepigrapha"]
    return Subject(a.author_id, [a.author_id], f"Author: {a.name}", facts, queries)


#: Words that steer a work's Wikipedia search away from namesakes (albums, films).
GENRE_CONTEXT = {
    "scripture": "book of the Bible",
    "apocrypha": "apocryphal text",
    "liturgical": "liturgy",
    "council": "church council",
    "hagiography": "saint life",
    "patristic": "Christian",
}

LANGUAGES = {
    "grc": "Greek", "lat": "Latin", "hbo": "Hebrew", "syc": "Syriac", "cop": "Coptic",
    "gez": "Ge'ez", "hye": "Armenian", "got": "Gothic", "chu": "Church Slavonic",
    "arb": "Arabic", "oge": "Old Georgian", "sga": "Old Irish", "ang": "Old English",
    "goh": "Old High German", "osx": "Old Saxon", "lzh": "Literary Chinese", "eng": "English",
}


def work_subjects(entries: list[dict[str, Any]], normalized: Path) -> list[Subject]:
    """One subject per version group (or ungrouped work)."""
    works = {e["work"]["work_id"]: e for e in entries}
    groups = derive_version_groups(
        {wid: e["work"].get("translation_of") for wid, e in works.items()},
        external_ids={wid: e["work"].get("external_ids", []) for wid, e in works.items()})
    members: dict[str, list[str]] = {}
    for wid in works:
        members.setdefault(groups.group(wid) or wid, []).append(wid)
    index = author_index().authors
    return [group_subject(key, sorted(ids), works, index, normalized)
            for key, ids in sorted(members.items())]


def _is_mt(w: dict[str, Any]) -> bool:
    return w["source_id"] == "mt-eng"


def group_subject(key: str, ids: list[str], works: dict[str, dict[str, Any]],
                  index: dict[str, Author], normalized: Path) -> Subject:
    ws = [works[i]["work"] for i in ids]
    # The original: no translation_of, not English, if there is one.
    lead = min(ws, key=lambda w: (bool(w.get("translation_of")), w["language"] == "eng",
                                  w["work_id"]))
    english = [w for w in ws if w["language"] == "eng"]
    eng_title = next((w["title"] for w in english if not _is_mt(w)),
                     english[0]["title"] if english else None)
    author_ids = list(dict.fromkeys(a for w in ws for a in w.get("author_ids") or []))
    names = [index[a].name for a in author_ids if a in index]
    facts = [f"Title: {lead['title']}"]
    if eng_title and eng_title != lead["title"]:
        facts.append(f"English title: {eng_title}")
    other = sorted({w["title"] for w in ws} - {lead["title"], eng_title})
    if other:
        facts.append("Other titles of its versions: " + "; ".join(other[:5]))
    facts.append("Author: " + (", ".join(names) if names else "anonymous"))
    if lead.get("author") and lead["author"] not in names:
        facts.append(f"Attributed in the source as: {lead['author']}")
    if lead.get("date_range"):
        lo, hi = lead["date_range"]
        facts.append(f"Date of composition ({lead.get('date_confidence')}): "
                     + (year(lo) if lo == hi else f"{year(lo)} to {year(hi)}"))
    facts.append(f"Genre: {lead['genre']}")
    langs = sorted({LANGUAGES.get(w["language"], w["language"]) for w in ws})
    facts.append(f"Original language: {LANGUAGES.get(lead['language'], lead['language'])}"
                 + (f"; versions in the library: {', '.join(langs)}" if len(langs) > 1 else ""))
    title = eng_title or lead["title"]
    context = GENRE_CONTEXT.get(lead["genre"], "")
    # One query of its own per work (Wikimedia's limits); the author's article
    # comes from a query shared by all their works (cached), as context.
    queries = [f"{title} {names[0]}" if names else f"{title} {context}".strip()]
    if names:
        queries.append(names[0])  # context for an obscure work; never its link (SYSTEM)
    # The opening of the text: an English version (not a machine translation) first.
    order = sorted(ws, key=lambda w: (w["language"] != "eng", _is_mt(w), w is not lead))
    texts = [(w["work_id"], normalized / works[w["work_id"]]["path"]) for w in order]
    return Subject(key, ids, f"Work: {title}", facts, queries, texts)


def read_excerpt(path: Path, words: int = EXCERPT_WORDS) -> str | None:
    """The first *words* words of a normalized work, or None if it can't be read."""
    try:
        chunks = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    out: list[str] = []
    for c in sorted(chunks, key=lambda c: c.get("chunk_index", 0)):
        out += c.get("text", "").split()
        if len(out) >= words:
            break
    return " ".join(out[:words]) + (" …" if len(out) > words else "") if out else None


# --- Running ----------------------------------------------------------------


def load_manifest(path: Path = WORKS_MANIFEST) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def match_title(chosen: str, titles: list[str]) -> str | None:
    """The candidate title the model chose; it sometimes adds the short description."""
    chosen = chosen.strip().removeprefix("Article title:").strip()
    if chosen in titles:
        return chosen
    starts = [t for t in titles if chosen.startswith(t + " (")]
    return max(starts, key=len) if starts else None


def describe(subject: Subject, wiki: Wikipedia, model: str) -> tuple[list[Description], Usage]:
    subject.load_excerpt()
    cands = wiki.candidates(subject.queries)
    reply, usage = ask(SYSTEM, subject.prompt(cands), model)
    url = None
    if reply.wikipedia_title:
        if (title := match_title(reply.wikipedia_title, [c["title"] for c in cands])):
            url = wikipedia_url(title)
        else:
            log.warning("%s: model chose %r, not a candidate; no link", subject.key,
                        reply.wikipedia_title)
    sources = [url] if url else []
    if subject.excerpt_source:
        sources.append(f"text:{subject.excerpt_source}")
    text = " ".join(reply.text.split())
    model_tag = f"{model}/p{PROMPT_VERSION}"
    return [Description(i, text, url, model_tag, sources) for i in subject.ids], usage


def generated(d: Description | None) -> bool:
    return d is not None and d.model != PLACEHOLDER_MODEL


def needs(subject: Subject, have: dict[str, Description], redo: bool) -> bool:
    if redo:
        return True
    return not all(generated(have.get(i)) for i in subject.ids)


def settle(subjects: list[Subject], have: dict[str, Description]) -> tuple[int, int]:
    """The free part of a run: copy a group's description to members that lack
    one (a new version of a described work), and drop entries whose author or
    work is gone. Returns ``(copied, dropped)``."""
    copied = 0
    for s in subjects:
        source = next((have[i] for i in s.ids if generated(have.get(i))), None)
        if source is None:
            continue
        for i in s.ids:
            if not generated(have.get(i)):
                have[i] = Description(i, source.text, source.wikipedia, source.model,
                                      list(source.sources))
                copied += 1
    valid = {i for s in subjects for i in s.ids}
    gone = [i for i in have if i not in valid]
    for i in gone:
        del have[i]
    return copied, len(gone)


def pending(normalized: Path = Path("data/normalized"),
            root: Path = descriptions.DEFAULT_DIR) -> int:
    """Authors and version groups a ``generate`` run would send to the model
    (after copying within groups); for the pipeline's ``describe`` step."""
    entries = load_manifest(normalized / "_works.jsonl")
    n = 0
    for subjects, path in ((author_subjects([e["work"] for e in entries]),
                            root / descriptions.AUTHORS_FILE),
                           (work_subjects(entries, normalized), root / descriptions.WORKS_FILE)):
        have = descriptions.load(path)
        settle(subjects, have)
        n += sum(needs(s, have, False) for s in subjects)
    return n


def generate(subjects: list[Subject], path: Path, model: str, workers: int,
             stop_at: float, redo: bool, limit: int | None, requests: bool = True,
             only: set[str] | None = None) -> int:
    have = descriptions.load(path)
    copied, dropped = settle(subjects, have)
    if copied or dropped:
        log.info("%s: copied %d descriptions within version groups, dropped %d of removed ids",
                 path.name, copied, dropped)
    descriptions.save(path, have.values())
    if only:
        subjects = [s for s in subjects if s.key in only or only & set(s.ids)]
    todo = [s for s in subjects if needs(s, have, redo)]
    if not requests:
        log.info("%s: %d subjects to describe (--no-requests: none sent)", path.name, len(todo))
        return 0
    if limit is not None:
        todo = todo[:limit]
    log.info("%d of %d subjects to describe into %s with %s", len(todo), len(subjects),
             path, model)
    wiki = Wikipedia()
    done = failed = 0
    stop = False
    pending: dict[Future, Subject] = {}
    queue = iter(todo)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            while not stop and len(pending) < workers:
                s = next(queue, None)
                if s is None:
                    break
                pending[pool.submit(describe, s, wiki, model)] = s
            if not pending:
                break
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for fut in finished:
                s = pending.pop(fut)
                try:
                    entries, usage = fut.result()
                except Exception as exc:  # noqa: BLE001 - logged, retried on the next run
                    failed += 1
                    log.error("%s: %s", s.key, exc)
                    continue
                for e in entries:
                    have[e.id] = e
                done += 1
                if usage.five_hour is not None and usage.five_hour >= stop_at and not stop:
                    log.warning("Five-hour usage at %.0f%%: stopping (resume later)",
                                100 * usage.five_hour)
                    stop = True
                if done % 25 == 0:
                    descriptions.save(path, have.values())
                    log.info("%d/%d done, %d failed; usage 5h %s 7d %s", done, len(todo),
                             failed, usage.five_hour, usage.seven_day)
    descriptions.save(path, have.values())
    log.info("Described %d subjects, %d failed", done, failed)
    return failed


def lorem(key: str) -> str:
    """50-100 words of lorem ipsum, the length fixed by *key*."""
    words = (
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor "
        "incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud "
        "exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure "
        "dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
        "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt "
        "mollit anim id est laborum. Curabitur pretium tincidunt lacus, nulla gravida orci a "
        "odio, nullam varius turpis et commodo pharetra est eros bibendum elit nec luctus magna "
        "felis sollicitudin mauris. Integer in mauris eu nibh euismod gravida, duis ac tellus "
        "et risus vulputate vehicula donec lobortis risus a elit."
    ).split()
    n = 50 + int(hashlib.sha256(key.encode()).hexdigest(), 16) % 51
    return " ".join((words * 2)[:n]).rstrip(",.") + "."


def placeholder(root: Path) -> None:
    """Lorem ipsum for every author and work; every third work gets a link."""
    authors = author_index().authors
    bios = [Description(aid, lorem(aid), wikipedia_url(a.name), PLACEHOLDER_MODEL)
            for aid, a in authors.items()]
    works = [Description(e["work"]["work_id"], lorem(e["work"]["work_id"]),
                         wikipedia_url("Special:Random") if i % 3 == 0 else None,
                         PLACEHOLDER_MODEL)
             for i, e in enumerate(load_manifest())]
    descriptions.save(root / descriptions.AUTHORS_FILE, bios)
    descriptions.save(root / descriptions.WORKS_FILE, works)
    log.info("Wrote placeholders for %d authors and %d works", len(bios), len(works))


def status(root: Path) -> None:
    for name, ids in ((descriptions.AUTHORS_FILE, list(author_index().authors)),
                      (descriptions.WORKS_FILE, [e["work"]["work_id"] for e in load_manifest()])):
        have = descriptions.load(root / name)
        missing = [i for i in ids if i not in have]
        lorem_ = [i for i in ids if i in have and have[i].model == PLACEHOLDER_MODEL]
        linked = sum(1 for i in ids if i in have and have[i].wikipedia)
        print(f"{name}: {len(ids)} ids, {len(missing)} missing, {len(lorem_)} placeholder, "
              f"{linked} with a Wikipedia link")


def main() -> None:
    console.setup_logging()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", type=Path, default=descriptions.DEFAULT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("placeholder", help="lorem ipsum for every author and work")
    sub.add_parser("status", help="count missing and placeholder entries")
    g = sub.add_parser("generate", help="write bios and descriptions with Claude")
    which = g.add_mutually_exclusive_group()
    which.add_argument("--authors", action="store_true", help="authors only")
    which.add_argument("--works", action="store_true", help="works only")
    g.add_argument("--id", action="append", default=[],
                   help="only this author id, version group id or work id (repeatable)")
    g.add_argument("--model", default=MODEL)
    g.add_argument("--workers", type=int, default=6)
    g.add_argument("--limit", type=int)
    g.add_argument("--redo", action="store_true", help="rewrite generated entries too")
    g.add_argument("--stop-at", type=float, default=0.85,
                   help="stop sending at this five-hour usage (0-1)")
    g.add_argument("--normalized-dir", type=Path, default=Path("data/normalized"))
    g.add_argument("--keep-going", action="store_true",
                   help="exit 0 even when some requests failed (they are logged; the pipeline)")
    g.add_argument("--no-requests", action="store_true",
                   help="only copy within version groups and drop removed ids; send nothing")
    args = parser.parse_args()
    if args.command == "placeholder":
        placeholder(args.dir)
        return
    if args.command == "status":
        status(args.dir)
        return

    entries = load_manifest()  # this checkout's works; their text from --normalized-dir
    failed = 0
    jobs = []
    if not args.works:
        jobs.append((author_subjects([e["work"] for e in entries]),
                     args.dir / descriptions.AUTHORS_FILE))
    if not args.authors:
        jobs.append((work_subjects(entries, args.normalized_dir),
                     args.dir / descriptions.WORKS_FILE))
    for subjects, path in jobs:
        failed += generate(subjects, path, args.model, args.workers, args.stop_at,
                           args.redo or bool(args.id), args.limit, not args.no_requests,
                           set(args.id) or None)
    raise SystemExit(1 if failed and not args.keep_going else 0)


if __name__ == "__main__":
    main()
