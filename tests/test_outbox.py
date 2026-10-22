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


def test_undo_boundary_is_exactly_the_window():
    box, clock = outbox()
    first = box.approve(proposal())
    clock[0] += UNDO_SECONDS                                      # exactly 10 minutes: still allowed
    assert box.undo(first["send_id"])["cancelled"] is True
    second = box.approve(proposal())
    clock[0] += UNDO_SECONDS + 1                                  # one second more: too late
    with pytest.raises(ValueError, match="too late"):
        box.undo(second["send_id"])
    assert len(box.active()) == 1


def test_forged_attendee_is_refused():
    box, _ = outbox()
    forged = proposal()
    forged["attendees"][0]["id"] = "zed"
    with pytest.raises(ValueError, match="Unknown person"):
        box.approve(forged)
    assert box.sent == []


def test_forged_attendee_name_is_ignored_for_the_invite():
    box, _ = outbox()
    forged = proposal()
    forged["attendees"][0]["name"] = "Mallory"
    forged["attendees"][0]["local_start"] = "Sat 01 Jan 00:00"
    sent = box.approve(forged)
    assert sent["invites"][0]["to"] == "Ana Ortiz"
    assert sent["invites"][0]["when"] == "Mon 26 Oct 11:00-12:00 (America/New_York)"


def test_forged_room_is_refused():
    box, _ = outbox()
    forged = proposal()
    forged["room"] = {"id": "ghost", "name": "Ghost"}
    with pytest.raises(ValueError, match="Unknown room"):
        box.approve(forged)
    assert box.sent == []


def test_end_before_start_is_refused():
    box, _ = outbox()
    forged = proposal()
    forged["end_utc"] = "2026-10-26T14:00Z"                       # start is 15:00Z
    with pytest.raises(ValueError, match="ends before it starts"):
        box.approve(forged)
    assert box.sent == []


def test_outside_working_hours_is_refused():
    box, _ = outbox()
    forged = proposal()
    forged["start_utc"], forged["end_utc"] = "2026-10-26T03:00Z", "2026-10-26T04:00Z"
    with pytest.raises(ValueError, match="outside working hours"):
        box.approve(forged)
    assert box.sent == []


def test_too_many_people_for_the_room_is_refused():
    box, _ = outbox()
    forged = proposal()
    forged["room"] = {"id": "nook", "name": "Nook"}               # capacity 2, but...
    forged["attendees"].append({"id": "dev"})                     # ...three people (dev is in hours then)
    with pytest.raises(ValueError, match="too small"):
        box.approve(forged)
    assert box.sent == []


def test_missing_or_broken_keys_are_value_errors():
    box, _ = outbox()
    for key in ("attendees", "room", "start_utc", "end_utc"):
        broken = proposal()
        del broken[key]
        for action in (box.approve, box.dry_run):
            with pytest.raises(ValueError):
                action(broken)
    broken = proposal()
    broken["start_utc"] = "soon"
    with pytest.raises(ValueError, match="bad start or end time"):
        box.approve(broken)
    naive = proposal()
    naive["start_utc"] = "2026-10-26T15:00"                       # no zone: refused, not guessed
    with pytest.raises(ValueError, match="bad start or end time"):
        box.approve(naive)
    no_hold = proposal()
    del no_hold["hold_id"]
    with pytest.raises(ValueError):
        box.reject(no_hold)
    assert box.sent == []


def test_returned_copies_cannot_change_what_was_sent():
    box, _ = outbox()
    sent = box.approve(proposal())
    sent["invites"].append({"person_id": "x"})
    sent["room"]["name"] = "HACKED"
    fresh = box.sent[0]
    assert len(fresh["invites"]) == 2 and fresh["room"]["name"] == "Loft"
    undone = box.undo(sent["send_id"])
    undone["invites"].clear()
    assert len(box.sent[0]["invites"]) == 2
    preview = box.dry_run(proposal())
    preview["invites"].clear()
    assert len(box.sent) == 1 and len(box.sent[0]["invites"]) == 2


def test_nothing_else_can_write_to_the_outbox():
    for path in ("tools.py", "agent.py"):
        try:
            source = open(path).read()
        except FileNotFoundError:
            continue  # agent.py arrives in Task 4; Task 4 re-runs this test
        for banned in ("import outbox", "from outbox", "Outbox("):
            assert banned not in source, (path, banned)
