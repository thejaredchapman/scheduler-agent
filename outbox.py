"""The outbox: the only place where invites are "sent". Plain code, after a person approves.

The AI cannot reach anything in this file. A person looks at a proposal and chooses:
  dry_run  - see exactly what would be sent; nothing changes
  approve  - re-check the slot is still free, then send the invites and book the room
  reject   - send nothing
  undo     - cancel a send within 10 minutes and free the slot again
Nothing leaves the demo: "sent" just means added to this list.

A proposal is only a dict, so it is never trusted: every person, room, time and size is
checked against the world again here, and every name shown is taken from the world.
"""
import copy
import itertools
import math
import time
from datetime import datetime

from world import UTC, get_world, parse_utc, utc_text

UNDO_SECONDS = 600


class Outbox:
    def __init__(self, world=None, clock=time.monotonic):
        self.world = world or get_world()
        self.clock = clock
        self.sent = []
        self._numbers = itertools.count(1)

    @staticmethod
    def _only_proposals(result):
        if not isinstance(result, dict) or result.get("status") != "proposed":
            raise ValueError("Only a proposal can be approved, rejected or previewed.")

    @staticmethod
    def _need(result, key):
        value = result.get(key)
        if value is None:
            raise ValueError(f"The proposal is missing {key}. Nothing was sent.")
        return value

    @staticmethod
    def _moment(text):
        """A UTC start or end such as '2026-10-26T15:00Z'. Naive or broken times are refused."""
        message = "The proposal has a bad start or end time. Nothing was sent."
        if not isinstance(text, str):
            raise ValueError(message)
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError(message) from None
        if moment.tzinfo is None:
            raise ValueError(message)
        return moment.astimezone(UTC)

    def _checked(self, result):
        """Re-check a proposal against the world. Returns the checked facts (no names from the dict)."""
        self._only_proposals(result)
        world = self.world
        attendees = self._need(result, "attendees")
        if not isinstance(attendees, list) or not attendees:
            raise ValueError("The proposal has no attendees. Nothing was sent.")
        ids = []
        for attendee in attendees:
            person = attendee.get("id") if isinstance(attendee, dict) else None
            if not isinstance(person, str) or person not in world.people:
                raise ValueError(f"Unknown person {person!r} in the proposal. Nothing was sent.")
            ids.append(person)
        if len(set(ids)) != len(ids):
            raise ValueError("The proposal lists someone twice. Nothing was sent.")
        room = self._need(result, "room")
        room_id = room.get("id") if isinstance(room, dict) else None
        if not isinstance(room_id, str) or room_id not in world.rooms:
            raise ValueError(f"Unknown room {room_id!r} in the proposal. Nothing was sent.")
        start = self._moment(self._need(result, "start_utc"))
        end = self._moment(self._need(result, "end_utc"))
        if start >= end:
            raise ValueError("The proposal ends before it starts. Nothing was sent.")
        for person in ids:
            if not world.within_hours(person, start, end):
                raise ValueError(f"{world.people[person]['name']} is outside working hours then. Nothing was sent.")
        if len(ids) > world.rooms[room_id]["capacity"]:
            raise ValueError(f"Room {room_id} is too small for {len(ids)} people. Nothing was sent.")
        return {"ids": ids, "room_id": room_id, "start": start, "end": end}

    def _letters(self, checked):
        """The invites and the room booking, with every name and time computed from the world."""
        world, start, end = self.world, checked["start"], checked["end"]
        return {"invites": [{"person_id": p, "to": world.people[p]["name"],
                             "when": (f"{world.local(p, start).strftime('%a %d %b %H:%M')}-"
                                      f"{world.local(p, end).strftime('%H:%M')} "
                                      f"({world.people[p]['time_zone']})")}
                            for p in checked["ids"]],
                "room": {"id": checked["room_id"], "name": world.rooms[checked["room_id"]]["name"]},
                "start_utc": utc_text(start), "end_utc": utc_text(end)}

    def active(self):
        return [s for s in self.sent if not s["cancelled"]]

    def as_holds(self):
        return [{"owners": {i["person_id"] for i in s["invites"]} | {s["room"]["id"]},
                 "start": parse_utc(s["start_utc"]), "end": parse_utc(s["end_utc"])} for s in self.active()]

    def listing(self):
        """Active sends for the outbox panel, with the seconds left to undo each one."""
        now = self.clock()
        return [copy.deepcopy({**{k: v for k, v in s.items() if k not in ("sent_at", "cancelled")},
                               "undo_seconds_left": max(0, math.ceil(UNDO_SECONDS - (now - s["sent_at"])))})
                for s in self.active()]

    def dry_run(self, result):
        checked = self._checked(result)
        free = self._all_free(checked)  # only looks; nothing is changed
        return copy.deepcopy({"dry_run": True, "still_free": free, **self._letters(checked)})

    def _not_free(self, checked):
        """The first person or room that is no longer free for this slot (None if all are free)."""
        for owner in checked["ids"] + [checked["room_id"]]:
            if not self.world.is_free(owner, checked["start"], checked["end"], self.as_holds()):
                return owner
        return None

    def _all_free(self, checked):
        return self._not_free(checked) is None

    def approve(self, result):
        checked = self._checked(result)
        owner = self._not_free(checked)  # the world may have changed since the proposal: check again
        if owner is not None:
            raise ValueError(f"{owner} is no longer free at that time. Nothing was sent.")
        send = {"send_id": f"send-{next(self._numbers)}", "cancelled": False, "sent_at": self.clock(),
                **self._letters(checked)}
        self.sent.append(send)
        return copy.deepcopy(send)

    def reject(self, result):
        self._only_proposals(result)
        return {"rejected": True, "hold_id": copy.deepcopy(self._need(result, "hold_id"))}

    def undo(self, send_id):
        send = next((s for s in self.sent if s["send_id"] == send_id and not s["cancelled"]), None)
        if send is None:
            raise ValueError(f"Nothing to undo for {send_id!r}.")
        if self.clock() - send["sent_at"] > UNDO_SECONDS:
            raise ValueError("It is too late to undo (more than 10 minutes have passed).")
        send["cancelled"] = True
        return copy.deepcopy(send)
