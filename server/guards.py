"""Two small protections for a public demo: a rate limit and a daily token budget.

Both live in memory. That is fine on one server; on serverless hosting each
instance has its own counters, so treat them as best-effort (replay mode is the
real backstop for cost).
"""
import threading
import time
from datetime import date


class RateLimiter:
    """Allow at most `max_requests` per visitor in any `window_seconds` window."""

    # Every this many calls to allow(), we sweep out visitors we have not seen
    # in a whole window. Without this, a client that keeps changing its IP
    # could make the dictionary grow forever.
    _sweep_every = 1000

    def __init__(self, max_requests=5, window_seconds=60, clock=time.monotonic):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits = {}  # visitor key -> list of recent request times
        self._calls = 0  # how many times allow() has been called
        self._lock = threading.Lock()  # requests can arrive on several threads at once

    def _sweep(self, now):
        # Drop every visitor whose newest request is already outside the window.
        for key in list(self._hits):
            times = self._hits[key]
            if not times or now - times[-1] >= self.window_seconds:
                del self._hits[key]

    def allow(self, key):
        now = self._clock()
        with self._lock:
            self._calls += 1
            if self._calls % self._sweep_every == 0:
                self._sweep(now)
            recent = [t for t in self._hits.get(key, []) if now - t < self.window_seconds]
            allowed = len(recent) < self.max_requests
            if allowed:
                recent.append(now)  # only allowed requests count toward the limit
            if recent:
                self._hits[key] = recent
            else:
                # Never keep an empty list around; it would just waste memory.
                self._hits.pop(key, None)
            return allowed


class TokenBudget:
    """Count tokens spent today; once over the cap, the site switches to replay mode."""

    def __init__(self, daily_cap=500_000, today=date.today):
        self.daily_cap = daily_cap
        self._today = today
        self._day = today()
        self._spent = 0
        self._lock = threading.Lock()

    def _roll_over_if_new_day(self):
        if self._today() != self._day:
            self._day = self._today()
            self._spent = 0

    def add(self, tokens):
        with self._lock:
            self._roll_over_if_new_day()
            # Clamp at 0: a negative "settle" adjustment must never leave a negative total.
            self._spent = max(0, self._spent + tokens)

    def try_reserve(self, tokens):
        """Atomically check the cap and charge `tokens` up front.

        Doing the check and the charge under one lock means two requests arriving
        together cannot both slip in under the cap. Returns False (and charges
        nothing) when the budget is already used up.
        """
        with self._lock:
            self._roll_over_if_new_day()
            if self._spent >= self.daily_cap:
                return False
            self._spent += tokens
            return True

    def exhausted(self):
        with self._lock:
            self._roll_over_if_new_day()
            return self._spent >= self.daily_cap
