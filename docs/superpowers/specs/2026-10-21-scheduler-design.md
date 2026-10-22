# Scheduler ("the doer"): Design Spec

Date: 2026-10-21
Status: Approved by the user in two parts in conversation; pending written-spec review.
Parent spec: `expense-policy-agent/docs/superpowers/specs/2026-10-20-agents-explained-article-design.md` (deliverable 5 in its section 2; requirements in its sections 3 and 8).

## 0. Plain-English summary

A Claude agent that finds a meeting time and a room for several people at a fictional company, pencils it in, and proposes it. It can look and pencil in, but it cannot send anything: when a person clicks Approve, ordinary code sends the invites into a mock outbox. If the request is ambiguous or impossible, it asks a question instead of guessing. It is the article's "doer": medium freedom, real consequences, and the consequence is held by code behind a person.

## 1. Goal and what the demo must show

- The outbox is the consequence. Nothing is "sent" unless a person approves; the agent has no send tool (enforced by design and tested).
- Code checks every proposal before a person sees it: the slot is free for every attendee, inside each attendee's working hours, the room fits and has what was asked for, and the hold matches.
- It handles time zones correctly (including a real daylight-saving gotcha, section 3), conflicting constraints, and impossible requests (by asking a question).
- Dry run shows exactly what would be sent; Undo cancels sent invites within a short window.
- Every run records model calls, tokens and elapsed time, like the other demos.

## 2. User decisions

- Approval design: **the AI proposes, code sends** (no send tool for the AI; approval and sending are plain code).
- Full demo kit, built as two plans like the research analyst: Plan 1 core (world, calendar maths, tools, checker, loop, CLI, outbox, eval, paid run), Plan 2 website (server, front-desk page, recordings, guides).

## 3. The world (fictional, fixed, repeatable)

- `data/people.json`: 8 people at Acme Corp, each with `id`, `name`, `role`, `time_zone` (IANA name), `working_hours` (local, e.g. `09:00`–`17:00`) and `working_days` (Mon–Fri unless stated). Time zones: America/New_York (3 people), Europe/London (2), America/Denver (2), Asia/Singapore (1).
- `data/rooms.json`: 4 rooms with `id`, `name`, `capacity` (2, 4, 8, 14), `equipment` (subset of `screen`, `video`, `whiteboard`) and `time_zone` (America/New_York; rooms are in the New York office, remote people join by video).
- `data/calendars.json`: busy blocks per person and per room for the demo week, as UTC start/end pairs, no titles. Hand-written so that the eval scenarios have known answers.
- Pinned "today": `DEMO_TODAY = 2026-10-20` (Tuesday). "Next week" is Monday 2026-10-26 to Friday 2026-10-30. That week the UK has already left summer time (25 October) but the US has not (1 November), so London is 4 hours ahead of New York instead of the usual 5 — a real gotcha the code handles through Python's `zoneinfo`, and one the article can point to.
- Slots use 15-minute steps; meetings are 15 to 120 minutes.

## 4. The agent

**Tools** (look and pencil in only):

| Tool | Input | Output |
|---|---|---|
| `list_people` | none | id, name, role, time zone, working hours |
| `list_rooms` | none | id, name, capacity, equipment |
| `get_busy_times` | `people` (ids), `start_date`, `end_date` | busy blocks per person, in UTC and in each person's local time |
| `find_open_slots` | `people`, `duration_minutes`, `start_date`, `end_date`, optional `earliest_local`/`latest_local` per person or for all, optional `room_needs` (`min_capacity`, `equipment`) | up to 10 candidate slots that fit everyone's busy times and working hours (and a matching free room when `room_needs` is given), each with every attendee's local time; code does all calendar and time-zone maths |
| `place_hold` | `start_utc`, `duration_minutes`, `people`, `room_id` | a hold id; the hold is visible as "held, not sent"; fails if anything is no longer free |
| `release_hold` | `hold_id` | confirmation |
| `submit_proposal` | `hold_id`, `reasons[]` (at least one), `tradeoffs[]` (may be empty), `summary` | ends the run with a proposal |
| `ask_question` | `question` | ends the run with a question and releases all holds |

_Note, 2026-10-21: the single `submit_proposal(status, ...)` tool was split into these two final tools after the first measured run. The user approved the change. The cause of that run's failures was reasons leaking into the `summary` text, not a missing field; see `eval/NOTES.md`._

The AI never gets a tool that sends, books or changes anything outside the run's own holds.

**Proposal check (code).** A `submit_proposal` is valid only if: the `hold_id` is a hold placed in this run and still held; the hold's slot is inside every attendee's working hours and working days; no attendee and not the room is busy in that slot (and no other hold overlaps it); the room's capacity is at least the number of attendees; `summary` and at least one reason are present; and no `summary`, reason or trade-off contains tag markup such as `<parameter` or `</` (a sign the reasons leaked into the summary). An `ask_question` needs a non-empty question and releases all holds. An invalid final call gets one retry with the errors listed; a second invalid one ends as `unable`. When a proposal is accepted, every other hold is released. Code computes, and the model cannot change, the slot in UTC and in each attendee's local time, the room, and the attendee list. The summary, reasons and trade-offs are Claude's own words; they may mention times, which are not checked. The terminal shows them under a "Claude's note:" label.

**Loop.** Manual tool-use loop on the Anthropic Python SDK, copied in spirit from the research analyst: default model `claude-haiku-5-5` (override with `AGENT_MODEL` or `--model`), budget 12 model calls, `max_tokens=2048`, one final event per run: `{"type": "result", "result": {"status": "proposed" | "question" | "unable", ...}, "usage", "turns", "proposal_retries", "elapsed_seconds"}`. Every failure (API error, start failure, internal error, step budget, second invalid proposal) ends as `unable` and releases every hold the run placed. The request text is untrusted and wrapped and neutralised like the other demos.

