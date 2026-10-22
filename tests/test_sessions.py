"""Each visitor gets their own outbox and proposals; old sessions expire."""
import pytest

from server.sessions import SessionStore
from tests.fixtures import fixture_world


def store(clock=None, **kwargs):
    now = clock or [0.0]
    return SessionStore(clock=lambda: now[0], world=fixture_world(), **kwargs), now


def test_new_and_returning_sessions():
    s, _ = store()
    sid, session, created = s.get(None)
    assert created and len(sid) >= 24
    again_sid, again, created2 = s.get(sid)
    assert again_sid == sid and again is session and not created2
    other_sid, other, _ = s.get("made-up")
    assert other_sid != sid and other is not session


def test_proposals_are_issued_and_taken_once():
    s, _ = store()
    _, session, _ = s.get(None)
    pid = session.remember({"status": "proposed", "x": 1})
    assert pid == "prop-1" and session.take(pid) == {"status": "proposed", "x": 1}
    with pytest.raises(KeyError):
        session.take(pid)


def test_idle_expiry_and_cap():
    s, now = store(idle_seconds=10, max_sessions=2)
    a, _, _ = s.get(None)
    now[0] = 11
    a2, _, created = s.get(a)
    assert created and a2 != a                  # expired: a fresh session
    b, _, _ = s.get(None)
    c, _, _ = s.get(None)
    assert s.get(a2)[2]                         # the oldest was evicted to keep at most 2
