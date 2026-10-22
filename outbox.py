"""The outbox: the only place where invites are "sent". Plain code, after a person approves.

The AI cannot reach anything in this file. A person looks at a proposal and chooses:
  dry_run  - see exactly what would be sent; nothing changes
  approve  - re-check the slot is still free, then send the invites and book the room
  reject   - send nothing
  undo     - cancel a send within 10 minutes and free the slot again
Nothing leaves the demo: "sent" just means added to this list.
"""
import itertools
import time

from world import get_world, parse_utc

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
    def _letters(result):
        """The invites and the room booking, from the code-computed result."""
        return {"invites": [{"person_id": a["id"], "to": a["name"],
                             "when": f"{a['local_start']}-{a['local_end']} ({a['time_zone']})"}
                            for a in result["attendees"]],
                "room": dict(result["room"]), "start_utc": result["start_utc"], "end_utc": result["end_utc"]}

    def active(self):
        return [s for s in self.sent if not s["cancelled"]]

    def _as_holds(self):
        return [{"owners": {i["person_id"] for i in s["invites"]} | {s["room"]["id"]},
                 "start": parse_utc(s["start_utc"]), "end": parse_utc(s["end_utc"])} for s in self.active()]

    def dry_run(self, result):
        self._only_proposals(result)
        return {"dry_run": True, **self._letters(result)}

    def approve(self, result):
        self._only_proposals(result)
        start, end = parse_utc(result["start_utc"]), parse_utc(result["end_utc"])
        owners = [a["id"] for a in result["attendees"]] + [result["room"]["id"]]
        for owner in owners:  # the world may have changed since the proposal: check again
            if not self.world.is_free(owner, start, end, self._as_holds()):
                raise ValueError(f"{owner} is no longer free at that time. Nothing was sent.")
        send = {"send_id": f"send-{next(self._numbers)}", "cancelled": False, "sent_at": self.clock(),
                **self._letters(result)}
        self.sent.append(send)
        return dict(send)

    def reject(self, result):
        self._only_proposals(result)
        return {"rejected": True, "hold_id": result["hold_id"]}

    def undo(self, send_id):
        send = next((s for s in self.sent if s["send_id"] == send_id and not s["cancelled"]), None)
        if send is None:
            raise ValueError(f"Nothing to undo for {send_id!r}.")
        if self.clock() - send["sent_at"] > UNDO_SECONDS:
            raise ValueError("It is too late to undo (more than 10 minutes have passed).")
        send["cancelled"] = True
        return dict(send)
