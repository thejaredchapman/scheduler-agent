"""Record the four sample requests, for replay mode and the sample buttons.

Usage:  python -m server.record [--yes]      (needs ANTHROPIC_API_KEY; costs real money, a few cents)

These recordings are what the public sees, so nothing is saved unless EVERY sample ends the
way we expect AND is a correct, valid answer. A failed or surprising run never overwrites a good file.
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

from agent import DEFAULT_MODEL, run_agent
from eval.scoring import grade, proposal_problems
from world import get_world

ROOT = Path(__file__).resolve().parent.parent

# Each sample is one scenario from the eval, so the recorder and the eval agree on what "right" means.
SCENARIOS = {s["id"]: s for s in json.loads((ROOT / "eval" / "scenarios.json").read_text())}
_LABELS = {
    "straightforward-morning-sync": "A simple meeting",
    "time-zones-london-new-york": "London and New York (the 4-hour week)",
    "tight-four-people-two-regions": "Only one slot fits",
    "impossible-singapore-new-york": "Impossible: asks a question",
}
SAMPLES = [{"id": sid, "label": label, "request": SCENARIOS[sid]["request"],
            "expected_status": SCENARIOS[sid]["expected_status"]} for sid, label in _LABELS.items()]

# The start of every "unable" reason in agent.py: a run that hit one of these broke.
ERROR_MARKERS = ("Could not start the agent", "The model call failed", "Internal error",
                 "Could not produce a valid proposal", "Ran out of steps")


def check_recordings(results):
    """Return a list of problems with the runs (empty list = all good). Pure: no API, no files."""
    problems = []
    world = get_world()
    for sample in SAMPLES:
        events = results.get(sample["id"])
        if events is None:
            problems.append(f"missing sample: {sample['id']}")
            continue
        if not events or events[-1].get("type") != "result":
            problems.append(f"{sample['id']}: the run did not end with a result")
            continue
        result = events[-1]["result"]
        reason = result.get("reason") or ""
        scenario = SCENARIOS[sample["id"]]
        if result.get("status") == "unable" or any(reason.startswith(marker) for marker in ERROR_MARKERS):
            problems.append(f"{sample['id']}: the run hit an error: {reason}")
        elif result.get("status") != sample["expected_status"]:
            problems.append(f"{sample['id']}: got {result.get('status')!r}, expected {sample['expected_status']!r}")
        elif result["status"] == "proposed" and proposal_problems(scenario, result, world):
            found = "; ".join(proposal_problems(scenario, result, world))
            problems.append(f"{sample['id']}: the proposal is not valid: {found}")
        elif grade(scenario, result, world)[0] is not True:
            # Valid, but not what the eval counts as a correct answer (for example, an unaccepted start).
            problems.append(f"{sample['id']}: the eval would not count this answer as correct")
    return problems


def write_atomically(path, text):
    """Write via a temp file in the same folder, then swap it in, so a crash can't leave half a file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def main(argv=None, runner=None, out_dir=None, recorded_on=None):
    # The optional arguments let tests use a fake agent and a temporary folder.
    parser = argparse.ArgumentParser(description="Record the four sample requests for replay mode.")
    parser.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    args = parser.parse_args(argv)
    if runner is None:  # The real thing: needs a key and costs money.
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("Set ANTHROPIC_API_KEY first (it is not stored anywhere in this repo).")
            return 1
        runner = run_agent
        print(f"4 requests on {DEFAULT_MODEL}: a few cents in total (each takes several model calls). "
              "Check current pricing.")
        if not args.yes and input("Continue? [y/N] ").strip().lower() != "y":
            print("Cancelled.")
            return 1
    out_dir = Path(out_dir) if out_dir else ROOT / "web" / "replays"
    recorded_on = recorded_on or date.today().isoformat()

    # Run every sample first and keep the results in memory; write nothing yet.
    results = {sample["id"]: list(runner(sample["request"])) for sample in SAMPLES}
    problems = check_recordings(results)
    if problems:
        print("NOT SAVED. Problems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    for sample in SAMPLES:
        recording = {"id": sample["id"], "label": sample["label"], "request": sample["request"],
                     "model": DEFAULT_MODEL, "recorded_on": recorded_on, "events": results[sample["id"]]}
        write_atomically(out_dir / f"{sample['id']}.json", json.dumps(recording, indent=2, ensure_ascii=False) + "\n")
        print(f"{sample['id']}: {results[sample['id']][-1]['result']['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
