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
