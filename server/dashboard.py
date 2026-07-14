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

app.mount("/ui", StaticFiles(directory=UI_DIR), name="ui")

connected_clients = set()
log_pattern = re.compile(r'\[(.*?)\]:\s*(.*)')

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


async def broadcast(message: dict):
    if not connected_clients:
        return
    text = json.dumps(message)
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


async def _pump_logcat(process):
    while True:
        line = await process.stdout.readline()
        if not line:
            break
        try:
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


def _now_iso(days=0):
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


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
    except Exception:
        pass
    return {
        "version": cfg.get("serverVersion", "?"),
        "patchFolder": cfg.get("patchFolder", "?"),
        "players": len(players),
        "heroesLoaded": len(HEROES),
        "trackerClients": len(connected_clients),
        "adbSerial": ADB_SERIAL,
    }


# Reward types whose grant actually mutates player state (server.py _grant_reward) vs
# types the client only renders in the mail (gift the real item as an Item reward box).
GRANTABLE_TYPES = ["Gold", "Cash", "Heart", "Item", "Unit", "UnitSoul", "Card"]
DISPLAY_ONLY_TYPES = ["Artifact", "Treasure", "Accessory"]


@app.get("/api/catalog")
def api_catalog():
    return {"catalog": CATALOG, "grantable": GRANTABLE_TYPES, "displayOnly": DISPLAY_ONLY_TYPES}


@app.get("/api/players")
def api_players():
    out = []
    for pid, path in _player_files():
        try:
            out.append(_summary(pid, _read_json(path)))
        except Exception as e:
            out.append({"id": pid, "error": str(e)})
    return out


@app.get("/api/player/{pid}")
def api_player(pid: str):
    st = _read_json(_resolve_pid(pid))
    return {"summary": _summary(pid, st), "posts": st.get("posts", []) or []}


@app.patch("/api/player/{pid}")
async def api_player_edit(pid: str, patch: dict):
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
    if not isinstance(s, str):
        return ""
    s = s.strip()
    while s.lower().startswith("@raw:"):
        s = s[5:].lstrip()
    return s


@app.post("/api/player/{pid}/mail")
async def api_send_mail(pid: str, body: dict):
    path = _resolve_pid(pid)
    title = _clean_mail_field(body.get("title", ""))
    text = _clean_mail_field(body.get("text", ""))
    if not title and not text:
        raise HTTPException(400, "title or body required")
    st = _read_json(path)
    posts = st.setdefault("posts", [])
    next_id = max((p.get("id", 0) for p in posts), default=0) + 1
    posts.append({
        "id": next_id,
        "type": body.get("type", "Normal"),
        "title": title,
        "text": text,
        "rewardType": body.get("rewardType", ""),
        "rewardId": int(body.get("rewardId", 0) or 0),
        "rewardAmount": int(body.get("rewardAmount", 0) or 0),
        "untilAt": _now_iso(int(body.get("days", 30) or 30)),
    })
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
@app.get("/")
def index():
    return FileResponse(os.path.join(UI_DIR, "index.html"))


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
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
