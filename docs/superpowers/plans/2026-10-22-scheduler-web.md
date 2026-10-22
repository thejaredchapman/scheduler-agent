# Scheduler, Plan 2 (Server, Front Desk, Replays, Guides) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the command-line scheduler (Plan 1) into a public-demo-ready website: a streaming server where each visitor has their own server-side outbox, a "front desk" page with a week calendar grid, Approve / Reject / Dry run / Undo, recorded samples for replay mode, and business and developer guides pinned to the measured results.

**Architecture:** A small core change lets a run treat the visitor's already-approved meetings as busy (`run_agent(..., booked=...)`), and gives the server read helpers (`World.week_blocks`, `Outbox.as_holds`, `Outbox.listing`). `server/` is adapted from the research analyst's server (`../research-analyst-agent/server/`): same guards, SSE, replay, security headers and hash CSP. New: a cookie-keyed `SessionStore` holding each visitor's `Outbox` and their proposals, so approval acts only on proposals the server itself produced (the browser sends a `proposal_id`, never a proposal). The page in `web/` is plain HTML/CSS/JS. Guides are pinned by `tests/test_docs.py`.

**Tech Stack:** Python 3.12, FastAPI 0.156.1 / Starlette 1.9.0 (same pins as the other demos), plain HTML/CSS/JS, pytest + httpx.

**Spec:** `docs/superpowers/specs/2026-10-21-scheduler-design.md` sections 5–6, 9.

## Global Constraints

- Repository `/Users/thejaredchapman/coding_stuff/scheduler-agent`; branch work only, never commit on `main`; do not push or deploy.
- `.venv` (Python 3.12). Tests: `.venv/bin/python -m pytest -q`; all pass before every commit (94 at the start). Tests never call the network or the real API.
- Never change `data/`, `eval/scenarios.json` or any `eval/results*` file. `tools.py` and `agent.py` must still never import `outbox`.
- The browser can never send a proposal to approve: it sends a `proposal_id` that the server issued for that visitor's session. Approve, Reject, Dry run and Undo act only on that visitor's server-side `Outbox`.
- Sessions: random id from `secrets.token_urlsafe(24)` in an `HttpOnly`, `SameSite=Strict` cookie named `sid`; idle expiry 30 minutes; at most 500 sessions (oldest evicted); nothing else stored.
- Public limits: request text 1–500 characters (not only whitespace), clarification 0–500; unknown request fields rejected (422); `/schedule` rate limit 5 per 60 seconds per client; `DAILY_TOKEN_CAP = 1_500_000`; `RESERVED_TOKENS_PER_RUN = 45_000` (the largest measured run used about 41,000 tokens), settled to real usage on the final `result` event.
- Front end: text only via `textContent` (never `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`); exactly one inline `<script>` (the theme setter) for the CSP hash; keyboard operable; live regions; `prefers-reduced-motion`; WCAG AA (4.5:1) text contrast in both themes; 44px targets; no horizontal page scroll at 320px (the week grid may scroll inside its own container).
- Honest wording: the slot, each attendee's local time, the room and the attendees are computed by code; summary, reasons and trade-offs are labelled as Claude's note. "Sent without approval: 0" is described as by design (the AI has no sending tool), checked by tests.
- The API key lives only in a gitignored `.env`; never print, copy or commit it; never write the Anthropic key prefix literally in a committed file (tests build it as `"sk-" + "ant"`). Paid steps use `/Users/thejaredchapman/coding_stuff/expense-policy-agent/.env` and run only after the user says yes.
- Help contact: https://github.com/thejaredchapman only. Beginner-friendly comments. Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## File map

| File | Responsibility |
|---|---|
| `tools.py`, `agent.py` | `booked` meetings block searches and holds (Task 1) |
| `world.py` | `week_blocks` for the grid (Task 1) |
| `outbox.py` | public `as_holds`, `listing` with undo seconds left (Task 1) |
| `requirements.txt`, `requirements-dev.txt` | web pins (Task 2) |
| `server/guards.py` | rate limiter and token budget (copied verbatim) |
| `server/replay.py` | replay mode |
| `server/sessions.py` | per-visitor `Session` and `SessionStore` |
| `server/app.py` | FastAPI app, SSE, endpoints, headers |
| `server/record.py` | recorder for four samples |
| `web/index.html`, `web/styles.css`, `web/app.js` | the front desk |
| `web/replays/*.json` | recordings (Task 5) |
| `docs/business-guide.md`, `docs/developer-guide.md`, `README.md` | guides |
| `tests/test_hooks.py`, `tests/test_guards.py`, `tests/test_sessions.py`, `tests/test_server.py`, `tests/test_record.py`, `tests/test_web_static.py`, `tests/test_contrast.py`, `tests/test_replays.py`, `tests/test_docs.py` | tests |

---

### Task 1: Core hooks for the website

**Files:**
- Modify: `tools.py` (`Workspace`, the places that pass holds to free/busy checks), `agent.py` (`run_agent`, `_run_events`), `world.py` (add `week_blocks`), `outbox.py` (add `as_holds`, `listing`)
- Create: `tests/test_hooks.py`

**Interfaces:**
- Produces: `Workspace(world=None, booked=())` with `.booked` (list of hold-like dicts `{"owners": set, "start", "end"}`) and `.blocking()` = `active_holds() + booked`. `find_open_slots`, `place_hold` and `validate_proposal` treat booked meetings as busy (use `blocking()` wherever they previously passed `active_holds()` to a free/busy check). `release_all()` and `active_holds()` are unchanged (booked meetings are never released by a run).
- Produces: `run_agent(request, client=None, model=DEFAULT_MODEL, max_turns=MAX_TURNS, clock=time.monotonic, world=None, booked=())` passing `booked` to `Workspace`.
- Produces: `World.week_blocks(start, end) -> {owner_id: [(start, end), ...]}` for every person and room with busy blocks overlapping `[start, end)`, sorted.
- Produces: `Outbox.as_holds()` (public; the existing `_as_holds` becomes an alias or is renamed with callers updated) and `Outbox.listing() -> [{"send_id", "start_utc", "end_utc", "room", "invites", "undo_seconds_left": int}]` for active sends, where `undo_seconds_left = max(0, ceil(UNDO_SECONDS - (clock() - sent_at)))`.

