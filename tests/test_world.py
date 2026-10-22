"""Calendar maths and time zones."""
from world import DEMO_TODAY, parse_utc, utc_text
from tests.fixtures import fixture_world

W = fixture_world()


def t(text):
    return parse_utc(text)


def test_utc_round_trip():
    assert utc_text(t("2026-10-26T13:00Z")) == "2026-10-26T13:00Z"
    assert DEMO_TODAY == "2026-10-20"


def test_the_demo_week_daylight_saving_gap():
    # Monday 26 Oct: London has left summer time, New York has not -> 4 hours apart.
    assert W.local("ben", t("2026-10-26T12:00Z")).hour == 12
    assert W.local("ana", t("2026-10-26T12:00Z")).hour == 8
    # The Friday before, London was still on summer time (UTC+1).
    assert W.local("ben", t("2026-10-23T12:00Z")).hour == 13


def test_within_hours_days_and_midnight():
    assert W.within_hours("ben", t("2026-10-26T09:00Z"), t("2026-10-26T09:30Z"))
    assert not W.within_hours("ana", t("2026-10-26T09:00Z"), t("2026-10-26T09:30Z"))   # 05:00 in New York
    assert W.within_hours("ana", t("2026-10-26T20:00Z"), t("2026-10-26T21:00Z"))       # ends exactly at 17:00
    assert not W.within_hours("dev", t("2026-10-30T16:00Z"), t("2026-10-30T17:00Z"))   # Dev does not work Fridays
    assert not W.within_hours("ben", t("2026-10-26T16:30Z"), t("2026-10-26T17:30Z"))   # runs past 17:00
    assert not W.within_hours("ben", t("2026-10-26T10:00Z"), t("2026-10-26T11:00Z"), earliest="10:30")


def test_free_and_holds():
    assert not W.is_free("ana", t("2026-10-26T14:30Z"), t("2026-10-26T15:30Z"))
    assert W.is_free("ana", t("2026-10-26T15:00Z"), t("2026-10-26T16:00Z"))              # touching ends is fine
    hold = {"owners": {"ana", "loft"}, "start": t("2026-10-26T15:00Z"), "end": t("2026-10-26T16:00Z")}
    assert not W.is_free("ana", t("2026-10-26T15:30Z"), t("2026-10-26T16:30Z"), holds=[hold])
    assert W.is_free("ben", t("2026-10-26T15:30Z"), t("2026-10-26T16:30Z"), holds=[hold])


def test_open_slots_for_new_york_and_london():
    slots = W.open_slots(["ana", "ben"], 60, "2026-10-26", "2026-10-26", limit=None)
    starts = [utc_text(s["start"]) for s in slots]
    assert starts == ["2026-10-26T13:00Z", "2026-10-26T15:00Z", "2026-10-26T15:15Z", "2026-10-26T15:30Z",
                      "2026-10-26T15:45Z", "2026-10-26T16:00Z"]
    assert all(s["room"] is None for s in slots)


def test_open_slots_with_a_room_and_a_local_window():
    with_video = W.open_slots(["ana", "ben"], 60, "2026-10-26", "2026-10-26", room_needs={"equipment": ["video"]})
    assert utc_text(with_video[0]["start"]) == "2026-10-26T15:00Z" and with_video[0]["room"]["id"] == "loft"
    late = W.open_slots(["ana", "ben"], 30, "2026-10-26", "2026-10-26", earliest="10:00")
    assert utc_text(late[0]["start"]) == "2026-10-26T15:00Z"     # 10:00 in New York is 14:00Z, when Ana is busy
    assert len(W.open_slots(["ana", "ben"], 15, "2026-10-26", "2026-10-30")) == 10     # the default limit
    assert W.open_slots(["ana", "chen"], 60, "2026-10-26", "2026-10-30") == []         # New York and Singapore never overlap


def test_rooms_that_fit():
    assert [r["id"] for r in W.rooms_that_fit(2)] == ["nook", "loft"]
    assert [r["id"] for r in W.rooms_that_fit(3)] == ["loft"]
    assert [r["id"] for r in W.rooms_that_fit(2, {"equipment": ["video"]})] == ["loft"]
    assert W.rooms_that_fit(2, {"min_capacity": 10}) == []
