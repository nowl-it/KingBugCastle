"""Coupon bot dashboard + JSON API.

Runs as its own process (see `systemd/kgc-coupon.service`): the emulator server
on :8080 must never share a failure domain with a tool that holds player IDs and
calls an external API. Bind loopback and let the ingress (Caddy) or an SSH
tunnel decide who reaches it; `COUPON_WEB_PASSWORD` guards the API either way.

    .venv/bin/uvicorn couponbot.web:app --host 127.0.0.1 --port 8083
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, state, worker
from .coupon_client import Limiter, Result, make_client, redeem

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
COOKIE = "coupon_sess"
SESSION_TTL = 7 * 24 * 3600
PROBE_CODE = "ZZZZZZZZZZ9"          # verified live: always "coupon does not exist"
LOCKOUT_AFTER, LOCKOUT_SECONDS = 5, 10 * 60
_login_hits: dict[str, list[float]] = {}
_run_flag = {"running": False}

app = FastAPI(title="KGC Coupon Bot", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- auth -------------------------------------------------------------------

def _sign(payload: str) -> str:
    return hmac.new(config.web_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def _issue_cookie() -> str:
    expiry = int(time.time()) + SESSION_TTL
    return f"{expiry}.{_sign(str(expiry))}"


def _authed(request: Request) -> bool:
    password = config.web_password()
    if not password:
        return True
    raw = request.cookies.get(COOKIE, "")
    expiry, _, sig = raw.partition(".")
    if not (expiry.isdigit() and sig):
        return False
    if int(expiry) < time.time():
        return False
    return hmac.compare_digest(sig, _sign(expiry))


def _json(status: int, **data) -> JSONResponse:
    return JSONResponse(status_code=status, content=data)


def _unauthorized() -> JSONResponse:
    return _json(HTTPStatus.UNAUTHORIZED, error="login required")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _locked_out(ip: str) -> bool:
    hits = [t for t in _login_hits.get(ip, []) if time.time() - t < LOCKOUT_SECONDS]
    _login_hits[ip] = hits
    return len(hits) >= LOCKOUT_AFTER


@app.middleware("http")
async def require_auth(request: Request, call_next):
    # The login page (and its endpoint) must answer before the cookie exists.
    if request.url.path in ("/", "/app.js", "/favicon.ico", "/api/login") \
            or request.url.path.startswith("/static/"):
        return await call_next(request)
    if not _authed(request):
        return _unauthorized()
    return await call_next(request)


# --- models -----------------------------------------------------------------

class AccountIn(BaseModel):
    uid: str
    label: str = ""


class CodeIn(BaseModel):
    code: str


class LoginIn(BaseModel):
    password: str


# --- auth routes ------------------------------------------------------------

@app.post("/api/login")
def login(body: LoginIn, request: Request):
    ip = _client_ip(request)
    if _locked_out(ip):
        return _json(HTTPStatus.TOO_MANY_REQUESTS, error="quá nhiều lần sai, thử lại sau 10 phút")
    expected = config.web_password()
    if not expected or not hmac.compare_digest(body.password, expected):
        _login_hits.setdefault(ip, []).append(time.time())
        return _json(HTTPStatus.UNAUTHORIZED, error="sai mật khẩu")
    _login_hits.pop(ip, None)
    return JSONResponse(
        content={"ok": True},
        headers={"Set-Cookie": f"{COOKIE}={_issue_cookie()}; HttpOnly; SameSite=Lax;"
                               f" Path=/; Max-Age={SESSION_TTL}"},
    )


@app.post("/api/logout")
def logout():
    return JSONResponse(content={"ok": True},
                        headers={"Set-Cookie": f"{COOKIE}=; HttpOnly; Path=/; Max-Age=0"})


# --- read routes ------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/app.js")
def app_js():
    return FileResponse(os.path.join(STATIC_DIR, "app.js"),
                        media_type="application/javascript")


def _status_payload() -> dict:
    accounts = state.accounts(enabled_only=False)
    codes = state.codes()
    return {
        "accounts": accounts,
        "codes": codes,
        "matrix": state.matrix(),
        "last_run": state.last_run(),
        "discord_mode": state.meta_get("discord_mode") or "unknown",
        "discord_cursor": state.meta_get("discord_cursor"),
        "rate_remaining": _rate_remaining(),
        "running": _run_flag["running"],
        "runs": _recent_runs(),
        "auth_required": bool(config.web_password()),
    }


def _rate_remaining():
    from .coupon_client import RATE
    return RATE["remaining"]


def _recent_runs() -> list[dict]:
    state.init_db()
    conn = state.connect()
    try:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 10").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@app.get("/api/state")
def api_state():
    return _json(HTTPStatus.OK, **_status_payload())


# --- write routes -----------------------------------------------------------

@app.post("/api/accounts")
def add_account(body: AccountIn, request: Request):
    uid = body.uid.strip()
    if not uid or len(uid) > 24 or any(c.isspace() for c in uid):
        return _json(HTTPStatus.BAD_REQUEST, error="Player-ID không hợp lệ")
    if state.account(uid):
        return _json(HTTPStatus.CONFLICT, error="Player-ID đã có trong danh sách")

    # Probe: a code that does not exist - the site validates the ID first, so
    # "Player-ID does not exist" here means the ID is wrong (Phase 0, live).
    client = make_client()
    try:
        out = redeem(uid, PROBE_CODE, client=client, limiter=Limiter(0))
    finally:
        client.close()
    if out.result is Result.NO_PID:
        return _json(HTTPStatus.UNPROCESSABLE_ENTITY,
                     error="Player-ID không tồn tại (kiểm tra lại trong game: Settings)")
    if out.result is Result.ERROR:
        return _json(HTTPStatus.BAD_GATEWAY, error=f"không kiểm tra được ID: {out.message}")

    state.add_account(uid, body.label.strip())
    return _json(HTTPStatus.OK, ok=True, uid=uid, probe=out.result.value)


@app.delete("/api/accounts/{uid}")
def disable_account(uid: str):
    if not state.set_account_enabled(uid, False):
        return _json(HTTPStatus.NOT_FOUND, error="không tìm thấy Player-ID")
    return _json(HTTPStatus.OK, ok=True, uid=uid, enabled=False)


@app.post("/api/accounts/{uid}/enable")
def enable_account(uid: str):
    if not state.set_account_enabled(uid, True):
        return _json(HTTPStatus.NOT_FOUND, error="không tìm thấy Player-ID")
    return _json(HTTPStatus.OK, ok=True, uid=uid, enabled=True)


@app.post("/api/codes")
def add_code(body: CodeIn):
    code = body.code.strip().upper()
    if not (8 <= len(code) <= 24):
        return _json(HTTPStatus.BAD_REQUEST, error="code phải 8-24 ký tự")
    if not any(c.isdigit() for c in code) or not any(c.isalpha() for c in code):
        return _json(HTTPStatus.BAD_REQUEST, error="code phải có cả chữ và số")
    new = state.add_code(code, "manual")
    return _json(HTTPStatus.OK, ok=True, code=code, new=new)


@app.post("/api/run")
def run_now():
    if _run_flag["running"]:
        return _json(HTTPStatus.CONFLICT, error="đang có một lượt chạy")
    _run_flag["running"] = True

    def _go():
        try:
            worker.run_cycle()
        finally:
            _run_flag["running"] = False

    threading.Thread(target=_go, daemon=True).start()
    return _json(HTTPStatus.OK, ok=True, started=True)


@app.get("/api/runs/last")
def last_run():
    return _json(HTTPStatus.OK, last_run=state.last_run(),
                 running=_run_flag["running"], mode=state.meta_get("discord_mode"))


def main() -> int:  # pragma: no cover - exercised on the box, not in CI
    import uvicorn
    port = int(config.get("COUPON_WEB_PORT", "8083"))
    host = config.get("COUPON_WEB_BIND", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
