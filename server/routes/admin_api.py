"""The /admin/api/* endpoints the dashboard proxies, lifted out of server.py.

The UI itself lives in dashboard.py (:8081); this module only serves data. Player
creation stays here rather than in the dashboard so the "new save" shape is defined
in exactly one place - the dashboard calls POST /admin/api/players/create over HTTP.

Why `register(app, srv)` and not plain imports: server.py imports this module, so
importing server.py back would be a cycle. `srv` is the live server module, and every
lookup through it happens at request time - which also means hot-reloaded values
(RCFG after a config save, the OVERRIDES table) are read fresh instead of frozen at
import. Same pattern as google_login.register(app).
"""
import copy
import datetime
import json
import os
import secrets
import subprocess
import time

import config
import playerdb
from fastapi import Request
from fastapi.responses import HTMLResponse

DASHBOARD_URL = os.environ.get("KGC_DASHBOARD_URL", "http://127.0.0.1:8081")

# Fields the active-player editor hands back; the grouping mirrors how the dashboard
# form is laid out. Containers are edited through their own endpoints, not here.
_PLAYER_FIELDS = {
    "accountId": 0, "uid": "", "name": "", "castleName": "", "level": 1, "exp": 0,
    "gold": 0, "cash": 0, "paidCash": 0, "heart": 0,
    "bestClearedStage": 1, "bestClearedTheme": 1,
    "bestClearedHardStage": 1, "bestClearedHardTheme": 1,
    "currentDeckPreset": 0, "playedCount": 0, "winCount": 0,
    "hasFreeRename": True, "buildingPoints": 25,
    "accountCreatedAt": "", "lastHeartTime": "", "tomorrow": "", "nextWeek": "",
    "eventFlag": 0,
}
_PLAYER_CONTAINERS = {
    "cards": {}, "decks": [], "inventory": {"itemIds": [], "counts": []},
    "equippedArtifacts": [], "buildingPresets": [], "altarPoints": [],
    "altarLevels": [], "tokens": [], "missions": [], "tutorialKeyValues": [],
}
# What POST /admin/api/player/save accepts. Deliberately not every key in the save:
# uid is the row key, and the containers have dedicated endpoints that keep their
# parallel arrays in sync.
_SAVABLE = [k for k in _PLAYER_FIELDS if k not in ("accountId", "uid")] + [
    "inventory", "tokens", "buildingPresets", "altarPoints", "altarLevels",
    "missions", "tutorialKeyValues",
]


def list_players():
    result = []
    for uid, data, updated in playerdb.all_players():
        if data is None:
            result.append({"id": uid, "name": f"[invalid] {uid}", "error": True})
            continue
        result.append({
            "id": uid,
            "name": data.get("name", "Unknown"),
            "uid": data.get("uid", ""),
            "level": data.get("level", 1),
            "gold": data.get("gold", 0),
            "cash": data.get("cash", 0),
            "castleName": data.get("castleName", ""),
            "cards": len(data.get("cards", {})),
            "updatedAt": datetime.datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M"),
        })
    return result