- [ ] **Step 1: Write the failing tests** (`tests/test_hooks.py`)

```python
"""Hooks the website needs: booked meetings count as busy; grid and outbox read helpers."""
import agent
from agent import run_agent
from outbox import UNDO_SECONDS, Outbox
from tests.fakes import FakeClient, response, tool_use
from tests.fixtures import fixture_world
from tools import Workspace, build_result, run_tool
from world import parse_utc

BOOKED = [{"owners": {"ana", "loft"}, "start": parse_utc("2026-10-26T15:00Z"), "end": parse_utc("2026-10-26T16:00Z")}]


def test_booked_meetings_block_searches_and_holds():
    space = Workspace(fixture_world(), booked=BOOKED)
    slots = run_tool(space, "find_open_slots", {"people": ["ana", "ben"], "duration_minutes": 60,
                                                "start_date": "2026-10-26", "end_date": "2026-10-26"})["slots"]
    starts = [s["start_utc"] for s in slots]
    assert "2026-10-26T15:00Z" not in starts and "2026-10-26T13:00Z" in starts
    try:
        run_tool(space, "place_hold", {"start_utc": "2026-10-26T15:30Z", "duration_minutes": 30,
                                       "people": ["ana", "ben"], "room_id": "nook"})
        raise AssertionError("a booked slot must not be holdable")
    except ValueError as error:
        assert "not free" in str(error)
    space.release_all()
    assert space.blocking() == BOOKED            # a run never releases booked meetings


def test_run_agent_passes_booked_through(monkeypatch):
    seen = []
    real = agent.Workspace
    monkeypatch.setattr(agent, "Workspace", lambda world=None, booked=(): seen.append(booked) or real(world, booked))
    client = FakeClient([response(tool_use("ask_question", {"question": "Which week?"}, "q"))])
    list(run_agent("x", client=client, world=fixture_world(), booked=BOOKED))
    assert seen == [BOOKED]


def test_week_blocks():
    blocks = fixture_world().week_blocks(parse_utc("2026-10-26T00:00Z"), parse_utc("2026-10-31T00:00Z"))
    assert blocks["ana"] == [(parse_utc("2026-10-26T14:00Z"), parse_utc("2026-10-26T15:00Z"))]
    assert blocks["loft"] == [(parse_utc("2026-10-26T13:00Z"), parse_utc("2026-10-26T14:00Z"))]
    assert "ben" not in blocks


def proposal():
    space = Workspace(fixture_world())
    run_tool(space, "place_hold", {"start_utc": "2026-10-26T15:00Z", "duration_minutes": 60,
                                   "people": ["ana", "ben"], "room_id": "loft"})
    return build_result({"hold_id": "hold-1", "summary": "s", "reasons": ["r"], "tradeoffs": []}, space)


def test_outbox_listing_and_as_holds():
    clock = [100.0]
    box = Outbox(fixture_world(), clock=lambda: clock[0])
    sent = box.approve(proposal())
    clock[0] += 61
    listing = box.listing()
    assert listing[0]["send_id"] == sent["send_id"] and listing[0]["undo_seconds_left"] == UNDO_SECONDS - 61
    assert box.as_holds()[0]["owners"] == {"ana", "ben", "loft"}
    clock[0] += UNDO_SECONDS
    assert box.listing()[0]["undo_seconds_left"] == 0
```

Run → FAIL.

- [ ] **Step 2: Implement.** In `tools.py`: `Workspace.__init__(self, world=None, booked=())` stores `self.booked = list(booked)`; add `def blocking(self): return self.active_holds() + self.booked` with a one-line comment ("pencilled-in holds from this run plus meetings the person already approved"); in `find_open_slots` pass `space.blocking()`; in `_check_slot` build `others` from `space.blocking()` (still skipping `ignore`). In `agent.py`: add `booked=()` to `run_agent` and `_run_events` and build `Workspace(world, booked)`. In `world.py` add:

```python
    def week_blocks(self, start, end):
        """Every person's and room's busy blocks that overlap [start, end), for the calendar grid."""
        found = {owner: self.busy_blocks(owner, start, end) for owner in self.busy}
        return {owner: blocks for owner, blocks in found.items() if blocks}
```

In `outbox.py`: rename `_as_holds` to `as_holds` (update callers), add `import math` and:

```python
    def listing(self):
        """Active sends for the outbox panel, with the seconds left to undo each one."""
        now = self.clock()
        return [copy.deepcopy({**{k: v for k, v in s.items() if k not in ("sent_at", "cancelled")},
                               "undo_seconds_left": max(0, math.ceil(UNDO_SECONDS - (now - s["sent_at"])))})
                for s in self.active()]
```

- [ ] **Step 3: Run all tests** → all pass (including the existing isolation tests). **Step 4: Commit**

