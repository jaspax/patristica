"""The OCR pipeline's stages (#720). Each writes {page}.txt under its own directory.

    kraken       Kraken + CLLG on CPU -> ALTO (line boxes, word confidences)
    kgc          word flags (r95) on Kraken's lines; Gemini re-reads the flagged lines
    gemini_page  Gemini 3.8 Flash (low thinking) reads the whole page in strips
    opus_page    Claude Opus reads the whole page in strips
    synth1/2     Opus writes each line the three readers dispute (about 20% of lines),
                 from the line image and all readings; agreed lines are kept
    final        word vote of synth1, synth2, kgc, opus_page, gemini_page; Θεός repair

Every stage skips pages it has already written, so a run resumes, and logs
token usage per request to _usage.jsonl for `python -m scripts.ocr cost`.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from scripts.ocr import flags, prompts
from scripts.ocr.alto import read_alto
from scripts.ocr.backends import Job, Result, drop_comments, parse_json
from scripts.ocr.images import jpeg_b64, n_strips, stacked_chunks, strips
from scripts.ocr.text import lines_of, norm, pair_lines, same_reading
from scripts.ocr.vote import capitalize_theos, vote

log = logging.getLogger(__name__)

READERS = ("kgc", "opus_page", "gemini_page")


class Run:
    """One pipeline run: page images in, a directory per stage out."""

    def __init__(self, pages: list[str], images: Path, out: Path) -> None:
        self.pages, self.images, self.out = pages, images, out

    def dir(self, stage: str) -> Path:
        d = self.out / stage
        d.mkdir(parents=True, exist_ok=True)
        return d

    def image(self, page: str) -> Image.Image:
        return Image.open(next(self.images.glob(f"{page}.*")))

    def todo(self, stage: str, ext: str = "txt") -> list[str]:
        d = self.dir(stage)
        return [p for p in self.pages if not (d / f"{p}.{ext}").exists()]

    def text(self, stage: str, page: str) -> str:
        return (self.out / stage / f"{page}.txt").read_text(encoding="utf-8")

    def log_usage(self, stage: str, results: dict[str, Result]) -> None:
        with (self.dir(stage) / "_usage.jsonl").open("a") as f:
            for key, r in results.items():
                f.write(json.dumps({"key": key, "usage": r.usage, "error": r.error},
                                   ensure_ascii=False, default=str) + "\n")


# ---------------------------------------------------------------------------

def kraken(run: Run, workers: int = 4) -> None:
    """Kraken with the CLLG model (KRAKEN_BIN, KRAKEN_MODEL) -> {page}.xml (ALTO)."""
    binary = os.environ.get("KRAKEN_BIN", "kraken")
    model = os.environ.get("KRAKEN_MODEL")
    if not model:
        raise RuntimeError("set KRAKEN_MODEL to the cllg_recognition_v1.mlmodel path")
    d = run.dir("kraken")
    env = {**os.environ, "OMP_NUM_THREADS": "2", "MKL_NUM_THREADS": "2"}

    def one(page: str) -> None:
        img = next(run.images.glob(f"{page}.*"))
        subprocess.run([binary, "-i", str(img), str(d / f"{page}.xml"), "-a", "segment", "-bl",
                        "ocr", "-m", model], check=True, capture_output=True, env=env)
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, run.todo("kraken", "xml")))


def _page_jobs(run: Run, pages: list[str]) -> list[Job]:
    jobs = []
    for p in pages:
        img = run.image(p)
        for n, s in enumerate(strips(img, n_strips(img))):
            jobs.append(Job(f"{p}#{n}", prompts.PAGE_SYSTEM,
                            [("image", jpeg_b64(s)), ("text", prompts.PAGE_PROMPT)]))
    return jobs


def _write_pages(run: Run, stage: str, results: dict[str, Result]) -> None:
    by_page: dict[str, list[tuple[int, str]]] = {}
    for key, r in results.items():
        page, n = key.rsplit("#", 1)
        if r.error:
            log.error("%s %s: %s", stage, key, r.error)
            by_page.setdefault(page, []).append((int(n), None))
            continue
        by_page.setdefault(page, []).append((int(n), drop_comments(r.text)))
    for page, parts in by_page.items():
        if any(t is None for _, t in parts):
            continue  # a failed strip: leave the page for the next run
        text = "\n".join(t for _, t in sorted(parts))
        (run.dir(stage) / f"{page}.txt").write_text(text + "\n", encoding="utf-8")


def page_reader(run: Run, stage: str, backend) -> None:
    """A model reads every page in strips (gemini_page, opus_page)."""
    results = backend.run(_page_jobs(run, run.todo(stage)))
    run.log_usage(stage, results)
    _write_pages(run, stage, results)


def kgc(run: Run, backend, point: str = "r95") -> None:
    """Gemini re-reads the lines where the flags find a suspicious word in Kraken's reading."""
    jobs, plans = [], {}
    for p in run.todo("kgc"):
        lines = read_alto(run.out / "kraken" / f"{p}.xml")
        marks = flags.flag_lines(lines, point)
        listing, crops = [], []
        for i, (ln, fl) in enumerate(zip(lines, marks)):
            if any(fl):
                shown = " ".join(f"⟦{w.text}⟧" if f else w.text for w, f in zip(ln.words, fl))
                listing.append(f"Line {i}: {shown}")
                crops.append((i, ln.box))
        plans[p] = [ln.text for ln in lines]
        if crops:
            text = (prompts.LINES_PROMPT + "\n\n" + "\n".join(listing)
                    + "\n\nThe line images follow, each labelled on its left with its line "
                    "number (L n):")
            jobs.append(Job(p, prompts.LINES_SYSTEM, [("text", text)]
                            + [("image", b) for b in stacked_chunks(run.image(p), crops)],
                            json_answer=True))
    results = backend.run(jobs)
    run.log_usage("kgc", results)
    for p, base in plans.items():
        out = list(base)
        r = results.get(p)
        if r is not None:
            if r.error:
                log.error("kgc %s: %s", p, r.error)
                continue
            for x in parse_json(r.text).get("lines", []):
                if 0 <= int(x["id"]) < len(out):
                    out[int(x["id"])] = norm(x["text"])
        (run.dir("kgc") / f"{p}.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


def disputed(run: Run, page: str) -> tuple[list, list[str], list[list[str]]]:
    """Kraken's lines, the agreed text per line, and the readings of each line.

    A line is agreed when the three readers' versions are the same up to
    transcription conventions; about 80% of lines are.
    """
    lines = read_alto(run.out / "kraken" / f"{page}.xml")
    k_text = [ln.text for ln in lines]
    readings: list[list[str]] = [[t] for t in k_text]  # R1 is Kraken's line
    witnesses = [[] for _ in lines]
    for stage in READERS:
        wl = lines_of(run.text(stage, page))
        for i, j in pair_lines(k_text, wl):
            if i is not None and j is not None:
                witnesses[i].append(wl[j])
    agreed = []
    for i, w in enumerate(witnesses):
        readings[i] += w
        ok = len(w) == len(READERS) and all(same_reading(w[0], x) for x in w[1:])
        agreed.append(w[0] if ok else None)
    return lines, agreed, readings


def synth(run: Run, stage: str, backend) -> None:
    """Opus writes the disputed lines from their images and all readings."""
    jobs, plans = [], {}
    for p in run.todo(stage):
        lines, agreed, readings = disputed(run, p)
        todo = [i for i, a in enumerate(agreed) if a is None]
        plans[p] = (lines, agreed, readings)
        if not todo:
            continue
        listing = []
        for i in todo:
            listing.append(f"Line {i}:")
            listing += [f"  R{k + 1}: {r}" for k, r in enumerate(dict.fromkeys(readings[i]))]
        # The whole page as text, so the disputed lines are read in context:
        # judged alone, Opus misread or "corrected" more of them (#720).
        context = [f"{i}: {a}" if a is not None else f"{i}: [line {i} - to transcribe]"
                   for i, a in enumerate(agreed)]
        text = (prompts.SYNTH_PROMPT + "\n\nThe page, for context (lines already settled, "
                "and the lines to transcribe marked):\n" + "\n".join(context)
                + "\n\nThe lines to transcribe, with their OCR readings:\n" + "\n".join(listing)
                + "\n\nThe line images follow, each labelled on its left (L n):")
        crops = [(i, lines[i].box) for i in todo]
        jobs.append(Job(p, prompts.SYNTH_SYSTEM, [("text", text)]
                        + [("image", b) for b in stacked_chunks(run.image(p), crops)],
                        json_answer=True))
    results = backend.run(jobs)
    run.log_usage(stage, results)
    for p, (lines, agreed, readings) in plans.items():
        r = results.get(p)
        if r is not None and r.error:
            log.error("%s %s: %s", stage, p, r.error)
            continue
        ans = ({int(x["id"]): norm(x["text"]) for x in parse_json(r.text).get("lines", [])}
               if r else {})
        # A line the model did not answer keeps the first reader's version (kgc).
        out = [a if a is not None else ans.get(i, (readings[i] + readings[i])[1])
               for i, a in enumerate(agreed)]
        (run.dir(stage) / f"{p}.txt").write_text("\n".join(out) + "\n", encoding="utf-8")


def final(run: Run) -> None:
    """Word vote of the two synthesis runs and the three readers, then the Θεός repair."""
    for p in run.todo("final"):
        text = vote(run.text("synth1", p),
                    [run.text(s, p) for s in ("synth2", "kgc", "opus_page", "gemini_page")])
        (run.dir("final") / f"{p}.txt").write_text(capitalize_theos(text) + "\n", encoding="utf-8")
