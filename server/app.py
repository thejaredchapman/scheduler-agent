"""Web server: streams the scheduler's steps to the browser, and holds each visitor's outbox.

The API key never leaves this server. The browser never sends a proposal: it sends the id of a
proposal this server made for that visitor, and only then does plain code in outbox.py "send".
Adapted from the research analyst's server.
"""
import base64
import hashlib
import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from agent import next_week, run_agent
from server.guards import RateLimiter, TokenBudget
from server.replay import replay_events
from server.sessions import SessionStore
from world import DEMO_TODAY, UTC, get_world, utc_text

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
REPLAYS_DIR = WEB_DIR / "replays"
MAX_REQUEST_CHARS = 500
# Charged up front so abandoned streams still count; settled to the real usage on a normal finish.
# The largest measured run (eval/results-first-run.json) used about 41,000 tokens.
RESERVED_TOKENS_PER_RUN = 45_000
DAILY_TOKEN_CAP = 1_500_000
COOKIE = "sid"


def _inline_script_hash(index_path):
    """Return the CSP source token ('sha256-...') for the inline <script> in index.html.

    A Content-Security-Policy hash lets the browser run exactly one inline script (the
    tiny theme setter) while blocking every other inline script, so we never need
    'unsafe-inline'. We compute it from the real file at import time so the policy can
    never drift out of date when the script is edited. If we cannot find the script we
    fail loudly: silently dropping the hash would break the theme script in production.
    """
    html = Path(index_path).read_text(encoding="utf-8")
    # An inline script is a <script> tag with no attributes at all (no src=). The hash
    # covers the exact bytes between the tags, whitespace included.
    match = re.search(r"<script>(.*?)</script>", html, flags=re.DOTALL)
    if match is None:
        raise RuntimeError(f"CSP setup failed: no inline <script> found in {index_path}")
    digest = hashlib.sha256(match.group(1).encode("utf-8")).digest()
    return "sha256-" + base64.b64encode(digest).decode("ascii")


CSP = "; ".join([
    "default-src 'self'",
    f"script-src 'self' '{_inline_script_hash(WEB_DIR / 'index.html')}'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "object-src 'none'",
])

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": CSP,
}


class SecurityHeadersMiddleware:
    """Add the security headers to every HTTP response.

    This is a plain ASGI wrapper (not BaseHTTPMiddleware) on purpose: it only touches
    the response *start* message and passes body chunks straight through, so Server-Sent
    Events still stream chunk by chunk instead of being buffered.
    """

    def __init__(self, app):
        self.app = app
        self.raw_headers = [(k.lower().encode(), v.encode()) for k, v in SECURITY_HEADERS.items()]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                ours = {name for name, _ in self.raw_headers}
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in ours]
                message = {**message, "headers": kept + self.raw_headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class ScheduleRequest(BaseModel):
    # Reject unknown fields (422) so callers cannot smuggle extra data past validation.
    model_config = ConfigDict(extra="forbid")
    request: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS)
    clarification: str | None = Field(default=None, max_length=MAX_REQUEST_CHARS)
    sample_id: str | None = Field(default=None, max_length=40)


class ProposalAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(min_length=1, max_length=40)


class UndoAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    send_id: str = Field(min_length=1, max_length=40)


def _client_ip(request: Request):
    """Pick the address the rate limiter should count.

    X-Forwarded-For is a list the CALLER can start with anything; each proxy appends
    the address it saw. So the first entry is attacker-controlled and must not be the
    key (anyone could dodge the limit by sending a new fake value each time). We prefer
    headers the platform sets itself, then the LAST X-Forwarded-For entry (added by the
    proxy closest to us), then the socket address.
    Limits: off Vercel (or without a trusted proxy) these headers are only as honest as
    whoever sends them, so treat this as a best-effort demo guard, not real security.
    """
    for name in ("x-vercel-forwarded-for", "x-real-ip"):
        value = request.headers.get(name, "").strip()
        if value:
            return value
    rightmost = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    if rightmost:
        return rightmost
    return request.client.host if request.client else "unknown"


def _sse(events):
    """Wrap an iterator of event dicts as a Server-Sent Events response."""
    def stream():
        try:
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
        except Exception:
            # Public endpoint: never leak the real error text or a stack trace.
            yield f"data: {json.dumps({'type': 'notice', 'message': 'Something went wrong. Please try again.'})}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _with_cookie(response, sid):
    response.set_cookie(COOKIE, sid, max_age=1800, httponly=True, samesite="strict", path="/")
    return response


