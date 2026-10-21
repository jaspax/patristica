# Passage alignments

Which passages of the versions of a work render the same text (#179): the
same passage in every language and edition of a work. Written by
`scripts.align`; the method is in `patristica/alignment.py`, the format and
helpers in `patristica/alignment_store.py`. The vectors it is computed from
(`data/embeddings/`) are not tracked, so the files are.

## Layout

One file per work-level version group (`patristica/versions.py`, #178) with
at least two members that have vectors. The Scripture book group `book:gen`
is `book/gen.json`; any other group is `{group id}.json`, the group id being a
work id (`ogpg/vol-032/epistulae.json`). Group ids can change when a version
link is added; `scripts.align` then writes the new file and, on a full run,
deletes the old one.

`_fingerprint.json` is not an alignment (`iter_store` skips `_` files). It
records the hash of the aligner's code and, per version group with two or more
publishable members, what it was aligned from (#130): the members, for a
Scripture book a hash of every member's versification-mapped refs, and why it
was skipped if it has no file (fewer than two members with vectors):

```json
{"align": {"code": "<16 hex>"},
 "groups": {"book:gen": {"members": ["kjv/gen", "oshb/gen", …], "keys": "<16 hex>"},
            "<group id>": {"members": […], "skipped": "fewer than two members with vectors"}}}
```

`tests/test_align_fingerprint.py` (`scripts.align.check_groups`) fails when the
code hash is stale, or a group is new, gained or lost a member, had its refs
moved by a versification change, or lost its file without a recorded skip.
None of this needs the vectors, so CI checks it.

## File format

One JSON object, one member per line:

| field | meaning |
|---|---|
| `format` | `1` |
| `group` | the version group id |
| `pivot` | the member every other member was aligned with; groups are numbered in its order |
| `groups` | number of alignment groups |
| `inputs` | hash of everything the alignment depends on; `scripts.align` skips a group whose hash still matches |
| `run` | the run that wrote the file: `aligner` version, `method`, `params`, embedding `models`, `date`, `script` |
| `members` | one row per member, by work id |

Each member row:

| field | meaning |
|---|---|
| `work_id`, `units` | the work, and its number of units (chunks of its normalized file) |
| `ids` | hash of its chunk ids in order (`ids_sha`): a loader uses the spans only while the work's units are unchanged |
| `inputs` | hash of its units, the vectors used for them and their ref keys |
| `spans` | one token per unit, in normalized order: `.` in no group, `+` the next group, `+N` / `-N` that many groups on (or back) from the last one used, `=` the same group as the unit before |
| `conf` | one digit per group the member is in, in order of first appearance: confidence 0–9 (tenths) |

A member's units in one group are contiguous. A group's span in the pivot is
the pivot's units in it; the pivot's confidence is the best of the others'.
Spans below confidence 5 (`MIN_CONFIDENCE`) are flagged: they stay in the
file but are not used as groups. Scripture's verse-by-verse alignment is
`+++…`, one byte a verse.

```python
from pathlib import Path
from patristica import alignment_store as store

a = store.load(Path("data/alignments"), "book:ps")
a.groups_of()   # {group: {work_id: (first unit, last unit + 1)}}
```
