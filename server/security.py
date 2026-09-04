"""HTTP hardening middleware: admin guard, rate limiting + bans, body cap, and
the state-write serialization gate. All installed via register(app, srv) so the
decorators bind to the live FastAPI app.

The server module is bound per app (app.state.kgc_srv), NOT in one global:
test_dashboard_api execs server.py a second time as a separate module instance,
and a shared global made every registered app read config from the last
instance that registered.
"""
import asyncio, os, shutil, subprocess, time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import _CachedRequest

from common import admin_log
from state import CURRENT_IP, CURRENT_UID

srv = None      # fallback server module, set by register()


def register(app, server_module):
    global srv
    srv = server_module
    app.state.kgc_srv = server_module
    # FastAPI prepends middleware registrations. Register innermost first so the
    # public rejection checks run before a request can take the game-state lock.
    app.middleware("http")(serialize_state_writes)
    install_body_limit(app)
    app.middleware("http")(rate_limit)
    app.middleware("http")(guard_admin)


def register_public(app):
    """Install public-network safeguards without the game-state write lock.

    Standalone services own their own state transactions, but they remain
    Internet-facing and need the same request-size and per-IP rate boundaries as
    the game API.
    """
    app.middleware("http")(rate_limit)
    install_body_limit(app)


def register_portal(app):
    """Compatibility name for the Player Portal's public middleware setup."""
    register_public(app)


def _srv(request):
    """The server module that owns the app serving this request."""
    return getattr(request.app.state, "kgc_srv", None) or srv


# Trusted-proxy handling. KGC_TRUST_PROXY=1 makes client_ip read the real client
# from cf-connecting-ip / x-forwarded-for; it belongs ONLY on a deployment where a
# proxy is the sole way in.
TRUST_PROXY = os.environ.get("KGC_TRUST_PROXY") == "1"


def client_ip(request):
    peer = request.client.host if request.client else "-"
    if not TRUST_PROXY:
        return peer
    fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
    # x-forwarded-for is a chain; the leftmost entry is the original client.
    return fwd.split(",")[0].strip() or peer


_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
ADMIN_COOKIE = "kgc_admin"          # same session cookie the dashboard issues


def _admin_ok(request):
    """Whether this request may touch /admin. Two ladders, most specific first.

    With an admin account configured, the signed-in dashboard session (its
    cookie, or that cookie forwarded as x-admin-token by the dashboard's
    upstream proxy) is required from everyone. The loopback fallback is last
    and weakest: behind a tunnel or any reverse proxy EVERY request arrives
    from loopback, so it is only safe on a box nobody else can reach. It is
    therefore refused outright once a real account exists.
    """
    import playerdb
    if playerdb.admin_count():
        token = (request.cookies.get(ADMIN_COOKIE)
                 or request.headers.get("x-admin-token") or "")
        return playerdb.admin_for_token(token) is not None
    # client_ip, not the raw peer: with KGC_TRUST_PROXY on we can tell a real remote
    # player apart from the proxy in front of us, and this check stops lying.
    return client_ip(request) in _LOOPBACK


async def guard_admin(request: Request, call_next):
    """The /admin routes can rewrite or delete any player's save.

    serve_public.sh binds 0.0.0.0 so remote players can reach the game API - which
    exposes these too.
    """
    if request.url.path.startswith("/admin") and not _admin_ok(request):
        return JSONResponse(
            {"error": "admin credentials required", "login": True}, status_code=403)
    return await call_next(request)