def create_app(agent_runner=run_agent, limiter=None, budget=None, sessions=None, replays_dir=REPLAYS_DIR,
               web_dir=WEB_DIR, replay_delay=0.4):
    # No docs_url/redoc_url/openapi_url: the auto-generated API pages are not part of the demo.
    app = FastAPI(title="The Front Desk", docs_url=None, redoc_url=None, openapi_url=None)
    limiter = limiter or RateLimiter()
    budget = budget or TokenBudget(daily_cap=DAILY_TOKEN_CAP)
    sessions = sessions or SessionStore(world=get_world())  # load the demo data once, shared by every visitor
    world = sessions.world or get_world()

    def visitor(request):
        return sessions.get(request.cookies.get(COOKIE))

    def tagged(events, session):
        """Give each proposal an id the browser can use, and remember it for this visitor."""
        for event in events:
            if event.get("type") == "result" and event["result"].get("status") == "proposed":
                event = {**event, "result": {**event["result"], "proposal_id": session.remember(event["result"])}}
            yield event

    @app.post("/schedule")
    def schedule(body: ScheduleRequest, request: Request):
        if not body.request.strip():
            raise HTTPException(status_code=422, detail="Please type a request.")
        if not limiter.allow(_client_ip(request)):
            raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute.")
        sid, session, _ = visitor(request)
        # Check the cap and reserve tokens in one atomic step (no race between requests).
        if not budget.try_reserve(RESERVED_TOKENS_PER_RUN):
            return _with_cookie(_sse(tagged(replay_events(replays_dir, body.sample_id, delay=replay_delay),
                                            session)), sid)
        text = body.request + (f"\n\nClarification: {body.clarification}" if body.clarification else "")

        def live_events():
            for event in agent_runner(text, booked=session.outbox.as_holds()):
                if event.get("type") == "result":
                    # Settle: swap the estimate for the real usage (the difference may be negative).
                    usage = event.get("usage") or {}
                    budget.add(usage.get("input_tokens", 0) + usage.get("output_tokens", 0) - RESERVED_TOKENS_PER_RUN)
                yield event
        return _with_cookie(_sse(tagged(live_events(), session)), sid)

    def act(request, proposal_id, action, consume):
        """Look up the proposal this server made for this visitor, run `action` on it, answer in JSON."""
        sid, session, _ = visitor(request)
        proposal = session.proposals.get(proposal_id)
        if proposal is None:
            return _with_cookie(JSONResponse({"detail": "No such proposal"}, status_code=404), sid)
        try:
            outcome = action(session, proposal)
        except ValueError as error:  # the outbox refused, e.g. the slot is no longer free
            return _with_cookie(JSONResponse({"detail": str(error)}, status_code=409), sid)
        if consume:
            session.take(proposal_id)
        return _with_cookie(JSONResponse(outcome), sid)

    def send_it(session, proposal):
        sent = session.outbox.approve(proposal)  # plain code re-checks the slot, then "sends"
        return {"sent": sent, "outbox": session.outbox.listing()}

    def turn_down(session, proposal):
        session.outbox.reject(proposal)
        return {"rejected": True}

    def preview(session, proposal):
        return session.outbox.dry_run(proposal)  # only looks; nothing changes

    @app.post("/approve")
    def approve(body: ProposalAction, request: Request):
        return act(request, body.proposal_id, send_it, consume=True)

    @app.post("/reject")
    def reject(body: ProposalAction, request: Request):
        return act(request, body.proposal_id, turn_down, consume=True)

    @app.post("/dry-run")
    def dry_run(body: ProposalAction, request: Request):
        return act(request, body.proposal_id, preview, consume=False)

    @app.post("/undo")
    def undo(body: UndoAction, request: Request):
        sid, session, _ = visitor(request)
        try:
            cancelled = session.outbox.undo(body.send_id)
        except ValueError as error:
            return _with_cookie(JSONResponse({"detail": str(error)}, status_code=409), sid)
        return _with_cookie(JSONResponse({"cancelled": cancelled, "outbox": session.outbox.listing()}), sid)

    @app.get("/api/world")
    def world_view(request: Request):
        sid, _, _ = visitor(request)
        monday, friday = next_week(DEMO_TODAY)
        # Pad the window by 14 hours each side so time zones far from UTC still get their edges.
        start = datetime.combine(date.fromisoformat(monday), time(0), UTC) - timedelta(hours=14)
        end = datetime.combine(date.fromisoformat(friday) + timedelta(days=1), time(0), UTC) + timedelta(hours=14)
        busy = {owner: [{"start_utc": utc_text(s), "end_utc": utc_text(e)} for s, e in blocks]
                for owner, blocks in world.week_blocks(start, end).items()}
        people = [{key: p[key] for key in ("id", "name", "role", "time_zone", "working_hours", "working_days")}
                  for p in world.people.values()]
        rooms = [{key: r[key] for key in ("id", "name", "capacity", "equipment")} for r in world.rooms.values()]
        return _with_cookie(JSONResponse({"week": {"monday": monday, "friday": friday}, "people": people,
                                          "rooms": rooms, "busy": busy}), sid)

    @app.get("/api/outbox")
    def outbox_view(request: Request):
        sid, session, _ = visitor(request)
        return _with_cookie(JSONResponse({"sent": session.outbox.listing()}), sid)

    @app.get("/api/samples")
    def samples():
        found = []
        for path in sorted(Path(replays_dir).glob("*.json")):
            recording = json.loads(path.read_text())
            found.append({key: recording[key] for key in ("id", "label", "request")})
        return found

    # Mounted last so the /api routes and /schedule above win.
    if Path(web_dir).is_dir():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    # Wrap the whole app (outside Starlette's own error handling) so even a 500 carries
    # the headers. add_middleware() would sit inside that handler and miss those.
    build_stack = app.build_middleware_stack
    app.build_middleware_stack = lambda: SecurityHeadersMiddleware(build_stack())
    return app


app = create_app()
