"""The CLI: approval is a person typing at a prompt, then plain code sends."""
from cli import main
from outbox import Outbox
from tests.fixtures import fixture_world

PROPOSED = {"type": "result", "usage": {"input_tokens": 1, "output_tokens": 1}, "turns": 2, "proposal_retries": 0,
            "elapsed_seconds": 1.0, "result": {
                "status": "proposed", "summary": "s", "reasons": ["r"], "tradeoffs": [], "question": None,
                "reason": None, "hold_id": "hold-1", "start_utc": "2026-10-26T15:00Z", "end_utc": "2026-10-26T16:00Z",
                "duration_minutes": 60, "room": {"id": "loft", "name": "Loft"},
                "attendees": [{"id": "ana", "name": "Ana Ortiz", "time_zone": "America/New_York",
                               "local_start": "Mon 26 Oct 11:00", "local_end": "12:00"}]}}


def runner(request, **kwargs):
    return [PROPOSED]


def test_approve_sends(capsys):
    box = Outbox(fixture_world())
    assert main(["Find an hour"], input_fn=lambda prompt: "approve", outbox=box, runner=runner) == 0
    assert len(box.sent) == 1 and "Sent" in capsys.readouterr().out


def test_reject_and_dry_run_send_nothing(capsys):
    for answer in ("reject", "dry-run"):
        box = Outbox(fixture_world())
        main(["x"], input_fn=lambda prompt, a=answer: a, outbox=box, runner=runner)
        assert box.sent == []
    assert "Would send" in capsys.readouterr().out


def test_a_refused_approval_prints_the_reason_and_returns_1(capsys):
    class RefusingOutbox(Outbox):
        def approve(self, result):
            raise ValueError("Room Loft is too small for 9 people. Nothing was sent.")

    box = RefusingOutbox(fixture_world())
    assert main(["x"], input_fn=lambda prompt: "approve", outbox=box, runner=runner) == 1
    out = capsys.readouterr().out
    assert "Not sent: Room Loft is too small" in out and box.sent == []


def test_end_of_input_counts_as_reject(capsys):
    def no_input(prompt):
        raise EOFError
    box = Outbox(fixture_world())
    assert main(["x"], input_fn=no_input, outbox=box, runner=runner) == 0
    assert box.sent == [] and "Rejected" in capsys.readouterr().out
