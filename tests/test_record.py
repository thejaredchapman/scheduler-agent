"""The recorder never saves a broken or surprising run (no API calls)."""
import json

from eval.scoring import grade
from server.record import ERROR_MARKERS, SAMPLES, SCENARIOS, check_recordings, main
from tools import Workspace, build_result, question_result, run_tool, utc_text
from world import get_world


def result_event(result):
    """Wrap a result the way run_agent's last event looks."""
    return {"type": "result", "result": result, "usage": {"input_tokens": 1, "output_tokens": 1},
            "turns": 1, "proposal_retries": 0, "elapsed_seconds": 1.0}


def proposed_event(scenario):
    """A real, valid proposal built with the same code the agent uses (no model involved)."""
    world = get_world()
    bounds = scenario["local_bounds"] or {}
    slots = world.open_slots(scenario["attendees"], scenario["duration_minutes"],
                             scenario["window"]["start_date"], scenario["window"]["end_date"],
                             bounds.get("earliest"), bounds.get("latest"), scenario["room_needs"] or {},
                             limit=None)
    if scenario["acceptable_starts"]:  # the tight sample has only one right answer
        slots = [s for s in slots if utc_text(s["start"]) in scenario["acceptable_starts"]]
    slot = slots[0]
    space = Workspace(world)
    held = run_tool(space, "place_hold", {"start_utc": utc_text(slot["start"]),
                                          "duration_minutes": scenario["duration_minutes"],
                                          "people": scenario["attendees"], "room_id": slot["room"]["id"]})
    args = {"hold_id": held["hold_id"], "summary": "A good time.", "reasons": ["Everyone is free."]}
    return result_event(build_result(args, space))


def good_event(sample):
    scenario = SCENARIOS[sample["id"]]
    if sample["expected_status"] == "question":
        return result_event(question_result({"question": "Which of you can stretch your hours?"}))
    return proposed_event(scenario)


def good_results():
    return {s["id"]: [good_event(s)] for s in SAMPLES}


def unable_event(reason="Ran out of steps (12) without a valid proposal"):
    return result_event({"status": "unable", "reason": reason})


def test_the_four_samples():
    assert [s["id"] for s in SAMPLES] == ["straightforward-morning-sync", "time-zones-london-new-york",
                                          "tight-four-people-two-regions", "impossible-singapore-new-york"]
    assert [s["label"] for s in SAMPLES] == ["A simple meeting", "London and New York (the 4-hour week)",
                                             "Only one slot fits", "Impossible: asks a question"]
    assert [s["expected_status"] for s in SAMPLES] == ["proposed", "proposed", "proposed", "question"]
    assert all(s["request"] == SCENARIOS[s["id"]]["request"] for s in SAMPLES)
    assert len(ERROR_MARKERS) == 5 and ERROR_MARKERS[0] == "Could not start the agent"


def test_good_fakes_are_really_correct():
    for sample in SAMPLES:  # guards the test helpers themselves
        assert grade(SCENARIOS[sample["id"]], good_event(sample)["result"], get_world())[0] is True


def test_check_accepts_good_runs():
    assert check_recordings(good_results()) == []


def test_check_names_problems():
    results = good_results()
    results["impossible-singapore-new-york"] = [proposed_event(SCENARIOS["straightforward-morning-sync"])]
    results["straightforward-morning-sync"] = [unable_event("Internal error (KeyError)")]
    del results["time-zones-london-new-york"]
    results["tight-four-people-two-regions"] = [{"type": "token", "text": "hi"}]
    problems = check_recordings(results)
    assert "missing sample: time-zones-london-new-york" in problems
    assert "impossible-singapore-new-york: got 'proposed', expected 'question'" in problems
    assert any(p.startswith("straightforward-morning-sync: the run hit an error") for p in problems)
    assert "tight-four-people-two-regions: the run did not end with a result" in problems


def test_check_refuses_every_error_marker():
    for marker in ERROR_MARKERS:
        results = good_results()
        results["impossible-singapore-new-york"] = [result_event(
            {"status": "question", "question": "?", "reason": marker + " (x)"})]
        assert any("hit an error" in p for p in check_recordings(results))


def test_check_refuses_an_invalid_proposal():
    results = good_results()
    event = proposed_event(SCENARIOS["straightforward-morning-sync"])
    event["result"]["attendees"] = event["result"]["attendees"][:1]  # someone is missing
    results["straightforward-morning-sync"] = [event]
    problems = check_recordings(results)
    assert any(p.startswith("straightforward-morning-sync: the proposal is not valid") and "wrong attendees" in p
               for p in problems)


def test_check_refuses_a_valid_but_unacceptable_start(monkeypatch):
    # A legal proposal that the eval would not count as correct (its start is not an accepted one)
    # must not be published. Make the tight scenario accept a different start than the valid one.
    sid = "tight-four-people-two-regions"
    results = good_results()
    assert check_recordings(results) == []
    strict = dict(SCENARIOS[sid], acceptable_starts=["2026-10-29T00:00Z"])
    monkeypatch.setitem(SCENARIOS, sid, strict)
    problems = check_recordings(results)
    assert f"{sid}: the eval would not count this answer as correct" in problems


def test_main_writes_nothing_unless_every_run_is_good(tmp_path):
    def bad(request):
        return [unable_event()]
    assert main([], runner=bad, out_dir=tmp_path) == 1
    assert list(tmp_path.glob("*")) == []


def test_main_saves_labelled_recordings(tmp_path):
    by_request = {s["request"]: [good_event(s)] for s in SAMPLES}
    assert main([], runner=lambda request: by_request[request], out_dir=tmp_path, recorded_on="2026-10-22") == 0
    saved = json.loads((tmp_path / "impossible-singapore-new-york.json").read_text())
    assert set(saved) == {"id", "label", "request", "model", "recorded_on", "events"}
    assert saved["recorded_on"] == "2026-10-22" and saved["events"][-1]["type"] == "result"
    assert len(list(tmp_path.glob("*.json"))) == 4


def test_main_needs_a_key_for_real_runs(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main([], out_dir=tmp_path) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().out
