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
import time

import config
import playerdb
from fastapi import Request
from fastapi.responses import HTMLResponse

DASHBOARD_URL = os.environ.get("KGC_DASHBOARD_URL", "http://127.0.0.1:8081")

# Fields the active-player editor hands back; the grouping mirrors how the dashboard
# form is laid out. Containers are edited through their own endpoints, not here.
_PLAYER_FIELDS = {
    "accountId": 1, "uid": "", "name": "", "castleName": "", "level": 1, "exp": 0,
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
        st["accountCreatedAt"] = srv.now_iso(0)
        st["lastHeartTime"] = srv.now_iso(0)
        st["tomorrow"] = srv.now_iso(1)
        st["nextWeek"] = srv.now_iso(7)
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
        existing.update(body)
        playerdb.save(pid, existing)
        return {"ok": True}

    @app.post("/admin/api/players/{pid}/reset")
    async def admin_reset_player_by_id(pid: str):
        st = copy.deepcopy(srv.DEFAULT_PLAYER)
        st["uid"] = pid
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
        st["uid"] = playerdb.active() or st.get("uid", "dev-0001")
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
            "level": 30, "exp": 0, "potentialTier": 1,
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
        return {"ok": True, "count": len(srv.DEFAULT_TREASURES)}

    @app.post("/admin/api/rift-crystals/grant")
    async def admin_grant_rift_crystals(request: Request):
        body = await request.json()
        weapon_id = body.get("weaponId", 0)
        match = [t for t in srv.DEFAULT_RIFT_CRYSTALS if t["weaponId"] == weapon_id]
        if not match:
            return {"ok": False, "error": f"no template for weaponId {weapon_id}"}
        st = active_state()
        crystals = st.setdefault("riftCrystals", [])
        new = dict(match[0])
        new["id"] = max((c["id"] for c in crystals), default=0) + 1
        new["createdAt"] = srv.now_iso()
        new["updatedAt"] = srv.now_iso()
        crystals.append(new)
        srv.save_state(st)
        return {"ok": True, "crystal": new}

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
