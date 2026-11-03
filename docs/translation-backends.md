# Translation backends

`scripts.translate` (#93) sends every request through one harness: `Clients.call()` in `scripts/embed_eval/translate.py`. The prompts, batching, editorial stripping, hashing, reuse, response checks and provenance are the same whichever model answers. Only the transport differs (#417).

| `--model` | Model | Transport | Pays with | Reports |
|---|---|---|---|---|
| `sol` (default) | GPT-6.1 Sol | OpenAI API | `OPENAI_API_KEY`, per token | cost |
| `opus` | Claude Opus 5.5 | Anthropic API | `ANTHROPIC_API_KEY`, per token (about 3× Sol) | cost |
| `local-opus` | Claude Opus 5.5 | local `claude -p` | the Claude subscription's usage windows | usage windows |

Sol and Opus translate the rare languages equally well (#84: fidelity 4.44 and 4.48 of 5, no hallucinations), so the choice is about cost and where the run happens, not quality. Each row's provenance records the model that answered (`claude-opus-5-5` for both Opus backends), so mixing translators within a language needs no re-run.

## Which backend to use

- **On a machine logged in to the subscription** (the pipeline machine, an agent working with the owner in Claude Code): use **`local-opus`**. It is the pipeline's default (#601): `scripts.pipeline --pay` runs `scripts.translate --model local-opus --workers 4`, with no API key. For a big batch, translate first by hand, so you can watch the usage windows as below; the pipeline's translate step then finds nothing pending:

  ```bash
  uv run python -m scripts.translate --usage                              # usage now
  uv run python -m scripts.translate --model local-opus --dry-run        # what would be sent
  uv run python -m scripts.translate --model local-opus --workers 4      # run (watch the log)
  uv run --extra pipeline python -m scripts.pipeline --dry-run           # translate: nothing to do
  ```

- **Where there is no subscription login** (CI, the droplet, a cloud session): use **Sol**, `scripts.pipeline --pay --translate-model sol`. It retries what Sol's content filter blocks with `opus` through the API. `--translate-model opus` uses Opus through the API alone.
- **When local usage runs short** (see below): switch to Sol for the rest. Sol costs money: report its `--dry-run` estimate to the owner and wait for an OK, unless they already approved the spend for this run.

`local-opus` runs `claude -p` with the request's system prompt (`--system-prompt`), JSON schema (`--json-schema`), model and effort. The passages go on stdin. It runs with no tools, settings, MCP servers or session, from an empty directory, so no project context (CLAUDE.md, memory) reaches the model. One subprocess per request, so `--workers 4` is plenty: more mostly burns the 5-hour window faster.

## Usage is feedback, not a gate

The harness never stops on usage. With `local-opus` the run logs the subscription's windows next to its cost, after every 50 requests and at the end:

```
50/1200 requests, $0.00 so far; subscription usage 5-hour 34% (resets Thu 22:00 UTC), 7-day 61% (resets Sat 08:00 UTC)
```

`--usage` prints the same line from one tiny Haiku request. The figures come from the CLI's `rate_limit_event` (`limits` in each usage dict). That event isn't a documented interface: if the line goes missing, treat usage as unknown and pace conservatively instead of assuming headroom.

The controlling agent decides whether to go on, pause or switch, with a projection, not a fixed percentage:

1. **Measure the rate.** Note `--usage`, run a pilot (`--max-requests 40` or so, enough to move the 5-hour figure by several points), and note it again. That gives the share of each window per request, `r5` and `r7`. Windows are reported in whole percent, and everything else on the subscription (your own session included) counts too, so a pilot that moves a window by 1 point tells you little. Re-estimate from the progress lines as the run goes on: the rate depends on the language and the passage length.
2. **Project the 7-day window**, the one that matters for large jobs. With `R` requests left, the run ends at about `current7 + R × r7`. Add an allowance for the owner's other use until the job ends or the window resets, whichever comes first. If the job will still be running at the weekly reset, only the requests before the reset count against this week. Go on only if the projection stays below 100 %.
3. **Project the 5-hour window** at the run's pace. At `N` requests per hour and `t5` hours until the reset, it reaches about `current5 + N × t5 × r5`, and refills after the reset. A 5-hour projection over 100 % doesn't make the job too big: it means slow down (`--workers`) or stop and resume after the reset. A stopped run resumes where it left off.
4. **Stop if either window is projected to exceed its limit.** Then choose: wait for the reset when it is soon and the job can wait (schedule a wakeup for just after it), or switch the rest to Sol (with the owner's OK on cost, above). Stop between requests with an interrupt: finished works are written, and only the requests in flight are lost.

Extra usage keeps the owner's interactive work going when a window runs out. It is not a budget for bulk runs: it is billed at API rates, so a bulk run in overage costs more than Sol would. Count a projection into overage as exceeding the limit, and stop at once if the log says `using extra usage`.

The decision is the agent's. Always leave room for the owner's work. If the projection is close, prefer the cheaper risk: finish the current work, stop, and say what is left and when the windows reset.

## Machine translations for readers

`scripts.machine_translate` (#423) uses the same backends to translate whole works, by chapter, into English for readers: the `mt-eng` works of `docs/machine-translation.md`. Its default is `local-opus`, and it logs the same usage line after every few requests and per work. The method above applies per work: project the work's requests before starting it. The nightly agent (#425) does that with `scripts.nightly_budget`, which keeps the usage samples and computes the projection, including the weekly reserve measured from the owner's daytime use (`docs/machine-translation.md` → "Nightly runs").
