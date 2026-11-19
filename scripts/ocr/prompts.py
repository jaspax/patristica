# ruff: noqa: E501
"""Prompts of the OCR stages. Changing one changes the stage's output: bump PROMPT_VERSION."""

PROMPT_VERSION = "2026-11-18"

PAGE_SYSTEM = (
    "You are a diplomatic OCR engine for 19th-century printed Ancient Greek "
    "(Migne's Patrologia Graeca). Transcribe exactly what is printed."
)

PAGE_PROMPT = (
    "Transcribe the text in this image strip exactly as printed, one printed line "
    "per output line. Keep every accent, breathing, iota subscript, punctuation "
    "mark, capital letter, and the hyphen at a line end. Do not correct, "
    "normalize, modernize, or complete anything; do not join hyphenated words. "
    "If a line is cut off at the top or bottom edge of the strip, skip it. "
    "If the strip has no printed text, output nothing at all. "
    "Output only the transcription, no comments."
)

LINES_SYSTEM = (
    "You proofread OCR of 19th-century printed Ancient Greek (Migne's Patrologia "
    "Graeca) against images of the printed lines. You transcribe exactly what is "
    "printed: never correct the author's Greek, normalize or modernize."
)

LINES_PROMPT = (
    "An OCR engine read the lines below; words a statistical check found suspicious "
    "are marked ⟦…⟧, but other words may be wrong too. For every line, give the whole "
    "line exactly as printed in its image, without the marks. Keep every accent, "
    "breathing, iota subscript, capital, punctuation mark and line-end hyphen as "
    "printed. Answer with JSON "
    '{"lines": [{"id": n, "text": "..."}]} covering every line.'
)

SYNTH_SYSTEM = (
    "You produce a diplomatic transcription of 19th-century printed Ancient Greek "
    "(Migne's Patrologia Graeca) from images of the printed lines."
)

SYNTH_PROMPT = """Below are printed lines of Greek, each with several independent OCR readings (R1, R2, …). The readings are usually right, and where they disagree the image decides; but they can all share a mistake, so always check the image.

Transcribe every line exactly as printed: the letters, accents, breathings, iota subscripts, capitals and punctuation that are on the page, including the hyphen at a line end. This is a diplomatic transcription of an old printing, misprints and all: if the print has a non-standard form (ξ for ζ, a circumflex where an acute is expected, an old spelling), keep it. Never correct, complete or modernize a word. A breathing printed before a capital belongs to the capital (Ἀ, not ’Α). Leave out footnote reference numbers.

Answer with JSON {"lines": [{"id": n, "text": "..."}]}, one entry per line id."""

LINES_SCHEMA = {"type": "object", "properties": {"lines": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
    "required": ["id", "text"]}}}, "required": ["lines"]}
