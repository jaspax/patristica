<!-- Machine translation of one work (#422). Opened by the nightly agent (#425); needs no issue. -->

## Machine translation: {title} ({author})

- **Original:** `{original work id}` ({language}, {edition}, {licence})
- **MT work:** `mt-eng/{original work id}`, file `data/raw/mt-eng/{path}`
- **Size:** {chars} source characters, {units} paragraphs, {requests} requests
- **Model:** {model that answered}, prompt {prompt version}

### Why this work
{One or two sentences: its importance in its tradition, and whether English is already widely available elsewhere.}

### English elsewhere
{Checked before translating: a public-domain English translation (ANF/NPNF, CCEL, older Loeb…) and where, or "none known"; widely available modern English, if any. A public-domain one means #341, not this PR.}

### Usage
{5-hour and 7-day utilization before and after; time taken.}

### Spot-check
{Three paragraphs compared with the source: anything omitted, summarized, refused or garbled; OCR problems in the original.}

### Data-quality issues
{Issues filed or found for this work's source (links), or "none". Every source problem the spot-check or the translation's `[?]` points at gets an issue.}

### After merging
Run `scripts.pipeline` (normalize, anchor on the original, embed for alignment, align, build_index, export). The work gets no search vectors.

<!-- For the night's curation PR (branch mt-curation/{date}), use this section instead of the ones above:

## Machine-translation curation, {date}

Edits to `patristica/data/mt_exceptions.csv` and `patristica/data/mt_blocked.csv` from the nightly run (#425). Nothing to run after merging: the next night's candidates follow these tables.

### Exceptions added
- `{work id}`: {what differs from the original, and where (refs)}

### Blocked
- `{work id}`: #{issue}, {why translation is impractical}

### Unblocked
- `{work id}`: #{issue} is closed
-->

🤖 Generated with [Claude Code](https://claude.com/claude-code)
