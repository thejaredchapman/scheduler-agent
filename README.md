# The Front Desk scheduler

A demo AI agent that finds a meeting time and room for a fictional company. Claude looks up people, rooms and calendars with read-only tools and pencils in a hold, then hands a proposal to a person. It has no tool for sending: only after a person approves does plain code "send" (into an in-memory outbox that can be undone for 10 minutes). The slot, each attendee's local time, the room and the attendees are computed by code; the summary, reasons and trade-offs are "Claude's note", Claude's own words, which are not checked. It has a command line, a streaming web server, a web page, recorded sample runs and an evaluation. Nothing has been deployed.

## Results

On a development set of 16 scheduling requests we wrote, run 3 times each (48 runs):

- **98%** success in the re-run ([`eval/results.md`](eval/results.md)), up from **79%** in the first run ([`eval/results-first-run.md`](eval/results-first-run.md)).
- The first run's failures were not missing reasons: Claude wrote its reasons inside the summary text as markup in 25 submissions. We split the final tool in two, then re-ran. See [`eval/NOTES.md`](eval/NOTES.md). A check for that markup was added afterwards and is unmeasured.
- **0%** bad proposals in both runs, and **100%** questions asked when needed.
- Median **6.5 seconds** per request, about 3.8 model calls.
- Sent without approval: 0, by design (the AI has no sending tool), checked by tests.

These are small, self-written numbers, so treat them as a development result.

## Quick start

Put `ANTHROPIC_API_KEY=your-key-here` in a `.env` file in this folder (it is gitignored), then:

```
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
set -a; source .env; set +a
.venv/bin/python cli.py "Find 45 minutes next week for Priya and Tom"
```

Run `.venv/bin/python -m uvicorn server.app:app` for the web page. See the developer guide for details.

## Guides

- [Business guide](docs/business-guide.md): what it is, how well it worked, its limits.
- [Developer guide](docs/developer-guide.md): architecture, API, testing, deployment.
