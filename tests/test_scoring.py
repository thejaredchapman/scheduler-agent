from eval.scoring import grade, proposal_problems, render_markdown, summarize, timing_stats
from tests.fixtures import fixture_world

W = fixture_world()
SCENARIO = {"id": "x", "group": "straightforward", "kind": None, "request": "r", "expected_status": "proposed",
            "attendees": ["ana", "ben"], "duration_minutes": 60,
            "window": {"start_date": "2026-10-26", "end_date": "2026-10-26"}, "local_bounds": None,
            "room_needs": {"equipment": ["video"]}, "acceptable_starts": None, "required_tradeoff": None}


def proposed(start="2026-10-26T15:00Z", end="2026-10-26T16:00Z", room="loft", people=("ana", "ben"), tradeoffs=()):
    return {"status": "proposed", "start_utc": start, "end_utc": end, "duration_minutes": 60,
            "room": {"id": room, "name": room}, "attendees": [{"id": p} for p in people],
            "tradeoffs": list(tradeoffs), "summary": "s", "reasons": ["r"], "question": None, "reason": None,
            "hold_id": "hold-1"}


def test_a_good_proposal():
    assert proposal_problems(SCENARIO, proposed(), W) == []
    assert grade(SCENARIO, proposed(), W) == (True, False)


def test_bad_proposals_are_flagged():
    assert grade(SCENARIO, proposed(start="2026-10-26T14:00Z", end="2026-10-26T15:00Z"), W) == (False, True)  # Ana busy
    assert grade(SCENARIO, proposed(room="nook"), W) == (False, True)                     # no video in Nook
    assert grade(SCENARIO, proposed(people=("ana",)), W) == (False, True)                 # wrong attendees
    assert grade(SCENARIO, proposed(start="2026-10-26T10:00Z", end="2026-10-26T11:00Z"), W) == (False, True)  # hours


def test_acceptable_starts_tradeoffs_and_questions():
    tight = dict(SCENARIO, acceptable_starts=["2026-10-26T16:00Z"])
    assert grade(tight, proposed(), W) == (False, False)
    soft = dict(SCENARIO, required_tradeoff=["morning"])
    assert grade(soft, proposed(), W) == (False, False)
    assert grade(soft, proposed(tradeoffs=["Not in the morning for Ben."]), W) == (True, False)
    ask = dict(SCENARIO, expected_status="question")
    assert grade(ask, {"status": "question", "question": "Which week?"}, W) == (True, False)
    assert grade(ask, proposed(), W) == (False, False)
    assert grade(SCENARIO, {"status": "unable", "reason": "x"}, W) == (False, False)


def row(group, expected, status, correct, bad=False, **extra):
    base = {"id": "x", "group": group, "run": 1, "expected_status": expected, "status": status, "correct": correct,
            "bad_proposal": bad, "problems": [], "result": {}, "tool_calls": [], "unknown_tools": 0, "tokens": 10,
            "seconds": 2.0, "calls": 3, "retries": 0}
    base.update(extra)
    return base


def test_summary_and_report():
    rows = [row("straightforward", "proposed", "proposed", True),
            row("tight", "proposed", "proposed", False, bad=True),
            row("impossible_or_ambiguous", "question", "question", True),
            row("impossible_or_ambiguous", "question", "proposed", False),
            row("time_zones", "proposed", "unable", False, retries=1)]
    summary = summarize(rows)
    assert summary["accuracy"] == 0.4 and summary["bad_proposals"] == 1 and summary["bad_proposal_rate"] == 0.2
    assert summary["question_when_needed"] == 0.5 and summary["unable"] == 1 and summary["retried"] == 1
    assert summary["unknown_tools"] == 0
    text = render_markdown(summary, "m", 3, 50, [r for r in rows if not r["correct"]], timing=timing_stats(rows), workers=1)
    assert text.startswith("# Eval results: m\n")
    for line in ("- Success: **40%**", "- Bad-proposal rate: **20%**", "- Asked a question when needed: **50%**",
                 "- Sent without approval: **0** (the AI has no sending tool; checked by tests)",
                 "- Time per run: median **2.0 s**, slowest 2.0 s (1 run at a time)"):
        assert line in text, line


def test_run_case_grades_and_counts_tools():
    import importlib.util
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "eval"))
    spec = importlib.util.spec_from_file_location("run_eval", root / "eval" / "run_eval.py")
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)

    def fake(request, model):
        return [{"type": "tool_call", "id": "a", "name": "send_invites", "input": {}},
                {"type": "result", "result": proposed(), "usage": {"input_tokens": 7, "output_tokens": 3},
                 "turns": 2, "proposal_retries": 0, "elapsed_seconds": 1.5}]
    r = run_eval.run_case(SCENARIO, "m", 1, runner=fake, world=W)
    assert r["correct"] and r["tokens"] == 10 and r["unknown_tools"] == 1 and r["result"]["start_utc"]
