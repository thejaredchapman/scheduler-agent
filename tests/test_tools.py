"""The scheduler's tools, the proposal check and the result builder (fixture world, no API)."""
import pytest

from tests.fixtures import fixture_world
from tools import (TOOL_NAMES, TOOL_SCHEMAS, Workspace, build_result, run_tool, unable_result,
                   validate_proposal)


def ws():
    return Workspace(fixture_world())


def hold(space, start="2026-10-26T15:00Z", people=("ana", "ben"), room="loft", minutes=60):
    return run_tool(space, "place_hold", {"start_utc": start, "duration_minutes": minutes,
                                         "people": list(people), "room_id": room})


def test_tool_names_and_no_sending_tool():
    assert TOOL_NAMES == ("list_people", "list_rooms", "get_busy_times", "find_open_slots",
                          "place_hold", "release_hold")
    assert [s["name"] for s in TOOL_SCHEMAS] == list(TOOL_NAMES) + ["submit_proposal"]
    for word in ("send", "book", "approve", "outbox", "invite"):
        assert not any(word in name for name in TOOL_NAMES)
    source = open("tools.py").read()
    assert "import outbox" not in source and "from outbox" not in source


def test_list_people_and_rooms():
    space = ws()
    people = run_tool(space, "list_people", {})["people"]
    assert {p["id"] for p in people} == {"ana", "ben", "chen", "dev"}
    assert next(p for p in people if p["id"] == "dev")["working_days"] == ["Mon", "Tue", "Wed", "Thu"]
    assert run_tool(space, "list_rooms", {})["rooms"][0] == {"id": "nook", "name": "Nook", "capacity": 2,
                                                            "equipment": ["screen"]}


def test_get_busy_times_shows_local_times_and_no_titles():
    out = run_tool(ws(), "get_busy_times", {"people": ["ana"], "start_date": "2026-10-26", "end_date": "2026-10-26"})
    assert out["busy"]["ana"] == [{"start_utc": "2026-10-26T14:00Z", "end_utc": "2026-10-26T15:00Z",
                                   "local": "Mon 26 Oct 10:00-11:00"}]


def test_find_open_slots_reports_each_persons_local_time():
    out = run_tool(ws(), "find_open_slots", {"people": ["ana", "ben"], "duration_minutes": 60,
                                             "start_date": "2026-10-26", "end_date": "2026-10-26",
                                             "room_needs": {"equipment": ["video"]}})
    first = out["slots"][0]
    assert first == {"start_utc": "2026-10-26T15:00Z", "room_id": "loft",
                     "local": {"ana": "Mon 26 Oct 11:00", "ben": "Mon 26 Oct 15:00"}}


def test_bad_inputs_raise():
    space = ws()
    with pytest.raises(ValueError):
        run_tool(space, "find_open_slots", {"people": ["zoe"], "duration_minutes": 60,
                                            "start_date": "2026-10-26", "end_date": "2026-10-26"})
    with pytest.raises(ValueError):
        run_tool(space, "find_open_slots", {"people": ["ana"], "duration_minutes": 50,
                                            "start_date": "2026-10-26", "end_date": "2026-10-26"})
    with pytest.raises(ValueError):
        run_tool(space, "send_invites", {})
    with pytest.raises(KeyError):
        run_tool(space, "get_busy_times", {"people": ["ana"]})


def test_place_hold_checks_everything_and_blocks_later_slots():
    space = ws()
    placed = hold(space)
    assert placed == {"hold_id": "hold-1", "start_utc": "2026-10-26T15:00Z", "end_utc": "2026-10-26T16:00Z",
                      "room_id": "loft", "people": ["ana", "ben"], "state": "held"}
    with pytest.raises(ValueError, match="not free"):
        hold(space, start="2026-10-26T15:30Z")                    # overlaps the first hold
    with pytest.raises(ValueError, match="not free"):
        hold(space, start="2026-10-26T14:00Z")                    # Ana is busy
    with pytest.raises(ValueError, match="working hours"):
        hold(space, start="2026-10-26T10:00Z")                    # 06:00 in New York
    with pytest.raises(ValueError, match="too small"):
        hold(space, start="2026-10-27T15:00Z", people=("ana", "ben", "dev"), room="nook")
    with pytest.raises(ValueError, match="15-minute"):
        hold(space, start="2026-10-27T15:10Z")
    slots = run_tool(space, "find_open_slots", {"people": ["ana", "ben"], "duration_minutes": 60,
                                                "start_date": "2026-10-26", "end_date": "2026-10-26"})["slots"]
    assert "2026-10-26T15:00Z" not in [s["start_utc"] for s in slots]


