# The Front Desk scheduler: developer guide

This guide is for people who will run, change or deploy the demo. For a plain-language overview, see the [business guide](business-guide.md).

Nothing has been deployed. Everything below describes running it on your own computer.

## Overview and architecture

A Claude model finds a meeting by calling tools in a loop. Our code runs the tools, sends results back, and checks the final proposal. A person then approves, and plain code in `outbox.py` "sends".

```
browser (web/) --POST /schedule--> server/app.py --> agent.run_agent() --> Claude
               <--SSE events--          |                |  tools.py: eight tools, none can send
                                        |                |  world.py: people, rooms, calendars, time zones
                                        +--> server/sessions.py (per-visitor outbox + proposals)
                                        +--> outbox.py (approve / reject / dry-run / undo)
                                        +--> server/replay.py (recorded runs when the daily budget is spent)
```

- `agent.py`: the loop (`run_agent`, a generator of events) and the command line helpers. Default model `claude-haiku-5-5` (override with `AGENT_MODEL` or `--model`).
- `tools.py`: the tool schemas, the proposal check and the result builders.
- `world.py` and `data/`: eight people in four time zones, four rooms and one week of busy calendars. "Today" is fixed at 2026-10-20, so "next week" is 26 to 30 October 2026.
- `outbox.py`: the only code that "sends" (it records letters in memory). `agent.py` never imports it.
- `server/`: `app.py` (FastAPI), `sessions.py`, `guards.py` (rate limit and token budget), `replay.py`, `record.py`.
- `web/`: the page and `web/replays/*.json`, four recorded runs.
- `eval/`: 16 scenarios, a runner, the scorer, two measured result sets and `NOTES.md`.

**The eight tools.** `list_people`, `list_rooms`, `get_busy_times`, `find_open_slots`, `place_hold`, `release_hold`, `submit_proposal`, `ask_question`. None of them can send. The last two are the two ways a run can finish. `find_open_slots` does all calendar and time-zone arithmetic in code (up to 10 slots, 15-minute steps).

**The proposal check.** `tools.validate_proposal` runs on every `submit_proposal`: the `hold_id` must be a hold placed in this run and still held; code re-checks that everyone is free and at work and that the room is big enough; the summary must be non-empty text; `reasons` must be a non-empty list of text; `tradeoffs` must be a list of text; and none of them may contain `<parameter` or `</` (the leaked-markup check). A failed check gets one retry with the exact errors. A second failure ends as an unable result.

**Code-computed fields versus Claude's note.** `build_result` fills the slot (`start_utc`, `end_utc`, `duration_minutes`), the room and each attendee's `local_start` and `local_end` from the hold and the world, not from anything Claude wrote. Only `summary`, `reasons` and `tradeoffs` are Claude's words, shown as "Claude's note". They are not verified and may mention a time that nothing checked. Do not claim that every time on the page is computed by code.

**Why a leaked-markup check exists.** In the first measured run (79%), Claude wrote its reasons inside the summary text as `<parameter>` markup in 25 submissions, so the real `reasons` field was empty. It did not omit them. The final tool was split into `submit_proposal` and `ask_question` (approved by the user), and the re-run scored 98%. The leaked-markup check and the schema reordering (summary last) were added after both runs, so their effect is unmeasured. See `eval/NOTES.md`.

## Quick start

