<!-- One night's machine translations (#422), opened by the nightly agent (#425); needs no issue. One commit per work, plus one curation commit if the night edited the tables. -->

## Machine translations, {date}: {N} works

| Work | Original | Chars | Time | Data-quality |
|---|---|---:|---:|---|
| {title} ({author}) | `{original work id}` ({language}) | {chars} | {minutes} | {issue links, or —} |

- **Model:** {model that answered}, prompt {prompt version}. Coordinator: Claude {model}.
- **Usage:** 5-hour {start} → {end}, 7-day {start} → {end}; tonight's weekly allowance {allowance}.
- **Report:** {link to tonight's comment on #429}

Each work is one commit (`data/raw/mt-eng/{path}`), so the PR's commits tab reviews them one at a time.

### {title} ({author})
- **Why this work:** {one or two sentences: its importance in its tradition}
- **English elsewhere:** {public-domain English and where, or "none known"; widely available modern English, if any. A public-domain one means #341, not this PR}
- **Spot-check:** {three paragraphs against the source: anything omitted, summarized, refused or garbled}
- **Source problems:** {issues filed or found (links), or "none"}

{… one section per work …}

### Curation
{Only if the night edited `patristica/data/mt_exceptions.csv` or `mt_blocked.csv` (its own commit); otherwise "none".}
- **Exceptions added:** `{work id}`: {what differs from the original, and where (refs)}
- **Blocked:** `{work id}`: #{issue}, {why translation is impractical}
- **Unblocked:** `{work id}`: #{issue} is closed

### After merging
Run `scripts.pipeline` (normalize, anchor on the originals, embed for alignment, align, build_index, export). MT works get no search vectors. The next night's candidates follow the curation tables once this is merged.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