# A public server is reachable by anyone, and every route does real work (master-data
# lookups, a state read-modify-write under a cross-process lock). This is the ceiling
# on how fast one address can drive that, so a single misbehaving client - or a bored
# one with curl - cannot starve everyone else.
# ponytail: fixed window per process, no burst smoothing. Two uvicorns and a human
# operator; move it to Redis if this ever fronts real traffic.
# 600/min is deliberately generous. A lobby boot is a burst of ~60-80 requests, and
# the address is often shared: friends behind one NAT, or - without KGC_TRUST_PROXY -
# every player on the server behind one tunnel. Too tight and legitimate players fail
# to boot, which looks exactly like the server being down. It still bounds a runaway
# client to something the state lock can absorb.
RATE_LIMIT = int(os.environ.get("KGC_RATE_LIMIT") or 600)      # requests
RATE_WINDOW = int(os.environ.get("KGC_RATE_WINDOW") or 60)     # seconds
# Blowing the window once is a misbehaving client; blowing it repeatedly is an
# attacker. After RATE_BAN_AFTER consecutive 429s the address is banned for
# RATE_BAN_SECONDS: banned requests are refused BEFORE the rate table is touched,
# so a spammer can no longer burn a state-lock cycle (or the event loop) per
# request. KGC_IPTABLES_BAN=1 also drops the address at the firewall - needs a
# sudoers rule granting `sudo -n iptables -I/-D INPUT -s <ip> -j DROP` to the
# service user, see serve_public.sh. The ban is in-memory per process: the two
# uvicorns (8080/8443) each keep their own copy, which is fine - the firewall
# rule is what actually stops the bytes.
RATE_BAN_AFTER = int(os.environ.get("KGC_RATE_BAN_AFTER") or 5)
RATE_BAN_SECONDS = int(os.environ.get("KGC_RATE_BAN_SECONDS") or 900)
IPTABLES_BAN = os.environ.get("KGC_IPTABLES_BAN") == "1"
_rate_hits = {}
_banned = {}             # ip -> unban wall-clock timestamp
_ban_strikes = {}        # ip -> consecutive 429 count
_IPTABLES = shutil.which("iptables") if IPTABLES_BAN else None


def _cfg(name, default, mod=None):
    """Live value from the server module - the tests pin server.RATE_LIMIT etc.
    after import, and the re-export is a copy, so read through the module."""
    m = mod or srv
    return getattr(m, name, default) if m is not None else default


def _iptables_rule(action, ip, mod=None):
    """action: "-I" (insert, position 1) or "-D" (delete). Never touch the loopback
    or a proxy address - banning 127.0.0.1 behind a tunnel locks everyone out."""
    if not _cfg("IPTABLES_BAN", IPTABLES_BAN, mod) or not _IPTABLES or ":" in ip or ip in _LOOPBACK:
        return
    cmd = [_IPTABLES, "-I", "INPUT", "1", "-s", ip, "-j", "DROP"] if action == "-I" \
        else [_IPTABLES, "-D", "INPUT", "-s", ip, "-j", "DROP"]
    try:
        subprocess.run(["sudo", "-n"] + cmd, capture_output=True, timeout=10)
    except Exception as e:
        admin_log(f"[ban] iptables {action} {ip} failed: {type(e).__name__}: {e}")


async def _unban_later(ip, mod=None):
    await asyncio.sleep(_cfg("RATE_BAN_SECONDS", RATE_BAN_SECONDS, mod))
    _banned.pop(ip, None)
    await asyncio.to_thread(_iptables_rule, "-D", ip, mod)


def _ban(ip, now=None, mod=None):
    now = time.time() if now is None else now
    ban_secs = _cfg("RATE_BAN_SECONDS", RATE_BAN_SECONDS, mod)
    _banned[ip] = now + ban_secs
    _ban_strikes.pop(ip, None)
    if len(_banned) > 5000:                # bound memory, drop everyone expired
        _banned.clear()
    admin_log(f"[ban] {ip} -> {ban_secs}s (rate abuse)")
    if _cfg("IPTABLES_BAN", IPTABLES_BAN, mod):
        _iptables_rule("-I", ip, mod)
        asyncio.create_task(_unban_later(ip, mod))