Requires a recent Python 3 (built on 3.12). Put your key in a `.env` file in the repo root, which is gitignored: one line, `ANTHROPIC_API_KEY=` followed by your key. Never commit it or paste it into a command.

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
set -a; source .env; set +a                      # loads the key into this shell only
.venv/bin/python cli.py "Find 45 minutes next week for Priya and Tom"
.venv/bin/python -m uvicorn server.app:app       # then open http://127.0.0.1:8000
.venv/bin/python -m pytest -q                    # no key needed, no model calls
```

## Expected behavior

The command line prints each tool call, then the result. For a simple request it lists people and rooms, finds open slots, places a hold and submits a proposal. The proposal prints the code-computed lines first (each attendee's local time, the room), then "Claude's note" with the summary, reasons and trade-offs. It then asks you to type approve, reject or dry-run. An impossible request (for example a meeting inside working hours in both Singapore and New York) ends as a question.

**Events.** `run_agent` yields dicts, and `/schedule` sends each as one SSE `data:` line of JSON:

| type | fields |
|---|---|
| `tool_call` | `id`, `name`, `input` |
| `tool_result` | `id`, `name`, `output` |
| `result` | `result`, `usage` (`input_tokens`, `output_tokens`), `turns`, `proposal_retries`, `elapsed_seconds` |
| `notice` | `message` (server only: replay mode, or a crash) |

The last event of `run_agent` is always exactly one `result`. Over `/schedule`, a server crash instead ends the stream with a `notice` and no result.

**Statuses.** `proposed`, `question` or `unable`.

**The five unable reasons.** An `unable` result has a `reason` that starts with one of:

1. `Could not start the agent` (for example no API key or missing data files).
2. `The model call failed`.
3. `Internal error`.
4. `Could not produce a valid proposal` (the proposal check failed twice).
5. `Ran out of steps` (12 model calls without a valid final call).

## API reference

**Limits**

| Limit | Value |
|---|---|
| Request length | 500 characters (also the clarification) |
| Requests per visitor | 5 per 60 seconds |
| Daily token budget | 1,500,000 tokens |
| Tokens reserved per run | 45,000 |
| Model calls per request | 12 |
| Output tokens per model call | 2048 |
| Search date range | 31 days |
| Undo window | 10 minutes (600 seconds) |
| Session expiry | 30 minutes idle (1800 seconds) |
| Sessions kept | 500 (least recently used is dropped) |

**Sessions.** The first `/schedule` response (the only rate-limited route that creates sessions) sets a cookie `sid` (random, `HttpOnly`, `SameSite=Strict`, 30-minute max age). It names a private space in server memory holding that visitor's outbox and the proposals the server made for them. The browser never sends a proposal. It sends only the `proposal_id` (such as `prop-1`) the server attached to a proposal it produced, so a visitor cannot approve something the scheduler never proposed, or something belonging to another visitor. An unknown or expired cookie gets a fresh session only on `/schedule`. Every other route (`/api/world`, `/api/outbox`, `/approve`, `/reject`, `/dry-run`, `/undo`) never creates a session, so a flood of cookieless requests cannot push real visitors out: `/api/world` sets no cookie, `/api/outbox` returns an empty list, `/approve`, `/reject` and `/dry-run` return 404, and `/undo` returns 409.

**POST /schedule** streams events. Body: `{"request": "...", "clarification": "...", "sample_id": "straightforward-morning-sync"}` (`clarification` and `sample_id` optional; unknown fields give 422).

```
curl -N -X POST http://127.0.0.1:8000/schedule -H 'Content-Type: application/json' \
  -d '{"request": "Find 30 minutes next week for Priya and Tom. Mornings only."}'
```

422 for an empty or too-long request, 429 past the rate limit. A `proposed` result gets an added `proposal_id`. When the daily budget is spent it replays the recording named by `sample_id`, or sends a notice asking for a sample.

**POST /approve** body `{"proposal_id": "prop-1"}`. Re-checks the slot, then records the send. Returns `{"sent": {...}, "outbox": [...]}`. 404 if the id is unknown, 409 if someone is no longer free. The proposal is used up.

```
curl -b 'sid=YOUR_COOKIE' -X POST http://127.0.0.1:8000/approve -H 'Content-Type: application/json' \
  -d '{"proposal_id": "prop-1"}'
