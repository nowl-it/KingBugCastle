<<<<<<< HEAD
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

=======
"""Unified KGC dashboard (:8081).

One web UI + one server, replacing the old split (tracker_ui/ static + log_tracker.py +
the dead Next.js admin/). Serves webui/ and hosts:
  - WS /ws            live in-battle hero stats (adb logcat -s XignCodeStub -> parsed -> broadcast)
  - /api/*            admin: player state view/edit, mail send/delete, server status

Admin acts directly on state/player.json - server.py's authoritative live save (load_state
reads it) - so edits show up on the client's next fetch with no restart. The per-uid files
under state/players/ are backup mirrors server.py rewrites on save, so the dashboard lists a
uid once (mirror skipped) and never edits the mirror. Mail is appended to the `posts` array;
server.py serves it (wrapping the
title/text with its `@raw:` prefix so the literal text renders verbatim, bypassing Localizer).
"""
import asyncio
import re
import json
import subprocess
import xml.etree.ElementTree as ET
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="KGC Dashboard")

BASE = os.path.dirname(__file__)
UI_DIR = os.path.join(BASE, "webui")
STATE_DIR = os.path.join(BASE, "state")
PLAYERS_DIR = os.path.join(STATE_DIR, "players")
# player.json is server.py's AUTHORITATIVE live save (load_state reads it); the
# per-uid files under players/ are backup mirrors it writes via _sync_player_backup.
# Editing a mirror is pointless - the next in-game save overwrites it from player.json.
LIVE_STATE = os.path.join(STATE_DIR, "player.json")
CONFIG_FILE = os.path.join(BASE, "data", "response_config.json")
ADB_SERIAL = os.environ.get("ADB_SERIAL", "localhost:5556")
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5

app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

connected_clients = set()
log_pattern = re.compile(r'\[(.*?)\]:\s*(.*)')
<<<<<<< HEAD
CATALOG = gamedata.load_catalog()
print(f"[dashboard] gamedata {gamedata.summary()}", flush=True)


# --- battle tracker ---------------------------------------------------------
=======

# --- Hero / master-data lookup (for the live tracker) -----------------------
XML_DIR = os.path.join(BASE, "..", "scratchpad", "xml_live")
STRINGS_FILE = os.path.join(XML_DIR, "Strings_EN_US.xml")
UNITS_FILE = os.path.join(XML_DIR, "Units.xml")


def load_heroes():
    """Build a dict: lowercased localized name -> hero info."""
    name_keys = {}
    try:
        tree = ET.parse(STRINGS_FILE)
        for el in tree.findall("String"):
            key = el.get("Key", "")
            if key.startswith("UnitName_") and el.text:
                name_keys[key.replace("UnitName_", "")] = el.text
    except Exception as e:
        print(f"[tracker] Could not load strings: {e}")

    heroes = {}
    try:
        tree = ET.parse(UNITS_FILE)
        for unit in tree.findall("Unit"):
            t = unit.find("Type")
            if t is None or t.text != "Player":
                continue
            uid = unit.get("ID")
            hidden = unit.find("Visible")
            if hidden is not None and hidden.text == "false":
                continue
            role = unit.find("Role")
            sprite = unit.find("Sprite")
            display = name_keys.get(uid, f"Unit_{uid}")
            heroes[display.lower()] = {
                "id": int(uid),
                "name": display,
                "role": role.text if role is not None else "Unknown",
                "sprite": sprite.text if sprite is not None else None,
            }
    except Exception as e:
        print(f"[tracker] Could not load units: {e}")

    print(f"[tracker] Loaded {len(heroes)} heroes", flush=True)
    return heroes


HEROES = load_heroes()


def load_string_keys(prefix):
    """id (str) -> localized text for every Strings key `<prefix><id>`."""
    out = {}
    try:
        tree = ET.parse(STRINGS_FILE)
        for el in tree.findall("String"):
            key = el.get("Key", "")
            if key.startswith(prefix) and el.text:
                out[key[len(prefix):]] = el.text
    except Exception as e:
        print(f"[tracker] Could not load {prefix}*: {e}")
    return out