def _rate_ok(ip, now=None, mod=None):
    limit = _cfg("RATE_LIMIT", RATE_LIMIT, mod)
    if limit <= 0:
        return True                       # KGC_RATE_LIMIT=0 turns it off
    now = time.time() if now is None else now
    window = int(now // _cfg("RATE_WINDOW", RATE_WINDOW, mod))
    key, count = _rate_hits.get(ip, (None, 0))
    if key != window:
        if len(_rate_hits) > 5000:        # bound it: drop everyone from older windows
            _rate_hits.clear()
        _rate_hits[ip] = (window, 1)
        return True
    if count >= limit:
        return False
    _rate_hits[ip] = (window, count + 1)
    return True


async def rate_limit(request: Request, call_next):
    # The CDN is static bytes off a dict and is what a fresh install hammers hardest
    # (six bundles, one after another) - limiting it would break first launches.
    if request.url.path.startswith("/patch/"):
        return await call_next(request)
    mod = _srv(request)
    ip = client_ip(request)
    now = time.time()
    until = _banned.get(ip)
    if until is not None:
        if until > now:
            return JSONResponse({"error": "temporarily banned"}, status_code=429,
                                headers={"retry-after": str(int(until - now) + 1)})
        _banned.pop(ip, None)
    if not _rate_ok(ip, now, mod):
        strikes = _ban_strikes.get(ip, 0) + 1
        _ban_strikes[ip] = strikes
        if strikes >= _cfg("RATE_BAN_AFTER", RATE_BAN_AFTER, mod):
            _ban(ip, now, mod)
        return JSONResponse({"error": "too many requests"}, status_code=429,
                            headers={"retry-after": str(_cfg("RATE_WINDOW", RATE_WINDOW, mod))})
    _ban_strikes.pop(ip, None)   # a healthy request earns a clean slate
    return await call_next(request)


# The real client's biggest body is a roguelike save blob, a few KB. Starlette buffers
# the whole body in memory before a handler sees it, so with no cap one POST of a few
# hundred MB is a one-line denial of service against a public server.
MAX_BODY = int(os.environ.get("KGC_MAX_BODY") or 1_000_000)


class CappedBodyMiddleware:
    """Reject oversized streamed request bodies before FastAPI buffers them.

    ``Content-Length`` is only an advisory header: FastAPI's regular ``body:
    dict`` parsing otherwise buffers an unbounded chunked request before a route
    can call :func:`read_capped_body`. It reads at most ``max_body`` bytes and
    replays them through Starlette's own ``_CachedRequest`` bridge, which is the
    same lifecycle adapter BaseHTTPMiddleware uses for nested middleware.
    """

    def __init__(self, app, max_body=MAX_BODY):
        self.app = app
        self.max_body = max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = scope.get("headers", ())
        content_length = next((value for key, value in declared
                               if key.lower() == b"content-length"), b"")
        try:
            too_large = int(content_length) > self.max_body if content_length else False
        except ValueError:
            too_large = False
        if too_large:
            await self._reject(send)
            return

        request = _CachedRequest(scope, receive)
        chunks, total = [], 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > self.max_body:
                await self._reject(send)
                return
            chunks.append(chunk)
        request._body = b"".join(chunks)
        await self.app(scope, request.wrapped_receive, send)

    async def _reject(self, send):
        body = b'{"error":"request body too large"}'
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def install_body_limit(app):
    """Install the streaming body cap once for a FastAPI application."""
    app.add_middleware(CappedBodyMiddleware, max_body=MAX_BODY)


async def read_capped_body(request: Request, max_body=MAX_BODY):
    """Read a request stream without allocating beyond the configured limit.

    Content-Length is optional: direct FastAPI routes must use this too, otherwise
    a chunked upload reaches a direct route reader without a route-local limit.
    The ASGI middleware provides the outer boundary; this preserves the invariant
    for direct readers used independently in tests or future mounted apps.
    """
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_body:
            raise ValueError(f"body exceeded {max_body} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def serialize_state_writes(request: Request, call_next):
    """One request at a time may read-modify-write player state.

    Handlers load state, mutate it and save it as separate steps, so without
    this the :8080 and :8443 processes interleave and one silently discards the
    other's changes. CDN traffic never touches state - skip it, it is the bulk
    of the bytes.
    """
    if request.url.path.startswith(("/patch/", "/portal/")):
        # Phase-1 player-portal requests only manage their own credentials and
        # browser sessions in SQLite; they do not load/mutate a game save.  Keeping
        # the game-state flock around password hashing would serialize every login
        # behind battle writes for no correctness gain.  Ticket/grant mutations add
        # their own database transaction + state lock at the responsible layer.
        return await call_next(request)
    # Resolve identity BEFORE taking the lock: the ContextVar must be set in this
    # task so the child task call_next() spawns inherits it.
    import playerdb
    token = CURRENT_UID.set(playerdb.uid_for_token(request.headers.get("accesstoken")))
    ip_token = CURRENT_IP.set(client_ip(request))
    try:
        # asyncio.Lock first: flock blocks the thread, so a second request in THIS
        # process waiting on it would freeze the event loop and never let the holder
        # finish. Serialize in-process, then contend with the other process.
        async with _srv(request)._STATE_GATE:
            with playerdb.write_lock():
                return await call_next(request)
    finally:
        CURRENT_UID.reset(token)
        CURRENT_IP.reset(ip_token)
