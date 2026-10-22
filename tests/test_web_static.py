"""Static checks on the front desk page (no browser needed)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
HTML = (WEB / "index.html").read_text()
JS = (WEB / "app.js").read_text()
CSS = (WEB / "styles.css").read_text()

THEME_SCRIPT = ('<script>(function(){var t=null;try{t=localStorage.getItem("theme")}catch(e){}'
                'if(t!=="light"&&t!=="dark"){t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}'
                'document.documentElement.dataset.theme=t})();</script>')


def tag(id_):
    """The opening tag of the element with this id."""
    match = re.search(r'<[a-z]+[^>]*\bid="' + re.escape(id_) + r'"[^>]*>', HTML)
    assert match, id_
    return match.group(0)


def test_exactly_one_inline_script_and_external_assets():
    inline = re.findall(r"<script>(.*?)</script>", HTML, flags=re.S)
    assert len(inline) == 1 and THEME_SCRIPT in HTML  # byte-for-byte: the CSP hash is computed from it
    assert '<script src="app.js" defer></script>' in HTML
    assert '<link rel="stylesheet" href="styles.css">' in HTML
    for url in re.findall(r'href="(https?://[^"]+)"', HTML):
        assert url.startswith("https://fonts.googleapis.com") or url.startswith("https://fonts.gstatic.com"), url
    assert "style=" not in HTML  # the CSP has no 'unsafe-inline' for styles


def test_required_elements():
    for id_ in ("theme-toggle", "theme-icon", "request-form", "request", "schedule", "samples", "zone",
                "week-grid", "trail", "notice", "proposal", "proposal-times", "claude-note", "approve", "reject",
                "dry-run", "usage", "question-card", "question-text", "clarification", "reply", "preview",
                "outbox", "announce"):
        assert f'id="{id_}"' in HTML, id_
    assert re.search(r'<button[^>]*id="theme-toggle"[^>]*>\s*<span[^>]*id="theme-icon"', HTML)


def test_text_boxes_are_capped_and_labelled():
    for id_ in ("request", "clarification"):
        box = tag(id_)
        assert box.startswith("<textarea") and 'maxlength="500"' in box, id_
        assert f'<label for="{id_}"' in HTML, id_


def test_form_posts_so_a_request_never_lands_in_the_url():
    form = tag("request-form")
    assert form.startswith("<form") and 'method="post"' in form and 'action="/schedule"' in form
    assert 'type="submit"' in tag("schedule")


def test_live_regions_and_landmarks():
    assert re.search(r'<ol[^>]*id="trail"[^>]*aria-live="polite"', HTML)
    notice = tag("notice")
    assert 'role="status"' in notice and "hidden" in notice
    proposal = tag("proposal")
    for attr in ('role="region"', 'aria-label="Proposal"', 'tabindex="-1"', "hidden"):
        assert attr in proposal, attr
    assert "hidden" in tag("question-card") and "hidden" in tag("preview")
    announce = tag("announce")
    assert 'class="visually-hidden"' in announce and 'aria-live="polite"' in announce
    grid = tag("week-grid")
    assert ('role="grid"' in grid or 'role="table"' in grid) and ("aria-label" in grid or "aria-labelledby" in grid)
    assert "Claude's note" in HTML or "Claude&#8217;s note" in HTML or "Claude&#39;s note" in HTML


def test_zone_selector_has_the_four_zones():
    assert tag("zone").startswith("<select")
    for zone in ("America/New_York", "Europe/London", "America/Denver", "Asia/Singapore"):
        assert f'value="{zone}"' in HTML, zone


def test_text_only_ever_goes_in_as_text():
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert banned not in JS, banned
    assert '"use strict"' in JS and "function el(" in JS and "textContent" in JS


def test_endpoints():
    assert 'fetch("/schedule"' in JS
    assert "JSON.stringify({ request, clarification, sample_id" in JS
    for path in ('"/approve"', '"/reject"', '"/dry-run"', '"/undo"', '"/api/world"', '"/api/outbox"',
                 '"/api/samples"'):
        assert path in JS, path


def test_the_browser_sends_only_ids_never_a_proposal():
    assert "proposal_id" in JS and "JSON.stringify({ proposal_id" in JS
    assert "JSON.stringify({ send_id" in JS
    # Every request body is built from ids or the typed text, never from a result or its attendees.
    for body in re.findall(r"JSON\.stringify\(([^)]*)\)", JS):
        assert "result" not in body and "attendees" not in body, body


def test_times_shown_in_the_chosen_zone_and_from_code():
    assert "Intl.DateTimeFormat" in JS and "timeZone" in JS
    assert "local_start" in JS and "local_end" in JS and "room.name" in JS


def test_status_labels_and_usage():
    assert '"proposed": "PROPOSED"' in JS
    assert '"question": "NEEDS YOUR ANSWER"' in JS
    assert '"unable": "COULD NOT SCHEDULE"' in JS
    assert "function usageText(" in JS and "Number.isFinite" in JS


def test_running_and_refusals():
    assert "aria-disabled" in JS and ".disabled =" not in JS and ".disabled=" not in JS
    assert "That was a lot of requests in a short time. Wait a minute and try again." in JS
    assert "409" in JS and ".detail" in JS
    assert "undo_seconds_left" in JS


def test_focus_moves_to_what_arrived():
    assert '$("proposal").focus(' in JS and '$("question-card").focus(' in JS and '$("schedule").focus(' in JS


def test_defensive_reads():
    assert "Number.isFinite(event.elapsed_seconds)" in JS and "Number.isFinite(u.input_tokens)" in JS
    assert "Array.isArray(result.attendees)" in JS


def test_accessibility_css():
    assert re.search(r"\.visually-hidden\s*\{[^}]*white-space:\s*nowrap", CSS)
    assert "prefers-reduced-motion: reduce" in CSS
    assert len(re.findall(r"min-height:\s*2\.75rem", CSS)) >= 2
    assert re.search(r"overflow-x:\s*auto", CSS)


def test_copy_is_honest_about_who_does_what():
    assert "Sent without your approval: 0" in HTML
    assert "by design" in HTML
    assert "sent to Anthropic's API" in HTML or "sent to Anthropic&#8217;s API" in HTML
    for overclaim in ("Claude sends", "Claude books", "the AI sends"):
        assert overclaim not in HTML, overclaim