BUFF_NAMES = load_string_keys("BuffDataName_")
BUFF_DESCS = load_string_keys("BuffDataDesc_")
SKILL_NAMES = load_string_keys("SkillName_")
SKILL_DESCS = load_string_keys("SkillDesc_")
print(f"[tracker] Loaded {len(BUFF_NAMES)} buff names, {len(SKILL_NAMES)} skill names", flush=True)


def load_all_strings():
    out = {}
    try:
        for el in ET.parse(STRINGS_FILE).getroot().findall("String"):
            k = el.get("Key", "")
            if k and el.text:
                out[k] = el.text
    except Exception as e:
        print(f"[catalog] strings: {e}")
    return out


STRINGS = load_all_strings()


def _xml_children(fname):
    try:
        return list(ET.parse(os.path.join(XML_DIR, fname)).getroot())
    except Exception as e:
        print(f"[catalog] {fname}: {e}")
        return []


def load_catalog():
    """Every sendable reward, grouped by mail rewardType, with resolved display names.
    Feeds the dashboard's mail reward picker so the admin can browse the full inventory."""
    cat = {"Item": [], "Unit": [], "UnitSoul": [], "Artifact": [], "Treasure": [], "Accessory": []}
    # Inventory items (reward boxes, vouchers, card-levelup, accessory-substat items, ...)
    for it in _xml_children("InventoryItems.xml"):
        iid = it.get("ID")
        if not iid:
            continue
        namekey = (it.findtext("Name") or "").strip()
        name = STRINGS.get(namekey) or it.findtext("AdminToolOnlyName") or namekey or iid
        cat["Item"].append({"id": int(iid), "name": name, "sub": it.findtext("Type") or "None"})
    # Heroes (Unit reward = grant hero; UnitSoul = grant soul shards for that hero)
    for h in sorted(HEROES.values(), key=lambda x: x["id"]):
        entry = {"id": h["id"], "name": h["name"], "sub": h["role"]}
        cat["Unit"].append(entry)
        cat["UnitSoul"].append(dict(entry))
    # Artifacts / Treasures / Accessories (display in mail; gift the real item as a box)
    for a in _xml_children("Artifacts.xml"):
        if a.get("ID"):
            cat["Artifact"].append({"id": int(a.get("ID")), "name": STRINGS.get(f"ArtifactName_{a.get('ID')}", f"Artifact {a.get('ID')}")})
    for t in _xml_children("Treasures.xml"):
        if t.get("ID"):
            cat["Treasure"].append({"id": int(t.get("ID")), "name": STRINGS.get(f"TreasureName_{t.get('ID')}", f"Treasure {t.get('ID')}")})
    for ac in _xml_children("FixedAccessoryPresets.xml"):
        if ac.get("ID"):
            cat["Accessory"].append({"id": int(ac.get("ID")), "name": STRINGS.get(f"AccessoryName_{ac.get('ID')}", f"Accessory {ac.get('ID')}")})
    for k in cat:
        cat[k].sort(key=lambda x: x["id"])
    print(f"[catalog] Item:{len(cat['Item'])} Unit:{len(cat['Unit'])} Artifact:{len(cat['Artifact'])} "
          f"Treasure:{len(cat['Treasure'])} Accessory:{len(cat['Accessory'])}", flush=True)
    return cat


CATALOG = load_catalog()

CATEGORY_LABELS = {
    "BuffOpt": "Buff", "Bind": "Bind", "Item": "Item", "Tile": "Tile Buff",
    "Skill": "Skill", "Syn": "Synergy", "Poten": "Potential", "Event": "Event",
    "Custom": "Custom", "Treasure": "Treasure", "Acc": "Accessory", "Rune": "Rune",
    "Mark": "Mark", "Global": "Global", "Overcome": "Overcome",
}