```bash
git add tools.py agent.py world.py outbox.py tests/test_hooks.py
git commit -m "Hooks for the website: approved meetings count as busy; grid and outbox read helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Sessions and the server

**Files:**
- Modify: `requirements.txt`, `requirements-dev.txt`
- Create: `server/__init__.py` (empty), `server/guards.py`, `server/replay.py`, `server/sessions.py`, `server/app.py`, placeholder `web/index.html` (replaced in Task 4), `tests/test_guards.py`, `tests/test_sessions.py`, `tests/test_server.py`

**Interfaces:**
- Consumes: `run_agent(request, ..., booked=...)`, `Outbox` (`approve`, `reject`, `dry_run`, `undo`, `as_holds`, `listing`), `World.week_blocks`, `get_world`, `next_week`, `DEMO_TODAY`.
- Produces: `server.sessions.Session` (`outbox`, `proposals` dict, `remember(result) -> proposal_id` (`prop-1`, `prop-2`, …), `take(proposal_id) -> result` (removes it; `KeyError` if unknown), `last_seen`) and `SessionStore(max_sessions=500, idle_seconds=1800, clock=time.monotonic, world=None)` with `get(sid) -> (sid, Session, created: bool)` (unknown, expired or missing sid → a new session with a fresh id), thread-safe. `server.app.create_app(agent_runner=run_agent, limiter=None, budget=None, sessions=None, replays_dir=REPLAYS_DIR, web_dir=WEB_DIR, replay_delay=0.4)`; constants `MAX_REQUEST_CHARS = 500`, `RESERVED_TOKENS_PER_RUN = 45_000`, `DAILY_TOKEN_CAP = 1_500_000`, `CSP`, `SECURITY_HEADERS`. API:
  - `POST /schedule` `{"request": str, "clarification": str | null, "sample_id": str | null}` → SSE `data: <json>\n\n`; the agent input is `request` plus, when given, `"\n\nClarification: " + clarification`; the run gets `booked=session.outbox.as_holds()`; a `proposed` result event gets `"proposal_id"` added inside `result` and the result is remembered in the session; replay events are handled the same way. 422 bad input; 429 rate limited.
  - `POST /approve`, `POST /reject`, `POST /dry-run` `{"proposal_id": str}` → 200 JSON (`approve` → `{"sent": <send>, "outbox": listing}`; `reject` → `{"rejected": true}`; `dry-run` → the preview, proposal kept); 404 `{"detail": "No such proposal"}` for an unknown id; 409 `{"detail": <plain message>}` when the outbox refuses (e.g. no longer free). Approve and reject consume the proposal; dry run does not.
  - `POST /undo` `{"send_id": str}` → `{"cancelled": <send>, "outbox": listing}`; 409 with the plain message when refused.
  - `GET /api/world` → `{"week": {"monday", "friday"}, "people": [...], "rooms": [...], "busy": {owner: [{"start_utc", "end_utc"}]}}` for the demo week.
  - `GET /api/outbox` → `{"sent": listing}` for the visitor's session.
  - `GET /api/samples` → `[{"id", "label", "request"}]` from `web/replays/*.json`, sorted by file name.
  - Every response sets/refreshes the `sid` cookie (`HttpOnly`, `SameSite=Strict`, `path=/`, `max_age=1800`).

- [ ] **Step 1: Dependencies.** `requirements.txt`: `anthropic==1.16.0`, `fastapi==0.156.1`, `starlette==1.9.0`, `pydantic==2.14.1`, `pydantic_core==2.50.1`, `anyio==4.15.1`. `requirements-dev.txt`: `-r requirements.txt`, `pytest==9.1.1`, `httpx==0.28.1`, `uvicorn==0.54.0`. Install with `.venv/bin/pip install -q -r requirements-dev.txt`.

- [ ] **Step 2: Copy verbatim** `/Users/thejaredchapman/coding_stuff/research-analyst-agent/server/guards.py` → `server/guards.py` and `/Users/thejaredchapman/coding_stuff/research-analyst-agent/tests/test_guards.py` → `tests/test_guards.py`. Copy `/Users/thejaredchapman/coding_stuff/research-analyst-agent/server/replay.py` → `server/replay.py`, changing only the notice wording to "Live scheduling is paused for today (the daily limit was reached)." and "Pick one of the sample requests to watch a recorded run." / "Replaying a recorded run of this request.". Create the placeholder `web/index.html` with the same single inline theme script as `/Users/thejaredchapman/coding_stuff/research-analyst-agent/web/index.html` (copy that `<script>…</script>` byte-for-byte) and a `<title>The Front Desk</title>`.

- [ ] **Step 3: Write the failing tests**

`tests/test_sessions.py`:
```python
"""Each visitor gets their own outbox and proposals; old sessions expire."""
import pytest

from server.sessions import SessionStore
from tests.fixtures import fixture_world


def store(clock=None, **kwargs):
    now = clock or [0.0]
    return SessionStore(clock=lambda: now[0], world=fixture_world(), **kwargs), now


def test_new_and_returning_sessions():
    s, _ = store()
    sid, session, created = s.get(None)
    assert created and len(sid) >= 24
    again_sid, again, created2 = s.get(sid)
    assert again_sid == sid and again is session and not created2
    other_sid, other, _ = s.get("made-up")
    assert other_sid != sid and other is not session


def test_proposals_are_issued_and_taken_once():
    s, _ = store()
    _, session, _ = s.get(None)
    pid = session.remember({"status": "proposed", "x": 1})
    assert pid == "prop-1" and session.take(pid) == {"status": "proposed", "x": 1}
    with pytest.raises(KeyError):
        session.take(pid)


def test_idle_expiry_and_cap():
    s, now = store(idle_seconds=10, max_sessions=2)
    a, _, _ = s.get(None)
    now[0] = 11
    a2, _, created = s.get(a)
    assert created and a2 != a                  # expired: a fresh session
    b, _, _ = s.get(None)
    c, _, _ = s.get(None)
    assert s.get(a2)[2]                         # the oldest was evicted to keep at most 2
```

`tests/test_server.py`:
```python
"""The web server with a fake agent (no API calls)."""
import json

from fastapi.testclient import TestClient

from server.app import (CSP, DAILY_TOKEN_CAP, MAX_REQUEST_CHARS, RESERVED_TOKENS_PER_RUN, SECURITY_HEADERS,
                        create_app)
from server.guards import RateLimiter, TokenBudget
from server.sessions import SessionStore
from tests.fixtures import fixture_world
from tools import Workspace, build_result, run_tool

W = fixture_world()


def proposed_result():
    space = Workspace(W)
    run_tool(space, "place_hold", {"start_utc": "2026-10-26T15:00Z", "duration_minutes": 60,
                                   "people": ["ana", "ben"], "room_id": "loft"})
    return build_result({"hold_id": "hold-1", "summary": "Monday 11:00 NY.", "reasons": ["free"], "tradeoffs": []}, space)


def event(result):
    return {"type": "result", "result": result, "usage": {"input_tokens": 100, "output_tokens": 50},
            "turns": 2, "proposal_retries": 0, "elapsed_seconds": 1.5}


def runner_for(result, seen=None):
    def run(text, booked=()):
        if seen is not None:
            seen.append((text, booked))
        yield {"type": "tool_call", "id": "a", "name": "list_people", "input": {}}
        yield event(result)
    return run


def frames(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def app_client(runner=None, tmp_path=None, **kwargs):
    kwargs.setdefault("sessions", SessionStore(world=W))
    if tmp_path is not None:
        kwargs.setdefault("replays_dir", tmp_path)
    return TestClient(create_app(agent_runner=runner or runner_for(proposed_result()), replay_delay=0, **kwargs))


def schedule(c, **body):
    body.setdefault("request", "Find an hour for Ana and Ben")
    return frames(c.post("/schedule", json=body))


def test_a_proposal_gets_an_id_and_can_be_approved_once():
    c = app_client()
    events = schedule(c)
    result = events[-1]["result"]
    assert result["status"] == "proposed" and result["proposal_id"] == "prop-1"
    ok = c.post("/approve", json={"proposal_id": "prop-1"})
    assert ok.status_code == 200 and ok.json()["sent"]["send_id"] == "send-1"
    assert len(ok.json()["outbox"]) == 1
    assert c.post("/approve", json={"proposal_id": "prop-1"}).status_code == 404


def test_the_browser_cannot_send_a_proposal_or_use_another_visitors_id():
    app = create_app(agent_runner=runner_for(proposed_result()), sessions=SessionStore(world=W), replay_delay=0)
    c, stranger = TestClient(app), TestClient(app)   # same server, two visitors (separate cookie jars)
    schedule(c)
    assert c.post("/approve", json={"proposal_id": "prop-1", "result": {}}).status_code == 422
    assert stranger.post("/approve", json={"proposal_id": "prop-1"}).status_code == 404
    assert c.post("/approve", json={"proposal_id": "prop-1"}).status_code == 200   # still there for its owner


def test_dry_run_keeps_the_proposal_and_reject_consumes_it():
    c = app_client()
    schedule(c)
    preview = c.post("/dry-run", json={"proposal_id": "prop-1"}).json()
    assert preview["dry_run"] is True and preview["still_free"] is True
    assert c.post("/reject", json={"proposal_id": "prop-1"}).json() == {"rejected": True}
    assert c.post("/approve", json={"proposal_id": "prop-1"}).status_code == 404


def test_approved_meetings_are_passed_to_the_next_run_and_clashes_are_refused():
    seen = []
    c = app_client(runner=runner_for(proposed_result(), seen))
    schedule(c)
    c.post("/approve", json={"proposal_id": "prop-1"})
    schedule(c, clarification="Mornings please")
    assert seen[1][0] == "Find an hour for Ana and Ben\n\nClarification: Mornings please"
    assert seen[1][1][0]["owners"] == {"ana", "ben", "loft"}
    refused = c.post("/approve", json={"proposal_id": "prop-2"})   # the same slot again
    assert refused.status_code == 409 and "no longer free" in refused.json()["detail"]


def test_undo_and_outbox_listing():
    c = app_client()
    schedule(c)
    c.post("/approve", json={"proposal_id": "prop-1"})
    assert c.get("/api/outbox").json()["sent"][0]["undo_seconds_left"] > 0
    undone = c.post("/undo", json={"send_id": "send-1"})
    assert undone.status_code == 200 and undone.json()["outbox"] == []
    assert c.post("/undo", json={"send_id": "send-1"}).status_code == 409


def test_bad_input_and_rate_limit():
    c = app_client(limiter=RateLimiter(max_requests=1, window_seconds=60))
    assert c.post("/schedule", json={"request": "  "}).status_code == 422
    assert c.post("/schedule", json={"request": "x" * (MAX_REQUEST_CHARS + 1)}).status_code == 422
    assert c.post("/schedule", json={"request": "ok", "clarification": "y" * 501}).status_code == 422
    assert c.post("/schedule", json={"request": "ok", "extra": 1}).status_code == 422
    assert c.post("/schedule", json={"request": "ok"}).status_code == 200
    assert c.post("/schedule", json={"request": "ok"}).status_code == 429


def test_budget_reserves_and_settles():
    budget = TokenBudget(daily_cap=DAILY_TOKEN_CAP)
    schedule(app_client(budget=budget))
    assert budget._spent == 150 and RESERVED_TOKENS_PER_RUN == 45_000 and DAILY_TOKEN_CAP == 1_500_000


def test_replay_mode_remembers_recorded_proposals(tmp_path):
    (tmp_path / "pair.json").write_text(json.dumps({"id": "pair", "label": "L", "request": "R",
                                                    "events": [event(proposed_result())]}))
    c = app_client(tmp_path=tmp_path, budget=TokenBudget(daily_cap=0),
                   runner=lambda text, booked=(): (_ for _ in ()).throw(AssertionError("no live run")))
    events = schedule(c, sample_id="pair")
    assert events[0]["type"] == "notice" and "Replaying" in events[0]["message"]
    assert events[-1]["result"]["proposal_id"] == "prop-1"
    assert c.post("/approve", json={"proposal_id": "prop-1"}).status_code == 200


def test_world_samples_and_cookie(tmp_path):
    (tmp_path / "b.json").write_text(json.dumps({"id": "b", "label": "B", "request": "RB", "events": []}))
    c = app_client(tmp_path=tmp_path)
    world = c.get("/api/world")
    body = world.json()
    assert body["week"] == {"monday": "2026-10-26", "friday": "2026-10-30"}
    assert {p["id"] for p in body["people"]} == {"ana", "ben", "chen", "dev"}
    assert body["busy"]["ana"] == [{"start_utc": "2026-10-26T14:00Z", "end_utc": "2026-10-26T15:00Z"}]
    cookie = world.headers["set-cookie"].lower()
    assert "sid=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/api/samples").json() == [{"id": "b", "label": "B", "request": "RB"}]


def test_crash_becomes_a_notice_and_headers_everywhere():
    def broken(text, booked=()):
        yield {"type": "tool_call", "id": "a", "name": "list_people", "input": {}}
        raise RuntimeError("secret")
    c = app_client(runner=broken)
    assert schedule(c)[-1] == {"type": "notice", "message": "Something went wrong. Please try again."}
    for r in (c.get("/"), c.get("/api/world"), c.get("/nope"), c.post("/schedule", json={})):
        for name, value in SECURITY_HEADERS.items():
            assert r.headers[name] == value
    assert "'unsafe-inline'" not in CSP
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404
```

Run → FAIL.

- [ ] **Step 4: Write `server/sessions.py`**

```python
"""One small, private space per website visitor: their outbox and the proposals made for them.

The browser only ever holds a random session id (in a cookie) and proposal ids. To approve,
it sends a proposal id; the server looks up the proposal IT made for that visitor. So a visitor
cannot approve something the scheduler never proposed, or anything belonging to someone else.
Everything is in memory and expires; nothing is written to disk.
"""
import itertools
import secrets
import threading
import time
from collections import OrderedDict

from outbox import Outbox


class Session:
    def __init__(self, world, clock):
        self.outbox = Outbox(world, clock=clock)
        self.proposals = {}
        self._numbers = itertools.count(1)
        self.last_seen = clock()

    def remember(self, result):
        """Keep a proposal the scheduler produced; return the id the browser may use."""
        proposal_id = f"prop-{next(self._numbers)}"
        self.proposals[proposal_id] = result
        return proposal_id

    def take(self, proposal_id):
        """Hand back a proposal once (approve or reject uses it up). KeyError if unknown."""
        return self.proposals.pop(proposal_id)


class SessionStore:
    def __init__(self, max_sessions=500, idle_seconds=1800, clock=time.monotonic, world=None):
        self.max_sessions, self.idle_seconds, self.clock, self.world = max_sessions, idle_seconds, clock, world
        self._sessions = OrderedDict()  # oldest first, so eviction is easy
        self._lock = threading.Lock()

    def get(self, sid):
        """(sid, session, created). Unknown, expired or missing ids get a fresh session."""
        now = self.clock()
        with self._lock:
            session = self._sessions.get(sid) if sid else None
            if session is not None and now - session.last_seen > self.idle_seconds:
                del self._sessions[sid]
                session = None
            if session is not None:
                session.last_seen = now
                self._sessions.move_to_end(sid)
                return sid, session, False
            sid = secrets.token_urlsafe(24)
            session = Session(self.world, self.clock)
            self._sessions[sid] = session
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)  # forget the least recently used visitor
            return sid, session, True
```

Note: `Outbox(None, ...)` loads the demo world via `get_world()`; tests pass the fixture world.

- [ ] **Step 5: Write `server/app.py`.** Copy `/Users/thejaredchapman/coding_stuff/research-analyst-agent/server/app.py` and keep verbatim (with their comments): `_inline_script_hash`, `CSP`, `SECURITY_HEADERS`, `SecurityHeadersMiddleware`, `_client_ip`, `_sse`, and the static mount plus middleware wrapping at the end of `create_app` (fix the mount comment to name `/schedule`). Replace the rest with:

```python
"""Web server: streams the scheduler's steps to the browser, and holds each visitor's outbox.

The API key never leaves this server. The browser never sends a proposal: it sends the id of a
proposal this server made for that visitor, and only then does plain code in outbox.py "send".
Adapted from the research analyst's server.
"""
import base64
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from agent import next_week, run_agent
from server.guards import RateLimiter, TokenBudget
from server.replay import replay_events
from server.sessions import SessionStore
from world import DEMO_TODAY, UTC, get_world, utc_text

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
REPLAYS_DIR = WEB_DIR / "replays"
MAX_REQUEST_CHARS = 500
# Charged up front so abandoned streams still count; settled to the real usage on a normal finish.
# The largest measured run (eval/results-first-run.json) used about 41,000 tokens.
RESERVED_TOKENS_PER_RUN = 45_000
DAILY_TOKEN_CAP = 1_500_000
COOKIE = "sid"

# ... _inline_script_hash, CSP, SECURITY_HEADERS, SecurityHeadersMiddleware copied verbatim ...


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown fields are rejected (422)
    request: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS)
    clarification: str | None = Field(default=None, max_length=MAX_REQUEST_CHARS)
    sample_id: str | None = Field(default=None, max_length=40)


class ProposalAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(min_length=1, max_length=40)


class UndoAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    send_id: str = Field(min_length=1, max_length=40)


# ... _client_ip and _sse copied verbatim ...


def _with_cookie(response, sid):
    response.set_cookie(COOKIE, sid, max_age=1800, httponly=True, samesite="strict", path="/")
    return response


def create_app(agent_runner=run_agent, limiter=None, budget=None, sessions=None, replays_dir=REPLAYS_DIR,
               web_dir=WEB_DIR, replay_delay=0.4):
    app = FastAPI(title="The Front Desk", docs_url=None, redoc_url=None, openapi_url=None)
    limiter = limiter or RateLimiter()
    budget = budget or TokenBudget(daily_cap=DAILY_TOKEN_CAP)
    sessions = sessions or SessionStore(world=get_world())  # load the demo data once, shared by every visitor
    world = sessions.world or get_world()

    def visitor(request):
        return sessions.get(request.cookies.get(COOKIE))

    def tagged(events, session):
        """Give each proposal an id the browser can use, and remember it for this visitor."""
        for event in events:
            if event.get("type") == "result" and event["result"].get("status") == "proposed":
                event = {**event, "result": {**event["result"], "proposal_id": session.remember(event["result"])}}
            yield event

    @app.post("/schedule")
    def schedule(body: ScheduleRequest, request: Request):
        if not body.request.strip():
            raise HTTPException(status_code=422, detail="Please type a request.")
        if not limiter.allow(_client_ip(request)):
            raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute.")
        sid, session, _ = visitor(request)
        if not budget.try_reserve(RESERVED_TOKENS_PER_RUN):
            return _with_cookie(_sse(tagged(replay_events(replays_dir, body.sample_id, delay=replay_delay),
                                            session)), sid)
        text = body.request + (f"\n\nClarification: {body.clarification}" if body.clarification else "")

        def live_events():
            for event in agent_runner(text, booked=session.outbox.as_holds()):
                if event.get("type") == "result":
                    usage = event.get("usage") or {}
                    budget.add(usage.get("input_tokens", 0) + usage.get("output_tokens", 0) - RESERVED_TOKENS_PER_RUN)
                yield event
        return _with_cookie(_sse(tagged(live_events(), session)), sid)

    def act(request, proposal_id, action, consume):
        sid, session, _ = visitor(request)
        proposal = session.proposals.get(proposal_id)
        if proposal is None:
            return _with_cookie(JSONResponse({"detail": "No such proposal"}, status_code=404), sid)
        try:
            outcome = action(session, proposal)
        except ValueError as error:
            return _with_cookie(JSONResponse({"detail": str(error)}, status_code=409), sid)
        if consume:
            session.take(proposal_id)
        return _with_cookie(JSONResponse(outcome), sid)

    def send_it(session, proposal):
        sent = session.outbox.approve(proposal)  # plain code re-checks the slot, then "sends"
        return {"sent": sent, "outbox": session.outbox.listing()}

    def turn_down(session, proposal):
        session.outbox.reject(proposal)
        return {"rejected": True}

    def preview(session, proposal):
        return session.outbox.dry_run(proposal)  # only looks; nothing changes

    @app.post("/approve")
    def approve(body: ProposalAction, request: Request):
        return act(request, body.proposal_id, send_it, consume=True)

    @app.post("/reject")
    def reject(body: ProposalAction, request: Request):
        return act(request, body.proposal_id, turn_down, consume=True)

    @app.post("/dry-run")
    def dry_run(body: ProposalAction, request: Request):
        return act(request, body.proposal_id, preview, consume=False)

    @app.post("/undo")
    def undo(body: UndoAction, request: Request):
        sid, session, _ = visitor(request)
        try:
            cancelled = session.outbox.undo(body.send_id)
        except ValueError as error:
            return _with_cookie(JSONResponse({"detail": str(error)}, status_code=409), sid)
        return _with_cookie(JSONResponse({"cancelled": cancelled, "outbox": session.outbox.listing()}), sid)

    @app.get("/api/world")
    def world_view(request: Request):
        sid, _, _ = visitor(request)
        monday, friday = next_week(DEMO_TODAY)
        start = datetime.combine(date.fromisoformat(monday), time(0), UTC) - timedelta(hours=14)
        end = datetime.combine(date.fromisoformat(friday) + timedelta(days=1), time(0), UTC) + timedelta(hours=14)
        busy = {owner: [{"start_utc": utc_text(s), "end_utc": utc_text(e)} for s, e in blocks]
                for owner, blocks in world.week_blocks(start, end).items()}
        people = [{key: p[key] for key in ("id", "name", "role", "time_zone", "working_hours", "working_days")}
                  for p in world.people.values()]
        rooms = [{key: r[key] for key in ("id", "name", "capacity", "equipment")} for r in world.rooms.values()]
        return _with_cookie(JSONResponse({"week": {"monday": monday, "friday": friday}, "people": people,
                                          "rooms": rooms, "busy": busy}), sid)

    @app.get("/api/outbox")
    def outbox_view(request: Request):
        sid, session, _ = visitor(request)
        return _with_cookie(JSONResponse({"sent": session.outbox.listing()}), sid)

    @app.get("/api/samples")
    def samples():
        found = []
        for path in sorted(Path(replays_dir).glob("*.json")):
            recording = json.loads(path.read_text())
            found.append({key: recording[key] for key in ("id", "label", "request")})
        return found

    # ... static mount and SecurityHeadersMiddleware wrapping copied verbatim ...
    return app


app = create_app()
```

(`create_app` builds the default `SessionStore` with the demo world loaded once; tests pass their own store with the fixture world. The grid reads the same world.)

- [ ] **Step 6: Run all tests** → all pass. Boot check without a key (free): `env -u ANTHROPIC_API_KEY .venv/bin/python -m uvicorn server.app:app --port 8021` in the background, `curl -s localhost:8021/api/world | head -c 300`, then stop it.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt requirements-dev.txt server web/index.html tests/test_guards.py tests/test_sessions.py tests/test_server.py
git commit -m "Server: streaming /schedule, per-visitor outboxes, approve/reject/dry-run/undo by proposal id

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The sample recorder (`server/record.py`)

**Files:**
- Create: `server/record.py`, `tests/test_record.py`

**Interfaces:**
- Produces: `SAMPLES` = four `{"id", "label", "request", "expected_status"}` built from `eval/scenarios.json` (ids `straightforward-morning-sync`, `time-zones-london-new-york`, `tight-four-people-two-regions`, `impossible-singapore-new-york`, with labels "A simple meeting", "London and New York (the 4-hour week)", "Only one slot fits", "Impossible: asks a question"); `ERROR_MARKERS` (the five unable prefixes); `check_recordings(results) -> list[str]`; `main(argv=None, runner=None, out_dir=None, recorded_on=None) -> int`; recordings `web/replays/<id>.json` = `{"id", "label", "request", "model", "recorded_on", "events"}`.

Copy the structure of `/Users/thejaredchapman/coding_stuff/research-analyst-agent/server/record.py` (key check before spending, cost line and confirmation, run all four in memory, refuse unless all pass, atomic writes, `--yes`), adapted: `check_recordings` requires a final `result` event, status equal to `expected_status`, and refuses `unable` or any reason starting with an `ERROR_MARKERS` entry; for `proposed` samples it also requires the result to pass `eval.scoring.proposal_problems(scenario, result, get_world()) == []` (so a recorded proposal shown to the public is a valid one). Tests mirror `/Users/thejaredchapman/coding_stuff/research-analyst-agent/tests/test_record.py` (the four samples, good runs pass, a wrong status / unable / missing sample / invalid proposal are named, nothing written unless all good, recordings carry the six keys and the injected date, no key → returns 1 and prints `ANTHROPIC_API_KEY`). For the "good runs" fake, build valid proposed results with `tools.Workspace(get_world())`, `place_hold` on the scenario's first slot from `get_world().open_slots(...)` and `build_result`, and a `question_result` for the impossible sample.

- [ ] Write the tests first, see them fail, implement, run all tests (`server/record.py --help` free; never run it without `--help`), commit with message `Recorder: four sample requests for replay mode, saved only when every run is right and valid` and the trailer.

---

### Task 4: The front desk page (`web/`)

Needs design judgment: **use the `frontend-design` skill.** The research analyst's page (`/Users/thejaredchapman/coding_stuff/research-analyst-agent/web/`) is the reference for structure, accessibility patterns, the SSE reader (`readEventStream`, including the CRLF and final-frame handling) and defensive reads; copy patterns, not the look.

**Files:** `web/index.html`, `web/styles.css`, `web/app.js`, `tests/test_web_static.py`, `tests/test_contrast.py`

**Visual direction:** a hotel or office front desk: a calm planner. A week grid (Mon–Fri columns, working-day hour rows) shows busy blocks for the people involved (all people when idle; the request's attendees once known from the result or from `get_busy_times` / `find_open_slots` tool calls), labelled by person, in the time zone chosen in a selector (default: the browser's zone if it is one of the four, else America/New_York); the pencilled-in hold appears as a dashed block, approved meetings as solid "booked" blocks. The AI's steps appear as compact log lines. The memorable moment: the dashed hold "inking in" to solid on Approve (a fade under reduced motion).

**Contract (tests check these):**
- `index.html`: the Task 2 inline theme script byte-for-byte as the only inline script; `styles.css` and `app.js` (`defer`) linked; Google Fonts only from `https://fonts.googleapis.com`; ids: `theme-toggle` (containing `theme-icon`), `request-form` (form, `method="post"`, `action="/schedule"`) with `request` (textarea, `maxlength="500"`, `<label for="request">`) and `schedule` (submit button); `samples`; `zone` (a `<select>` with the four zones); `week-grid` (`role="grid"` or `role="table"`, with an accessible name); `trail` (`<ol aria-live="polite">`); `notice` (`role="status"`, `hidden`); `proposal` (`role="region"`, `aria-label="Proposal"`, `tabindex="-1"`, `hidden`) containing `proposal-times` (code-computed per-person times and room), `claude-note` (labelled "Claude's note"), `approve`, `reject`, `dry-run`, `usage`; `question-card` (`hidden`) containing `question-text`, `clarification` (textarea, `maxlength="500"`, labelled) and `reply`; `preview` (`hidden`, dry-run output); `outbox` (list of sent meetings, each with an Undo button and seconds left); `announce` (visually hidden, `aria-live="polite"`).
- `app.js`: `"use strict"`; no `innerHTML`/`outerHTML`/`insertAdjacentHTML`/`document.write`; `el(tag, className, text)` helper; `readEventStream` copied; `fetch("/schedule"` with `{request, clarification, sample_id}`; approve/reject/dry-run post `{proposal_id}` only (never a proposal object) to `/approve`, `/reject`, `/dry-run`; undo posts `{send_id}` to `/undo`; loads `/api/world`, `/api/samples`, `/api/outbox`; renders grid times with `Intl.DateTimeFormat` and the selected `timeZone` (display only); proposal card times come from `result.attendees[].local_start/local_end` and `result.room.name` (code-computed), with summary/reasons/trade-offs under "Claude's note"; status labels `{"proposed": "PROPOSED", "question": "NEEDS YOUR ANSWER", "unable": "COULD NOT SCHEDULE"}`; a question shows `question-card`, and Reply re-posts the original request with `clarification`; 409 responses show their `detail`; 429 → "That was a lot of requests in a short time. Wait a minute and try again."; `usageText(event)` as in the research analyst page (`Number.isFinite` guards); focus moves to `#proposal` or `#question-card` when one arrives, back to `#schedule` otherwise; `aria-disabled` (not `disabled`) while running; outbox Undo counts down from `undo_seconds_left` and disables itself at 0 (via `aria-disabled`).
- `styles.css`: colours as custom properties in `:root { ... }` and `:root[data-theme="dark"] { ... }` including `--paper`, `--ink`, `--muted`, `--accent` (6-digit hex); `.visually-hidden` with `white-space: nowrap`; at least two `min-height: 2.75rem` rules (buttons, chips); a `prefers-reduced-motion: reduce` block; the week grid sits in a container with `overflow-x: auto` so the page itself never scrolls sideways.
- Page copy follows the honest-wording rule (Global Constraints).

- [ ] **Step 1: Tests.** `tests/test_contrast.py`: copy `/Users/thejaredchapman/coding_stuff/research-analyst-agent/tests/test_contrast.py` verbatim. `tests/test_web_static.py`: adapt `/Users/thejaredchapman/coding_stuff/research-analyst-agent/tests/test_web_static.py` to this contract: one inline script; external assets; every id above present; `request`/`clarification` maxlength 500 with labels; `request-form` method/action; `trail` aria-live; `proposal` region attributes; no banned DOM APIs; `"use strict"`, `function el(`, `textContent`; `fetch("/schedule"`, `"/approve"`, `"/reject"`, `"/dry-run"`, `"/undo"`, `"/api/world"`, `"/api/outbox"`, `"/api/samples"` present; `proposal_id` present and the approve/reject/dry-run bodies never include `result`/`attendees` (assert `JSON.stringify({ proposal_id` appears); `Intl.DateTimeFormat` and `timeZone`; the three status labels; `Claude's note`; `function usageText(` and `Number.isFinite`; `aria-disabled` and no `.disabled =`; the 429 text; CSS `.visually-hidden` nowrap, reduced-motion block, ≥2 `min-height: 2.75rem`, `overflow-x: auto`.
- [ ] **Step 2: Build the page** with the frontend-design skill; keep the inline script byte-for-byte; run all tests.
- [ ] **Step 3: Free local check:** run the server with a spent budget and no key (`env -u ANTHROPIC_API_KEY .venv/bin/python -c "import uvicorn; from server.app import create_app; from server.guards import TokenBudget, RateLimiter; uvicorn.run(create_app(budget=TokenBudget(daily_cap=0), limiter=RateLimiter(max_requests=1000), replay_delay=0.05), port=8022)"`), confirm `/api/world` loads and the page renders the grid; stop the server. (Recordings arrive in Task 5; the controller does the full browser check then.)
- [ ] **Step 4: Commit** `web/index.html web/styles.css web/app.js tests/test_web_static.py tests/test_contrast.py` with message `Front desk page: week grid, proposal card with Approve/Reject/Dry run, outbox with Undo` and the trailer.

---

### Task 5: Recordings and the browser check (controller step; paid part needs the user's yes)

- [ ] **Step 1: Ask the user** (4 requests, roughly 60,000 tokens, well under 1 cent at Haiku 5.5 list prices); wait for yes.
- [ ] **Step 2: Record:** `set -a; . /Users/thejaredchapman/coding_stuff/expense-policy-agent/.env; set +a; .venv/bin/python -m server.record --yes`. If `NOT SAVED`, run once more; if an elapsed time looks inflated by network retries (more than about 60 seconds), re-record.
- [ ] **Step 3: Recording tests** (`tests/test_replays.py`): one recording per sample; `check_recordings` passes on the committed files; each has the six keys, a float `elapsed_seconds` on the final event, and no leaks (`"/Users/"`, `"Traceback"`, `"sk-" + "ant"`). Commit `web/replays tests/test_replays.py` with message `Replays: recorded runs of the four sample requests` and the trailer.
- [ ] **Step 4: Browser check (free):** with the spent-budget server and a relaxed rate limiter, headless Chromium (Playwright under `/private/tmp/claude-501/pwcheck`), both themes, widths 1280 / 375 / 320: run each sample; for proposals, Dry run, Approve (hold becomes booked, outbox lists it with a countdown), Undo; for the question sample, the question card appears; check no page-level horizontal overflow, no "undefined"/"NaN", no console errors. Problems go to an implementer as findings.

---

### Task 6: Guides, README and doc tests

Model on the research analyst's guides (`/Users/thejaredchapman/coding_stuff/research-analyst-agent/docs/` and `README.md`) and doc tests (`tests/test_docs.py`), adapted.

**Business guide sections (level-2, in order):** What this is; What it could do for your team; How to try the demo; Use cases; What it is not; How well it worked in testing; Frequently asked questions; Glossary. Plain language, no code blocks, no emoji. Testing section: the first run's 79% and why (Claude wrote its reasons inside the summary text in 25 submissions; see `eval/NOTES.md`), the user-approved split into two final tools, the re-run's 98%, 0% bad proposals, 100% questions when needed, median time, "sent without approval: 0 by design", and that it is a 16-scenario development set we wrote.

**Developer guide sections (in order):** Overview and architecture; Quick start; Expected behavior; API reference; Data formats; Extending; Testing; Security model and deployment; Troubleshooting; Getting help. Must cover: the eight tools and that none can send; the proposal check and code-computed fields vs Claude's note; the five unable reasons; sessions and why the browser sends only `proposal_id`; every endpoint with examples and status codes; the limits table (500, 500, 5 per 60 s, 1,500,000 per day, 45,000 reserved, 12 model calls, 2048 output tokens, 31-day search cap, 10-minute undo, 30-minute session expiry, 500 sessions); replay and `python -m server.record`; the eval commands; a Testing table with one row per `tests/test_*.py` in the form `` | `tests/<file>` | <covers> | ``; "nothing has been deployed" and a before-deploying list (dedicated key with a spend limit, `Secure` cookies behind HTTPS, HSTS, body-size limit, replay sleeps in a thread, sessions are in memory per instance); Getting help with only https://github.com/thejaredchapman.

**README:** what it is; headline numbers with links to `eval/results.md`, `eval/results-first-run.md` and `eval/NOTES.md`; quick start; links to both guides.

- [ ] **Step 1: `tests/test_docs.py`** adapted from the research analyst's: sections in order; relative links resolve; business guide has no code blocks or emoji; numbers match the files (`- Success: **NN%**` from both results files, `- Bad-proposal rate: **NN%**`, `median **X s**` as "X seconds") in the business guide and README; the limits in the developer guide match the code constants; every test module listed; contact only the GitHub profile, no "@"; no key prefix; "nothing has been deployed"; the phrase "Claude's note" appears in the developer guide; neither guide claims every time shown is computed by code (assert "every time you see" and "all times are computed" are absent).
- [ ] **Step 2: Write the three documents**, every number read from the files; run all tests. **Step 3: Commit** `docs/business-guide.md docs/developer-guide.md README.md tests/test_docs.py` with message `Guides and README, pinned to the measured results` and the trailer.

---

## After the tasks

Final whole-branch review (most capable model), one fix wave, merge into local `main` with the user's okay. Do not push or deploy.
