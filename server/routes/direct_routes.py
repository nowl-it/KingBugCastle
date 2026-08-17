"""The four routes that must bypass build_model, plus /pvp/info.

`respond()` builds its answer from the client's declared model and overlays the
handler's dict on top. These five carry a shape build_model cannot produce - a list of
whole objects (accessories, invasion records) rather than named scalar fields - so
they are registered as direct `@app` routes, which FastAPI matches before the generic
`for _r in ROUTE_MODELS` dispatcher.

/accessory is GET-list and POST-equip on one path (the same split /shop uses), so it
needs two decorated functions rather than one DYNAMIC_OVERRIDES entry.

Uses the `register(app, srv)` pattern.

    python3 direct_routes.py     # self-check
"""
import json

from common import admin_log
from config import RCFG
from state import load_state, save_state

srv = None      # the live server module, set by register()


async def _body(request, srv_mod):
    """The request body, AES envelope or plain JSON, never raising on either."""
    raw = await request.body()
    if not raw:
        return {}
    try:
        return srv_mod.aes_decrypt(raw)
    except Exception:
        try:
            return json.loads(raw)
        except Exception:
            return {}


def _enc(payload):
    from fastapi.responses import Response
    return Response(srv.aes_encrypt(payload), media_type="application/json",
                    headers={"encryptedWithHex": "true"})


def invasion_records():
    """One record per (theme, difficulty) up to the unlocked one.

    Accessory/treasure/rift-weapon unlocks gate on invasion cleared difficulty, not on
    hard mode, so every difficulty up to `invasionUnlockedDifficulty` must be present
    and carry that same number as its unlockedDifficulty.

    `difficulty` is the highest CLEARED tier and MUST be `unlocked`, not the loop var:
    GetInvasionClearedDifficulty reads records.First(theme).difficulty, so a `d` there
    reports cleared=1 and every Invasion II theme (diff >= 6) stays locked in Battle.
    The d-loop only pads the list length for per-tier indexing (same fix as r_player)."""
    unlocked = RCFG["player"]["invasionUnlockedDifficulty"]
    themes = ([t for a, b in RCFG["player"]["invasionThemeRanges"] for t in range(a, b)]
              + srv._PREREQ_THEMES)
    return [{"theme": t, "difficulty": unlocked, "unlockedDifficulty": unlocked}
            for t in themes for d in range(1, unlocked + 1)]


def equip_accessories(st, target_ids, unit_id):
    """Move `target_ids` onto `unit_id`, clearing whatever that hero wore.

    A hero wears one set, so equipping must unequip the previous holder first -
    otherwise the same slot reads as filled twice and the panel shows a duplicate."""
    accs = srv.get_st_accessories(st)
    if not (target_ids and unit_id):
        return accs
    for a in accs:
        if a["unitId"] == unit_id:
            a["unitId"] = 0
        if a["id"] in target_ids:
            a["unitId"] = unit_id
    save_state(st)
    return accs