def _clean_desc(text):
    if not text:
        return None
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\{[0-9]+\}", "N", text)
    text = re.sub(r"\\n|\n", " ", text)
    return re.sub(r"\s+", " ", text).strip() or None


def resolve_effects(eff_field):
    """'N[b123@2.5/5.0,s456,Poten]' -> [{name,kind,desc,time,total} ...]."""
    if not eff_field:
        return []
    inner = eff_field[eff_field.find("[") + 1: eff_field.rfind("]")]
    out = []
    for tok in inner.split(","):
        tok = tok.strip()
        if not tok:
            continue
        time_v = total_v = None
        if "@" in tok:
            tok, timing = tok.split("@", 1)
            if "/" in timing:
                try:
                    a, b = timing.split("/", 1)
                    time_v, total_v = float(a), float(b)
                except ValueError:
                    pass
        eff = {"name": tok, "kind": "category", "desc": None,
               "time": time_v, "total": total_v}
        if tok and tok[0] == "b" and tok[1:].isdigit():
            eff["name"] = BUFF_NAMES.get(tok[1:], f"Buff #{tok[1:]}")
            eff["kind"] = "buff"
            eff["desc"] = _clean_desc(BUFF_DESCS.get(tok[1:]))
        elif tok and tok[0] == "s" and tok[1:].isdigit():
            sid = tok[1:]
            eff["name"] = SKILL_NAMES.get(sid) or SKILL_NAMES.get(sid[:-1]) or f"Skill #{sid}"
            eff["kind"] = "skill"
            eff["desc"] = _clean_desc(SKILL_DESCS.get(sid) or SKILL_DESCS.get(sid[:-1]))
        else:
            eff["name"] = CATEGORY_LABELS.get(tok, tok)
        out.append(eff)
    return out


>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
async def broadcast(message: dict):
    if not connected_clients:
        return
    text = json.dumps(message)
<<<<<<< HEAD
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
=======
    disconnected = set()
    for client in connected_clients:
        try:
            await client.send_text(text)
        except Exception:
            disconnected.add(client)
    for client in disconnected:
        connected_clients.discard(client)