def test_release_hold():
    space = ws()
    hold(space)
    assert run_tool(space, "release_hold", {"hold_id": "hold-1"}) == {"hold_id": "hold-1", "state": "released"}
    with pytest.raises(ValueError):
        run_tool(space, "release_hold", {"hold_id": "hold-1"})
    hold(space, start="2026-10-26T15:30Z")                         # free again after release


def good(space, **changes):
    args = {"status": "proposed", "hold_id": "hold-1", "summary": "Monday 11:00 New York time.",
            "reasons": ["Everyone is free."], "tradeoffs": []}
    args.update(changes)
    return args


def test_a_valid_proposal_and_the_code_computed_result():
    space = ws()
    hold(space)
    assert validate_proposal(good(space), space) == []
    result = build_result(good(space), space)
    assert result["status"] == "proposed" and result["start_utc"] == "2026-10-26T15:00Z"
    assert result["duration_minutes"] == 60 and result["room"] == {"id": "loft", "name": "Loft"}
    assert result["attendees"] == [
        {"id": "ana", "name": "Ana Ortiz", "time_zone": "America/New_York",
         "local_start": "Mon 26 Oct 11:00", "local_end": "12:00"},
        {"id": "ben", "name": "Ben Okafor", "time_zone": "Europe/London",
         "local_start": "Mon 26 Oct 15:00", "local_end": "16:00"}]
    assert result["question"] is None and result["reason"] is None


def test_proposal_check_rules():
    space = ws()
    assert validate_proposal(good(space), space) == ["hold_id must be a hold placed in this run and still held"]
    hold(space)
    assert validate_proposal(good(space, summary=" "), space) == ["summary must be non-empty text"]
    assert validate_proposal(good(space, reasons=[]), space) == ["reasons must be a non-empty list of text"]
    assert validate_proposal(good(space, tradeoffs="none"), space) == ["tradeoffs must be a list of text"]
    assert validate_proposal({"status": "maybe"}, space) == ["status must be 'proposed' or 'question'"]
    assert validate_proposal("nope", space) == ["submit_proposal input must be an object"]
    assert validate_proposal({"status": "question", "question": ""}, space) == ["question must be non-empty text"]
    assert validate_proposal({"status": "question", "question": "Which week?"}, space) == []


def test_question_and_unable_results():
    space = ws()
    q = build_result({"status": "question", "question": "Which week?"}, space)
    assert q["status"] == "question" and q["question"] == "Which week?" and q["attendees"] == []
    u = unable_result("Ran out of steps (12) without a valid proposal")
    assert u["status"] == "unable" and u["reason"].startswith("Ran out of steps") and u["room"] is None
    assert set(q) == set(u) == {"status", "summary", "reasons", "tradeoffs", "question", "reason", "hold_id",
                                "start_utc", "end_utc", "duration_minutes", "room", "attendees"}


@pytest.mark.parametrize("start", ["2026-10-26T15:00", "2026-10-26 15:00", 5])
def test_place_hold_refuses_naive_or_non_text_start(start):
    with pytest.raises(ValueError, match="UTC time"):
        run_tool(ws(), "place_hold", {"start_utc": start, "duration_minutes": 60,
                                      "people": ["ana", "ben"], "room_id": "loft"})


@pytest.mark.parametrize("start", ["2026-10-26T15:00:30Z", "2026-10-26T15:00:00.5Z"])
def test_place_hold_refuses_fractional_seconds(start):
    with pytest.raises(ValueError, match="15-minute"):
        run_tool(ws(), "place_hold", {"start_utc": start, "duration_minutes": 60,
                                      "people": ["ana", "ben"], "room_id": "loft"})


ODD_INPUTS = [
    ("find_open_slots", {"people": [{}], "duration_minutes": 60, "start_date": "2026-10-26",
                         "end_date": "2026-10-26"}),
    ("find_open_slots", {"people": ["ana"], "duration_minutes": 60, "start_date": "2026-10-26",
                         "end_date": "2026-10-26", "room_needs": "x"}),
    ("find_open_slots", {"people": ["ana"], "duration_minutes": 60, "start_date": "2026-10-26",
                         "end_date": "2026-10-26", "earliest_local": 5}),
    ("place_hold", {"start_utc": "2026-10-26T15:00Z", "duration_minutes": 60, "people": ["ana", "ben"],
                    "room_id": []}),
    ("place_hold", {"start_utc": 5, "duration_minutes": 60, "people": ["ana", "ben"], "room_id": "loft"}),
    ("release_hold", {"hold_id": []}),
    ("list_people", None),
]


@pytest.mark.parametrize("name, args", ODD_INPUTS)
def test_odd_typed_inputs_raise_value_error(name, args):
    with pytest.raises(ValueError):
        run_tool(ws(), name, args)


def test_release_all():
    space = ws()
    hold(space)
    hold(space, start="2026-10-26T16:00Z", minutes=30)
    space.release_all()
    assert space.active_holds() == []
