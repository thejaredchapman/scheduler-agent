"""Grade scheduler results against the scenarios, and turn rows into the numbers we publish."""
import statistics

from world import parse_utc


def _ratio(part, whole):
    return part / whole if whole else 0.0


def proposal_problems(scenario, result, world):
    """Hard-constraint violations of a proposed result, checked against the world (empty = none).

    A malformed result (missing or odd fields) is reported as a problem instead of raising,
    so one bad model answer cannot abort a whole paid eval.
    """
    try:
        return _check_proposal(scenario, result, world)
    except Exception as error:
        return [f"malformed result: {type(error).__name__}"]


def _check_proposal(scenario, result, world):
    problems = []
    attendees = [a["id"] for a in result["attendees"]]
    if sorted(attendees) != sorted(scenario["attendees"]):
        problems.append("wrong attendees")
    start, end = parse_utc(result["start_utc"]), parse_utc(result["end_utc"])
    if int((end - start).total_seconds() // 60) != scenario["duration_minutes"]:
        problems.append("wrong length")
    bounds = scenario["local_bounds"] or {}
    first, last = scenario["window"]["start_date"], scenario["window"]["end_date"]
    for person in attendees:
        if person not in world.people:
            problems.append(f"unknown person {person}")
            continue
        day = world.local(person, start).date().isoformat()
        if not first <= day <= last:
            problems.append(f"outside the requested days for {person}")
        if not world.within_hours(person, start, end, bounds.get("earliest"), bounds.get("latest")):
            problems.append(f"outside working hours or the requested times for {person}")
        if not world.is_free(person, start, end):
            problems.append(f"{person} is busy")
    room = world.rooms.get(result["room"]["id"])
    if room is None:
        problems.append("unknown room")
    else:
        fits = {r["id"] for r in world.rooms_that_fit(len(scenario["attendees"]), scenario["room_needs"])}
        if room["id"] not in fits:
            problems.append("room does not fit the needs")
        if not world.is_free(room["id"], start, end):
            problems.append("room is busy")
    return problems


def grade(scenario, result, world):
    """(correct, bad): bad means a proposal that breaks a hard constraint (the dangerous error)."""
    status = result.get("status")
    problems = proposal_problems(scenario, result, world) if status == "proposed" else []
    if status != scenario["expected_status"]:
        if scenario["expected_status"] == "question" and status == "proposed":
            return False, True  # a proposal where a question was needed is a bad proposal
        return False, bool(problems)
    if status == "question":
        return True, False
    if problems:
        return False, True
    if scenario["acceptable_starts"] is not None and result["start_utc"] not in scenario["acceptable_starts"]:
        return False, False
    if scenario["required_tradeoff"]:
        said = " ".join(result.get("tradeoffs", [])).lower()
        if not any(phrase in said for phrase in scenario["required_tradeoff"]):
            return False, False
    return True, False


def summarize(rows):
    by_group = {}
    for r in rows:
        group = by_group.setdefault(r["group"], {"total": 0, "correct": 0})
        group["total"] += 1
        group["correct"] += bool(r["correct"])
    for group in by_group.values():
        group["accuracy"] = _ratio(group["correct"], group["total"])
    needs_question = [r for r in rows if r["expected_status"] == "question"]
    bad = sum(bool(r["bad_proposal"]) for r in rows)
    return {"total": len(rows), "accuracy": _ratio(sum(bool(r["correct"]) for r in rows), len(rows)),
            "by_group": by_group, "bad_proposals": bad, "bad_proposal_rate": _ratio(bad, len(rows)),
            "question_when_needed": _ratio(sum(r["status"] == "question" for r in needs_question), len(needs_question)),
            "unable": sum(r["status"] == "unable" for r in rows), "retried": sum(r["retries"] for r in rows),
            "unknown_tools": sum(r["unknown_tools"] for r in rows)}


def timing_stats(rows):
    timed = [r for r in rows if "seconds" in r]
    if not timed:
        return None
    seconds = [r["seconds"] for r in timed]
    return {"median_seconds": round(statistics.median(seconds), 1), "slowest_seconds": round(max(seconds), 1),
            "mean_calls": round(float(statistics.mean(r["calls"] for r in timed)), 1)}


def render_markdown(summary, model, runs, tokens, failures, timing=None, workers=None):
    lines = [f"# Eval results: {model}", "",
             f"{summary['total']} graded runs ({runs} runs per scenario). Total tokens used: {tokens:,}.", "",
             f"- Success: **{summary['accuracy']:.0%}**",
             f"- Bad-proposal rate: **{summary['bad_proposal_rate']:.0%}** ({summary['bad_proposals']} proposals that "
             "would double-book someone, break working hours or miss a hard requirement)",
             f"- Asked a question when needed: **{summary['question_when_needed']:.0%}**",
             "- Sent without approval: **0** — by design: the AI has no sending tool (checked by tests)",
             f"- Unable: {summary['unable']} {'run' if summary['unable'] == 1 else 'runs'}; proposal retries: {summary['retried']}; "
             f"unknown tool calls: {summary['unknown_tools']}"]
    if timing:
        at_a_time = "1 run at a time" if workers == 1 else f"{workers} runs at a time"
        lines += [f"- Time per run: median **{timing['median_seconds']} s**, slowest {timing['slowest_seconds']} s "
                  f"({at_a_time})", f"- Model calls per run: average **{timing['mean_calls']}**"]
    lines += ["", "| Group | Correct | Total | Success |", "|---|---|---|---|"]
    for name, group in sorted(summary["by_group"].items()):
        lines.append(f"| {name} | {group['correct']} | {group['total']} | {group['accuracy']:.0%} |")
    lines += ["", "## Wrong answers", ""]
    if not failures:
        lines.append("None.")
    for f in failures:
        result = f.get("result") or {}
        detail = result.get("question") or result.get("reason") or result.get("start_utc") or ""
        lines.append(f"- `{f['id']}` run {f['run']} ({f['group']}): expected `{f['expected_status']}`, got "
                     f"`{f['status']}` {detail} {('problems: ' + '; '.join(f['problems'])) if f['problems'] else ''}".rstrip())
    return "\n".join(lines) + "\n"
