"""One small, private space per website visitor: their outbox and the proposals made for them.

The browser only ever holds a random session id (in a cookie) and proposal ids. To approve,
it sends a proposal id; the server looks up the proposal IT made for that visitor. So a visitor
cannot approve something the scheduler never proposed, or anything belonging to someone else.
Everything is in memory and expires; nothing is written to disk.
"""
import itertools
import secrets
import threading
import time
from collections import OrderedDict

from outbox import Outbox


class Session:
    def __init__(self, world, clock):
        self.outbox = Outbox(world, clock=clock)
        self.proposals = {}
        # The server handles requests on several threads at once (a double-click, or two tabs
        # sharing one cookie). Anything that checks-then-changes this visitor's outbox or
        # proposals must hold this lock, so two requests cannot both pass the "is it free?" check.
        self.lock = threading.RLock()  # re-entrant: take() locks again while act() already holds it
        self._numbers = itertools.count(1)
        self.last_seen = clock()

    def remember(self, result):
        """Keep a proposal the scheduler produced; return the id the browser may use."""
        with self.lock:
            proposal_id = f"prop-{next(self._numbers)}"
            self.proposals[proposal_id] = result
            return proposal_id

    def take(self, proposal_id):
        """Hand back a proposal once (approve or reject uses it up). KeyError if unknown."""
        with self.lock:
            return self.proposals.pop(proposal_id)


class SessionStore:
    def __init__(self, max_sessions=500, idle_seconds=1800, clock=time.monotonic, world=None):
        self.max_sessions, self.idle_seconds, self.clock, self.world = max_sessions, idle_seconds, clock, world
        self._sessions = OrderedDict()  # oldest first, so eviction is easy
        self._lock = threading.Lock()

    def get(self, sid):
        """(sid, session, created). Unknown, expired or missing ids get a fresh session."""
        now = self.clock()
        with self._lock:
            session = self._sessions.get(sid) if sid else None
            if session is not None and now - session.last_seen > self.idle_seconds:
                del self._sessions[sid]
                session = None
            if session is not None:
                session.last_seen = now
                self._sessions.move_to_end(sid)
                return sid, session, False
            sid = secrets.token_urlsafe(24)
            session = Session(self.world, self.clock)
            self._sessions[sid] = session
            while len(self._sessions) > self.max_sessions:
                self._sessions.popitem(last=False)  # forget the least recently used visitor
            return sid, session, True