def register(app, srv):
    """Add /admin and the /admin/api/* endpoints. `srv` is the server module."""

    def active_state():
        """The save the operator has selected in the dashboard.

        Reads playerdb.active() directly rather than going through load_state():
        in multiplayer mode that one deliberately refuses to fall back to the
        active player for a request with no session, because on a public port
        that fallback let anyone read and write it without a token. Admin
        requests are already past the /admin guard, so here the fallback is the
        whole point.
        """
        uid = playerdb.active()
        return (playerdb.load(uid) if uid else None) or srv.load_state()

    @app.get("/admin")
    async def admin_page():
        return HTMLResponse(
            f'<!doctype html><meta charset="utf-8"><title>KGC admin</title>'
            f'<body style="font:15px system-ui;background:#0b0f17;color:#e6ecf7;padding:40px">'
            f'<h1 style="font-size:18px">The admin UI moved</h1>'
            f'<p>It is now the dashboard at <a style="color:#7aa8ff" href="{DASHBOARD_URL}">{DASHBOARD_URL}</a> '
            f'(<code>python3 server/dashboard.py</code>).</p>'
            f'<p style="color:#6d7c99">This server still serves the <code>/admin/api/*</code> endpoints '
            f'the dashboard calls.</p>')

    @app.get("/admin/api/info")
    async def admin_info():
        players = list_players()
        return {
            "version": srv.SERVER_VERSION, "patchFolder": srv.PATCH_FOLDER,
            "routes": len(srv.ROUTE_MODELS) + len(srv.OVERRIDES),
            "players": players,
            "playerCount": len(players),
            "activePlayerId": playerdb.active(),
        }

    # ── Player CRUD ──
    @app.get("/admin/api/players")
    async def admin_list_players():
        return {"players": list_players()}

    @app.post("/admin/api/players/create")
    async def admin_create_player(body: dict):
        uid = body.get("uid", "player-" + secrets.token_hex(4))
        # deep: a shallow copy shares nested dicts with the template
        st = copy.deepcopy(srv.DEFAULT_PLAYER)
        st["name"] = body.get("name", "NewPlayer")
        st["uid"] = uid
        st["accountId"] = playerdb.next_account_id()
        st["accountCreatedAt"] = srv.now_iso(0)
        st["lastHeartTime"] = srv.now_iso(0)
        st["tomorrow"] = srv.now_iso(1)
        st["nextWeek"] = srv.now_iso(7)
        
        # --- Tier 1 Defaults ---
        st["gold"] = 290909
        st["cash"] = 290909
        st["heart"] = 290909
        st["level"] = 100
        st["exp"] = 9999999
        import gamedata
        for unit_id, info in gamedata.HEROES.items():
            if info.get("min_version", 0) <= srv.CONTENT_GATE:
                if str(unit_id) in st["cards"]:
                    st["cards"][str(unit_id)]["level"] = 20
        arts = st.setdefault("artifacts", [])
        arts.clear()
        for i, aid in enumerate(srv.ALL_ARTIFACT_IDS):
            arts.append(srv.make_max_artifact(i + 1, aid))
        # -----------------------
        
        playerdb.save(uid, st)
        return {"ok": True, "uid": uid}

    @app.post("/admin/api/players/delete")
    async def admin_delete_player(body: dict):
        # playerdb.active() falls back to the first remaining row on its own.
        playerdb.delete(body.get("uid", ""))
        return {"ok": True}

    @app.post("/admin/api/players/switch")
    async def admin_switch_player(body: dict):
        pid = body.get("uid", "")
        if playerdb.load(pid) is None:
            return {"ok": False, "error": "Player not found"}
        playerdb.set_active(pid)
        return {"ok": True}

    @app.get("/admin/api/players/{pid}")
    async def admin_get_player_by_id(pid: str):
        return playerdb.load(pid) or {"error": "not found"}

    @app.post("/admin/api/players/{pid}/save")
    async def admin_save_player_by_id(pid: str, body: dict):
        # body may contain partial updates or full state
        existing = playerdb.load(pid) or {}
        # These two fields identify the database row and the player's public
        # targetId.  They must not change through a generic save payload.
        updates = dict(body)
        updates.pop("uid", None)
        updates.pop("accountId", None)
        existing.update(updates)
        existing["uid"] = pid
        playerdb.save(pid, existing)
        return {"ok": True}

    @app.post("/admin/api/players/{pid}/reset")
    async def admin_reset_player_by_id(pid: str):
        st = copy.deepcopy(srv.DEFAULT_PLAYER)
        st["uid"] = pid
        st["accountId"] = (playerdb.load(pid) or {}).get("accountId") or playerdb.next_account_id()
        playerdb.save(pid, st)
        return {"ok": True}

    # ── Legacy single-player endpoints (target the active save) ──
    @app.get("/admin/api/player")
    async def admin_get_active_player():
        st = active_state()
        out = {k: st.get(k, d) for k, d in _PLAYER_FIELDS.items()}
        out.update({k: st.get(k, copy.deepcopy(d)) for k, d in _PLAYER_CONTAINERS.items()})
        return out

    @app.post("/admin/api/player/save")
    async def admin_save_active_player(body: dict):
        st = active_state()
        for k in _SAVABLE:
            if k in body:
                st[k] = body[k]
        srv.save_state(st)
        return {"ok": True}

    @app.post("/admin/api/player/reset")
    async def admin_reset_active_player():
        st = copy.deepcopy(srv.DEFAULT_PLAYER)
        # reset the data, keep the identity
        st["uid"] = playerdb.active() or "dev-0001"
        srv.save_state(st)
        return {"ok": True}

    @app.post("/admin/api/heroes/save")
    async def admin_save_heroes(body: dict):
        st = active_state()
        if "cards" in body:
            st["cards"] = body["cards"]
        srv.save_state(st)
        return {"ok": True}

    @app.post("/admin/api/heroes/give-all")
    async def admin_give_all_heroes():
        st = active_state()
        template = {
            "level": 30, "exp": 0, "potentialTier": 0,
            "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
            "randomSkinApply": False, "soul": 999,
        }
        cards = st.setdefault("cards", {})
        for hid in srv.ALL_HERO_IDS:
            cards.setdefault(str(hid), {"unitId": hid, **template})
        srv.save_state(st)
        return {"ok": True, "count": len(cards)}

    @app.post("/admin/api/decks/save")
    async def admin_save_decks(body: dict):
        st = active_state()
        if "decks" in body:
            st["decks"] = body["decks"]
        srv.save_state(st)
        return {"ok": True}

    @app.post("/admin/api/artifacts/give-all")
    async def admin_give_all_artifacts():
        return {"ok": True, "count": len(srv.DEFAULT_ARTIFACTS)}

    @app.post("/admin/api/treasures/give-all")
    async def admin_give_all_treasures():
        st = active_state()
        st["treasures"] = copy.deepcopy(srv.DEFAULT_TREASURES)
        srv.save_state(st)
        return {"ok": True, "count": len(srv.DEFAULT_TREASURES)}

    @app.post("/admin/api/rift-crystals/grant-all-legendary")
    async def admin_grant_all_legendary_rift_crystals():
        import rift
        st = active_state()
        st["riftWeapons"] = []
        st["equippedRiftWeapons"] = {}
        st["riftCrystals"] = rift.make_all_legendary_crystals()
        st["riftGauge"] = 1000
        for kv in st.setdefault("keyValues", []):
            if kv.get("key") == "RiftGauge":
                kv["value"] = "1000"
        srv.save_state(st)
        return {"ok": True, "count": len(st["riftCrystals"])}

    @app.post("/admin/api/altars/grant-premium")
    async def admin_grant_premium_altars():
        st = active_state()
        st["rogueLikeBoughtDlcs"] = list(srv.ALL_ROGUE_LIKE_DLCS)
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
        srv.save_state(st)
        return {"ok": True, "count": len(srv.ALL_ROGUE_LIKE_DLCS)}

    @app.post("/admin/api/state/reload")
    async def admin_reload_state():
        active_state()
        return {"ok": True}

    @app.get("/admin/api/config")
    async def admin_get_config():
        return json.loads(config.CONFIG_FILE.read_text())

    @app.post("/admin/api/config/save")
    async def admin_save_config(body: dict):
        config.CONFIG_FILE.write_text(json.dumps(body, indent=2))
        # In place, not `config.RCFG = body`: server.py and the domain modules hold
        # their own reference to this dict, and rebinding would leave all of them
        # reading the pre-save copy.
        config.RCFG.clear()
        config.RCFG.update(body)
        return {"ok": True}

    @app.get("/admin/api/logs")
    async def admin_get_logs():
        return srv.LOG_BUF[-100:]

    @app.get("/admin/api/system")
    async def admin_system():
        uptime = int(time.time() - srv.SERVER_START_TIME)

        # Host metrics, stdlib-only (/proc + statvfs) so nothing new is required on
        # the OCI box. One-shot /proc/stat deltas are noisy, so CPU is the load
        # average instead; the dashboard renders it against nproc.
        load = [0.0, 0.0, 0.0]
        try:
            with open("/proc/loadavg") as f:
                load = [float(x) for x in f.read().split()[:3]]
        except OSError:
            pass
        mem = {"total": 0, "available": 0, "used": 0, "percent": 0.0}
        try:
            with open("/proc/meminfo") as f:
                fields = {}
                for line in f:
                    k, _, v = line.partition(":")
                    fields[k] = int(v.strip().split()[0]) // 1024   # kB -> MB
            mem["total"] = fields.get("MemTotal", 0)
            mem["available"] = fields.get("MemAvailable", 0)
            mem["used"] = max(0, mem["total"] - mem["available"])
            mem["percent"] = round(100.0 * mem["used"] / mem["total"], 1) if mem["total"] else 0.0
        except OSError:
            pass
        disk = {"total": 0, "free": 0, "used": 0, "percent": 0.0}
        try:
            v = os.statvfs(srv.DATA_DIR)
            disk["total"] = round(v.f_blocks * v.f_frsize / 2**30, 1)      # GB
            disk["free"] = round(v.f_bavail * v.f_frsize / 2**30, 1)
            disk["used"] = round(disk["total"] - disk["free"], 1)
            disk["percent"] = round(100.0 * disk["used"] / disk["total"], 1) if disk["total"] else 0.0
        except OSError:
            pass

        processes = []
        try:
            output = subprocess.check_output(
                ["ps", "-eo", "pid,comm,%cpu,%mem", "--sort=-%cpu"],
                text=True
            )
            lines = output.strip().split("\n")
            for line in lines[1:6]:
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    processes.append({
                        "pid": parts[0],
                        "name": parts[1],
                        "cpu": float(parts[2]),
                        "mem": float(parts[3])
                    })
        except Exception:
            pass

        return {
            "version": srv.SERVER_VERSION,
            "patchFolder": srv.PATCH_FOLDER,
            "startTime": datetime.datetime.fromtimestamp(
                srv.SERVER_START_TIME).strftime("%Y-%m-%d %H:%M:%S"),
            "uptime": uptime,
            "uptimeStr": f"{uptime//3600}h{(uptime%3600)//60}m{uptime%60}s",
            "routeCount": len(srv.ROUTE_MODELS),
            "overrideCount": len(srv.OVERRIDES),
            "playerCount": playerdb.count(),
            "cdmFiles": len(srv._CDN_FILES),
            "logLines": len(srv.LOG_BUF),
            "cpu": {"load1": load[0], "load5": load[1], "load15": load[2],
                    "cores": os.cpu_count() or 1},
            "mem": mem,
            "disk": disk,
            "processes": processes,
        }

    @app.get("/admin/api/routes")
    async def admin_routes():
        items = [{
            "path": path,
            "model": model.__class__.__name__ if hasattr(model, "__class__") else str(model)[:60],
            "overridden": path in srv.OVERRIDES,
        } for path, model in sorted(srv.ROUTE_MODELS.items())]
        return {"routes": items, "total": len(items)}

    @app.get("/admin/api/cdn")
    async def admin_cdn():
        items = [{"name": n, "size": len(d)} for n, d in sorted(srv._CDN_FILES.items())]
        return {"files": items, "total": len(items)}

    @app.post("/admin/api/restart")
    async def admin_restart():
        import sys
        os.execl(sys.executable, sys.executable, "-m", "uvicorn", "server:app",
                 "--host", "0.0.0.0", "--port", "8080")
