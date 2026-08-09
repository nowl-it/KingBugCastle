"""KGC private-server dashboard (:8081) - the one admin UI.

Serves webui-next/out (Next.js) and hosts:
  - /api/*               admin: players, saves, heroes, inventory, accessories, mail
  - /api/server/*        read-only proxy of server.py's own /admin/api (:8080)

The UI is served from webui-next/out when it exists (bundle via
`npm run build` in webui-next/).

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
import dimension
import playerdb

app = FastAPI(title="KGC Dashboard")

BASE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE, "webui-next", "out")
if not os.path.isdir(UI_DIR):
    os.makedirs(UI_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(BASE, "data", "response_config.json")
SERVER_URL = os.environ.get("KGC_SERVER_URL", "http://127.0.0.1:8080")
ADMIN_TOKEN = os.environ.get("KGC_ADMIN_TOKEN")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_STATE_GATE = asyncio.Lock()


# --- guards -----------------------------------------------------------------
# Three ways in, checked in this order:
#   1. an admin account (username + password -> session cookie). Once ANY admin
#      exists this is the only way in from a non-loopback address, because a
#      tunnel/reverse proxy makes every request look like loopback.
#   2. KGC_ADMIN_TOKEN, for scripts and the old bookmarked ?admin_token= links.
#   3. nothing configured at all -> loopback only, same as before.
SESSION_COOKIE = "kgc_admin"
_OPEN_PATHS = {"/api/auth/login", "/api/auth/whoami"}


def _session_user(request):
    return playerdb.admin_for_token(request.cookies.get(SESSION_COOKIE))


def _token_ok(request):
    if not ADMIN_TOKEN:
        return False
    sent = request.headers.get("x-admin-token") or request.query_params.get("admin_token") or ""
    return secrets.compare_digest(sent, ADMIN_TOKEN)


def _authorized(request):
    """(ok, why_not). Static assets are open so the login page itself can load."""
    path = request.url.path
    if path in _OPEN_PATHS or not path.startswith(("/api", "/ws")):
        return True, None
    if _session_user(request) or _token_ok(request):
        return True, None
    if playerdb.admin_count():
        return False, "sign in to the dashboard"
    if ADMIN_TOKEN:
        return False, "admin token required"
    if (request.client.host if request.client else None) in _LOOPBACK:
        return True, None
    return False, ("dashboard is loopback-only; create an admin account "
                   "(python3 dashboard.py --create-admin <user>) or set KGC_ADMIN_TOKEN")


@app.middleware("http")
async def guard_admin(request, call_next):
    """This whole app edits saves and sends mail, and it binds 0.0.0.0 - gate it."""
    ok, why = _authorized(request)
    if not ok:
        return JSONResponse({"error": why, "login": True}, status_code=401)
    return await call_next(request)


# Endpoints that write by calling the game server instead of touching playerdb here.
# They must NOT hold the flock: server.py takes the same cross-process lock for its own
# request, so holding it across the proxy call deadlocks both sides until the timeout.
# The write still happens under a lock - server.py's.
_DELEGATED = {("POST", "/api/players")}

def _upstream_headers(request):
    """Credential for the /admin/api/* calls we make against the game server.

    The game port runs the same three-ladder guard we do. A shared token covers it
    when one is configured; otherwise forward the signed-in operator's own session
    token, which playerdb resolves on the other side. Sending nothing works only on
    a loopback-only box, and that is exactly the case a tunnel breaks.
    """
    if ADMIN_TOKEN:
        return {"x-admin-token": ADMIN_TOKEN}
    tok = request.cookies.get(SESSION_COOKIE)
    return {"x-admin-token": tok} if tok else {}



@app.middleware("http")
async def serialize_state_writes(request, call_next):
    """Hold playerdb's cross-process lock for any request that can mutate state.
    Keyed on method, not path: a new mutating endpoint is then covered by default
    instead of silently racing until someone remembers to add its prefix here."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    if (request.method, request.url.path) in _DELEGATED:
        return await call_next(request)
    async with _STATE_GATE:                 # in-process first: flock blocks the loop
        with playerdb.write_lock():
            return await call_next(request)


app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

CATALOG = gamedata.load_catalog()
print(f"[dashboard] gamedata {gamedata.summary()}", flush=True)

# --- state helpers ----------------------------------------------------------
EDITABLE_FIELDS = {
    "name": str, "castleName": str,
    "gold": int, "cash": int, "paidCash": int, "heart": int, "level": int, "exp": int,
    "bestClearedStage": int, "bestClearedTheme": int,
    "bestClearedHardStage": int, "bestClearedHardTheme": int,
    "buildingPoints": int, "playedCount": int, "winCount": int, "eventFlag": int,
}


def _read_state(pid):
    st = playerdb.load(pid)
    if st is None:
        raise HTTPException(404, f"player {pid} not found")
    return st


def _write_state(pid, st):
    playerdb.save(pid, st)


def _now_iso(days=0):
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


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
        "authMode": "token" if ADMIN_TOKEN else "loopback-only",
        "gamedata": gamedata.summary(),
    }


GRANTABLE_TYPES = ["Gold", "Cash", "Heart", "Item", "Unit", "UnitSoul", "Card", "Treasure"]
DISPLAY_ONLY_TYPES = ["Artifact", "Accessory"]


@app.get("/api/catalog")
def api_catalog():
    return {"catalog": CATALOG, "grantable": GRANTABLE_TYPES, "displayOnly": DISPLAY_ONLY_TYPES}


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
    _read_state(pid)
    if not isinstance(body, dict) or not body:
        raise HTTPException(400, "raw state must be a non-empty object")
    body["uid"] = pid
    _write_state(pid, body)
    return {"ok": True, "summary": _summary(pid, body)}


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
        import server
        arts = st.setdefault("artifacts", [])
        arts.clear()
        for i, aid in enumerate(server.ALL_ARTIFACT_IDS):
            art = server.make_artifact(i + 1, aid)
            art["count"] = 1 # 0*
            arts.append(art)
    elif macro == "legacy_advanced":
        import server
        arts = st.setdefault("artifacts", [])
        arts.clear()
        for i, aid in enumerate(server.ALL_ARTIFACT_IDS):
            art = server.make_artifact(i + 1, aid)
            art["count"] = 99999 # 10*
            arts.append(art)
    elif macro == "legacy_max":
        import server, xml.etree.ElementTree as ET
        arts = st.setdefault("artifacts", [])
        arts.clear()
        tree = ET.parse(server.XML_DIR / "Artifacts.xml")
        all_relic_ids = [int(el.get("ID")) for el in tree.findall("Artifact") if el.findtext("Type") == "Artifact" and el.findtext("FromType") not in ("Special", "RogueLike", "RogueLikeBuildingArtifact", "Event")]
        for i, aid in enumerate(all_relic_ids):
            art = server.make_artifact(i + 1, aid)
            art["count"] = 99999 # 10*
            arts.append(art)
    elif macro == "accessory_admin":
        from cli import grant_accessories
        st["accessories"] = grant_accessories.build(pid)
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
        "untilAt": _now_iso(int(body.get("days", 30) or 30)),
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
            "untilAt": _now_iso(int(body.get("days", 30) or 30)),
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
            "tokenMode": bool(ADMIN_TOKEN),
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
    ip = request.client.host if request.client else "-"
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
    # Not `secure`: the dashboard is normally served over plain http on a LAN or a
    # tunnel that terminates TLS itself. httponly + samesite=lax are what stop a
    # page in another tab from reading or replaying it.
    res.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                   max_age=playerdb.ADMIN_SESSION_TTL, path="/")
    return res


@app.post("/api/auth/logout")
def api_logout(request: Request):
    playerdb.admin_logout(request.cookies.get(SESSION_COOKIE))
    res = JSONResponse({"ok": True})
    res.delete_cookie(SESSION_COOKIE, path="/")
    return res


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
    print(f"GET / headers={request.headers}")
    return FileResponse(os.path.join(UI_DIR, "index.html"), headers={"Cache-Control": "no-cache, no-store, must-revalidate, no-transform"})

# Next.js static export uses real paths (/players, /heroes, ...). Map any
# non-API path to the exported file, with an index.html fallback, so direct
# loads and refreshes never 404. Registered after every /api route on purpose.
@app.get("/{path:path}")
@app.head("/{path:path}")
def ui_path(path: str, request: Request):
    print(f"GET /{path} headers={request.headers}")
    if path.startswith(("api/", "ws")) or not path:
        raise HTTPException(404)
        
    clean_path = path.rstrip("/")
    full = os.path.join(UI_DIR, clean_path)
    if os.path.isfile(full):
        return FileResponse(full, headers={"Cache-Control": "no-cache, no-store, must-revalidate, no-transform"})
        
    html_file = os.path.join(UI_DIR, f"{clean_path}.html")
    if os.path.isfile(html_file):
        return FileResponse(html_file, headers={"Cache-Control": "no-cache, no-store, must-revalidate, no-transform"})
        
    index = os.path.join(full, "index.html")
    if os.path.isfile(index):
        return FileResponse(index, headers={"Cache-Control": "no-cache, no-store, must-revalidate, no-transform"})
        
    return FileResponse(os.path.join(UI_DIR, "index.html"), headers={"Cache-Control": "no-cache, no-store, must-revalidate, no-transform"})


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