**Questions.** A `question` result shows the question; the person's answer starts a new run whose input is the original request plus `Clarification: <answer>`. Nothing stays paused on the server.

**CLI.** `python agent.py "request"` prints the steps and the result; with a proposal it then offers `approve`, `reject` or `dry-run` at the prompt (plain code, not the model).

## 5. Approval, outbox and undo (plain code)

`outbox.py`: an `Outbox` holds holds, sent invites and room bookings for one session (one CLI run or one website visitor), in memory.
- `dry_run(proposal)` returns the invites and booking that would be created (one invite per attendee with their local time, plus the room booking) and changes nothing.
- `approve(proposal)` re-checks the slot is still free (the world could have changed), then creates the invites and booking and marks the hold confirmed. Returns what was sent.
- `reject(proposal)` releases the hold.
- `undo(send_id)` cancels a send within 10 minutes and frees the slot.
- Only these functions write to `sent`; the agent's tools cannot reach them. Tests assert that after any agent run, `sent` is empty, and that the tool registry contains no sending function.

## 6. Website (Plan 2)

- FastAPI server with Server-Sent Events: `POST /schedule` (`{"request": str, "clarification": optional str, "sample_id": optional}`; request capped at 500 characters), `POST /approve`, `POST /reject`, `POST /dry-run`, `POST /undo`, `GET /api/world` (people, rooms, calendars for the grid), `GET /api/samples`. Each visitor's outbox lives server-side for their session (a random session id in a cookie, expiring after 30 minutes; nothing else stored), so approval cannot be faked by the browser.
- Public-demo safety copied from the other demos: rate limit, daily token budget with up-front reservation, replay mode, security headers and hash CSP, API docs disabled, key server-side only.
- "The front desk" page: a week grid (Mon–Fri) of everyone's busy blocks shown in a chosen time zone; the AI's steps appear as it works; a hold appears on the grid as a dashed pencilled-in block; the proposal card shows the time per person, the room, reasons and trade-offs with Approve, Reject and Dry run; the outbox panel shows what was sent with Undo; a question card has a reply box. Light and dark, accessible, designed with the frontend-design skill.
- Four recorded samples: a straightforward meeting, a time-zone one (using the London gotcha), a tight one, and an impossible one that ends in a question.

## 7. Eval

`eval/scenarios.json`, about 16 scenarios, each run 3 times, one at a time.

| Group | About | Pass rule |
|---|---|---|
| straightforward | 4 | status `proposed`, the proposal passes the code check, and it meets the scenario's constraints (attendees, duration, window, room needs) |
| time_zones | 4 | as above, with each attendee's local time inside their working hours (at least one scenario depends on the 4-hour London–New York gap that week) |
| tight | 4 | the single valid slot (or one from the listed acceptable slots) is proposed; or, where the scenario says no perfect slot exists, a proposal whose trade-offs name the broken preference |
| impossible_or_ambiguous | 4 | status `question` |

Report (`eval/results.md`, failures listed): success overall and per group; **bad-proposal rate** (share of runs whose proposal would double-book someone, break working hours or ignore a hard constraint — the doer's dangerous error, expected 0 because of the code check, which the article explains); question-when-needed rate; unable count and proposal retries; **sent without approval: 0** (checked); median and slowest time, average model calls, total tokens. Rows store the full result so runs can be re-graded for free. Called a development-set result in the docs.

## 8. Tests (no API calls)

Calendar maths and time zones (including the 25 October / 1 November gap, working days, 15-minute steps); busy-time and open-slot finding against hand-checked answers; holds (place, conflict, release); the proposal check (every rule, with good and bad cases); the loop with a fake client (normal run, one retry, second invalid, question, step budget, API error, start failure, internal error, holds released on every failure, exactly one timed result); the outbox (dry run changes nothing, approve, re-check on approve, reject, undo window, no send reachable from tools); eval scoring; and in Plan 2 the server, page static checks, contrast, replays and doc tests.

## 9. Repository

`coding_stuff/scheduler-agent`, its own git repository, local only until the user asks. Python 3.12 (`.venv`), `anthropic` pinned like the other demos (Plan 2 adds the web pins). Layout mirrors the research analyst: `agent.py`, `world.py` (data loading and calendar maths), `tools.py`, `outbox.py`, `data/`, `eval/`, `server/`, `web/`, `tests/`, `docs/`. Beginner-friendly comments. API key only in a gitignored `.env` (paid runs use the expense project's `.env`, as before). Help contact: https://github.com/thejaredchapman.

## 10. Non-goals

Real calendars or email; recurring meetings; more than one week; booking for real people; multi-agent; deployment or publishing (always asked first).

## 11. Risks

- **Time-zone bugs** would undermine the demo's credibility: all maths in code with `zoneinfo`, heavily tested, and the DST gap is a named test.
- **The model may propose without placing a hold, or misstate local times:** the code check and code-computed local times cover both; the article says so.
- **Grading tight scenarios** can be ambiguous: each lists its acceptable slots explicitly.
- **Cost:** estimated before every paid run; roughly $0.10 to $0.30 for the eval.

## 12. Open items (decided during the build)

- The people's names and the exact busy blocks (designed with the scenarios).
- The final scenario set and the four website samples.
- The exact visual design (frontend-design skill, Plan 2).
