# Notes on the two measured eval runs

Both runs used `claude-haiku-5-5`, 16 scenarios x 3 runs = 48 graded runs. The raw files are kept exactly as measured.

| Run | Files | Success | Unable | Proposal retries |
|---|---|---|---|---|
| First run (one combined final tool) | `results-first-run.*` | 79% | 10 | 15 |
| Second run (final tool split in two) | `results.*` | 98% | 1 | 2 |

Both runs had a 0% bad-proposal rate: code never let a double-booked or out-of-hours proposal through.

## What actually went wrong in the first run

The earlier story was: "the schema only required `status`, so the model left out `reasons`." That is not what the recorded tool calls show.

The model did write reasons. They leaked into the `summary` text as tag-like markup, for example `...Nothing has been sent yet.</summary>` followed by a `<parameter name="reasons">[...]` block. Code saw an empty `reasons` field, rejected the proposal, and most retries failed the same way.

Counts, checked directly in `results-first-run.json` and `results.json` (every `submit_proposal` call in `rows[*].tool_calls`):

- First run: 63 `submit_proposal` calls. 37 had no `reasons` field. Of those, 25 had the leaked markup in `summary`. The other 12 were questions sent through the old combined form (`status: "question"`), which never needed reasons, so they were not leaks.
- Second run: 38 `submit_proposal` calls, 3 leaked: `time-zones-three-regions` run 1 (both tries, so it ended as the one unable run) and the first try of `time-zones-london-new-york` run 1 (which recovered on the retry).

Splitting the form into `submit_proposal` and `ask_question` made the leak much rarer (25 down to 3), which is why the score rose from 79% to 98%. We still do not know why the model sometimes leaks.

## Where the earlier wrong diagnosis still appears

The message of commit `8d2bfd8` ("every failure a missing reasons field ... because the combined submit_proposal form only required 'status'") and the brief for the split-form change state the earlier diagnosis. Git history is not rewritten, so this note is the correction.

## The summary check came after both runs

After both runs, the proposal check was hardened: a `summary`, reason or trade-off that contains `<parameter` or `</` is rejected with a message telling the model to send reasons as their own field, and the schema now lists `summary` last. Neither measured run reflects that check, so a new run would be needed to measure its effect.
