"""KGC private-server dashboard (:8081) - the one admin UI.

Serves webui-next/out (Next.js) and hosts:
  - /api/*               admin: players, saves, heroes, inventory, accessories, mail
  - /api/server/*        read-only proxy of server.py's own /admin/api (:8080)

The UI is served from webui-next/out when it exists (bundle via
`pnpm run build` in webui-next/).

State goes through `playerdb`, the same store server.py reads per request, so an edit
lands on the client's next fetch with no restart. Master-data name lookups live in
`gamedata`.

Two things here are load-bearing and easy to break:
  * every mutating request holds playerdb's cross-process write lock for its whole
    duration - a dashboard edit must not be clobbered by an in-game save landing
    between its read and its write (see reference_kgc_state_store);
  * the websocket carries its own copy of the admin guard, because HTTP middleware
    never sees websocket scope.
"""
import asyncio
import copy
import json
import os
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

import sys
import pathlib

_HERE = pathlib.Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "routes", _HERE / "builders", _HERE / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import gamedata
from common import now_iso
import dimension
import playerdb
import security

app = FastAPI(title="KGC Dashboard")

BASE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE, "webui-next", "out")
if not os.path.isdir(UI_DIR):
    os.makedirs(UI_DIR, exist_ok=True)
UI_ROOT = pathlib.Path(UI_DIR).resolve()
CONFIG_FILE = os.path.join(BASE, "data", "response_config.json")
DATA_DIR = os.path.join(BASE, "data")
ADMIN_ACCESSORIES_FILE = os.path.join(DATA_DIR, "admin_accessories.json")
SERVER_URL = os.environ.get("KGC_SERVER_URL", "http://127.0.0.1:8080")
TRUST_PROXY = os.environ.get("KGC_TRUST_PROXY") == "1"
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_STATE_GATE = asyncio.Lock()


def _client_ip(request):
    """Real client address. Behind Cloudflare every request's client.host is the
    same edge IP, so per-address limits (the login rate limiter) must key on the
    forwarded header - but only when a proxy is the sole way in."""
    peer = request.client.host if request.client else "-"
    if not TRUST_PROXY:
        return peer
    fwd = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or peer


# --- guards -----------------------------------------------------------------
# Two ways in, checked in this order:
#   1. an admin account (username + password -> session cookie). Once ANY admin
#      exists this is the only way in from a non-loopback address, because a
#      tunnel/reverse proxy makes every request look like loopback.
#   2. nothing configured at all -> loopback only, same as before.
SESSION_COOKIE = "kgc_admin"
_OPEN_PATHS = {"/api/auth/login", "/api/auth/whoami"}


def _same_origin(request):
    """Reject browser cross-site mutations made with an admin cookie.

    SameSite=Lax is the primary browser control; Origin gives the dashboard the
    explicit server-side check that protects XHR/future cookie-policy changes.
    Calls without Origin remain available for local operator tooling.
    """
    origin = request.headers.get("origin")
    if not origin:
        return
    scheme = request.headers.get("x-forwarded-proto") if TRUST_PROXY else request.url.scheme
    expected = f"{scheme or request.url.scheme}://{request.headers.get('host', '')}"
    if origin.rstrip("/") != expected.rstrip("/"):
        raise HTTPException(403, "cross-site dashboard request refused")


def _cookie_is_secure(request):
    """Whether this response reaches the browser over HTTPS.

    The dashboard stays usable on local plain HTTP.  A public reverse proxy sets
    ``X-Forwarded-Proto`` and is trusted only under the same deployment invariant
    that powers origin and client-IP handling above.
    """
    scheme = request.headers.get("x-forwarded-proto") if TRUST_PROXY else request.url.scheme
    return (scheme or "").split(",", 1)[0].strip().lower() == "https"


def _session_user(request):
    return playerdb.admin_for_token(request.cookies.get(SESSION_COOKIE))


def _authorized(request):
    """(ok, why_not). Static assets are open so the login page itself can load."""
    path = request.url.path
    if path in _OPEN_PATHS or not path.startswith(("/api", "/ws")):
        return True, None
    if _session_user(request):
        return True, None
    if playerdb.admin_count():
        return False, "sign in to the dashboard"
    if (request.client.host if request.client else None) in _LOOPBACK:
        return True, None
    return False, ("dashboard is loopback-only; create an admin account "
                   "(python3 dashboard.py --create-admin <user>)")


async def guard_admin(request, call_next):
    """This whole app edits saves and sends mail, and it binds 0.0.0.0 - gate it."""
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        _same_origin(request)
    ok, why = _authorized(request)
    if not ok:
        return JSONResponse({"error": why, "login": True}, status_code=401)
    return await call_next(request)


# Endpoints that write by calling the game server instead of touching playerdb here.
# They must NOT hold the flock: server.py takes the same cross-process lock for its own
# request, so holding it across the proxy call deadlocks both sides until the timeout.
# The write still happens under a lock - server.py's.
_DELEGATED = {("POST", "/api/players")}


def _owns_state_lock(request):
    """Whether the endpoint owns its complete transaction and flock itself.

    Request approval changes a wallet, a save/mail, audit rows and its queue row
    in one playerdb transaction.  Wrapping it in this middleware's separate
    flock would acquire the same non-reentrant file lock twice.
    """
    path = request.url.path
    return path.startswith(("/api/requests/", "/api/donations/")) or path == "/api/player-portal/tickets"

def _upstream_headers(request):
    """Credential for the /admin/api/* calls we make against the game server.

    The game port runs the same two-ladder guard we do. We forward the signed-in
    operator's own session cookie, which playerdb resolves on the other side.
    Sending nothing works only on a loopback-only box, and that is exactly the
    case a tunnel breaks.
    """
    tok = request.cookies.get(SESSION_COOKIE)
    return {"x-admin-token": tok} if tok else {}



