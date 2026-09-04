"""Public HTTP API for the separately hosted player dashboard.

The portal has its own origin, process, and cookie; it never accepts the admin
cookie or a game ``accesstoken``. Account identity comes from the game account
already in ``playerdb.accounts``: Google users use the portal OAuth callback and
Guest users receive an operator-issued portal password.
"""
import os
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import google_login
import gamedata
import playerdb
from security import client_ip


SESSION_COOKIE = "kgc_player"
UI_DIR = Path(__file__).resolve().parent / "webui-next" / "out"
GAM_REWARDED_AD_UNIT_PATH = os.environ.get("GAM_REWARDED_AD_UNIT_PATH", "")
PLAYER_DONATE_INSTRUCTIONS = os.environ.get("PLAYER_DONATE_INSTRUCTIONS", "").strip()

# This is intentionally a small, non-premium starter catalog. It keeps player
# rewards safe while the economy is observed in production: no Cash, new heroes,
# artifacts, accessories, or direct treasures. Add an entry only after its in-game
# claim path has been verified.
_GRANT_CATALOG = (
    {"type": "Gold", "id": 0, "name": "Gold", "minCount": 50_000, "maxCount": 50_000,
     "note": "Tài nguyên cơ bản."},
    {"type": "Heart", "id": 0, "name": "Heart", "minCount": 10, "maxCount": 10,
     "note": "Năng lượng chơi game."},
    {"type": "Item", "id": 100, "minCount": 20, "maxCount": 20,
     "note": "Vật phẩm kinh nghiệm anh hùng."},
    {"type": "Item", "id": 150, "minCount": 10, "maxCount": 10,
     "note": "Vật phẩm tăng trưởng."},
)


def _grant_catalog():
    """Return only the fixed player-reward catalog, never the admin catalog."""
    entries = []
    for configured in _GRANT_CATALOG:
        entry = dict(configured)
        if entry["type"] == "Item":
            entry["name"] = gamedata.item_name(entry["id"])
        entries.append(entry)
    return entries


def _grant_from_body(body):
    body = body or {}
    try:
        reward_id = int(body.get("id"))
        amount = int(body.get("count"))
    except (TypeError, ValueError):
        raise ValueError("invalid reward selection")
    reward_type = str(body.get("type") or "")
    for entry in _grant_catalog():
        if entry["type"] == reward_type and entry["id"] == reward_id:
            if entry["minCount"] <= amount <= entry["maxCount"]:
                return entry, amount
            raise ValueError("reward amount is outside the allowed range")
    raise ValueError("reward is not available in the player catalog")


def _same_origin(request):
    """Reject cross-site mutations while keeping command-line/dev calls usable.

    SameSite=Lax protects normal browser requests too.  Checking an Origin when a
    browser sends one closes the remaining fetch/XHR case without inventing a
    separate CSRF-token protocol for this same-origin application.
    """
    origin = request.headers.get("origin")
    public = google_login.portal_public_url().rstrip("/")
    if origin and public and origin.rstrip("/") != public:
        raise HTTPException(403, "cross-site portal request refused")


def _login_id(request):
    return playerdb.portal_for_token(request.cookies.get(SESSION_COOKIE))


def _require_login(request):
    login_id = _login_id(request)
    if not login_id:
        raise HTTPException(401, "sign in to the player portal")
    return login_id


def _profile(login_id):
    uid = playerdb.uid_for_login(login_id)
    if not uid:
        # The game account could only disappear through an operator delete.  Its
        # portal session then has no authority over a replacement save.
        return None
    st = playerdb.load(uid)
    if st is None:
        return None
    return {
        "loginId": login_id,
        "uid": uid,
        "name": st.get("name") or "Player",
        "castleName": st.get("castleName") or "",
        "authType": "google" if login_id.startswith("google_") else "guest",
    }


def _session_response(payload, token):
    response = JSONResponse(payload)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                        secure=google_login.portal_public_url().startswith("https://"), path="/",
                        max_age=playerdb.PLAYER_PORTAL_SESSION_TTL)
    return response


def _portal_page_response(page_name="player.html"):
    """Serve the exported player route at this service's root.

    The shared Next export also contains the admin root. Marking the document tells
    the client shell that this response came from the dedicated player service,
    without coupling the portal hostname to a hard-coded prefix in the frontend.
    """
    page = UI_DIR / page_name
    if not page.is_file():
        return HTMLResponse("Player portal UI has not been built. Run pnpm run build in server/webui-next.",
                            status_code=503)
    content = page.read_text(encoding="utf-8").replace(
        "<html", '<html data-kgc-player-portal="1"', 1)
    return HTMLResponse(content, headers={"Cache-Control": "no-cache"})


