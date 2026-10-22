"""The committed replay files are complete, correct, and free of leaks (no API calls, no network)."""
import json
from pathlib import Path

from server.record import SAMPLES, check_recordings

REPLAYS = Path(__file__).resolve().parent.parent / "web" / "replays"

# The keys every recording file must have, and nothing else.
KEYS = {"id", "label", "request", "model", "recorded_on", "events"}

# Things that must never be in a public file. The key prefix is built by joining pieces,
# so this test file never contains the literal start of an API key.
LEAK_MARKERS = ["/Users/", "Traceback", "sk-" + "ant"]


def load_all():
    """Read every replay file into a dict: sample id -> the whole recording."""
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in REPLAYS.glob("*.json")}


def test_one_file_per_sample():
    # Exactly one file per sample, named <id>.json, and no extra files.
    expected = {sample["id"] for sample in SAMPLES}
    files = sorted(path.name for path in REPLAYS.glob("*.json"))
    assert files == sorted(f"{sid}.json" for sid in expected)


def test_recordings_pass_the_recorder_checks():
    # Rebuild the same shape the recorder checks: sample id -> list of events.
    recordings = load_all()
    results = {sid: recording["events"] for sid, recording in recordings.items()}
    assert check_recordings(results) == []


def test_each_file_has_the_right_keys():
    for sid, recording in load_all().items():
        assert set(recording.keys()) == KEYS, sid
        assert recording["id"] == sid


def test_each_file_ends_with_a_result():
    # The last event must be the final result, with a timing number.
    for sid, recording in load_all().items():
        last = recording["events"][-1]
        assert last["type"] == "result", sid
        assert isinstance(last["elapsed_seconds"], float), sid


def test_no_leaks_in_any_file():
    # Check the raw text, so a leak anywhere in the file is caught.
    for path in REPLAYS.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        for marker in LEAK_MARKERS:
            assert marker not in text, f"{path.name} contains {marker!r}"