async def read_logcat():
    # Self-healing loop: if the device is absent/adb dies, retry instead of freezing.
    # Everything here is async (NOT subprocess.run) so a missing device never blocks the
    # event loop - the web UI + admin API stay responsive with no device connected.
    while True:
        try:
            print("Starting adb logcat reader...", flush=True)
            clr = await asyncio.create_subprocess_exec(
                "adb", "-s", ADB_SERIAL, "logcat", "-c",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(clr.wait(), timeout=10)
            process = await asyncio.create_subprocess_exec(
                "adb", "-s", ADB_SERIAL, "logcat", "-s", "XignCodeStub",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
            await _pump_logcat(process)
        except Exception as e:
            print(f"[tracker] logcat reader error: {e}", flush=True)
        await asyncio.sleep(5)  # device gone / adb reset -> back off then retry
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5


async def _pump_logcat(process):
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        try:
<<<<<<< HEAD
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
=======
            decoded = line.decode('utf-8', errors='replace').strip()
            if "I XignCodeStub:" in decoded and "]: " in decoded:
                idx = decoded.find("I XignCodeStub: ")
                if idx == -1:
                    continue
                content = decoded[idx + len("I XignCodeStub: "):].strip()
                match = log_pattern.match(content)
                if not match:
                    continue
                name = match.group(1).split('#', 1)[0]
                stats_str = match.group(2)
                hero_info = HEROES.get(name.lower())
                if not hero_info:
                    continue
                stats = {}
                effects = []
                eff_match = re.search(r'Eff=(\d+\[[^\]]*\])', stats_str)
                if eff_match:
                    effects = resolve_effects(eff_match.group(1))
                    stats_str = stats_str[:eff_match.start()] + stats_str[eff_match.end():]
                for pair in stats_str.split(','):
                    pair = pair.strip()
                    if '=' in pair:
                        k, v = pair.split('=', 1)
                        try:
                            stats[k.strip()] = float(v.strip())
                        except ValueError:
                            pass
                await broadcast({
                    "type": "hero_update", "name": name, "role": hero_info["role"],
                    "heroId": hero_info["id"], "sprite": hero_info["sprite"],
                    "stats": stats, "effects": effects,
                })
        except Exception as e:
            print(f"Error parsing line: {e}")


# --- Admin: player state files ----------------------------------------------
EDITABLE_FIELDS = ("name", "castleName", "gold", "cash", "heart", "level", "exp")


def _player_files():
    # Authoritative live save first, keyed by its uid. The players/ mirrors of that
    # same uid are skipped (server.py overwrites them from player.json on save), so
    # one player shows once. Genuinely distinct per-uid files still list separately.
    seen = {}
    if os.path.exists(LIVE_STATE):
        try:
            uid = json.load(open(LIVE_STATE, encoding="utf-8")).get("uid", "dev-0001")
        except Exception:
            uid = "dev-0001"
        seen[uid] = LIVE_STATE
    if os.path.isdir(PLAYERS_DIR):
        for fn in sorted(os.listdir(PLAYERS_DIR)):
            if fn.endswith(".json") and fn[:-5] not in seen:
                seen[fn[:-5]] = os.path.join(PLAYERS_DIR, fn)
    return list(seen.items())


def _resolve_pid(pid):
    for name, path in _player_files():
        if name == pid:
            return path
    raise HTTPException(404, f"player {pid} not found")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5


def _now_iso(days=0):
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


<<<<<<< HEAD
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
=======
def _summary(pid, st):
    return {
        "id": pid,
        "name": st.get("name", pid),
        "castleName": st.get("castleName", ""),
        "gold": st.get("gold", 0), "cash": st.get("cash", 0),
        "heart": st.get("heart", 0), "level": st.get("level", 0),
        "exp": st.get("exp", 0),
        "postCount": len(st.get("posts", []) or []),
    }


@app.get("/api/status")
def api_status():
    players = _player_files()
    cfg = {}
    try:
        cfg = _read_json(CONFIG_FILE).get("server", {})
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
    except Exception:
        pass
    return {
        "version": cfg.get("serverVersion", "?"),
        "patchFolder": cfg.get("patchFolder", "?"),
<<<<<<< HEAD
        "players": playerdb.count(),
        "activePlayer": playerdb.active(),
        "trackerClients": len(connected_clients),
        "adbSerial": ADB_SERIAL,
        "serverUrl": SERVER_URL,
        "multiplayer": os.environ.get("KGC_MULTIPLAYER", "1") != "0",   # default on, matches server.py
        "authMode": "token" if ADMIN_TOKEN else "loopback-only",
        "gamedata": gamedata.summary(),
    }


=======
        "players": len(players),
        "heroesLoaded": len(HEROES),
        "trackerClients": len(connected_clients),
        "adbSerial": ADB_SERIAL,
    }


# Reward types whose grant actually mutates player state (server.py _grant_reward) vs
# types the client only renders in the mail (gift the real item as an Item reward box).
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
GRANTABLE_TYPES = ["Gold", "Cash", "Heart", "Item", "Unit", "UnitSoul", "Card"]
DISPLAY_ONLY_TYPES = ["Artifact", "Treasure", "Accessory"]


@app.get("/api/catalog")
def api_catalog():
    return {"catalog": CATALOG, "grantable": GRANTABLE_TYPES, "displayOnly": DISPLAY_ONLY_TYPES}


<<<<<<< HEAD
# --- player CRUD ------------------------------------------------------------
@app.get("/api/players")
def api_players():
    active = playerdb.active()
    out = []
    for pid, st, _updated in playerdb.all_players():
        try:
            out.append(_summary(pid, st, active))
=======
@app.get("/api/players")
def api_players():
    out = []
    for pid, path in _player_files():
        try:
            out.append(_summary(pid, _read_json(path)))
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
        except Exception as e:
            out.append({"id": pid, "error": str(e)})
    return out


<<<<<<< HEAD
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
=======
@app.get("/api/player/{pid}")
def api_player(pid: str):
    st = _read_json(_resolve_pid(pid))
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
    return {"summary": _summary(pid, st), "posts": st.get("posts", []) or []}


@app.patch("/api/player/{pid}")
async def api_player_edit(pid: str, patch: dict):
<<<<<<< HEAD
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
=======
    path = _resolve_pid(pid)
    st = _read_json(path)
    for k, v in patch.items():
        if k not in EDITABLE_FIELDS:
            raise HTTPException(400, f"field '{k}' not editable")
        if k in ("gold", "cash", "heart", "level", "exp"):
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"'{k}' must be an integer")
        st[k] = v
    _write_json(path, st)
    return {"ok": True, "summary": _summary(pid, st)}


