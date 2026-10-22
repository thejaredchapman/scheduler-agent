"""The scheduler's tools: look things up and pencil things in. Nothing here can send.

A Workspace belongs to one run and holds that run's pencilled-in holds. The outbox, where
invites are actually "sent", lives in outbox.py and no tool can reach it: sending happens
only after a person approves, in plain code. Every time shown to a person is computed here
by code, never copied from what the model wrote.
"""
import itertools
from datetime import date, datetime, time, timedelta

from world import UTC, get_world, utc_text

MAX_SLOTS = 10
MAX_DAYS = 31  # the longest date range a search may cover
RESULT_KEYS = ("status", "summary", "reasons", "tradeoffs", "question", "reason", "hold_id", "start_utc",
               "end_utc", "duration_minutes", "room", "attendees")


class Workspace:
    """One run's holds. Holds block later searches in the same run until released."""

    def __init__(self, world=None, booked=()):
        self.world = world or get_world()
        self.holds = {}
        self.booked = list(booked)  # meetings the person already approved; a run never releases them
        self._numbers = itertools.count(1)

    def active_holds(self):
        return [h for h in self.holds.values() if h["state"] == "held"]

    def blocking(self):
        """Everything that makes a time busy: pencilled-in holds from this run plus approved meetings."""
        return self.active_holds() + self.booked

    def release_all(self):
        for h in self.holds.values():
            h["state"] = "released"

    def new_id(self):
        return f"hold-{next(self._numbers)}"


def _people(space, ids):
    """Check a list of person ids: non-empty, known, no repeats."""
    if not isinstance(ids, list) or not ids:
        raise ValueError("people must be a non-empty list of person ids")
    unknown = [str(i) for i in ids if i not in space.world.people]
    if unknown:
        raise ValueError(f"unknown people: {', '.join(unknown)} (use list_people)")
    if len(set(ids)) != len(ids):
        raise ValueError("people must not repeat")
    return ids


