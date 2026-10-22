from datetime import date, timedelta

from server.guards import RateLimiter, TokenBudget


def test_rate_limiter_blocks_after_the_limit():
    limiter = RateLimiter(max_requests=2, window_seconds=60, clock=lambda: 0.0)
    assert limiter.allow("1.1.1.1") and limiter.allow("1.1.1.1")
    assert not limiter.allow("1.1.1.1")


def test_rate_limiter_tracks_each_visitor_separately():
    limiter = RateLimiter(max_requests=1, window_seconds=60, clock=lambda: 0.0)
    assert limiter.allow("a") and limiter.allow("b")


def test_rate_limiter_allows_again_after_the_window():
    now = [0.0]
    limiter = RateLimiter(max_requests=1, window_seconds=60, clock=lambda: now[0])
    assert limiter.allow("a")
    assert not limiter.allow("a")
    now[0] = 61.0
    assert limiter.allow("a")


def test_budget_exhausts_at_the_cap():
    budget = TokenBudget(daily_cap=100)
    assert not budget.exhausted()
    budget.add(60)
    assert not budget.exhausted()
    budget.add(40)
    assert budget.exhausted()


def test_budget_resets_on_a_new_day():
    day = [date(2026, 10, 20)]
    budget = TokenBudget(daily_cap=10, today=lambda: day[0])
    budget.add(10)
    assert budget.exhausted()
    day[0] += timedelta(days=1)
    assert not budget.exhausted()


def test_rate_limiter_forgets_expired_visitors():
    # Many one-time visitors must not pile up in memory forever.
    now = [0.0]
    limiter = RateLimiter(max_requests=5, window_seconds=60, clock=lambda: now[0])
    for i in range(1000):
        assert limiter.allow(f"visitor-{i}")
    now[0] = 61.0
    for _ in range(1000):
        limiter.allow("regular")  # enough calls to trigger the periodic sweep
    assert len(limiter._hits) <= 2


def test_denied_requests_do_not_store_empty_entries():
    limiter = RateLimiter(max_requests=0, window_seconds=60, clock=lambda: 0.0)
    for _ in range(5):
        assert not limiter.allow("a")
    assert "a" not in limiter._hits
    assert len(limiter._hits) == 0


def test_denied_request_does_not_extend_the_window():
    now = [0.0]
    limiter = RateLimiter(max_requests=1, window_seconds=60, clock=lambda: now[0])
    assert limiter.allow("a")
    now[0] = 30.0
    assert not limiter.allow("a")
    now[0] = 61.0
    assert limiter.allow("a")


def test_try_reserve_succeeds_below_cap_and_adds_tokens():
    budget = TokenBudget(daily_cap=100)
    assert budget.try_reserve(40)
    assert budget._spent == 40


def test_try_reserve_refuses_once_cap_is_reached_and_adds_nothing():
    budget = TokenBudget(daily_cap=100)
    budget.add(100)
    assert not budget.try_reserve(40)
    assert budget._spent == 100


def test_negative_add_never_drives_total_below_zero():
    budget = TokenBudget(daily_cap=100)
    budget.add(10)
    budget.add(-50)
    assert budget._spent == 0


def test_two_sequential_reserves_near_the_cap_allow_only_one():
    budget = TokenBudget(daily_cap=100)
    budget.add(90)
    assert budget.try_reserve(50)
    assert not budget.try_reserve(50)
