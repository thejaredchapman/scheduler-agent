"""The demo world is well formed and every scenario's answer key matches the calendar maths."""
import json
import re
from collections import Counter
from pathlib import Path

from world import get_world, parse_utc, utc_text

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = json.loads((ROOT / "eval" / "scenarios.json").read_text())
W = get_world()
KEYS = {"id", "group", "kind", "request", "expected_status", "attendees", "duration_minutes", "window",
        "local_bounds", "room_needs", "acceptable_starts", "required_tradeoff"}


def slots(s):
    bounds = s["local_bounds"] or {}
    found = W.open_slots(s["attendees"], s["duration_minutes"], s["window"]["start_date"], s["window"]["end_date"],
                         bounds.get("earliest"), bounds.get("latest"), s["room_needs"], limit=None)
    return [utc_text(x["start"]) for x in found]


def test_world_shape():
    zones = Counter(p["time_zone"] for p in W.people.values())
    assert zones == {"America/New_York": 3, "Europe/London": 2, "America/Denver": 2, "Asia/Singapore": 1}
    assert sorted(r["capacity"] for r in W.rooms.values()) == [2, 4, 8, 14]
    assert any(p["working_hours"] == ["09:00", "14:00"] and p["time_zone"] == "Europe/London" for p in W.people.values())
    assert any(p["working_days"] == ["Mon", "Tue", "Wed", "Thu"] for p in W.people.values())
    for owner, blocks in json.loads((ROOT / "data" / "calendars.json").read_text()).items():
        assert owner in W.people or owner in W.rooms, owner
        for b in blocks:
            start, end = parse_utc(b["start"]), parse_utc(b["end"])
            assert start < end and start.minute % 15 == 0 and end.minute % 15 == 0
            assert set(b) == {"start", "end"}, "no titles"


def test_scenario_counts_and_keys():
    assert Counter(s["group"] for s in SCENARIOS) == {"straightforward": 4, "time_zones": 4, "tight": 4,
                                                      "impossible_or_ambiguous": 4}
    assert len({s["id"] for s in SCENARIOS}) == 16
    for s in SCENARIOS:
        assert set(s) == KEYS, s["id"]
        assert all(a in W.people for a in s["attendees"]), s["id"]
        assert not any(a in s["request"] for a in s["attendees"]), f"{s['id']}: use names, not ids"
        assert 15 <= s["duration_minutes"] <= 120 and s["duration_minutes"] % 15 == 0


def test_answer_keys_match_the_maths():
    for s in SCENARIOS:
        found = slots(s)
        if s["kind"] == "impossible":
            assert found == [], s["id"]
        elif s["kind"] == "ambiguous":
            assert s["expected_status"] == "question"
        elif s["acceptable_starts"] is not None:
            assert found == s["acceptable_starts"], (s["id"], found)
        else:
            assert len(found) >= 1, s["id"]
        if s["kind"]:
            assert s["expected_status"] == "question", s["id"]


def test_the_four_hour_gap_scenario_exists():
    short_day = [p for p in W.people.values() if p["working_hours"] == ["09:00", "14:00"]][0]["id"]
    new_york = {p["id"] for p in W.people.values() if p["time_zone"] == "America/New_York"}
    assert any(short_day in s["attendees"] and new_york & set(s["attendees"]) and s["expected_status"] == "proposed"
               for s in SCENARIOS if s["group"] == "time_zones")


def test_tradeoff_scenario():
    soft = [s for s in SCENARIOS if s["required_tradeoff"]]
    assert len(soft) >= 1 and all(s["expected_status"] == "proposed" for s in soft)
    for s in soft:
        assert all(p == p.lower() and p.strip() for p in s["required_tradeoff"])