async def serialize_state_writes(request, call_next):
    """Hold playerdb's cross-process lock for any request that can mutate state.
    Keyed on method, not path: a new mutating endpoint is then covered by default
    instead of silently racing until someone remembers to add its prefix here."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    if (request.method, request.url.path) in _DELEGATED or _owns_state_lock(request):
        return await call_next(request)
    async with _STATE_GATE:                 # in-process first: flock blocks the loop
        with playerdb.write_lock():
            return await call_next(request)


# FastAPI prepends registrations. The state lock must be innermost: unauthenticated,
# rate-limited, or oversized requests must never occupy it while an operator edit is
# waiting. Dashboard transactions still use the lock implementation above.
app.middleware("http")(serialize_state_writes)
app.middleware("http")(guard_admin)
security.register_public(app)


app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

CATALOG = gamedata.load_catalog()
print(f"[dashboard] gamedata {gamedata.summary()}", flush=True)

# --- state helpers ----------------------------------------------------------
EDITABLE_FIELDS = {
    "name": str, "castleName": str,
    "gold": int, "cash": int, "paidCash": int, "heart": int, "level": int, "exp": int,
    "bestClearedStage": int, "bestClearedTheme": int,
    "bestClearedHardStage": int, "bestClearedHardTheme": int,
    "buildingPoint": int, "playedCount": int, "winCount": int, "eventFlag": int,
}


def _read_state(pid):
    st = playerdb.load(pid)
    if st is None:
        raise HTTPException(404, f"player {pid} not found")
    return st


def _write_state(pid, st):
    playerdb.save(pid, st)


# --- player portal access ---------------------------------------------------
@app.get("/api/player/{pid}/portal-access")
def api_player_portal_access(pid: str):
    _read_state(pid)                         # keep the dashboard's normal 404 contract
    return {"accounts": playerdb.portal_access_for_uid(pid)}


@app.post("/api/player/{pid}/portal-access")
def api_player_portal_access_grant(pid: str, body: dict):
    _read_state(pid)
    login_id = (body or {}).get("loginId", "")
    if login_id not in playerdb.login_ids_for_uid(pid):
        raise HTTPException(400, "login id is not bound to this player")
    try:
        access = playerdb.portal_guest_access(
            login_id, (body or {}).get("username", ""),
            (body or {}).get("password", ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "access": access,
            "accounts": playerdb.portal_access_for_uid(pid)}


# --- player portal requests -------------------------------------------------
def _admin_reward_name(reward_type, reward_id):
    if reward_type == "Item":
        return gamedata.item_name(reward_id)
    if reward_type == "Unit":
        return gamedata.hero_name(reward_id)
    return reward_type


@app.get("/api/requests")
def api_requests(status: str | None = None, limit: int = 100):
    try:
        return {"entries": playerdb.grant_requests(status=status, limit=limit)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/requests/{request_id}/approve")
def api_request_approve(request_id: int, body: dict, request: Request):
    body = body or {}
    reward_type = str(body.get("rewardType") or "")
    if reward_type not in GRANTABLE_TYPES:
        raise HTTPException(400, "choose a grantable reward type")
    try:
        reward_id, reward_amount = int(body.get("rewardId")), int(body.get("rewardAmount"))
        result = playerdb.resolve_grant_request(
            request_id, "approve", _session_user(request), reward_type, reward_id,
            reward_amount, _admin_reward_name(reward_type, reward_id))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **result}


@app.post("/api/requests/{request_id}/deny")
def api_request_deny(request_id: int, body: dict, request: Request):
    try:
        result = playerdb.resolve_grant_request(
            request_id, "deny", _session_user(request), deny_reason=(body or {}).get("reason"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **result}


# --- player portal donations ------------------------------------------------
@app.get("/api/donations")
def api_donations(limit: int = 100):
    try:
        return {"entries": playerdb.donations(limit)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/donations/{donation_id}/credit")
def api_donation_credit(donation_id: int, body: dict, request: Request):
    try:
        donation = next(entry for entry in playerdb.donations(200) if entry["id"] == donation_id)
        result = playerdb.admin_credit_tickets(
            donation["loginId"], (body or {}).get("count"), "donation credit",
            _session_user(request), donation_id)
    except StopIteration:
        raise HTTPException(404, "donation not found")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **result}


@app.post("/api/player-portal/tickets")
def api_player_portal_tickets(body: dict, request: Request):
    body = body or {}
    try:
        result = playerdb.admin_credit_tickets(
            body.get("loginId"), body.get("count"), body.get("reason"), _session_user(request))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **result}


def _summary(pid, st, active=None):
    inv = st.get("inventory") or {}
    return {
        "id": pid,
        "uid": st.get("uid", pid),
        "name": st.get("name", pid),
        "castleName": st.get("castleName", ""),
        "gold": st.get("gold", 0), "cash": st.get("cash", 0),
        "heart": st.get("heart", 0), "level": st.get("level", 0), "exp": st.get("exp", 0),
        "active": pid == (active if active is not None else playerdb.active()),
        "counts": {
            "posts": len(st.get("posts") or []),
            "cards": len(st.get("cards") or {}),
            "accessories": len(st.get("accessories") or []),
            "treasures": len(st.get("treasures") or []),
            "items": len(inv.get("itemIds") or []),
        },
    }


# --- status / catalog -------------------------------------------------------
@app.get("/api/status")
def api_status():
    cfg = {}
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f).get("server", {})
    except Exception:
        pass
    return {
        "version": cfg.get("serverVersion", "?"),
        "patchFolder": cfg.get("patchFolder", "?"),
        "players": playerdb.count(),
        "activePlayer": playerdb.active(),
        "serverUrl": SERVER_URL,
        "multiplayer": os.environ.get("KGC_MULTIPLAYER", "1") != "0",   # default on, matches server.py
        "authMode": "password" if playerdb.admin_count() else "loopback-only",
        "gamedata": gamedata.summary(),
    }


GRANTABLE_TYPES = ["Gold", "Cash", "Heart", "Item", "Unit", "UnitSoul", "Card", "Treasure"]
DISPLAY_ONLY_TYPES = ["Artifact", "Accessory"]


@app.get("/api/catalog")
def api_catalog():
    return {"catalog": CATALOG, "grantable": GRANTABLE_TYPES, "displayOnly": DISPLAY_ONLY_TYPES}


@app.get("/api/game-data")
def api_game_data():
    """Full master-data browser for the Game Data tab: every hero, item, relic,
    treasure, accessory and skin with id, type, name and (where extracted) art."""
    return gamedata.game_data()


@app.get("/api/stats/realtime")
def api_stats_realtime():
    import time
    active = playerdb.active()
    total_players = 0
    active_24h = 0
    total_gold = 0
    total_cash = 0
    
    now = time.time()
    for pid, st, updated in playerdb.all_players():
        total_players += 1
        if now - updated < 86400:
            active_24h += 1
        total_gold += st.get("gold", 0)
        total_cash += st.get("cash", 0)
        
    return {
        "ccu": len(active),
        "total_players": total_players,
        "active_24h": active_24h,
        "total_gold": total_gold,
        "total_cash": total_cash
    }

# --- player CRUD ------------------------------------------------------------
@app.get("/api/players")
def api_players():
    active = playerdb.active()
    out = []
    for pid, st, _updated in playerdb.all_players():
        try:
            out.append(_summary(pid, st, active))
        except Exception as e:
            out.append({"id": pid, "error": str(e)})
    return out


@app.post("/api/players")
async def api_create_player(body: dict, request: Request):
    """Delegated to server.py rather than built here.

    A fresh save is not just default_player.json - server.py expands it with the hero
    and item id lists *after* the content-version gate, pads decks to DECK_SLOTS, and
    stamps the daily-reset timestamps. Rebuilding that here would be a second
    definition of "new player" that drifts from the real one on the next content bump,
    so this asks the game server for it and only then reads the row back.
    """
    uid = (body.get("uid") or "player-" + secrets.token_hex(4)).strip()
    if playerdb.load(uid) is not None:
        raise HTTPException(409, f"player {uid} already exists")
    headers = _upstream_headers(request)
    payload = {"uid": uid, "name": (body.get("name") or "NewPlayer").strip()}
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(SERVER_URL + "/admin/api/players/create",
                                  json=payload, headers=headers)
    except Exception as e:
        raise HTTPException(503, f"game server unreachable at {SERVER_URL} "
                                 f"(needed to build a new save): {type(e).__name__}")
    if r.status_code != 200:
        raise HTTPException(502, f"game server refused create: HTTP {r.status_code}")
    st = playerdb.load(uid)
    if st is None:
        raise HTTPException(502, "game server reported success but no save appeared")
    return {"ok": True, "summary": _summary(uid, st)}


@app.post("/api/players/{pid}/clone")
async def api_clone_player(pid: str, body: dict = None):
    st = copy.deepcopy(_read_state(pid))
    uid = ((body or {}).get("uid") or f"{pid}-copy-{secrets.token_hex(2)}").strip()
    if playerdb.load(uid) is not None:
        raise HTTPException(409, f"player {uid} already exists")
    st["uid"] = uid
    st["name"] = ((body or {}).get("name") or f"{st.get('name', pid)} copy")
    _write_state(uid, st)
    return {"ok": True, "summary": _summary(uid, st)}


@app.post("/api/players/{pid}/activate")
async def api_activate_player(pid: str):
    _read_state(pid)
    playerdb.set_active(pid)
    return {"ok": True, "active": pid}


@app.delete("/api/players/{pid}")
async def api_delete_player(pid: str):
    _read_state(pid)
    # Deleting a save is irreversible - there is no history table and no undo. Refusing
    # the last one keeps a stray click from wiping the only progress on the box.
    if playerdb.count() <= 1:
        raise HTTPException(400, "refusing to delete the only remaining save")
    playerdb.delete(pid)
    return {"ok": True, "active": playerdb.active()}


@app.get("/api/player/{pid}")
def api_player(pid: str):
    st = _read_state(pid)
    return {"summary": _summary(pid, st), "posts": st.get("posts", []) or []}


@app.patch("/api/player/{pid}")
async def api_player_edit(pid: str, patch: dict):
    st = _read_state(pid)
    for k, v in patch.items():
        caster = EDITABLE_FIELDS.get(k)
        if caster is None:
            raise HTTPException(400, f"field '{k}' not editable")
        try:
            st[k] = caster(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"'{k}' must be {caster.__name__}")
    _write_state(pid, st)
    return {"ok": True, "summary": _summary(pid, st)}


@app.get("/api/player/{pid}/raw")
def api_player_raw(pid: str):
    return _read_state(pid)


@app.put("/api/player/{pid}/raw")
async def api_player_raw_save(pid: str, body: dict):
    """Full-state replace for the JSON editor. The uid is forced back to the row key -
    a save whose uid disagrees with its key is how a player ends up editing a ghost."""
    current = _read_state(pid)
    if not isinstance(body, dict) or not body:
        raise HTTPException(400, "raw state must be a non-empty object")
    # accountId is the immutable cross-player identity (ranking/targetId), not a
    # dashboard-editable field.  Letting a raw JSON paste replace it can duplicate
    # another player or make every leaderboard fail to deserialize.
    body["accountId"] = current.get("accountId")
    body["uid"] = pid
    _write_state(pid, body)
    return {"ok": True, "summary": _summary(pid, body)}


def _max_treasures(st):
    """Max every released treasure: overcome 10 (the 10* Transcendence tier,
    TreasureOvercomeUp -> MaxLevel 30) and level 30, exp 0. Keeps the equipped
    unitId for treasures the account already owns."""
    import server, routes.artifact_routes as ar
    owned = {t.get("treasureId"): t for t in st.setdefault("treasures", [])}
    st["treasures"] = []
    for i, tid in enumerate(server.ALL_TREASURE_IDS):
        t = owned.get(tid) or ar.make_treasure(i + 1, tid)
        t["overcome"] = 10
        t["level"] = 30
        t["exp"] = 0
        st["treasures"].append(t)


def _accessory_fingerprint(a):
    """What makes two accessories "the same" for dedup purposes."""
    subs = tuple(sorted(
        (s.get("key"), round(float(s.get("value")), 2))
        for s in (a.get("data") or {}).get("subStats") or []))
    return (a.get("type"), a.get("rarity"), a.get("level"),
            a.get("synergy"), (a.get("data") or {}).get("mainStat"), subs)


def _set_admin_accessories(st, new_accs):
    """REPLACE (set) the player's accessories with the admin list, renumbering
    ids so they stay unique within the save. This is the pre-append behaviour."""
    st["accessories"] = []
    for i, a in enumerate(new_accs):
        a["id"] = i + 1
        st["accessories"].append(a)
    return len(st["accessories"])


def _admin_accessory_list(pid):
    """The accessories the `accessory_admin` macro grants.

    Driven by data/admin_accessories.json - one JSON object with
      { "include_builtin": true|false,
        "accessories": [ { name, type, rarity, level, synergy, mainStat, subStats } ] }
    `include_builtin` adds the curated 65-piece best-in-slot set. The JSON's own
    entries add custom pieces. Falls back to the built-in set when the file is
    missing or has no accessories - so an empty file never grants nothing."""
    from cli import grant_accessories
    cfg = grant_accessories.load_admin_config(ADMIN_ACCESSORIES_FILE)
    out = []
    if cfg.get("include_builtin", True):
        out.extend(grant_accessories.build(pid))
    out.extend(cfg.get("accessories", []))
    return out


@app.post("/api/player/{pid}/macro")
async def api_player_macro(pid: str, body: dict):
    st = _read_state(pid)
    macro = (body or {}).get("macro")
    
    if macro == "max_wealth":
        st["gold"] = 99999999
        st["cash"] = 99999999
        st["heart"] = 99999
        inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
        ids = inv.setdefault("itemIds", [])
        cnts = inv.setdefault("counts", [])
        for token_id in (204, 207, 211, 210, 206, 203): # Arena, Clan, KingGod, Event, Babel, Raid
            if token_id in ids:
                cnts[ids.index(token_id)] = 99999
            else:
                ids.append(token_id)
                cnts.append(99999)
    elif macro == "max_inventory":
        import server
        st["inventory"] = {
            "itemIds": list(server.ALL_ITEM_IDS),
            "counts": [99999] * len(server.ALL_ITEM_IDS)
        }
        st["gachaKeys"] = {str(k): 99999 for k in server.ALL_ITEM_IDS}
    elif macro == "max_resources":
        st["gold"] = 290909
        st["cash"] = 290909
        st["heart"] = 290909
        st["level"] = 100
        st["exp"] = 9999999
    elif macro == "hero_basic":
        import server
        cards = st.setdefault("cards", {})
        for unit_id, info in gamedata.HEROES.items():
            if info.get("min_version", 0) <= server.CONTENT_GATE:
                c = cards.setdefault(str(unit_id), {"unitId": unit_id, **server.SEED["cardTemplate"]})
                c["level"] = 20
                c["soul"] = 0
    elif macro == "hero_advanced":
        import server
        cards = st.setdefault("cards", {})
        for unit_id, info in gamedata.HEROES.items():
            if info.get("min_version", 0) <= server.CONTENT_GATE:
                c = cards.setdefault(str(unit_id), {"unitId": unit_id, **server.SEED["cardTemplate"]})
                c["level"] = 30
                c["soul"] = 9999
    elif macro == "hero_max":
        import server
        cards = st.setdefault("cards", {})
        for unit_id, info in gamedata.HEROES.items():
            c = cards.setdefault(str(unit_id), {"unitId": unit_id, **server.SEED["cardTemplate"]})
            c["level"] = 30
            c["soul"] = 9999
    elif macro == "legacy_basic":
        # 0*: base templates (count=1, level-1 option) - the gacha default.
        import server
        arts = st.setdefault("artifacts", [])
        arts.clear()
        for i, aid in enumerate(server.ALL_ARTIFACT_IDS):
            arts.append(server.make_artifact(i + 1, aid))
    elif macro == "legacy_advanced":
        # 10*: maxed artifacts (count 99999 + polishPoint + options) AND every
        # treasure maxed (overcome 10 -> "Transcendence 10", level 30).
        import server
        arts = st.setdefault("artifacts", [])
        arts.clear()
        for i, aid in enumerate(server.ALL_ARTIFACT_IDS):
            arts.append(server.make_max_artifact(i + 1, aid))
        _max_treasures(st)
    elif macro == "legacy_max":
        import server, routes.artifact_routes as ar
        arts = st.setdefault("artifacts", [])
        arts.clear()
        tree = ET.parse(server.XML_DIR / "Artifacts.xml")
        all_relic_ids = [int(el.get("ID")) for el in tree.findall("Artifact") if el.findtext("Type") == "Artifact" and el.findtext("FromType") not in ("Special", "RogueLike", "RogueLikeBuildingArtifact", "Event")]
        for i, aid in enumerate(all_relic_ids):
            arts.append(server.make_max_artifact(i + 1, aid))
        _max_treasures(st)
    elif macro == "accessory_admin":
        # SET (replace): the player's accessories are replaced by the admin set
        # (built-in 65 + data/admin_accessories.json custom pieces).
        _set_admin_accessories(st, _admin_accessory_list(pid))
    elif macro == "rift_legendary_all":
        _grant_rift_collection_to_player(st, wipe_test_equip=True)
    elif macro == "grant_all_skins":
        _grant_all_skins_to_player(st)
    elif macro == "grant_premium_altars":
        _grant_premium_altars_to_player(st)
    elif macro == "toggle_infinity_rift":
        st["infinityRiftEnergy"] = not st.get("infinityRiftEnergy", False)
        if st["infinityRiftEnergy"]:
            st["riftGauge"] = 1000
            for kv in st.setdefault("keyValues", []):
                if kv.get("key") == "RiftGauge":
                    kv["value"] = "1000"
    else:
        raise HTTPException(400, f"unknown macro {macro}")
        
    _write_state(pid, st)
    return {"ok": True, "macro": macro, "summary": _summary(pid, st)}


# --- heroes (cards) ---------------------------------------------------------
HERO_FIELDS = {"level": int, "exp": int, "potentialTier": int, "soul": int,
               "currentSkin": int, "overcome": int, "dimensionLevel": int}


@app.get("/api/player/{pid}/heroes")
def api_heroes(pid: str):
    st = _read_state(pid)
    cards = st.get("cards") or {}
    owned = []
    for key, card in cards.items():
        uid = card.get("unitId", key)
        info = gamedata.hero(uid) or {}
        is_dim = dimension.model(uid, xml_dir=gamedata.XML_DIR) is not None
        owned.append({
            "unitId": int(uid), "name": info.get("name", f"Unit {uid}"),
            "role": info.get("role", "Unknown"), "isDimensionUnit": is_dim,
            "level": card.get("level", 0), "exp": card.get("exp", 0),
            "potentialTier": card.get("potentialTier", 0), "soul": card.get("soul", 0),
            "skins": len(card.get("skins") or []), "currentSkin": card.get("currentSkin", 0),
            "overcome": card.get("overcome", 0),
            "dimensionLevel": card.get("dimensionLevel", 0),
        })
    owned.sort(key=lambda h: h["unitId"])
    owned_ids = {h["unitId"] for h in owned}
    missing = [{"unitId": h["id"], "name": h["name"], "role": h["role"],
                "isDimensionUnit": dimension.model(h["id"], xml_dir=gamedata.XML_DIR) is not None}
               for h in sorted(gamedata.HEROES.values(), key=lambda x: x["id"])
               if h["id"] not in owned_ids]
    return {"owned": owned, "missing": missing}


@app.patch("/api/player/{pid}/heroes/{unit_id}")
async def api_hero_edit(pid: str, unit_id: int, patch: dict):
    st = _read_state(pid)
    cards = st.setdefault("cards", {})
    card = cards.get(str(unit_id))
    if card is None:
        raise HTTPException(404, f"hero {unit_id} not owned")
    for k, v in patch.items():
        caster = HERO_FIELDS.get(k)
        if caster is None:
            raise HTTPException(400, f"field '{k}' not editable")
        try:
            card[k] = caster(v)
        except (TypeError, ValueError):
            raise HTTPException(400, f"'{k}' must be {caster.__name__}")
    _write_state(pid, st)
    return {"ok": True}


@app.post("/api/player/{pid}/heroes/{unit_id}")
async def api_hero_grant(pid: str, unit_id: int):
    if unit_id not in gamedata.HEROES:
        raise HTTPException(404, f"no hero with id {unit_id} in master data")
    st = _read_state(pid)
    cards = st.setdefault("cards", {})
    if str(unit_id) in cards:
        raise HTTPException(409, "hero already owned")
    cards[str(unit_id)] = _new_card(unit_id)
    _write_state(pid, st)
    return {"ok": True}


@app.delete("/api/player/{pid}/heroes/{unit_id}")
async def api_hero_remove(pid: str, unit_id: int):
    st = _read_state(pid)
    cards = st.setdefault("cards", {})
    if cards.pop(str(unit_id), None) is None:
        raise HTTPException(404, f"hero {unit_id} not owned")
    _write_state(pid, st)
    return {"ok": True}


def _new_card(unit_id, level=30, soul=999, overcome=0, dimension_level=0):
    return {"unitId": int(unit_id), "level": level, "exp": 0, "potentialTier": 0,
            "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
            "randomSkinApply": False, "soul": soul,
            "overcome": overcome, "dimensionLevel": dimension_level}


@app.post("/api/player/{pid}/heroes-grant-all")
async def api_heroes_grant_all(pid: str, body: dict = None):
    st = _read_state(pid)
    cards = st.setdefault("cards", {})
    b = body or {}
    level = int(b.get("level", 30))
    soul = int(b.get("soul", 999))
    overcome = int(b.get("overcome", 0))
    dim_level = int(b.get("dimensionLevel", 0))
    added = 0
    for hid in gamedata.HEROES:
        if str(hid) not in cards:
            cards[str(hid)] = _new_card(hid, level, soul, overcome, dim_level)
            added += 1
    _write_state(pid, st)
    return {"ok": True, "added": added, "total": len(cards)}


def _load_all_hero_skins():
    import xml.etree.ElementTree as ET
    from pathlib import Path
    tree = ET.parse(Path(gamedata.XML_DIR) / "Skins.xml")
    skins_by_unit = {}
    inherit_map = {}
    for s in tree.findall("Skin"):
        sid_str = s.get("ID")
        if not sid_str:
            continue
        sid = int(sid_str)
        unit_str = s.get("Unit")
        inherit_str = s.get("Inherit")
        if unit_str:
            uid = int(unit_str)
            inherit_map[sid] = uid
            skins_by_unit.setdefault(uid, []).append(sid)
        elif inherit_str:
            parent_id = int(inherit_str)
            if parent_id in inherit_map:
                uid = inherit_map[parent_id]
                inherit_map[sid] = uid
                skins_by_unit.setdefault(uid, []).append(sid)
    return skins_by_unit


def _grant_all_skins_to_player(st):
    skins_map = _load_all_hero_skins()
    cards = st.setdefault("cards", {})
    total_skins = 0
    for uid in gamedata.HEROES:
        if str(uid) not in cards:
            cards[str(uid)] = _new_card(uid)
        c = cards[str(uid)]
        unit_skins = skins_map.get(uid, [])
        all_skins = set(c.get("skins") or [])
        all_skins.update(unit_skins)
        c["skins"] = sorted(list(all_skins))
        total_skins += len(c["skins"])
    return total_skins


def _grant_rift_collection_to_player(st, wipe_test_equip=True):
    import rift
    if wipe_test_equip:
        st["riftWeapons"] = []
        st["equippedRiftWeapons"] = {}
    st["riftCrystals"] = rift.make_all_legendary_crystals()
    st["riftGauge"] = 1000
    for kv in st.setdefault("keyValues", []):
        if kv.get("key") == "RiftGauge":
            kv["value"] = "1000"


@app.post("/api/player/{pid}/grant-all-skins")
async def api_player_grant_all_skins(pid: str):
    st = _read_state(pid)
    total = _grant_all_skins_to_player(st)
    _write_state(pid, st)
    return {"ok": True, "totalSkins": total}


@app.post("/api/players/grant-all-skins")
async def api_players_grant_all_skins():
    count = 0
    for uid, st, _ in playerdb.all_players():
        if not st:
            continue
        _grant_all_skins_to_player(st)
        playerdb.save(uid, st)
        count += 1
    return {"ok": True, "playersUpdated": count}


@app.post("/api/player/{pid}/toggle-infinity-rift")
async def api_player_toggle_infinity_rift(pid: str):
    st = _read_state(pid)
    st["infinityRiftEnergy"] = not st.get("infinityRiftEnergy", False)
    if st["infinityRiftEnergy"]:
        st["riftGauge"] = 1000
        for kv in st.setdefault("keyValues", []):
            if kv.get("key") == "RiftGauge":
                kv["value"] = "1000"
    _write_state(pid, st)
    return {"ok": True, "infinityRiftEnergy": st["infinityRiftEnergy"]}


@app.post("/api/players/toggle-infinity-rift")
async def api_players_toggle_infinity_rift(body: dict = None):
    b = body or {}
    enable = b.get("enable", True)
    count = 0
    for uid, st, _ in playerdb.all_players():
        if not st:
            continue
        st["infinityRiftEnergy"] = enable
        if enable:
            st["riftGauge"] = 1000
            for kv in st.setdefault("keyValues", []):
                if kv.get("key") == "RiftGauge":
                    kv["value"] = "1000"
        playerdb.save(uid, st)
        count += 1
    return {"ok": True, "playersUpdated": count, "infinityRiftEnergy": enable}


@app.post("/api/player/{pid}/grant-legendary-rift-crystals")
async def api_grant_legendary_rift_crystals(pid: str, body: dict = None):
    st = _read_state(pid)
    b = body or {}
    wipe = bool(b.get("wipeTestEquip", True))
    _grant_rift_collection_to_player(st, wipe_test_equip=wipe)
    _write_state(pid, st)
    return {"ok": True, "crystalCount": len(st.get("riftCrystals", [])), "riftGauge": st.get("riftGauge", 1000)}


@app.post("/api/players/grant-all-legendary-rift-crystals")
async def api_grant_all_players_legendary_rift_crystals(body: dict = None):
    b = body or {}
    wipe = bool(b.get("wipeTestEquip", True))
    count = 0
    for uid, st, _ in playerdb.all_players():
        if not st:
            continue
        _grant_rift_collection_to_player(st, wipe_test_equip=wipe)
        playerdb.save(uid, st)
        count += 1
    return {"ok": True, "migratedPlayers": count, "crystalsPerPlayer": 216}


def _grant_premium_altars_to_player(st):
    dlcs = [
        {"dlc": 2400, "tier": 2},  # Altar of Death (6)
        {"dlc": 2410, "tier": 2},  # Altar of Immortality / Undead (7)
        {"dlc": 2420, "tier": 2},  # Altar of Domination (8)
    ]
    st["rogueLikeBoughtDlcs"] = dlcs
    inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
    item_ids = inv.setdefault("itemIds", [])
    counts = inv.setdefault("counts", [])
    for dlc_item_id in [2400, 2401, 2410, 2411, 2420, 2421, 2430, 2440]:
        if dlc_item_id not in item_ids:
            item_ids.append(dlc_item_id)
            counts.append(1)
        else:
            idx = item_ids.index(dlc_item_id)
            counts[idx] = max(counts[idx], 1)
    st["rogueLikeBuildings"] = [100, 101, 102, 103, 104, 105, 106, 107, 108]
    st["buildingPoint"] = max(st.get("buildingPoint", 25), 25)


@app.post("/api/player/{pid}/grant-premium-altars")
async def api_grant_premium_altars(pid: str):
    st = _read_state(pid)
    _grant_premium_altars_to_player(st)
    _write_state(pid, st)
    return {"ok": True, "rogueLikeBoughtDlcs": st.get("rogueLikeBoughtDlcs", [])}


@app.post("/api/players/grant-all-premium-altars")
async def api_grant_all_players_premium_altars():
    count = 0
    for uid, st, _ in playerdb.all_players():
        if not st:
            continue
        _grant_premium_altars_to_player(st)
        playerdb.save(uid, st)
        count += 1
    return {"ok": True, "playersUpdated": count}


# --- inventory --------------------------------------------------------------
@app.get("/api/player/{pid}/inventory")
def api_inventory(pid: str):
    st = _read_state(pid)
    inv = st.get("inventory") or {}
    ids = inv.get("itemIds") or []
    counts = inv.get("counts") or []
    return [{"id": int(i), "name": gamedata.item_name(i), "count": counts[n] if n < len(counts) else 0,
             "sub": (gamedata.ITEMS.get(int(i)) or {}).get("sub", "None")}
            for n, i in enumerate(ids)]


@app.post("/api/player/{pid}/inventory")
async def api_inventory_set(pid: str, body: dict):
    """Set an item's count (0 removes it). The save keeps two parallel arrays, so they
    are rebuilt together - editing one and not the other silently desyncs the pair."""
    try:
        iid, count = int(body["id"]), int(body["count"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "id and count (integers) required")
    if count < 0:
        raise HTTPException(400, "count must be >= 0")
    st = _read_state(pid)
    inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
    ids, counts = list(inv.get("itemIds") or []), list(inv.get("counts") or [])
    counts += [0] * (len(ids) - len(counts))
    pairs = dict(zip(ids, counts))
    if count == 0:
        pairs.pop(iid, None)
    else:
        pairs[iid] = count
    inv["itemIds"] = list(pairs.keys())
    inv["counts"] = list(pairs.values())
    _write_state(pid, st)
    return {"ok": True, "count": len(inv["itemIds"])}


# --- admin accessory builder (JSON-driven, persisted) --------------------------
# data/admin_accessories.json is the source of truth: entries survive dashboard
# restarts, are read by the `accessory_admin` macro, and are edited through the
# Accessories tab builder UI (same validation the JSON loader enforces).
_ACC_TYPE_NAMES = {1: "Necklace", 2: "Bracelet", 3: "Ring", 4: "Earring"}
_ACC_TYPE_IDS = {v: k for k, v in _ACC_TYPE_NAMES.items()}
_ACC_RARITIES = {1: "Common", 2: "Rare", 3: "Special"}


def _read_admin_accessories():
    """The raw persisted config: {"include_builtin": bool, "accessories": [...]}."""
    cfg = {"include_builtin": True, "accessories": []}
    try:
        if os.path.isfile(ADMIN_ACCESSORIES_FILE):
            with open(ADMIN_ACCESSORIES_FILE, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                cfg["include_builtin"] = bool(raw.get("include_builtin", True))
                cfg["accessories"] = raw.get("accessories") or []
    except Exception:
        cfg = {"include_builtin": True, "accessories": []}
    return cfg


def _write_admin_accessories(cfg):
    with open(ADMIN_ACCESSORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def _admin_acc_fingerprint(e):
    subs = tuple(sorted(
        (str(s.get("key")), round(float(s.get("value")), 2))
        for s in (e.get("subStats") or [])))
    return (e.get("type"), int(e.get("rarity") or 0), int(e.get("level") or 0),
            e.get("synergy"), e.get("mainStat"), subs)


def _validate_admin_accessory(entry):
    """Normalize + validate one JSON entry against the game's real rules
    (per AccessoryConstants.xml via cli.grant_accessories). Raises 400 on any
    violation so the builder cannot half-grant."""
    from cli import grant_accessories
    if not isinstance(entry, dict):
        raise HTTPException(400, "accessory entry must be an object")
    name = str((entry.get("name") or "").strip() or "Unnamed")

    t = entry.get("type")
    if isinstance(t, str):
        t = _ACC_TYPE_IDS.get(t)
    try:
        t = int(t)
    except (TypeError, ValueError):
        raise HTTPException(400, "type must be Necklace/Bracelet/Ring/Earring or 1..4")
    if t not in _ACC_TYPE_NAMES:
        raise HTTPException(400, f"unknown type {t}")

    rar = entry.get("rarity", 3)
    try:
        rar = int(rar)
    except (TypeError, ValueError):
        raise HTTPException(400, "rarity must be 1..3")

    lvl = entry.get("level", 20)
    try:
        lvl = int(lvl)
    except (TypeError, ValueError):
        raise HTTPException(400, "level must be an integer")
    if not 1 <= lvl <= 20:
        raise HTTPException(400, "level must be 1..20")

    syn = entry.get("synergy", 0)
    syn_by_name = {v[0]: k for k, v in grant_accessories.SETS.items()}
    if isinstance(syn, str):
        if syn not in syn_by_name:
            raise HTTPException(400, f"unknown synergy {syn!r} "
                                     f"(use {', '.join(sorted(syn_by_name))})")
        syn = syn_by_name[syn]
    try:
        syn = int(syn)
    except (TypeError, ValueError):
        raise HTTPException(400, "synergy must be a name or an id")
    if syn not in grant_accessories.SETS:
        raise HTTPException(400, f"synergy {syn} out of range (0..{max(grant_accessories.SETS)})")

    legal_mains = grant_accessories.allowed_mains()
    main = entry.get("mainStat")
    if isinstance(main, str):
        main = main.strip()
    if main not in legal_mains[t]:
        raise HTTPException(400, f"mainStat {main!r} is not legal for {_ACC_TYPE_NAMES[t]} "
                                 f"({', '.join(legal_mains[t])})")

    units = grant_accessories.per_score()
    slots, budget = grant_accessories.level_events(rar)
    mega = bool(entry.get("mega"))
    subs = entry.get("subStats") or []
    if not isinstance(subs, list) or not subs:
        raise HTTPException(400, "at least one subStat is required")
    if len(subs) > slots:
        raise HTTPException(400, f"rarity {_ACC_RARITIES[rar]} allows at most {slots} sub-stat(s)")

    normalized, total = [], 0.0
    for s in subs:
        if not isinstance(s, dict):
            raise HTTPException(400, "each subStat must be {key, value}")
        key = s.get("key")
        if key not in units:
            raise HTTPException(400, f"unknown subStat key {key!r}")
        try:
            score = round(float(s.get("value")), 3)
        except (TypeError, ValueError):
            raise HTTPException(400, f"subStat {key} value must be a number")
        if not (0 <= score <= (1000.0 if mega else 26.0)):
            raise HTTPException(400, f"subStat {key} score must be 0..{1000.0 if mega else 26.0} "
                                     f"({'literal MEGA value' if mega else 'SS ceiling'})")
        if not mega:
            total += score
        normalized.append({"key": key, "value": score})
    if not mega and total > budget + 1e-6:
        raise HTTPException(400, f"subStat scores sum to {total} but rarity "
                                 f"'{_ACC_RARITIES[rar]}' caps the shared pool at {budget}")

    out = {"name": name, "type": t, "rarity": rar, "level": lvl,
           "synergy": syn, "mainStat": main, "subStats": normalized}
    if mega:
        out["mega"] = True
    return out


@app.get("/api/admin-accessories")
def api_admin_accessories():
    return _read_admin_accessories()


@app.get("/api/admin-accessories/options")
def api_admin_accessory_options():
    """Legal choices for the builder form, derived from the same XML the loader
    validates against - the UI can never offer a stat the game rejects."""
    from cli import grant_accessories
    return {
        "types": [{"id": t, "name": _ACC_TYPE_NAMES[t]} for t in sorted(_ACC_TYPE_NAMES)],
        "rarities": [{"id": r, "name": _ACC_RARITIES[r]} for r in sorted(_ACC_RARITIES)],
        "levels": {"min": 1, "max": 20},
        "synergies": [{"id": k, "name": v[0]} for k, v in sorted(grant_accessories.SETS.items())],
        "mainStatsByType": {_ACC_TYPE_NAMES[t]: grant_accessories.allowed_mains()[t]
                            for t in sorted(_ACC_TYPE_NAMES)},
        "subStatKeys": sorted(grant_accessories.per_score().keys()),
        "scoreMax": 26.0,
        "slotsByRarity": {r: grant_accessories.level_events(r)[0] for r in sorted(_ACC_RARITIES)},
        "budgetByRarity": {r: grant_accessories.level_events(r)[1] for r in sorted(_ACC_RARITIES)},
    }


@app.post("/api/admin-accessories")
async def api_admin_accessory_add(body: dict):
    if not isinstance(body, dict) or not body:
        raise HTTPException(400, "empty body")
    entry = _validate_admin_accessory(body)
    cfg = _read_admin_accessories()
    have = {_admin_acc_fingerprint(e) for e in cfg["accessories"]}
    if _admin_acc_fingerprint(entry) in have:
        return {"ok": True, "duplicate": True, "entry": entry,
                "total": len(cfg["accessories"])}
    cfg["accessories"].append(entry)
    _write_admin_accessories(cfg)
    return {"ok": True, "duplicate": False, "entry": entry,
            "total": len(cfg["accessories"])}


@app.post("/api/admin-accessories/config")
async def api_admin_accessories_config(body: dict):
    cfg = _read_admin_accessories()
    if "include_builtin" in body:
        cfg["include_builtin"] = bool(body["include_builtin"])
    _write_admin_accessories(cfg)
    return {"ok": True, "include_builtin": cfg["include_builtin"]}


@app.post("/api/admin-accessories/delete")
async def api_admin_accessories_delete(body: dict):
    if "index" not in body:
        raise HTTPException(400, "index required")
    cfg = _read_admin_accessories()
    try:
        idx = int(body["index"])
    except (TypeError, ValueError):
        raise HTTPException(400, "index must be an integer")
    if not 0 <= idx < len(cfg["accessories"]):
        raise HTTPException(404, "no entry at that index")
    removed = cfg["accessories"].pop(idx)
    _write_admin_accessories(cfg)
    return {"ok": True, "removed": removed, "total": len(cfg["accessories"])}


@app.post("/api/admin-accessories/apply")
async def api_admin_accessories_apply(body: dict):
    """REPLACE the player's accessories with the whole admin set (built-in +
    custom JSON), exactly like the `accessory_admin` macro in the Players tab."""
    pid = (body or {}).get("pid")
    if not pid:
        raise HTTPException(400, "pid required")
    st = _read_state(pid)
    try:
        new_accs = _admin_accessory_list(pid)
    except SystemExit as e:
        raise HTTPException(400, str(e))
    count = _set_admin_accessories(st, new_accs)
    _write_state(pid, st)
    return {"ok": True, "set": count, "total": len(st.get("accessories") or [])}


# --- accessories / treasures (read-only views) ------------------------------
@app.get("/api/player/{pid}/accessories")
def api_accessories(pid: str):
    st = _read_state(pid)
    accs = [gamedata.decorate_accessory(a) for a in (st.get("accessories") or [])]
    accs.sort(key=lambda a: (a["synergy"] or 0, a["type"] or 0, a["id"] or 0))
    return {"accessories": accs, "scoreRange": gamedata.SUBSTAT_SCORE_RANGE,
            "grades": gamedata.GRADE_LETTERS, "synergies": gamedata.SYNERGY_NAMES}


# --- mail -------------------------------------------------------------------
def _clean_mail_field(s):
    """Trim, and strip any user-typed @raw: prefix. server.py adds @raw: itself at send
    time; a manual prefix or a leading space breaks its startswith check and the literal
    '@raw:' then shows in-game."""
    if not isinstance(s, str):
        return ""
    s = s.strip()
    while s.lower().startswith("@raw:"):
        s = s[5:].lstrip()
    return s


@app.post("/api/player/{pid}/mail")
async def api_send_mail(pid: str, body: dict):
    title = _clean_mail_field(body.get("title", ""))
    text = _clean_mail_field(body.get("text", ""))
    if not title and not text:
        raise HTTPException(400, "title or body required")
    st = _read_state(pid)
    posts = st.setdefault("posts", [])
    next_id = max((p.get("id", 0) for p in posts), default=0) + 1
    posts.append({
        "id": next_id,
        "type": body.get("type", "Normal"),
        "title": title, "text": text,
        "rewardType": body.get("rewardType", ""),
        "rewardId": int(body.get("rewardId", 0) or 0),
        "rewardAmount": int(body.get("rewardAmount", 0) or 0),
        "untilAt": now_iso(int(body.get("days", 30) or 30)),
    })
    _write_state(pid, st)
    return {"ok": True, "postId": next_id, "posts": posts}


@app.post("/api/mail/broadcast")
async def api_broadcast_mail(body: dict):
    """Same mail to every save - the realistic way to hand out a patch gift."""
    title = _clean_mail_field(body.get("title", ""))
    text = _clean_mail_field(body.get("text", ""))
    if not title and not text:
        raise HTTPException(400, "title or body required")
    sent = []
    for pid, st, _u in playerdb.all_players():
        posts = st.setdefault("posts", [])
        next_id = max((p.get("id", 0) for p in posts), default=0) + 1
        posts.append({
            "id": next_id, "type": body.get("type", "Normal"),
            "title": title, "text": text,
            "rewardType": body.get("rewardType", ""),
            "rewardId": int(body.get("rewardId", 0) or 0),
            "rewardAmount": int(body.get("rewardAmount", 0) or 0),
            "untilAt": now_iso(int(body.get("days", 30) or 30)),
        })
        _write_state(pid, st)
        sent.append(pid)
    return {"ok": True, "sent": sent}


@app.delete("/api/player/{pid}/mail/{post_id}")
async def api_delete_mail(pid: str, post_id: int):
    st = _read_state(pid)
    st["posts"] = [p for p in (st.get("posts") or []) if p.get("id") != post_id]
    _write_state(pid, st)
    return {"ok": True, "posts": st["posts"]}


# --- server.py admin proxy --------------------------------------------------
# One origin and one token for the UI. Read-only sections only: restart/config-save
# live on :8080 and are deliberately not reachable from here.
PROXY_SECTIONS = {"system": "/admin/api/system", "logs": "/admin/api/logs",
                  "routes": "/admin/api/routes", "cdn": "/admin/api/cdn",
                  "config": "/admin/api/config", "info": "/admin/api/info"}


@app.get("/api/server/{section}")
async def api_server_proxy(section: str, request: Request):
    path = PROXY_SECTIONS.get(section)
    if not path:
        raise HTTPException(404, f"unknown section '{section}'")
    headers = _upstream_headers(request)
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(SERVER_URL + path, headers=headers)
        return {"ok": r.status_code == 200, "status": r.status_code, "data": r.json()}
    except Exception as e:
        # The game server being down is a normal state for this UI, not an error page.
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "serverUrl": SERVER_URL}


# --- dashboard auth ---------------------------------------------------------
@app.get("/api/auth/whoami")
def api_whoami(request: Request):
    """What the UI needs to decide between the login form and the app. Open on
    purpose - it reveals only whether an account exists, never who."""
    ok, why = _authorized(_Probe(request))
    return {"user": _session_user(request),
            "hasAdmins": bool(playerdb.admin_count()),
            "tokenMode": False,
            "authenticated": ok, "reason": why}


class _Probe:
    """Ask _authorized() about a real API path, not about /api/auth/whoami itself."""
    def __init__(self, request):
        self.cookies, self.headers = request.cookies, request.headers
        self.query_params, self.client = request.query_params, request.client
        self.url = type("U", (), {"path": "/api/players"})()


_login_hits = {}

@app.post("/api/auth/login")
def api_login(request: Request, body: dict):
    """Password login. Rate-limited per source address: this endpoint is reachable
    from wherever the dashboard is, and a password is guessable in a way a 32-byte
    token is not."""
    ip = _client_ip(request)
    now = datetime.now().timestamp()
    hits = [t for t in _login_hits.get(ip, []) if now - t < 300]
    if len(hits) >= 10:
        _login_hits[ip] = hits
        raise HTTPException(429, "too many sign-in attempts, wait 5 minutes")
    hits.append(now)
    _login_hits[ip] = hits

    token = playerdb.admin_login((body or {}).get("username", ""), (body or {}).get("password", ""))
    if not token:
        raise HTTPException(401, "wrong username or password")
    _login_hits.pop(ip, None)
    res = JSONResponse({"ok": True, "user": body.get("username")})
    # Local development remains usable over plain HTTP. Public Caddy/Cloudflare
    # deployments set a trusted forwarded scheme, so never let an admin cookie
    # travel in cleartext after an HTTPS login.
    res.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                   secure=_cookie_is_secure(request), max_age=playerdb.ADMIN_SESSION_TTL, path="/")
    return res


@app.post("/api/auth/logout")
def api_logout(request: Request):
    playerdb.admin_logout(request.cookies.get(SESSION_COOKIE))
    res = JSONResponse({"ok": True})
    res.delete_cookie(SESSION_COOKIE, path="/")
    return res


@app.post("/api/auth/password")
def api_admin_change_password(request: Request, body: dict):
    """Signed-in admin changes their own password. The middleware already proved
    the session; the old password is still checked against the stored hash so a
    stolen cookie alone cannot re-key the account."""
    user = _session_user(request)
    if not user:
        raise HTTPException(401, "sign in first")
    old = (body or {}).get("oldPassword", "")
    new = (body or {}).get("newPassword", "")
    if len(new) < 8:
        raise HTTPException(400, "new password must be at least 8 characters")
    if not playerdb.admin_change_password(user, old, new,
                                          keep_token=request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(400, "current password is wrong")
    return {"ok": True}


@app.get("/api/auth/admins")
def api_admins():
    return {"admins": playerdb.admin_list()}


@app.post("/api/auth/admins")
def api_admin_create(body: dict):
    username = (body or {}).get("username", "").strip()
    password = (body or {}).get("password", "")
    if len(password) < 8:
        raise HTTPException(400, "password must be at least 8 characters")
    playerdb.admin_create(username, password)
    return {"ok": True, "admins": playerdb.admin_list()}


@app.delete("/api/auth/admins/{username}")
def api_admin_delete(username: str, request: Request):
    if playerdb.admin_count() <= 1:
        raise HTTPException(400, "cannot delete the last admin - you would lock yourself out")
    if username == _session_user(request):
        raise HTTPException(400, "cannot delete the account you are signed in as")
    playerdb.admin_delete(username)
    return {"ok": True, "admins": playerdb.admin_list()}


# --- UI + WS ----------------------------------------------------------------
@app.get("/")
@app.head("/")
def index(request: Request):
    return FileResponse(os.path.join(UI_DIR, "index.html"), headers={"Cache-Control": "no-cache, no-store, must-revalidate, no-transform"})

# Next.js static export uses real paths (/players, /heroes, ...). Map any
# non-API path to the exported file, with an index.html fallback, so direct
# loads and refreshes never 404. Registered after every /api route on purpose.
@app.get("/{path:path}")
@app.head("/{path:path}")
def ui_path(path: str, request: Request):
    if path.startswith(("api/", "ws")) or not path:
        raise HTTPException(404)

    clean_path = path.rstrip("/")
    try:
        full = (UI_ROOT / clean_path).resolve()
        full.relative_to(UI_ROOT)
        html_file = (UI_ROOT / f"{clean_path}.html").resolve()
        html_file.relative_to(UI_ROOT)
    except ValueError:
        raise HTTPException(404)
    if full.is_file():
        return FileResponse(full, headers={"Cache-Control": "no-cache, no-store, must-revalidate, no-transform"})

    if html_file.is_file():
        return FileResponse(html_file, headers={"Cache-Control": "no-cache, no-store, must-revalidate, no-transform"})

    nested_index = full / "index.html"
    if nested_index.is_file():
        return FileResponse(nested_index, headers={"Cache-Control": "no-cache, no-store, must-revalidate, no-transform"})

    return FileResponse(UI_ROOT / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate, no-transform"})


if __name__ == "__main__":
    import sys
    if "--create-admin" in sys.argv:
        # Bootstrap without a UI: the first account has to be made from the box the
        # server runs on, because until one exists the dashboard is loopback-only.
        import getpass
        i = sys.argv.index("--create-admin")
        user = sys.argv[i + 1] if len(sys.argv) > i + 1 else input("username: ").strip()
        pw = getpass.getpass("password: ")
        if len(pw) < 8:
            sys.exit("password must be at least 8 characters")
        if pw != getpass.getpass("repeat: "):
            sys.exit("passwords do not match")
        playerdb.init()
        playerdb.admin_create(user, pw)
        print(f"admin '{user}' created; sign in at http://127.0.0.1:8081/")
        sys.exit(0)
    if "--list-admins" in sys.argv:
        playerdb.init()
        for a in playerdb.admin_list():
            print(a["username"], "last_login:", a["last_login"])
        sys.exit(0)

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
