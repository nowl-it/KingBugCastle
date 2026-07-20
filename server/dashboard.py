"""KGC private-server dashboard (:8081) - the one admin UI.

Serves webui/ (Vue 3, vendored, no build step) and hosts:
  - WS  /ws              live in-battle hero stats (adb logcat -s XignCodeStub -> parsed -> broadcast)
  - /api/*               admin: players, saves, heroes, inventory, accessories, mail
  - /api/server/*        read-only proxy of server.py's own /admin/api (:8080)

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
import re
import secrets
from datetime import datetime, timedelta

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

import gamedata
import playerdb

app = FastAPI(title="KGC Dashboard")

BASE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE, "webui")
CONFIG_FILE = os.path.join(BASE, "data", "response_config.json")
ADB_SERIAL = os.environ.get("ADB_SERIAL", "localhost:5556")
SERVER_URL = os.environ.get("KGC_SERVER_URL", "http://127.0.0.1:8080")
ADMIN_TOKEN = os.environ.get("KGC_ADMIN_TOKEN")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_STATE_GATE = asyncio.Lock()


# --- guards -----------------------------------------------------------------
@app.middleware("http")
async def guard_admin(request, call_next):
    """This whole app edits saves and sends mail, and it binds 0.0.0.0 - gate it the
    same way server.py gates /admin: token if configured, else loopback only."""
    if ADMIN_TOKEN:
        sent = request.headers.get("x-admin-token") or request.query_params.get("admin_token") or ""
        if not secrets.compare_digest(sent, ADMIN_TOKEN):
            return JSONResponse({"error": "admin token required"}, status_code=403)
    elif (request.client.host if request.client else None) not in _LOOPBACK:
        return JSONResponse(
            {"error": "dashboard is loopback-only; set KGC_ADMIN_TOKEN to allow remote access"},
            status_code=403)
    return await call_next(request)


# Endpoints that write by calling the game server instead of touching playerdb here.
# They must NOT hold the flock: server.py takes the same cross-process lock for its own
# request, so holding it across the proxy call deadlocks both sides until the timeout.
# The write still happens under a lock - server.py's.
_DELEGATED = {("POST", "/api/players")}


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

connected_clients = set()
log_pattern = re.compile(r'\[(.*?)\]:\s*(.*)')
CATALOG = gamedata.load_catalog()
print(f"[dashboard] gamedata {gamedata.summary()}", flush=True)


# --- battle tracker ---------------------------------------------------------
async def broadcast(message: dict):
    if not connected_clients:
        return
    text = json.dumps(message)
    for client in list(connected_clients):
        try:
            await client.send_text(text)
        except Exception:
            connected_clients.discard(client)


async def read_logcat():
    # Self-healing: if the device is absent or adb dies, retry instead of freezing.
    # All async (never subprocess.run) so a missing device never blocks the event
    # loop - the UI and admin API stay responsive with no device connected.
    while True:
        try:
            print("[tracker] starting adb logcat reader...", flush=True)
            clr = await asyncio.create_subprocess_exec(
                "adb", "-s", ADB_SERIAL, "logcat", "-c",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            await asyncio.wait_for(clr.wait(), timeout=10)
            proc = await asyncio.create_subprocess_exec(
                "adb", "-s", ADB_SERIAL, "logcat", "-s", "XignCodeStub",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            await _pump_logcat(proc)
        except Exception as e:
            print(f"[tracker] logcat reader error: {e}", flush=True)
        await asyncio.sleep(5)


async def _pump_logcat(process):
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        try:
            decoded = line.decode("utf-8", errors="replace").strip()
            marker = "I XignCodeStub: "
            if marker not in decoded or "]: " not in decoded:
                continue
            content = decoded[decoded.find(marker) + len(marker):].strip()
            match = log_pattern.match(content)
            if not match:
                continue
            name = match.group(1).split("#", 1)[0]
            hero_info = gamedata.HEROES_BY_NAME.get(name.lower())
            if not hero_info:
                continue
            stats_str = match.group(2)
            effects = []
            eff_match = re.search(r"Eff=(\d+\[[^\]]*\])", stats_str)
            if eff_match:
                effects = gamedata.resolve_effects(eff_match.group(1))
                stats_str = stats_str[:eff_match.start()] + stats_str[eff_match.end():]
            stats = {}
            for pair in stats_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    try:
                        stats[k.strip()] = float(v.strip())
                    except ValueError:
                        pass
            await broadcast({"type": "hero_update", "name": name, "role": hero_info["role"],
                             "heroId": hero_info["id"], "sprite": hero_info["sprite"],
                             "stats": stats, "effects": effects})
        except Exception as e:
            print(f"[tracker] parse error: {e}", flush=True)


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
        "trackerClients": len(connected_clients),
        "adbSerial": ADB_SERIAL,
        "serverUrl": SERVER_URL,
        "multiplayer": os.environ.get("KGC_MULTIPLAYER") == "1",
        "authMode": "token" if ADMIN_TOKEN else "loopback-only",
        "gamedata": gamedata.summary(),
    }


GRANTABLE_TYPES = ["Gold", "Cash", "Heart", "Item", "Unit", "UnitSoul", "Card"]
DISPLAY_ONLY_TYPES = ["Artifact", "Treasure", "Accessory"]


@app.get("/api/catalog")
def api_catalog():
    return {"catalog": CATALOG, "grantable": GRANTABLE_TYPES, "displayOnly": DISPLAY_ONLY_TYPES}


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
async def api_create_player(body: dict):
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
    headers = {"x-admin-token": ADMIN_TOKEN} if ADMIN_TOKEN else {}
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


# --- heroes (cards) ---------------------------------------------------------
HERO_FIELDS = {"level": int, "exp": int, "potentialTier": int, "soul": int, "currentSkin": int}


@app.get("/api/player/{pid}/heroes")
def api_heroes(pid: str):
    st = _read_state(pid)
    cards = st.get("cards") or {}
    owned = []
    for key, card in cards.items():
        uid = card.get("unitId", key)
        info = gamedata.hero(uid) or {}
        owned.append({
            "unitId": int(uid), "name": info.get("name", f"Unit {uid}"),
            "role": info.get("role", "Unknown"),
            "level": card.get("level", 0), "exp": card.get("exp", 0),
            "potentialTier": card.get("potentialTier", 0), "soul": card.get("soul", 0),
            "skins": len(card.get("skins") or []), "currentSkin": card.get("currentSkin", 0),
        })
    owned.sort(key=lambda h: h["unitId"])
    owned_ids = {h["unitId"] for h in owned}
    missing = [{"unitId": h["id"], "name": h["name"], "role": h["role"]}
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


def _new_card(unit_id, level=30, soul=999):
    return {"unitId": int(unit_id), "level": level, "exp": 0, "potentialTier": 1,
            "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
            "randomSkinApply": False, "soul": soul}


@app.post("/api/player/{pid}/heroes-grant-all")
async def api_heroes_grant_all(pid: str, body: dict = None):
    st = _read_state(pid)
    cards = st.setdefault("cards", {})
    level = int((body or {}).get("level", 30))
    soul = int((body or {}).get("soul", 999))
    added = 0
    for hid in gamedata.HEROES:
        if str(hid) not in cards:
            cards[str(hid)] = _new_card(hid, level, soul)
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
async def api_server_proxy(section: str):
    path = PROXY_SECTIONS.get(section)
    if not path:
        raise HTTPException(404, f"unknown section '{section}'")
    headers = {"x-admin-token": ADMIN_TOKEN} if ADMIN_TOKEN else {}
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            r = await client.get(SERVER_URL + path, headers=headers)
        return {"ok": r.status_code == 200, "status": r.status_code, "data": r.json()}
    except Exception as e:
        # The game server being down is a normal state for this UI, not an error page.
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "serverUrl": SERVER_URL}


# --- UI + WS ----------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(os.path.join(UI_DIR, "index.html"))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # HTTP middleware never sees websocket scope, so this needs its own copy of the
    # guard - it streams live battle telemetry to whoever connects.
    if ADMIN_TOKEN:
        sent = websocket.headers.get("x-admin-token") or websocket.query_params.get("admin_token") or ""
        if not secrets.compare_digest(sent, ADMIN_TOKEN):
            return await websocket.close(code=1008)
    elif (websocket.client.host if websocket.client else None) not in _LOOPBACK:
        return await websocket.close(code=1008)
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.discard(websocket)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(read_logcat())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
