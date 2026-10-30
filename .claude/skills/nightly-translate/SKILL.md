---
name: nightly-translate
description: The nightly machine-translation run (#425). Started unattended by scripts/nightly/run.sh at 22:15 America/Chicago; picks untranslated works, machine-translates them on the Claude subscription with scripts.machine_translate, opens one PR per work and reports on issue #429. Use only when started for the nightly run, or when the owner asks for a supervised run.
---

# Nightly machine translation

You are the nightly agent of Patristica's machine translations (umbrella #422, runner #425, design `docs/machine-translation.md`). The owner is asleep: nobody answers questions or permission prompts tonight. A command that isn't allowed by `.claude/settings.json` is denied, so don't look for workarounds. How to stay inside the allowlist:

- **One command per Bash call.** No `&&`, `;` or pipes into commands of your own choosing: if any part of a compound command isn't allowed, the whole call is denied. (The second and third pilots each lost a night's start this way, #429.) A redirect into `logs/` is fine.
- **Use the commands as this skill writes them.** Don't add flags or extra checks that aren't shown here (`git branch --show-current`, `git rev-parse` …): `git -C .claude/worktrees/nightly-mt status` tells you the branch.
- **A denied check is not a stop.** If an optional or diagnostic command is denied, note it verbatim for the report and carry on without it. **Stop only when a required step is denied**: the budget sample, translating, committing, pushing, opening the PR, or posting the report. Then say so in the report (step 5 below), which `gh issue comment 429` can still post.

Your job tonight:
- translate a few well-chosen works, with **one PR per work**;
- curate as you go: exceptions for divergent ancient versions, data-quality issues, blocked works. All curation edits go in **one curation PR** for the night;
- post **one report comment on issue #429**. Then stop. You are a coordinator, so keep your own token use small: `scripts.machine_translate` does the translating (Opus through `local-opus`), and `scripts.nightly_budget` does the arithmetic. Don't read whole works into your context.

**Never:**
- translate with `--model sol` or `--model opus`: they cost money;
- run `scripts.pipeline`, `normalize`, `anchor`, `embed` or `build_index`;
- push to `master`, force-push, or amend;
- edit files other than `logs/**`, and, on the curation branch only, the worktree's `patristica/data/mt_exceptions.csv` and `patristica/data/mt_blocked.csv`. The translator writes the raw MT file itself.

Paths: you run in the **main checkout** (the working directory, which has all the data). The night's worktree is always `.claude/worktrees/nightly-mt`. `{date}` is tonight's local date (`date +%F`).

## 1. Start and budget

1. Record the start: `uv run python -m scripts.nightly_budget sample --tag start`.
2. Get the projection: `uv run python -m scripts.nightly_budget plan`. Read:
   - `deadline`, `hours_left`;
   - `five_hour` (utilization, `hours_to_reset`, `headroom`);
   - `seven_day`;
   - `weekly_allowance_tonight` and `remaining_tonight`: what you may spend of the 7-day window tonight. It leaves room for the owner's measured daytime use until the weekly reset (`daytime_source`: `measured`, or `default` until there are a few nights of history), plus a 5 % margin.
   - `rates`: 5-hour and 7-day usage, and hours, per 1k source characters, measured from earlier works.
3. **Stop now**, with the report (step 5), when any of these holds:
   - `using_extra_usage` is true;
   - `remaining_tonight` is under 0.01;
   - less than an hour is left to the deadline.

The decision to go on is yours, but make it from the projection, not from a fixed percentage. Before each work, run `plan --chars N` with the work's source characters. `work.fits` says whether it is projected to fit, `reasons` says why not, and `unknown` lists what isn't measured yet. If you are close to a limit, take the cheaper risk: stop, and say what is left and when the windows reset.

**No history yet** (`unknown` non-empty): do a pilot. Translate one small work (under about 15k characters) first, then re-plan: the `before`/`after` samples around it give the rates.

## 2. Prepare the worktree (once per night)

```bash
scripts/nightly/with-https.sh git fetch https://github.com/jaspax/patristica.git master:refs/remotes/origin/master
git worktree list            # if .claude/worktrees/nightly-mt is left from a failed night:
git worktree remove .claude/worktrees/nightly-mt --force
git worktree prune
git worktree add .claude/worktrees/nightly-mt origin/master
uv --directory .claude/worktrees/nightly-mt sync --locked --extra dev --extra eval --extra api --extra deploy --extra index
scripts/nightly/with-https.sh uv --directory .claude/worktrees/nightly-mt run python -m scripts.data pull --job tests
```

The pre-push hook runs the unit tests in that worktree, which is why it needs the extras and the LFS files the tests read.

## 3. Choose works

Keep the night's curation notes in `logs/mt-curation-{date}.md` as you go: exception rows to add, blocked rows to add or remove, and the issues filed. They become the curation PR in step 5. The candidate list reads master's tables, so anything you add tonight takes effect after the owner merges it. Until then, skip a work you have just blocked.

0. **Blocked works whose issue is closed.** Read `patristica/data/mt_blocked.csv` (`work_id,issue,reason`). For each row, check `gh issue view {issue} --json state --jq .state`. When it is `CLOSED`, note the row for removal, so the work is a candidate again on a later night.
1. **Resume first.** If `logs/mt-partial/` holds an unfinished work (`ls logs/mt-partial/`), finish it before starting anything new.
2. **Candidates:** narrow the list with the options of `scripts.machine_translate candidates` first (#432): `--work ID…` (details of given works), `--lang`, `--genre`, `--exclude-source`, `--min-chars`/`--max-chars`, `--sort chars` (smallest first), `--limit N`, and `--json` (one object per line with path, requests and `versions`). Plain output columns: work id, language, characters, author, title. Examples:
   - `uv run python -m scripts.machine_translate candidates --lang grc --max-chars 60000 --limit 200 > logs/mt-candidates.tsv`, then Read that file.
   - `uv run python -m scripts.machine_translate candidates --json --work W1 W2` for the works you shortlist.
   - The full list is about 2,000 works, so **don't read it whole**. `grep`, `awk`, `head` and `wc` on files under `logs/` are fine for searching it by author or title. The Grep and Glob tools may be unavailable in this session; use `grep` and `ls` through Bash.
   - Leave out works that already have an open PR: `gh pr list --label machine-translation --state open --limit 200`.
3. **Keep a shortlist** across nights in `logs/mt-shortlist.md`: about 30 next candidates with a line each on why. Update it each night instead of starting over.
4. **Judgement:**
   - First: well-known, influential works, or works important within their tradition. Examples: major works of the great Fathers, conciliar acts, core liturgical texts, foundational Syriac, Coptic and Armenian authors.
   - Later: works whose English is already widely available elsewhere (in print, on the web, in standard series).
   - These two pull in opposite directions, so weigh them, and say how in the PR.
   - **If a public-domain English translation exists** that the library could ingest (ANF/NPNF, CCEL, Loeb out of copyright and the like), don't translate it. Comment on #341 instead (`gh issue comment 341 --body "…"`) with the work id and where that English is.
   - **Prefer clean editions.** If a work's source text is badly garbled OCR (look at a few paragraphs of its normalized file with Read), skip it and note it in the report.
   - **Prefer works that fit tonight** (`plan --chars N`), unless it is a resumed one. A very long work can span nights: the partial store keeps finished requests. Start one only when it is clearly worth it.
5. **Derived versions: exceptions.** We translate the original, not later versions of it, unless a version diverges from it in ways that matter to readers and researchers. A candidate's `versions` (in `candidates --json`) lists the other non-English members of its group: language, source, `translation_of`, characters, and whether each is derived or another edition. `uv run python -m scripts.machine_translate review-versions --json > logs/mt-review-versions.jsonl` lists the derived versions with no exception row, in groups with no published English. Those are the ones to weigh, a few per night.
   - When a work you consider has other ancient versions, or you take a derived version from that list, **sample both**: a few sections at the start, middle and end (Read of `data/normalized/{path}`), not the whole work.
   - For Syriac, Coptic, Armenian, Ge'ez and Church Slavonic, the stored search translations in `data/translations/{path}` help you read the version.
   - Reading costs usage too: budget it like a work, and keep it to what decides the question.
   - If the version diverges in ways that matter (added or missing sections, a different recension, theologically significant rewording), note a row for `patristica/data/mt_exceptions.csv`: `work_id,reason`. The reason must be concrete: what differs, and where (refs).
   - If the version is a close translation, say so in the report and move on.
6. **Data-quality problems** you find while reading a source get a GitHub issue each. Examples: OCR damage, a mis-split or merged work, a wrong attribution or language, missing text, unmarked editorial material (#236).
   - **Search first**, so nothing is filed twice: `gh issue list --state all --search "{work id}"`, and a search on the problem's key words.
   - When it is new, write the body to `logs/dq-{slug}.md`: the work id, what is wrong, two or three refs with short quotes, and what a fix might be. Then file it:
     ```bash
     gh issue create --label data-quality --label "lang: {language}" --title "{work id}: {problem}" --body-file logs/dq-{slug}.md
     ```
     Language labels: `grc` → `lang: greek`, `lat` → `lang: latin`, `syc` → `lang: syriac`, `cop` → `lang: coptic`, `gez` → `lang: geez`, `hye` → `lang: armenian`, `chu` → `lang: slavonic`, `hbo` → `lang: hebrew`, `got` → `lang: gothic`.
   - **Blocking.** If the problems make translation impractical (too much of the text is garbled or missing, or the work is really several works), don't translate it. Note a row for `patristica/data/mt_blocked.csv`: `work_id,issue,reason`, with the issue you filed or found. Leave the work out tonight and on later nights.

## 4. Each work

Let `W` be the work id, `N` its characters, `P` its normalized path (from the candidates JSON or `data/normalized/_works.jsonl`), and `S` a branch slug: `W` lower-cased with `/` and `.` replaced by `-`.

1. `uv run python -m scripts.nightly_budget plan --chars N`, and go on only if it fits (or for the pilot).
2. `uv run python -m scripts.nightly_budget sample --tag before --work W --chars N`
3. `git -C .claude/worktrees/nightly-mt switch -c mt/S origin/master`
4. Translate, **in the background** (Bash `run_in_background`), and wait for its exit notification instead of polling:
   ```bash
   uv run python -m scripts.machine_translate --output-dir .claude/worktrees/nightly-mt/data/raw translate W --partial-dir logs/mt-partial --workers 3
   ```
   - For a work projected to take more than about an hour, also start a Monitor on its output for `using extra usage|ERROR|Traceback`.
   - Stop the task if extra usage starts, or if the deadline comes before it can finish. Finished requests stay in `logs/mt-partial/` for the next night.
5. `uv run python -m scripts.nightly_budget sample --tag after --work W`
6. If the run failed, note why and go to the next work. Don't retry a failed work more than once a night.
7. **Spot-check.** Read three paragraphs of `.claude/worktrees/nightly-mt/data/raw/mt-eng/P` (beginning, middle, end) against the same refs in `data/normalized/P`. Look for:
   - omissions or summaries instead of translation;
   - refusals or commentary;
   - wrong language;
   - text drifting from the source.

   If it is bad, don't open a PR: say so in the report and keep the file out of git.
8. Commit only that file:
   ```bash
   git -C .claude/worktrees/nightly-mt add data/raw/mt-eng/P
   git -C .claude/worktrees/nightly-mt commit -m "Machine translation: {title} ({W})" -m "Part of #422." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
   ```
9. Push **with the explicit refspec**, never a bare branch name. `switch -c` from `origin/master` makes the branch track master, and a bare `push <url> mt/S` would target master. The hook refuses that, but don't rely on it:
   ```bash
   scripts/nightly/with-https.sh git -C .claude/worktrees/nightly-mt push https://github.com/jaspax/patristica.git HEAD:refs/heads/mt/S
   ```
   - The pre-push hook runs the unit tests (about a minute). If they fail, say so in the report and leave the branch unpushed. Never use `--no-verify`.
10. Open the PR:
    - Fill `.github/PULL_REQUEST_TEMPLATE/machine_translation.md` into `logs/mt-pr-S.md`: why this work, the usage before and after from the samples, the time taken, and the spot-check notes.
    - Then run:
    ```bash
    gh pr create --base master --head mt/S --label machine-translation --title "Machine translation: {title} ({author})" --body-file logs/mt-pr-S.md
    ```
11. Re-plan (step 1.2) and continue with the next work, or stop.

## 5. Finish and report

1. `uv run python -m scripts.nightly_budget sample --tag end`
2. **The curation PR**, if tonight's notes have any table edits. One per night; per-work PRs never touch these tables, so they never conflict:
   ```bash
   git -C .claude/worktrees/nightly-mt switch -c mt-curation/{date} origin/master
   ```
   - Apply the notes to `.claude/worktrees/nightly-mt/patristica/data/mt_exceptions.csv` and `mt_blocked.csv` with Edit. Keep each file's header and row order (by work id).
   - Commit both with `git -C .claude/worktrees/nightly-mt add patristica/data/mt_exceptions.csv patristica/data/mt_blocked.csv` and a commit like the one in step 4.8 ("Machine-translation curation, {date}").
   - Push to `HEAD:refs/heads/mt-curation/{date}` with `scripts/nightly/with-https.sh` (as in 4.9). Validate doesn't read these tables, so the hook only runs the unit tests.
   - Open the PR from `logs/mt-pr-curation-{date}.md`, filled from the template's curation section: each row added or removed, with its reason or the closed issue.
     ```bash
     gh pr create --base master --head mt-curation/{date} --label machine-translation --title "Machine-translation curation, {date}" --body-file logs/mt-pr-curation-{date}.md
     ```
3. Clean up the worktree: `git worktree remove .claude/worktrees/nightly-mt --force`. The branches are on GitHub, and the worktree's checkout is the only thing removed.
4. Write the report to `logs/nightly-mt-{date}.md` and post it: `gh issue comment 429 --body-file logs/nightly-mt-{date}.md`. The report has:
   - **Translated:** each work with its PR link, characters and time.
   - **Curation:** the curation PR link; exceptions added (or versions judged close); works blocked and unblocked.
   - **Data-quality issues** filed tonight (links), and existing ones you found.
   - **Considered and skipped:** with why (open PR, public-domain English noted on #341, blocked, garbled OCR, too long tonight, failed run).
   - **Usage:** 5-hour and 7-day at the start and end, and tonight's weekly allowance.
   - **Why the run stopped:** deadline, 5-hour window, weekly allowance, extra usage, or an error (quote it).
   - **Unfinished work** in `logs/mt-partial/`, if any.
5. **A night that fails early** (a denied command, `gh` or the CLI not working, no usage figures) still posts a short comment on #429 saying what failed. If even that fails, the report file in `logs/` and your final message are the record (`claude agents`, `claude logs`).

End with the report as your final message.
