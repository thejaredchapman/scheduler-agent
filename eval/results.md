# Eval results: claude-haiku-5-5

48 graded runs (3 runs per scenario). Total tokens used: 658,286.

- Success: **98%**
- Bad-proposal rate: **0%** (0 proposals that would double-book someone, break working hours or miss a hard requirement)
- Asked a question when needed: **100%**
- Sent without approval: **0** (the AI has no sending tool; checked by tests)
- Unable: 1 runs; proposal retries: 2; unknown tool calls: 0
- Time per run: median **6.5 s**, slowest 13.6 s (1 run at a time)
- Model calls per run: average **3.8**

| Group | Correct | Total | Success |
|---|---|---|---|
| impossible_or_ambiguous | 12 | 12 | 100% |
| straightforward | 12 | 12 | 100% |
| tight | 12 | 12 | 100% |
| time_zones | 11 | 12 | 92% |

## Wrong answers

- `time-zones-three-regions` run 1 (time_zones): expected `proposed`, got `unable` Could not produce a valid proposal: reasons must be a non-empty list of text