def register(app):
    """Install routes on the dedicated player-dashboard ASGI application."""

    # Next's static export uses absolute /_next URLs. This process serves only the
    # portal page; the admin dashboard serves the same build independently on :8081.
    next_dir = UI_DIR / "_next"
    if next_dir.is_dir():
        app.mount("/_next", StaticFiles(directory=next_dir), name="player-next-assets")

    @app.get("/")
    @app.head("/")
    def player_portal_root():
        return _portal_page_response()

    @app.get("/player")
    @app.get("/player/")
    def player_portal_page():
        return _portal_page_response()

    @app.get("/donate")
    @app.get("/player/donate")
    def player_donate_page():
        return _portal_page_response("player/donate.html")

    @app.get("/portal/api/auth/whoami")
    def portal_whoami(request: Request):
        profile = _profile(_login_id(request)) if _login_id(request) else None
        return {"authenticated": bool(profile), "player": profile}

    @app.post("/portal/api/auth/login")
    def portal_login(request: Request, body: dict):
        _same_origin(request)
        token, login_id, must_change, locked = playerdb.portal_password_login(
            (body or {}).get("username", ""), (body or {}).get("password", ""),
            ip=client_ip(request))
        if locked:
            raise HTTPException(429, "too many sign-in attempts; wait 10 minutes")
        if not token:
            raise HTTPException(401, "wrong username or password")
        profile = _profile(login_id)
        if not profile:
            playerdb.portal_logout(token)
            raise HTTPException(403, "game account is no longer available")
        return _session_response({"ok": True, "player": profile,
                                  "mustChangePassword": must_change}, token)

    @app.get("/portal/api/auth/google")
    def portal_google_start():
        if not google_login.portal_enabled():
            raise HTTPException(503, "Google sign-in is not configured")
        return RedirectResponse(google_login.authorize_url("portal"))

    @app.post("/portal/api/auth/logout")
    def portal_logout(request: Request):
        _same_origin(request)
        playerdb.portal_logout(request.cookies.get(SESSION_COOKIE))
        response = JSONResponse({"ok": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.post("/portal/api/auth/password")
    def portal_password_change(request: Request, body: dict):
        _same_origin(request)
        login_id = _require_login(request)
        if not login_id.startswith("Guest_"):
            raise HTTPException(400, "Google accounts do not have a portal password")
        try:
            changed = playerdb.portal_change_password(
                login_id, (body or {}).get("oldPassword", ""),
                (body or {}).get("newPassword", ""))
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not changed:
            raise HTTPException(400, "current password is wrong")
        response = JSONResponse({"ok": True, "signInAgain": True})
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    @app.get("/portal/api/ticket/balance")
    def ticket_balance(request: Request):
        return playerdb.ticket_status(_require_login(request))

    @app.get("/portal/api/ticket/history")
    def ticket_history(request: Request, limit: int = 50):
        return {"entries": playerdb.ticket_history(_require_login(request), limit)}

    @app.get("/portal/api/grant/catalog")
    def grant_catalog(request: Request):
        _require_login(request)
        return {"entries": _grant_catalog()}

    @app.get("/portal/api/request/list")
    def request_list(request: Request, limit: int = 50):
        return {"entries": playerdb.grant_requests(login_id=_require_login(request), limit=limit)}

    @app.post("/portal/api/request/submit")
    def request_submit(request: Request, body: dict):
        _same_origin(request)
        try:
            result = playerdb.ticket_submit_grant_request(
                _require_login(request), (body or {}).get("text", ""),
                (body or {}).get("itemType"), (body or {}).get("itemId"))
        except playerdb.TicketUnavailable as e:
            raise HTTPException(409, {"code": e.code})
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "balanceLeft": result["balance"], **result}

    @app.get("/portal/api/donate/info")
    def donate_info(request: Request):
        _require_login(request)
        return {"instructions": PLAYER_DONATE_INSTRUCTIONS}

    @app.post("/portal/api/donate/note")
    def donate_note(request: Request, body: dict):
        _same_origin(request)
        try:
            result = playerdb.donation_submit(
                _require_login(request), (body or {}).get("note", ""), (body or {}).get("amount"))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, **result}

    @app.post("/portal/api/grant/self")
    def grant_self(request: Request, body: dict):
        _same_origin(request)
        try:
            reward, amount = _grant_from_body(body)
            result = playerdb.ticket_redeem_grant(
                _require_login(request), reward["type"], reward["id"], amount, reward["name"])
        except playerdb.TicketUnavailable as e:
            raise HTTPException(409, {"code": e.code})
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "balanceLeft": result["balance"], "postId": result["postId"]}

    @app.post("/portal/api/ticket/video/start")
    def ticket_video_start(request: Request):
        _same_origin(request)
        _require_login(request)
        if not GAM_REWARDED_AD_UNIT_PATH.startswith("/"):
            raise HTTPException(503, "Google rewarded video is not configured yet")
        # GPT reports rewarded completion only to browser JavaScript. A player can
        # forge that POST, so it is not an authority to mint a ticket. Keep the
        # endpoint for a clear client-facing explanation until a provider-signed
        # server callback is implemented.
        raise HTTPException(503, "server-verified rewarded completion is not available")

    @app.post("/portal/api/ticket/video/complete")
    def ticket_video_complete(request: Request, body: dict):
        """Reject browser-asserted completion until the provider can verify it."""
        _same_origin(request)
        _require_login(request)
        raise HTTPException(503, "server-verified rewarded completion is not available")