def _clean_mail_field(s):
    """Trim, and strip any user-typed @raw: prefix. server.py adds @raw: itself at send
    time (_ensure_raw_prefix); a manual prefix or a leading space breaks its startswith
    check -> the literal '@raw:' shows in-game. Normalize here so no caller can trip it."""
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
    if not isinstance(s, str):
        return ""
    s = s.strip()
    while s.lower().startswith("@raw:"):
        s = s[5:].lstrip()
    return s


@app.post("/api/player/{pid}/mail")
async def api_send_mail(pid: str, body: dict):
<<<<<<< HEAD
=======
    path = _resolve_pid(pid)
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
    title = _clean_mail_field(body.get("title", ""))
    text = _clean_mail_field(body.get("text", ""))
    if not title and not text:
        raise HTTPException(400, "title or body required")
<<<<<<< HEAD
    st = _read_state(pid)
=======
    st = _read_json(path)
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
    posts = st.setdefault("posts", [])
    next_id = max((p.get("id", 0) for p in posts), default=0) + 1
    posts.append({
        "id": next_id,
        "type": body.get("type", "Normal"),
<<<<<<< HEAD
        "title": title, "text": text,
=======
        "title": title,
        "text": text,
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
        "rewardType": body.get("rewardType", ""),
        "rewardId": int(body.get("rewardId", 0) or 0),
        "rewardAmount": int(body.get("rewardAmount", 0) or 0),
        "untilAt": _now_iso(int(body.get("days", 30) or 30)),
    })
<<<<<<< HEAD
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
=======
    _write_json(path, st)
    return {"ok": True, "postId": next_id, "posts": posts}


@app.delete("/api/player/{pid}/mail/{post_id}")
async def api_delete_mail(pid: str, post_id: int):
    path = _resolve_pid(pid)
    st = _read_json(path)
    posts = st.get("posts", []) or []
    st["posts"] = [p for p in posts if p.get("id") != post_id]
    _write_json(path, st)
    return {"ok": True, "posts": st["posts"]}


# --- Web UI + WS ------------------------------------------------------------
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
@app.get("/")
def index():
    return FileResponse(os.path.join(UI_DIR, "index.html"))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
<<<<<<< HEAD
    # HTTP middleware never sees websocket scope, so this needs its own copy of the
    # guard - it streams live battle telemetry to whoever connects.
    if ADMIN_TOKEN:
        sent = websocket.headers.get("x-admin-token") or websocket.query_params.get("admin_token") or ""
        if not secrets.compare_digest(sent, ADMIN_TOKEN):
            return await websocket.close(code=1008)
    elif (websocket.client.host if websocket.client else None) not in _LOOPBACK:
        return await websocket.close(code=1008)
=======
>>>>>>> 093e0fe102ea49cdcba6cf7470dbe680f57f95d5
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
