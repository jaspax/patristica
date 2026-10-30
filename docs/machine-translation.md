# Machine translations

Patristica gives an English **machine translation (MT)** to works the library has no English version of (#422). There are about 2,150 such works, some 284M characters, nearly all Latin and Greek. They are translated gradually, on the Claude subscription, by a nightly agent (#425). This page covers what qualifies, what an MT is in the data, and how it moves through the pipeline. Choosing a translator and watching usage is `docs/translation-backends.md`.

## What gets translated

`patristica/machine_translation.py` decides, and `python -m scripts.machine_translate candidates` lists the candidates with their sizes. A work is a candidate when:

- **Its version group has no English.** Neither a published translation nor an MT, among all versions of the work (`patristica/versions.py`). A published English version always wins: an MT whose group later gains one is *redundant*, and `scripts.export_library` leaves it out of the library.
- **It is the original.** It has no `translation_of`, or its original isn't in the corpus (an Armenian version of a lost Greek work). An ancient version of an original we have isn't translated, unless it diverges from the original in ways that matter to readers and researchers. Such a version is listed in `patristica/data/mt_exceptions.csv` (`work_id,reason`), and is then translated even if its group has English, until English made from it exists.
- **It is the best edition.** Where a group has two originals in one language, only one is translated: critical and digital editions (PTA, First1K, Perseus, CSEL, …) before Migne's OCR (`EDITION_PREFERENCE`).
- **It is publishable and isn't Scripture.** Every Scripture book has English versions, and a Scripture source would need a versification scheme.
- **It isn't blocked.** A work too damaged to translate (severe OCR or source problems) is listed in `patristica/data/mt_blocked.csv` (`work_id,issue,reason`), with the GitHub issue that tracks the fix.

Which candidates go first is the nightly agent's judgement: well-known, influential works and works important in their tradition first, works whose English is already widely available later (#425).

### What the listings show

- **`candidates`**: each candidate lists `versions`, the other non-English members of its version group. Each version has `work_id`, `language`, `source_id`, `translation_of`, its source characters (`chars`) and its `kind`: `derived` (it has a `translation_of`) or `edition` (another original). `--json` gives one object per line.
- **`review-versions`**: the derived non-English versions with no exception row, in groups with no published English. These are not translated by default, because their original is. They are the versions whose divergence an agent should weigh for an exception row.

### Curating the lists

The agents that translate keep the two curated files themselves, in the PR where the decision is made:

- **An exception row** (`mt_exceptions.csv`, `work_id,reason`) is added when reading a version shows it diverges from its original in ways readers and researchers need: a different recension, added or missing sections, a distinct theological reading. Say what differs.
- **A blocked row** (`mt_blocked.csv`, `work_id,issue,reason`) is added when a work's text is too damaged to translate well: OCR that garbles whole passages, columns run together, a source that is mostly apparatus. First file a GitHub issue for the fix, labelled `data-quality` plus the language's `lang:` label, then name it in the row.
- **Other problems found while reading** (a mislabelled work, a wrong attribution, a missing section) get the same kind of issue, even when the work can still be translated.
- **A blocked row whose issue is closed is removed again**, so the work becomes a candidate. Check the rows' issues (`gh issue view N --json state`) when choosing works.

Both files are sorted by `work_id`, every column is required, and an issue is a positive number. `tests/test_machine_translation.py` checks that every row names a work in the corpus.

## What an MT is

An MT is a work of the derived source **`mt-eng`**. Its raw file is `data/raw/mt-eng/{the original's normalized path}`, written by `scripts.machine_translate translate WORK_ID`. Unlike the rest of `data/raw`, it is **plain git, not git-lfs** (`.gitattributes`), so a PR shows the translation itself.

- **`work`**: the original's metadata, in English.
  - `work_id` is `mt-eng/{original id}` and `translation_of` is the original.
  - The author, title, dates, genre, tradition and licence are the original's. Our changes to a text go out under its licence (`DATA_LICENSE.md`).
  - The `edition` begins "Machine translation ({model}, Patristica, {date}) of:".
  - There are no `external_ids`: `translation_of` already joins the version group.
- **`paragraphs`**: one per paragraph of the original, with the original's ref.
  - The original's derived verses are joined back into their paragraph.
  - A work its ingestor delivered as verses keeps them as **`verses`**.
  - Each unit records `source_sha`, the hash of the source text it was translated from.
  - A unit that was editorial as a whole in the original (an added title or heading, #236) is translated and marked editorial again, so readers see it and it is never embedded.
- **`machine_translation`**: provenance. Normalize ignores this key.
  - It records the model that answered, the prompt version, the date, the original's id and path, and the number of requests.

Whether a work is MT is decided by its `source_id` (`patristica.sources.MACHINE_TRANSLATION_SOURCES`), never by a `Work` field: adding a field to `patristica/models.py` would change every ingest stamp (#130). `mt-eng` has no ingestor, so `scripts.status` expects no ingest stamp for it.

## How it is translated

`scripts.machine_translate` sends **paragraphs, not chunks**:

- One request holds a chapter, several short sections, or the whole work: consecutive paragraphs of a section (the ref without its last segment), up to `DOC_MAX_CHARS` (about 20k characters) of source.
- A longer section is split at paragraph boundaries, and each part gets the paragraphs before it as context.
- The prompt (`DOCUMENT_SYSTEM`, `PROMPT_VERSION`) asks for a faithful, complete, fluent translation for readers, one item per numbered paragraph.
- Each response must have every paragraph, none empty, at a plausible length (`RATIO_BAND`). A request that fails is retried once.

A work is all or nothing. Finished requests are kept in `logs/mt-partial/` (gitignored), so a work that stops resumes where it left off, and the raw file is written only when every request is done.

The default translator is `local-opus`, Claude Opus through `claude -p` on the subscription. Its 5-hour and 7-day usage is logged but never enforced. `--model opus` and `--model sol` use the APIs and cost money.

**Staleness.** When an original's text changes, `scripts.machine_translate stale` lists the MT works whose paragraphs no longer match, and `translate WORK_ID --update` re-translates only the requests with a changed paragraph. A change that only moves derived verses doesn't make an MT stale, since its units are paragraphs.

## Through the pipeline

An MT PR adds only the raw file, so it needs no issue (CLAUDE.md, "Branches and pull requests"). The next `scripts.pipeline` run takes it like any new work:

1. **normalize** builds it as a new work of `mt-eng`.
2. **anchor** cuts its derived verses where the original's are (`mt-eng` is in `patristica/data/anchored_sources.csv`, #304). It embeds the MT's segments with Voyage, a few cents a work, and writes their vectors to `data/embeddings`. The original needs current vectors (or, for a rare language, its translation vectors).
3. **embed** keeps its vectors current. They exist for alignment, never for search.
4. **align** aligns it with its original. Their derived verses are cut alike, so the passages pair 1:1 for parallel reading.
5. **build_index** loads its work and chunks but **no vectors**, so vector search never returns it. **Keyword search** skips it too (`api/keyword.py`). Under a hit on its original, the search context may show it as the English after every published version, as `machine: true`, with its `work_id` and `canonical_ref` (`api/context.py`).
6. **export_library** writes `machine_translation: true` on its `index.json` row, and the reader labels it with a disclaimer (#424).

`tests/test_machine_translation.py` checks that every tracked MT names its original in the corpus.

## Disclaimer

The reader shows every MT with a short notice: the English was machine-translated from the original by an AI model, has not been reviewed, and may contain errors, so readers should consult the original for close study (#424).

## Nightly runs

MTs are made by a nightly agent on the Claude subscription, while the owner is away (about 22:00–07:00 US Central, #425).

**How a night goes:**
1. A systemd user timer starts `scripts/nightly/run.sh` at 22:15 America/Chicago.
2. The script runs `scripts.data pull --all` over HTTPS, since a merged data PR leaves the files it changed as git-lfs pointers. A failed pull is logged and the night goes on. It then checks the main checkout (data present, no uncommitted changes, `gh` logged in).
3. It starts a background Claude Code session (`claude --bg`; the coordinator's model is `NIGHTLY_MODEL` in the service file, Opus by default, since Sonnet missed judgement steps in the pilots, #429) running the project skill `/nightly-translate` (`.claude/skills/nightly-translate/SKILL.md`), with `--permission-mode dontAsk`. Only what `.claude/settings.json` allows runs, and anything else is denied, never left waiting on a prompt.

**What the agent does:**
- **Budgets**, using `scripts.nightly_budget`. `sample` records the usage windows in `logs/usage.jsonl`, and `plan [--chars N]` projects the night:
  - the 06:30 deadline;
  - the 5-hour window to its reset;
  - a weekly allowance that leaves the owner's measured daytime use until the weekly reset, plus a margin;
  - usage and time per 1k characters, measured from earlier works.
  The decision is the agent's (`docs/translation-backends.md`).
- **Chooses works** by judgement: important works first, widely translated ones later, clean editions, public-domain English reported on #341 instead of translated.
- **Translates each work** with `scripts.machine_translate` (`local-opus`) in the worktree `.claude/worktrees/nightly-mt`, spot-checks it, and commits it as **one commit on tonight's branch** `mt/{date}-{HHMM}`, pushed after every work. At the end it opens **one PR for the night** (label `machine-translation`, template `machine_translation.md`), with a section per work; the commits tab reviews them one at a time.
- **Curates as it reads:**
  - It samples derived ancient versions against their original, and adds exceptions for those that diverge in ways that matter (`mt_exceptions.csv`).
  - It files `data-quality` issues for problems in a source, searching first.
  - It blocks works those problems make impractical to translate (`patristica/data/mt_blocked.csv`, `work_id,issue,reason`), and unblocks them when their issue is closed.
  - All table edits of a night are one more commit in the same PR.
- **Leaves nothing locally:** the worktree is detached at `origin/master` (no local branches), and it is removed once every commit is pushed. If a push fails, the worktree stays and the next night pushes it first.
- **Reports** with one comment per night on the pinned issue **#429**: what was translated, what was curated, issues filed, what was skipped and why, the usage, and why it stopped.

**In the morning:**
1. Read #429.
2. Review and merge the PRs.
3. Run `scripts.pipeline`.

The pipeline's anchor and embed steps cost a few cents per MT work in Voyage requests.

**Install** (once, on the machine with the data and the subscription login; linger must be on, `loginctl enable-linger`):

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/vibe-coding/patristica/scripts/nightly/patristica-nightly-mt.service ~/.config/systemd/user/
ln -sf ~/vibe-coding/patristica/scripts/nightly/patristica-nightly-mt.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now patristica-nightly-mt.timer
systemctl --user list-timers patristica-nightly-mt.timer     # next run
```

**Operate:**
- Run a night by hand: `scripts/nightly/run.sh` (`--check` runs only the checks).
- Pause: `systemctl --user disable --now patristica-nightly-mt.timer`.
- See the runs:
  - issue #429;
  - `claude agents` (sessions named `nightly-mt-{date}`; `claude logs` / `claude attach` for one);
  - `logs/nightly-mt-runs.log` (start lines and start failures);
  - `logs/nightly-mt-{date}-{HHMM}.md` (each run's report);
  - `logs/usage.jsonl`.
- Unfinished works wait in `logs/mt-partial/` and are resumed first the next night.
