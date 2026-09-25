"""Coupon bot dashboard + JSON API - public, no login.

Runs as its own process (see `systemd/kgc-coupon.service`): the emulator server
on :8080 must never share a failure domain with a tool that holds player IDs and
calls an external API. It binds 0.0.0.0:8083 on purpose.

Deliberately open (operator decision, 2026-09-25): anyone may register their own
Player-ID, every visitor sees the same full list of IDs and codes, and **nothing
can be removed through the API** - there is no delete/disable route at all, only
the add/read ones. The escape hatch for a bad row is the operator running
`state.set_account_enabled(uid, False)` from a shell on the box; the worker then
skips it (`accounts(enabled_only=True)`).

Because the probe on add-account costs one real request to the official coupon
site, the write routes are throttled per client IP (WRITE_LIMITS).

The UI is bilingual (VI/EN, `static/i18n.js`): errors carry a machine-readable
`code` for the page to translate alongside the human `error`, which stays
Vietnamese for logs and curl. `test_couponbot_worker.py` checks every `code=`
in this file has both translations.

    .venv/bin/uvicorn couponbot.web:app --host 0.0.0.0 --port 8083
"""

from __future__ import annotations

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
PROBE_CODE = "ZZZZZZZZZZ9"          # verified live: always "coupon does not exist"

# (max requests, window seconds) per client IP, per route. The probe and every
# redeem hit the official site from OUR IP, so an unauthenticated page needs a
# floor on how fast a single visitor can spend that budget.
WRITE_LIMITS: dict[str, tuple[int, float]] = {
    "account": (20, 3600),          # 1 external probe each
    "code": (20, 3600),             # 1 redeem per account on the next cycle
    "run": (5, 600),                # a whole cycle
}
_write_hits: dict[str, list[float]] = {}

_run_flag = {"running": False}

app = FastAPI(title="KGC Coupon Bot", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _json(status: int, **data) -> JSONResponse:
    return JSONResponse(status_code=status, content=data)


def _ensure_db() -> None:
    """`CREATE TABLE IF NOT EXISTS` on every entry point.

    A fresh box has no `coupons.db` until the first cycle or add, and the first
    `GET /api/state` then 500'd with "no such table" (found with curl - the test
    fixture always inits the DB first, so it could never see this).
    """
    state.init_db()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _throttled(bucket: str, request: Request) -> bool:
    limit, window = WRITE_LIMITS[bucket]
    now = time.time()
    if len(_write_hits) > 4096:                      # bound the memory, not the rule
        for key in [k for k, v in _write_hits.items() if not v or now - v[-1] > window * 2]:
            _write_hits.pop(key, None)
    key = f"{bucket}:{_client_ip(request)}"
    hits = [t for t in _write_hits.get(key, []) if now - t < window]
    _write_hits[key] = hits
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


# --- models -----------------------------------------------------------------

class AccountIn(BaseModel):
    uid: str
    label: str = ""


class CodeIn(BaseModel):
    code: str


# --- read routes ------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/app.js")
def app_js():
    return FileResponse(os.path.join(STATIC_DIR, "app.js"),
                        media_type="application/javascript")


def _status_payload() -> dict:
    # Both lists are complete on purpose: this page's whole job is showing every
    # registered ID and every stored code to everyone who opens it.
    _ensure_db()
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


@app.get("/api/runs/last")
def last_run():
    return _json(HTTPStatus.OK, last_run=state.last_run(),
                 running=_run_flag["running"], mode=state.meta_get("discord_mode"))


# --- write routes (add-only; there is deliberately no delete) ---------------

@app.post("/api/accounts")
def add_account(body: AccountIn, request: Request):
    # `code` is the machine key the dashboard translates (static/i18n.js);
    # `error` stays the human Vietnamese sentence for logs and curl.
    if _throttled("account", request):
        return _json(HTTPStatus.TOO_MANY_REQUESTS, code="throttled",
                     error="quá nhiều yêu cầu, thử lại sau ít phút")
    _ensure_db()
    uid = body.uid.strip()
    if not uid or len(uid) > 24 or any(c.isspace() for c in uid):
        return _json(HTTPStatus.BAD_REQUEST, code="bad_uid",
                     error="Player-ID không hợp lệ")
    if state.account(uid):
        return _json(HTTPStatus.CONFLICT, code="dup_uid",
                     error="Player-ID đã có trong danh sách")

    # Probe: a code that does not exist - the site validates the ID first, so
    # "Player-ID does not exist" here means the ID is wrong (Phase 0, live).
    client = make_client()
    try:
        out = redeem(uid, PROBE_CODE, client=client, limiter=Limiter(0))
    finally:
        client.close()
    if out.result is Result.NO_PID:
        return _json(HTTPStatus.UNPROCESSABLE_ENTITY, code="no_pid",
                     error="Player-ID không tồn tại (kiểm tra lại trong game: Settings)")
    if out.result is Result.ERROR:
        return _json(HTTPStatus.BAD_GATEWAY, code="probe_failed",
                     error=f"không kiểm tra được ID: {out.message}", detail=out.message)

    state.add_account(uid, body.label.strip()[:40])
    return _json(HTTPStatus.OK, ok=True, uid=uid, probe=out.result.value)


@app.post("/api/codes")
def add_code(body: CodeIn, request: Request):
    if _throttled("code", request):
        return _json(HTTPStatus.TOO_MANY_REQUESTS, code="throttled",
                     error="quá nhiều yêu cầu, thử lại sau ít phút")
    _ensure_db()
    code = body.code.strip().upper()
    if not (8 <= len(code) <= 24):
        return _json(HTTPStatus.BAD_REQUEST, code="code_len",
                     error="code phải 8-24 ký tự")
    if not any(c.isdigit() for c in code) or not any(c.isalpha() for c in code):
        return _json(HTTPStatus.BAD_REQUEST, code="code_charset",
                     error="code phải có cả chữ và số")
    new = state.add_code(code, "manual")
    return _json(HTTPStatus.OK, ok=True, code=code, new=new)


@app.post("/api/run")
def run_now(request: Request):
    if _throttled("run", request):
        return _json(HTTPStatus.TOO_MANY_REQUESTS, code="throttled",
                     error="quá nhiều yêu cầu, thử lại sau ít phút")
    if _run_flag["running"]:
        return _json(HTTPStatus.CONFLICT, code="busy",
                     error="đang có một lượt chạy")
    _run_flag["running"] = True

    def _go():
        try:
            worker.run_cycle()
        finally:
            _run_flag["running"] = False

    threading.Thread(target=_go, daemon=True).start()
    return _json(HTTPStatus.OK, ok=True, started=True)


def main() -> int:  # pragma: no cover - exercised on the box, not in CI
    import uvicorn
    port = int(config.get("COUPON_WEB_PORT", "8083"))
    host = config.get("COUPON_WEB_BIND", "0.0.0.0")
    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
