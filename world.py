"""The fictional world: people, rooms, busy times, and all the calendar maths.

All times are stored in UTC. Each person's local time comes from their time zone name
(like "Europe/London") through Python's zoneinfo, which knows every daylight-saving
change. That matters in the demo week: the UK leaves summer time on 25 October 2026 but
the US waits until 1 November, so London is 4 hours ahead of New York that week, not 5.
The AI never does this maths; this code does.
"""
import json
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(__file__).parent / "data"
DEMO_TODAY = "2026-10-20"  # a Tuesday; "next week" is Monday 26 to Friday 30 October 2026
STEP = timedelta(minutes=15)
UTC = timezone.utc
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def parse_utc(text):
    """'2026-10-26T13:00Z' -> a timezone-aware datetime in UTC."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def utc_text(moment):
    """A timezone-aware datetime -> '2026-10-26T13:00Z'."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


def overlaps(start_a, end_a, start_b, end_b):
    """True when two time ranges share any time (ranges that only touch do not overlap)."""
    return start_a < end_b and start_b < end_a


class World:
    """People, rooms and busy blocks, plus the calendar questions the tools ask."""

    def __init__(self, people, rooms, calendars):
        self.people = {p["id"]: p for p in people}
        self.rooms = {r["id"]: r for r in rooms}
        self.busy = {owner: [(parse_utc(b["start"]), parse_utc(b["end"])) for b in blocks]
                     for owner, blocks in calendars.items()}

    def zone(self, owner_id):
        record = self.people.get(owner_id) or self.rooms[owner_id]
        return ZoneInfo(record["time_zone"])

    def local(self, owner_id, moment):
        """The same moment on this person's (or room's) wall clock."""
        return moment.astimezone(self.zone(owner_id))

    def busy_blocks(self, owner_id, start, end):
        """This owner's busy blocks that overlap [start, end), earliest first."""
        return sorted((s, e) for s, e in self.busy.get(owner_id, []) if overlaps(s, e, start, end))

    def week_blocks(self, start, end):
        """Every person's and room's busy blocks that overlap [start, end), for the calendar grid."""
        found = {owner: self.busy_blocks(owner, start, end) for owner in self.busy}
        return {owner: blocks for owner, blocks in found.items() if blocks}

    def is_free(self, owner_id, start, end, holds=()):
        """True when no busy block and no hold for this owner overlaps the range."""
        if any(overlaps(s, e, start, end) for s, e in self.busy.get(owner_id, [])):
            return False
        return not any(owner_id in h["owners"] and overlaps(h["start"], h["end"], start, end) for h in holds)

    def within_hours(self, person_id, start, end, earliest=None, latest=None):
        """True when the range is inside this person's working day and hours.

        `earliest`/`latest` ("HH:MM", local time) can narrow the window further.
        """
        person = self.people[person_id]
        local_start, local_end = self.local(person_id, start), self.local(person_id, end)
        if local_start.date() != local_end.date():
            return False  # never across local midnight
        if DAY_NAMES[local_start.weekday()] not in person["working_days"]:
            return False
        opens, closes = (time.fromisoformat(t) for t in person["working_hours"])
        if earliest:
            opens = max(opens, time.fromisoformat(earliest))
        if latest:
            closes = min(closes, time.fromisoformat(latest))
        return opens <= local_start.time() and local_end.time() <= closes

    def rooms_that_fit(self, people_count, room_needs=None):
        """Rooms big enough and with the equipment asked for, smallest first."""
        needs = room_needs or {}
        size = max(people_count, needs.get("min_capacity", 0))
        wanted = set(needs.get("equipment", []))
        return sorted((r for r in self.rooms.values() if r["capacity"] >= size and wanted <= set(r["equipment"])),
                      key=lambda r: (r["capacity"], r["id"]))

    def open_slots(self, people, duration_minutes, start_date, end_date, earliest=None, latest=None,
                   room_needs=None, holds=(), limit=10):
        """Every start time (in 15-minute steps) when all `people` are at work and free, earliest first.

        `start_date`/`end_date` are calendar days (inclusive) on each attendee's own calendar.
        With `room_needs`, each slot also gets the smallest free room that fits, and slots with
        no such room are skipped. `limit=None` returns every slot (the eval's tests use that).
        """
        length = timedelta(minutes=duration_minutes)
        first, last = date.fromisoformat(start_date), date.fromisoformat(end_date)
        # Scan a little either side in UTC so every time zone's whole days are covered.
        moment = datetime.combine(first, time(0), UTC) - timedelta(hours=14)
        stop = datetime.combine(last + timedelta(days=1), time(0), UTC) + timedelta(hours=14)
        candidates = self.rooms_that_fit(len(people), room_needs) if room_needs is not None else None
        found = []
        while moment < stop and (limit is None or len(found) < limit):
            end = moment + length
            if all(first <= self.local(p, moment).date() <= last
                   and self.within_hours(p, moment, end, earliest, latest)
                   and self.is_free(p, moment, end, holds) for p in people):
                room = None
                if candidates is not None:
                    room = next((r for r in candidates if self.is_free(r["id"], moment, end, holds)), None)
                if candidates is None or room is not None:
                    found.append({"start": moment, "end": end, "room": room})
            moment += STEP
        return found


@lru_cache(maxsize=1)
def get_world():
    """The demo world from data/, loaded once per process."""
    def load(name):
        return json.loads((DATA_DIR / name).read_text())
    return World(load("people.json"), load("rooms.json"), load("calendars.json"))