```

**POST /reject** same body. Returns `{"rejected": true}`, 404 if unknown. The proposal is used up.

**POST /dry-run** same body. Returns the invites and `still_free` without changing anything; the proposal stays usable. 404 or 409 as above.

**POST /undo** body `{"send_id": "send-1"}`. Cancels a send within 10 minutes. Returns `{"cancelled": {...}, "outbox": [...]}`. 409 if there is nothing to undo or it is too late.

**GET /api/world** returns the week, people, rooms and busy blocks (titles are not included).

**GET /api/outbox** returns `{"sent": [...]}` with `undo_seconds_left` for each.

**GET /api/samples** returns the four samples as `id`, `label`, `request`.

```
curl http://127.0.0.1:8000/api/samples
```

## Data formats

**Result.** `{"status", "summary", "reasons", "tradeoffs", "hold_id", "start_utc", "end_utc", "duration_minutes", "room": {"id", "name"}, "attendees": [{"id", "name", "time_zone", "local_start", "local_end"}], "question", "reason"}`, with unused fields null or empty.

**Send.** `{"send_id", "invites": [{"person_id", "to", "when"}], "room": {"id", "name"}, "start_utc", "end_utc"}`. Everything in a send is computed from the world.

**Data files.** `data/people.json` (id, name, role, time zone, working hours and days), `data/rooms.json` (id, name, capacity, equipment) and `data/calendars.json` (busy blocks).

**Recording.** `web/replays/<id>.json` holds `id`, `label`, `request`, `model`, `recorded_on` and `events`. The four samples are `straightforward-morning-sync`, `time-zones-london-new-york`, `tight-four-people-two-regions` and `impossible-singapore-new-york`.

**Replay mode and recording.** Replay serves a saved run with a short delay between events. To re-record (needs the key, costs a few cents):

```
.venv/bin/python -m server.record          # asks before spending; --yes skips the question
```

Nothing is saved unless all four runs end as expected and pass the same checks as the eval. A bad run never overwrites a good file.

**Eval commands.**

```
.venv/bin/python eval/run_eval.py --runs 3     # real model calls; costs money
.venv/bin/python -m pytest -q tests/test_scoring.py   # free: checks the scorer
```

Results are in `eval/results.md` (98% success, 0% bad proposals, 100% questions when needed, median 6.5 s, average 3.8 model calls), the earlier `eval/results-first-run.md` (79%) and `eval/NOTES.md` (the corrected diagnosis). This is a 16-scenario development set we wrote ourselves, run 3 times each. "Sent without approval: 0" holds by design (the AI has no sending tool) and is checked by tests; it is not a measured achievement.

## Extending

- **Another person or room.** Add to `data/people.json` or `data/rooms.json` and give them busy blocks in `data/calendars.json`. `tests/test_data.py` checks the files.
- **Another tool.** Add a function and a dispatch entry in `tools.py` and a schema in `TOOL_SCHEMAS`. Keep it read-only or hold-only; never add anything that sends.
- **More scenarios.** Add to `eval/scenarios.json`, then re-run the eval.
- **A different model.** `AGENT_MODEL=...` or `--model`. Re-run the eval before trusting it.

## Testing

Run `.venv/bin/python -m pytest -q`. None of the tests call the model; they use fakes.

| File | What it covers |
|---|---|
| `tests/test_agent.py` | The loop with a fake model: retries, step cap, error handling, request-tag neutralising. |
| `tests/test_cli.py` | The command line: printing, approve, reject, dry-run. |
| `tests/test_contrast.py` | Page text colours meet 4.5:1 contrast in both themes. |
| `tests/test_data.py` | The demo people, rooms and calendars are well formed. |
| `tests/test_docs.py` | These guides and the README: sections, links, numbers, limits, contact. |
| `tests/test_guards.py` | Rate limiter and token budget, including the atomic reserve. |
| `tests/test_hooks.py` | Booked meetings count as busy; read helpers for the grid and outbox. |
| `tests/test_outbox.py` | Approve, reject, dry-run and undo, including the re-check and the 10-minute window. |
| `tests/test_record.py` | The recorder saves nothing unless every sample is good. |
| `tests/test_replays.py` | The committed recordings are well formed. |
| `tests/test_scoring.py` | Grading and the bad-proposal checks. |
| `tests/test_server.py` | The endpoints, limits, replay switch, safe errors and headers. |
| `tests/test_sessions.py` | Per-visitor spaces, expiry and the session cap. |
| `tests/test_tools.py` | The tools, the proposal check and the leaked-markup check. |
| `tests/test_web_static.py` | Static checks of the page, including honest copy. |
| `tests/test_world.py` | Time zones, working hours, free-time checks and slot search. |

## Security model and deployment

Nothing has been deployed. These protections exist in code:

- The key stays on the server; the browser only sees events.
- The AI has no sending tool. Only `outbox.py` records a send, after a person calls `/approve`, and it re-checks the slot first.
- The request is treated as untrusted data and wrapped so it cannot close its own tag.
- The browser sends only a `proposal_id`, looked up in that visitor's own session.
- Rate limit and daily budget are in memory and per server instance, so on serverless hosting they are best effort. Replay mode is the cost backstop.
- The client address comes from platform headers or the last `X-Forwarded-For` entry; off a trusted proxy this can be spoofed.
- Security headers and a strict Content-Security-Policy are set on every response, and the auto API docs are off.
- A crash reaches the browser only as a generic notice.

Before deploying:

- Use a dedicated API key with a spend limit at the AI provider, set as a host secret (never in the repo), and re-run the eval.
- Serve over HTTPS and mark the session cookie `Secure` (it is not marked now).
- Enable HSTS at the host.
- Set a request-body size limit at the proxy or host.
- Replay mode sleeps inside a thread (`time.sleep` in a sync generator), so many simultaneous replays can exhaust the server's thread pool. Make replay async or raise the thread limit first.
- Sessions are in memory per instance, so a visitor can lose their outbox if requests reach different instances or the server restarts.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Could not start the agent` | No `ANTHROPIC_API_KEY` in the environment; load `.env` first. |
| `The model call failed` | Network, a wrong model name, or an API error. |
| `Ran out of steps (12)` | The model kept looking; try a more specific request. |
| `Could not produce a valid proposal` | The proposal failed the check twice (a missing reason, a leaked tag, a stale hold). |
| Every request replays a recording | The daily budget is spent; restart the server to reset it. |
| 429 | More than 5 requests in 60 seconds. |
| 404 on approve | Unknown, used or expired `proposal_id` (or the session expired). |
| 409 on approve | Someone or the room is no longer free. |
| 409 on undo | Nothing to undo, or more than 10 minutes have passed. |
| Page loads but scripts are blocked | The Content-Security-Policy; the inline script hash is computed from `web/index.html`. |

## Getting help

Open an issue or send a message through https://github.com/thejaredchapman.