def _duration(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 15 <= value <= 120 or value % 15:
        raise ValueError("duration_minutes must be 15 to 120, in steps of 15")
    return value


def _dates(args):
    """The first and last day of a search. The end must not be before the start, and at most 31 days."""
    first, last = date.fromisoformat(args["start_date"]), date.fromisoformat(args["end_date"])
    if last < first:
        raise ValueError("end_date is before start_date")
    if (last - first).days + 1 > MAX_DAYS:
        raise ValueError(f"the date range is longer than {MAX_DAYS} days; ask for a shorter one")
    return first, last


def _day_range(args):
    """The UTC range that covers start_date..end_date in every time zone."""
    first, last = _dates(args)
    return (datetime.combine(first, time(0), UTC) - timedelta(hours=14),
            datetime.combine(last + timedelta(days=1), time(0), UTC) + timedelta(hours=14))


def _clock(world, owner, moment, with_day=True):
    return world.local(owner, moment).strftime("%a %d %b %H:%M" if with_day else "%H:%M")


def list_people(space, args):
    return {"people": [{"id": p["id"], "name": p["name"], "role": p["role"], "time_zone": p["time_zone"],
                        "working_hours": "-".join(p["working_hours"]), "working_days": p["working_days"]}
                       for p in space.world.people.values()]}


def list_rooms(space, args):
    return {"rooms": [{"id": r["id"], "name": r["name"], "capacity": r["capacity"], "equipment": r["equipment"]}
                      for r in space.world.rooms.values()]}


def get_busy_times(space, args):
    people = _people(space, args["people"])
    start, end = _day_range(args)
    world = space.world
    return {"busy": {p: [{"start_utc": utc_text(s), "end_utc": utc_text(e),
                          "local": f"{_clock(world, p, s)}-{_clock(world, p, e, with_day=False)}"}
                         for s, e in world.busy_blocks(p, start, end)] for p in people}}


def find_open_slots(space, args):
    people = _people(space, args["people"])
    _dates(args)
    slots = space.world.open_slots(people, _duration(args["duration_minutes"]), args["start_date"],
                                   args["end_date"], args.get("earliest_local"), args.get("latest_local"),
                                   args.get("room_needs"), space.blocking(), MAX_SLOTS)
    return {"slots": [{"start_utc": utc_text(s["start"]), "room_id": s["room"]["id"] if s["room"] else None,
                       "local": {p: _clock(space.world, p, s["start"]) for p in people}} for s in slots]}


def _check_slot(space, start, end, people, room, ignore=None):
    """Problems with booking this slot (empty list = fine). `ignore` skips one hold (its own)."""
    world = space.world
    others = [h for h in space.blocking() if h is not ignore]
    problems = []
    if room["capacity"] < len(people):
        problems.append(f"room {room['id']} is too small for {len(people)} people")
    for p in people:
        if not world.within_hours(p, start, end):
            problems.append(f"{p} is outside working hours then")
        elif not world.is_free(p, start, end, others):
            problems.append(f"{p} is not free then")
    if not world.is_free(room["id"], start, end, others):
        problems.append(f"room {room['id']} is not free then")
    return problems


def _start_moment(text):
    """A start such as '2026-10-26T15:00Z' (or with an explicit offset). Naive times are refused,
    because they would be read in the machine's own time zone."""
    message = "start_utc must be a UTC time such as 2026-10-26T15:00Z"
    if not isinstance(text, str):
        raise ValueError(message)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(message) from None
    if moment.tzinfo is None:
        raise ValueError(message)
    return moment.astimezone(UTC)


def place_hold(space, args):
    people = _people(space, args["people"])
    minutes = _duration(args["duration_minutes"])
    start = _start_moment(args["start_utc"])
    if start.minute % 15 or start.second or start.microsecond:
        raise ValueError("start_utc must be on a 15-minute step")
    room = space.world.rooms.get(args["room_id"])
    if room is None:
        raise ValueError(f"unknown room {args['room_id']!r} (use list_rooms)")
    end = start + timedelta(minutes=minutes)
    problems = _check_slot(space, start, end, people, room)
    if problems:
        raise ValueError("; ".join(problems))
    hold_id = space.new_id()
    space.holds[hold_id] = {"id": hold_id, "start": start, "end": end, "people": list(people),
                            "room_id": room["id"], "owners": set(people) | {room["id"]}, "state": "held"}
    return {"hold_id": hold_id, "start_utc": utc_text(start), "end_utc": utc_text(end), "room_id": room["id"],
            "people": list(people), "state": "held"}


def release_hold(space, args):
    found = space.holds.get(args["hold_id"])
    if found is None or found["state"] != "held":
        raise ValueError(f"no active hold {args['hold_id']!r}")
    found["state"] = "released"
    return {"hold_id": found["id"], "state": "released"}


_TOOLS = {"list_people": list_people, "list_rooms": list_rooms, "get_busy_times": get_busy_times,
          "find_open_slots": find_open_slots, "place_hold": place_hold, "release_hold": release_hold}
TOOL_NAMES = tuple(_TOOLS)


def run_tool(space, name, args):
    """Run one tool. Raises on an unknown tool or bad arguments; the loop reports that back."""
    if name not in _TOOLS:
        raise ValueError(f"unknown tool {name!r}")
    if not isinstance(args, dict):
        raise ValueError(f"input for {name} must be an object")
    try:
        return _TOOLS[name](space, args)
    except (ValueError, KeyError):
        raise
    except Exception as error:  # odd-typed input (e.g. a list where an id belongs) becomes a plain ValueError
        raise ValueError(f"bad input for {name}: {type(error).__name__}") from error


_LEAK_MARKS = ("<parameter", "</")  # "</" also catches "</summary>"
LEAK_MESSAGE = ("your reasons ended up inside summary; send reasons as its own JSON array field, "
                "and keep summary to one or two plain sentences")


def _leaked(args):
    """True if the model's own words contain tag markup (its reasons spilled into another field)."""
    texts = [args.get("summary")]
    for key in ("reasons", "tradeoffs"):
        if isinstance(args.get(key), list):
            texts += args[key]
    return any(isinstance(t, str) and any(mark in t for mark in _LEAK_MARKS) for t in texts)


def _texts(value):
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def validate_proposal(args, space):
    """Problems with a submitted proposal (empty list = valid). Code re-checks the slot itself."""
    if not isinstance(args, dict):
        return ["submit_proposal input must be an object"]
    found = space.holds.get(args.get("hold_id")) if isinstance(args.get("hold_id"), str) else None
    if found is None or found["state"] != "held":
        return ["hold_id must be a hold placed in this run and still held"]
    errors = _check_slot(space, found["start"], found["end"], found["people"],
                         space.world.rooms[found["room_id"]], ignore=found)
    if not isinstance(args.get("summary"), str) or not args["summary"].strip():
        errors.append("summary must be non-empty text")
    if not _texts(args.get("reasons")) or not args.get("reasons"):
        errors.append("reasons must be a non-empty list of text")
    if not _texts(args.get("tradeoffs", [])):
        errors.append("tradeoffs must be a list of text")
    if _leaked(args):
        errors.append(LEAK_MESSAGE)
    return errors


def validate_question(args):
    """Problems with a submitted question (empty list = valid)."""
    if not isinstance(args, dict):
        return ["ask_question input must be an object"]
    q = args.get("question")
    return [] if isinstance(q, str) and q.strip() else ["question must be non-empty text"]


def _empty():
    return {key: None for key in RESULT_KEYS} | {"reasons": [], "tradeoffs": [], "attendees": []}


def build_result(args, space):
    """The proposal a person sees. Every time and name comes from code, not from the model."""
    result = _empty()
    found = space.holds[args["hold_id"]]
    world = space.world
    room = world.rooms[found["room_id"]]
    return result | {
        "status": "proposed", "summary": args["summary"].strip(), "reasons": list(args["reasons"]),
        "tradeoffs": list(args.get("tradeoffs", [])), "hold_id": found["id"],
        "start_utc": utc_text(found["start"]), "end_utc": utc_text(found["end"]),
        "duration_minutes": int((found["end"] - found["start"]).total_seconds() // 60),
        "room": {"id": room["id"], "name": room["name"]},
        "attendees": [{"id": p, "name": world.people[p]["name"], "time_zone": world.people[p]["time_zone"],
                       "local_start": _clock(world, p, found["start"]),
                       "local_end": _clock(world, p, found["end"], with_day=False)} for p in found["people"]]}


def question_result(args):
    """The result when the agent asks a question instead of proposing."""
    return _empty() | {"status": "question", "question": args["question"].strip()}


def unable_result(reason):
    """The safe ending when anything goes wrong: no proposal, just the reason."""
    return _empty() | {"status": "unable", "reason": reason}


_PEOPLE = {"type": "array", "items": {"type": "string"}, "description": "Person ids from list_people."}
_DATE = {"type": "string", "description": "YYYY-MM-DD"}
TOOL_SCHEMAS = [
    {"name": "list_people", "description": "List everyone: id, name, role, time zone, working hours and days.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "list_rooms", "description": "List meeting rooms (all in the New York office): capacity, equipment.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_busy_times", "description": "Busy blocks (no titles) for people between two dates, in UTC and local time.",
     "input_schema": {"type": "object", "properties": {"people": _PEOPLE, "start_date": _DATE, "end_date": _DATE},
                      "required": ["people", "start_date", "end_date"]}},
    {"name": "find_open_slots",
     "description": "Code finds up to 10 start times when everyone is at work and free (15-minute steps), "
                    "with each person's local time. Use this for all calendar and time-zone maths.",
     "input_schema": {"type": "object", "properties": {
         "people": _PEOPLE, "duration_minutes": {"type": "integer", "description": "15 to 120, steps of 15"},
         "start_date": _DATE, "end_date": _DATE,
         "earliest_local": {"type": "string", "description": "Optional HH:MM, applied to each person's local time"},
         "latest_local": {"type": "string", "description": "Optional HH:MM, applied to each person's local time"},
         "room_needs": {"type": "object", "properties": {
             "min_capacity": {"type": "integer"},
             "equipment": {"type": "array", "items": {"type": "string", "enum": ["screen", "video", "whiteboard"]}}}}},
         "required": ["people", "duration_minutes", "start_date", "end_date"]}},
    {"name": "place_hold", "description": "Pencil in a slot and a room (not sent to anyone). Fails if anything is not free.",
     "input_schema": {"type": "object", "properties": {
         "start_utc": {"type": "string", "description": "From find_open_slots, e.g. 2026-10-26T15:00Z"},
         "duration_minutes": {"type": "integer"}, "people": _PEOPLE, "room_id": {"type": "string"}},
         "required": ["start_utc", "duration_minutes", "people", "room_id"]}},
    {"name": "release_hold", "description": "Remove one of your holds.",
     "input_schema": {"type": "object", "properties": {"hold_id": {"type": "string"}}, "required": ["hold_id"]}},
    {"name": "submit_proposal",
     "description": "Finish with a proposal for a person to approve. You cannot send anything.",
     "input_schema": {"type": "object", "properties": {
         "hold_id": {"type": "string", "description": "A hold you placed and still hold."},
         "reasons": {"type": "array", "items": {"type": "string"}, "minItems": 1,
                     "description": "At least one reason this slot is a good choice."},
         "tradeoffs": {"type": "array", "items": {"type": "string"},
                       "description": "Preferences not met; an empty list if none."},
         "summary": {"type": "string", "description": "One or two plain sentences. No reasons in here."}},
         "required": ["hold_id", "summary", "reasons", "tradeoffs"]}},
    {"name": "ask_question",
     "description": "Finish by asking the person one short, specific question when the request is unclear "
                    "or cannot be met. This releases your holds.",
     "input_schema": {"type": "object", "properties": {"question": {"type": "string"}},
                      "required": ["question"]}},
]
