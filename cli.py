"""Command line: run the scheduler, then let a PERSON approve, reject or preview.

Usage:  python cli.py "Find 45 minutes next week for Priya and Tom"   (needs ANTHROPIC_API_KEY)
"""
import argparse
import json
import sys

from agent import DEFAULT_MODEL, print_event, run_agent
from outbox import Outbox


def main(argv=None, input_fn=input, outbox=None, runner=None):
    parser = argparse.ArgumentParser(description="Find a meeting time; a person approves before anything is sent.")
    parser.add_argument("request")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args(argv)
    runner = runner or run_agent
    outbox = outbox or Outbox()
    final = None
    for event in runner(args.request, model=args.model):
        print_event(event)
        final = event
    result = final["result"]
    if result["status"] != "proposed":
        return 0
    try:
        choice = input_fn("\nType approve, reject or dry-run: ").strip().lower()
    except EOFError:  # no answer (e.g. piped input ended): treat it as a rejection
        choice = "reject"
    try:
        if choice == "approve":
            sent = outbox.approve(result)
            print(f"Sent {len(sent['invites'])} invites and booked {sent['room']['name']} ({sent['send_id']}).")
        elif choice == "dry-run":
            print("Would send:", json.dumps(outbox.dry_run(result), indent=2))
        else:
            outbox.reject(result)
            print("Rejected. Nothing was sent.")
    except ValueError as error:  # the outbox re-checks the proposal and refuses bad ones
        print(f"Not sent: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