def register(app, server_module):
    global srv
    srv = server_module
    from fastapi import Request

    @app.get("/auth")
    @app.get("/auth/auth")
    async def auth_native_google(request: Request):
        """The client's Google sign-in endpoint (`GET /auth?id=<account>&cookie=...`).

        The REAL backend answers it with a full AuthResponseModel carrying an
        accessToken; the route_models fallback used to return an empty model, so a
        client with no stored token (fresh install / cleared data) never got one:
        its /auth/login went out id-less, r_login refused it (multiplayer), and
        every following request hit load_state()'s throwaway template save - the
        "KingBug/BugCastle" ghost account. Mint a real session here, same path
        /auth/register takes."""
        host = request.headers.get("host", "?")
        login_id = str(request.query_params.get("id") or "")
        admin_log(f"[{host}] GET /auth id={login_id[:24]} cookie={str(request.query_params.get('cookie') or '')[:12]}")
        import secrets
        from common import now_iso
        # routes.player_routes, NOT top-level player_routes: server/routes/ is on
        # sys.path too, so a bare `import player_routes` here loads a SECOND module
        # instance whose injected `srv` is None - and the first-time-register path
        # (srv._registration_allowed) crashed with AttributeError, a 500, and the
        # client's "Failed to log in. Please try again." on brand-new accounts.
        from routes.player_routes import mint_session_token
        token = mint_session_token(login_id)
        if token is None:
            return _enc({"code": 200, "msg": "cannot create an account right now",
                         "success": False})
        return _enc({
            "code": 200, "msg": None, "success": True,
            "accessToken": token, "expiredAt": now_iso(7),
            "seed": secrets.token_hex(8), "serverTime": now_iso(0),
            "blockedUntilAt": now_iso(0), "blockedComment": "", "loginId": login_id,
        })

    @app.get("/accessory")
    async def accessory_inventory_direct(request: Request):
        st = load_state()
        host = request.headers.get("host", "?")
        admin_log(f"[{host}] DIRECT GET /accessory -> AccessoryInventoryResponseModel")
        import accessory
        res = accessory.r_accessory_inventory({}, st)
        return _enc({"code": 200, "msg": None, "success": True, **res})

    @app.post("/accessory")
    async def accessory_equip_direct(request: Request):
        st = load_state()
        host = request.headers.get("host", "?")
        body = await _body(request, srv)
        admin_log(f"[{host}] DIRECT POST /accessory -> AccessoryResultResponseModel")
        import accessory
        res = accessory.r_accessory_equip(body, st)
        return _enc({"code": 200, "msg": None, "success": True, **res})


    @app.get("/invasion/record")
    @app.post("/invasion/record")
    async def invasion_record_direct(request: Request):
        host = request.headers.get("host", "?")
        admin_log(f"[{host}] DIRECT /invasion/record -> InvasionRecordsResponseModel")
        return _enc({"code": 200, "msg": None, "success": True,
                     "difficultyRecords": invasion_records()})

    @app.get("/pvp/info")
    @app.post("/pvp/info")
    async def pvp_info_direct(request: Request):
        # The request body is never read - the response depends only on saved state.
        # pvpInfoDirect stays the base because it carries the fields that were tuned
        # against the live client (deckRecord, retry counts, ban lists); r_pvp_info
        # then overlays the parts that actually move, so a win shows up here too.
        host = request.headers.get("host", "?")
        payload = {"code": 200, "msg": None, "success": True}
        payload.update(RCFG["pvpInfoDirect"])
        payload.update(srv.PVP_OVERRIDES["/pvp/info"]({}, load_state()))
        admin_log(f"[{host}] PVP DIRECT /pvp/info -> "
                  f"seasonUntilAtDates={len(payload['seasonUntilAtDates'])}")
        return _enc(payload)


def handlers():
    """No DYNAMIC_OVERRIDES entries - every route here is a direct @app route."""
    return {}


if __name__ == "__main__":
    import pathlib as _pl
    import sys
    import tempfile

    import playerdb
    playerdb.DB_PATH = _pl.Path(tempfile.mkdtemp()) / "t.db"
    playerdb.init()
    import server                                        # noqa: E402
    register(server.app, sys.modules["server"])

    st = server.copy.deepcopy(server.DEFAULT_PLAYER)
    st["uid"] = "t"
    playerdb.save("t", st)
    playerdb.set_active("t")

    recs = invasion_records()
    unlocked = RCFG["player"]["invasionUnlockedDifficulty"]
    assert recs, "no invasion records - accessories/treasures stay locked"
    assert {r["difficulty"] for r in recs} == set(range(1, unlocked + 1)), \
        "a gap in the difficulty ladder leaves the unlock gate unsatisfied"
    assert all(r["unlockedDifficulty"] == unlocked for r in recs), \
        "the record must carry the unlocked difficulty, not the loop variable"

    # Equipping moves the set and clears the previous holder.
    accs = srv.get_st_accessories(st)
    if len(accs) >= 2:
        a, b = accs[0], accs[1]
        a["unitId"] = 10260
        equip_accessories(st, [b["id"]], 10260)
        assert a["unitId"] == 0, "the previous holder kept the slot"
        assert b["unitId"] == 10260, b
    assert equip_accessories(st, [], 0) is accs, "a no-op equip must not rebuild the list"

    print("direct_routes self-check ok (5 direct routes)")
