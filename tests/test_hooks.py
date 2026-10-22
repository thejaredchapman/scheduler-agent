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
