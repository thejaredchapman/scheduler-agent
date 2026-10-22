"""Run every scenario against the real model and report the results.

Usage:  python eval/run_eval.py [--model MODEL] [--runs 3] [--cases id1,id2] [--workers 1] [--out results] [--yes]
Costs real money. It prints what to expect and asks before starting.
"""
import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so `import agent` works when running this file directly
sys.path.insert(0, str(ROOT / "eval"))

from agent import DEFAULT_MODEL, run_agent  # noqa: E402
from scoring import grade, proposal_problems, render_markdown, summarize, timing_stats  # noqa: E402
from tools import TOOL_SCHEMAS  # noqa: E402
from world import get_world  # noqa: E402

TOKENS_PER_RUN = 25_000  # rough guess for the cost warning
KNOWN_TOOLS = {schema["name"] for schema in TOOL_SCHEMAS}


def run_case(scenario, model, run_number, runner=run_agent, world=None):
    """Run one scenario once and grade it."""
    world = world or get_world()
    base = {"id": scenario["id"], "group": scenario["group"], "run": run_number,
            "expected_status": scenario["expected_status"]}
    try:
        events = list(runner(scenario["request"], model=model))
        final = events[-1]
        if final["type"] != "result":
            raise RuntimeError("no result event")
        result = final["result"]
        correct, bad = grade(scenario, result, world)
        calls = [{"name": e["name"], "input": e["input"]} for e in events if e["type"] == "tool_call"]
        return {**base, "status": result.get("status"), "correct": correct, "bad_proposal": bad,
                "problems": proposal_problems(scenario, result, world) if result.get("status") == "proposed" else [],
                "result": result, "tool_calls": calls,
                "unknown_tools": sum(c["name"] not in KNOWN_TOOLS for c in calls),
                "tokens": final["usage"]["input_tokens"] + final["usage"]["output_tokens"],
                "seconds": final["elapsed_seconds"], "calls": final["turns"], "retries": final["proposal_retries"]}
    except Exception as error:
        # A crashed run becomes an "unable" row so the rest of the eval and its summary survive.
        # It has no seconds or calls keys, so it stays out of the timing numbers.
        return {**base, "status": "unable", "correct": False, "bad_proposal": False,
                "problems": [f"run crashed: {type(error).__name__}"], "result": {}, "tool_calls": [],
                "unknown_tools": 0, "tokens": 0, "retries": 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cases", help="comma-separated scenario ids (default: all)")
    parser.add_argument("--workers", type=int, default=1, help="runs at the same time (1 gives clean timing)")
    parser.add_argument("--out", default="results", help="writes eval/NAME.md, eval/NAME.json and eval/NAME.jsonl")
    parser.add_argument("--yes", action="store_true", help="skip the cost confirmation")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]+", args.out):
        sys.exit("--out must use only lowercase letters, digits and dashes")
    if args.workers < 1:
        sys.exit("--workers must be 1 or more")
    scenarios = json.loads((ROOT / "eval" / "scenarios.json").read_text())
    if args.cases:
        wanted = args.cases.split(",")
        unknown = sorted(set(wanted) - {s["id"] for s in scenarios})
        if unknown:
            sys.exit(f"Unknown scenario ids: {', '.join(unknown)}")
        scenarios = [s for s in scenarios if s["id"] in set(wanted)]
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY first (it is not stored anywhere in this repo).")
    runs = len(scenarios) * args.runs
    print(f"{len(scenarios)} scenarios x {args.runs} runs = {runs} runs on {args.model}.")
    print(f"Expect about {runs * TOKENS_PER_RUN:,} tokens. Check current pricing for that model before continuing.")
    if not args.yes and input("Continue? [y/N] ").strip().lower() != "y":
        sys.exit("Cancelled.")

    lines = ROOT / "eval" / f"{args.out}.jsonl"
    lines.write_text("")  # start fresh; each finished row is appended so a crash keeps them

    write_lock = threading.Lock()  # workers finish at different times; one at a time may append

    def one(job):
        row = run_case(job[0], args.model, job[1])
        with write_lock, lines.open("a") as f:
            f.write(json.dumps(row) + "\n")
        return row

    jobs = [(s, n) for s in scenarios for n in range(1, args.runs + 1)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(one, jobs))
    summary, timing = summarize(rows), timing_stats(rows)
    tokens = sum(r["tokens"] for r in rows)
    report = render_markdown(summary, args.model, args.runs, tokens, [r for r in rows if not r["correct"]],
                             timing=timing, workers=args.workers)
    (ROOT / "eval" / f"{args.out}.md").write_text(report)
    (ROOT / "eval" / f"{args.out}.json").write_text(
        json.dumps({"summary": summary, "timing": timing, "workers": args.workers, "rows": rows}, indent=2))
    print(report)


if __name__ == "__main__":
    main()
