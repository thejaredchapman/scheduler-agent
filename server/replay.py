"""Replay mode: when the daily budget is spent, show pre-recorded runs instead."""
import json
import re
import time
from pathlib import Path

# Only simple names are allowed, so a visitor cannot ask for "../../secrets".
_SAMPLE_ID = re.compile(r"^[a-z0-9-]{1,40}$")

PAUSED_NOTICE = "Live scheduling is paused for today (the daily limit was reached)."


def replay_events(replays_dir, sample_id, delay=0.4):
    """Yield a notice, then the recorded events for `sample_id` if one exists."""
    path = Path(replays_dir) / f"{sample_id}.json" if sample_id and _SAMPLE_ID.fullmatch(sample_id) else None
    if path is None or not path.is_file():
        yield {"type": "notice", "message": PAUSED_NOTICE + " Pick one of the sample requests to watch a recorded run."}
        return
    yield {"type": "notice", "message": PAUSED_NOTICE + " Replaying a recorded run of this request."}
    for event in json.loads(path.read_text())["events"]:
        time.sleep(delay)  # a small pause so the steps still appear one by one
        yield event
