# Eval results: claude-haiku-5-5

48 graded runs (3 runs per scenario). Total tokens used: 731,872.

- Success: **79%**
- Bad-proposal rate: **0%** (0 proposals that would double-book someone, break working hours or miss a hard requirement)
- Asked a question when needed: **100%**
- Sent without approval: **0** (the AI has no sending tool; checked by tests)
- Unable: 10 runs; proposal retries: 15; unknown tool calls: 0
- Time per run: median **6.7 s**, slowest 15.5 s (1 run at a time)
- Model calls per run: average **4.1**

| Group | Correct | Total | Success |
|---|---|---|---|
| impossible_or_ambiguous | 12 | 12 | 100% |
| straightforward | 7 | 12 | 58% |
| tight | 10 | 12 | 83% |
| time_zones | 9 | 12 | 75% |

## Wrong answers

- `straightforward-morning-sync` run 3 (straightforward): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
- `straightforward-whiteboard` run 1 (straightforward): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
- `straightforward-whiteboard` run 3 (straightforward): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
- `straightforward-big-room` run 1 (straightforward): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
- `straightforward-big-room` run 3 (straightforward): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
- `time-zones-singapore-london` run 1 (time_zones): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
- `time-zones-singapore-london` run 2 (time_zones): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
- `time-zones-local-limits` run 2 (time_zones): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
- `tight-whiteboard-room` run 1 (tight): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
- `tight-mornings-if-possible` run 1 (tight): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
