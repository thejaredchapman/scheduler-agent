"""Keep the guides and README honest: sections, links, numbers and contacts."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUSINESS, DEVELOPER, README = ROOT / "docs" / "business-guide.md", ROOT / "docs" / "developer-guide.md", ROOT / "README.md"
BUSINESS_SECTIONS = ["What this is", "What it could do for your team", "How to try the demo", "Use cases",
                     "What it is not", "How well it worked in testing", "Frequently asked questions", "Glossary"]
DEVELOPER_SECTIONS = ["Overview and architecture", "Quick start", "Expected behavior", "API reference", "Data formats",
                      "Extending", "Testing", "Security model and deployment", "Troubleshooting", "Getting help"]
PROFILE = "https://github.com/thejaredchapman"


def read(path):
    return path.read_text(encoding="utf-8")


def headings(text):
    return re.findall(r"^## (.+?)\s*$", text, re.M)


def section(text, title):
    match = re.search(rf"^## {re.escape(title)}.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"missing section {title}"
    return match.group(1)


def test_sections_in_order():
    assert [h for h in headings(read(BUSINESS)) if h in BUSINESS_SECTIONS] == BUSINESS_SECTIONS
    assert [h for h in headings(read(DEVELOPER)) if h in DEVELOPER_SECTIONS] == DEVELOPER_SECTIONS


def test_relative_links_resolve():
    for path in (BUSINESS, DEVELOPER, README):
        for target in re.findall(r"\]\(([^)#]+?)(?:#[^)]*)?\)", read(path)):
            if not target.startswith(("http://", "https://", "mailto:")):
                assert (path.parent / target).exists(), f"{path.name}: broken link {target}"


def test_business_guide_is_plain():
    text = read(BUSINESS)
    assert "```" not in text
    assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", text)


def test_numbers_match_the_result_files():
    results, first = read(ROOT / "eval" / "results.md"), read(ROOT / "eval" / "results-first-run.md")
    success = re.search(r"- Success: \*\*(\d+%)\*\*", results).group(1)
    first_success = re.search(r"- Success: \*\*(\d+%)\*\*", first).group(1)
    bad = re.search(r"- Bad-proposal rate: \*\*(\d+%)\*\*", results).group(1)
    first_bad = re.search(r"- Bad-proposal rate: \*\*(\d+%)\*\*", first).group(1)
    median = re.search(r"median \*\*([\d.]+) s\*\*", results).group(1)
    for path in (BUSINESS, README):
        text = read(path)
        for value in (success, first_success, bad, first_bad):
            assert value in text, (path.name, value)
        assert f"{median} seconds" in text, path.name
    dev = read(DEVELOPER)
    assert success in dev and first_success in dev and f"{median} s" in dev


def test_limits_in_the_developer_guide_match_the_code():
    from agent import MAX_TURNS
    from outbox import UNDO_SECONDS
    from server.app import DAILY_TOKEN_CAP, MAX_REQUEST_CHARS, RESERVED_TOKENS_PER_RUN
    from server.guards import RateLimiter
    from server.sessions import SessionStore
    from tools import MAX_DAYS
    text = read(DEVELOPER)
    limiter, store = RateLimiter(), SessionStore()
    for value in (MAX_REQUEST_CHARS, DAILY_TOKEN_CAP, RESERVED_TOKENS_PER_RUN, MAX_TURNS, 2048, MAX_DAYS,
                  limiter.max_requests, limiter.window_seconds, store.max_sessions, store.idle_seconds,
                  UNDO_SECONDS):
        assert f"{value:,}" in text or str(value) in text, value
    assert UNDO_SECONDS == 600 and store.idle_seconds == 1800  # the "10 minutes" and "30 minutes" in the text
    assert "10 minutes" in text and "30 minutes" in text


def test_every_test_module_is_listed():
    testing = section(read(DEVELOPER), "Testing")
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        assert f"| `tests/{path.name}` |" in testing, path.name


def test_contact_and_honest_wording():
    help_text = section(read(DEVELOPER), "Getting help")
    assert PROFILE in help_text and "@" not in help_text
    for path in (BUSINESS, DEVELOPER, README):
        text = read(path)
        lowered = text.lower()
        assert "@" not in text, path.name
        assert "sk-" + "ant" not in lowered
        assert "every time you see" not in lowered and "all times are computed" not in lowered, path.name
        assert "claude's note" in lowered, path.name
    assert "nothing has been deployed" in read(DEVELOPER).lower()
    assert "Claude's note" in read(DEVELOPER)
    assert "Sent without approval" in read(BUSINESS) or "sent without approval" in read(BUSINESS)


def test_business_guide_drops_the_unsupported_claims():
    text = (Path(__file__).resolve().parent.parent / "docs" / "business-guide.md").read_text()
    for phrase in ("four-hour overlap", "because code checks every proposal", "most likely to go wrong"):
        assert phrase not in text
