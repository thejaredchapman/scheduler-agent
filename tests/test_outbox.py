"""Only an approving person sends; code re-checks; undo has a time limit."""
import pytest

from outbox import UNDO_SECONDS, Outbox
from tests.fixtures import fixture_world
from tools import Workspace, build_result, run_tool


def proposal(start="2026-10-26T15:00Z"):
    space = Workspace(fixture_world())
    run_tool(space, "place_hold", {"start_utc": start, "duration_minutes": 60, "people": ["ana", "ben"],
                                   "room_id": "loft"})
    return build_result({"status": "proposed", "hold_id": "hold-1", "summary": "s", "reasons": ["r"],
                         "tradeoffs": []}, space)


def outbox(now=None):
    clock = now or [1000.0]
    return Outbox(fixture_world(), clock=lambda: clock[0]), clock


def test_dry_run_changes_nothing():
    box, _ = outbox()
    preview = box.dry_run(proposal())
    assert preview["dry_run"] is True and box.sent == []
    assert preview["invites"][0] == {"person_id": "ana", "to": "Ana Ortiz",
                                     "when": "Mon 26 Oct 11:00-12:00 (America/New_York)"}
    assert preview["room"] == {"id": "loft", "name": "Loft"}


def test_approve_sends_and_blocks_a_clash():
    box, _ = outbox()
    sent = box.approve(proposal())
    assert sent["send_id"] == "send-1" and len(box.sent) == 1 and len(sent["invites"]) == 2
    with pytest.raises(ValueError, match="no longer free"):
        box.approve(proposal())                                   # the same slot again


def test_only_proposals_can_be_sent():
    box, _ = outbox()
    space = Workspace(fixture_world())
    question = build_result({"status": "question", "question": "Which week?"}, space)
    for action in (box.approve, box.dry_run, box.reject):
        with pytest.raises(ValueError):
            action(question)


def test_reject_sends_nothing():
    box, _ = outbox()
    assert box.reject(proposal()) == {"rejected": True, "hold_id": "hold-1"}
    assert box.sent == []


def test_undo_within_the_window_only():
    box, clock = outbox()
    first = box.approve(proposal())
    clock[0] += UNDO_SECONDS - 1
    assert box.undo(first["send_id"])["cancelled"] is True
    assert box.active() == []
    box.approve(proposal())                                       # the slot is free again
    clock[0] += UNDO_SECONDS + 1
    with pytest.raises(ValueError, match="too late"):
        box.undo("send-2")
    with pytest.raises(ValueError):
        box.undo("send-99")


def test_nothing_else_can_write_to_the_outbox():
    for path in ("tools.py", "agent.py"):
        try:
            source = open(path).read()
        except FileNotFoundError:
            continue  # agent.py arrives in Task 4; Task 4 re-runs this test
        for banned in ("import outbox", "from outbox", "Outbox("):
            assert banned not in source, (path, banned)
