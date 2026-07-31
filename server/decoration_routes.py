"""Decoration: flags, name tags, map skins, login skins and advisors.

The tab used to be one fixed payload with five empty lists. Every other kind of owned
content is granted in full on this server, so the cosmetics are too; only what is
equipped, and the advisor contracts, are per-player state.

`_deco` is `decoration.block` - the same dict the rank rows and clan rows read, so an
equip made here shows up on the boards without a second copy of the defaults.

Uses the `register(app, srv)` pattern.

    python3 decoration_routes.py     # self-check
"""
import datetime

import decoration
from common import body_int
from config import CONTENT_GATE, XML_DIR
from decoration import block as _deco
from state import save_state

srv = None      # the live server module, set by register()


def _deco_flags(st):
    d = _deco(st)
    return {"flagsModel": [{"flagId": i, "season": 0}
                           for i in decoration.ids("flags", CONTENT_GATE, XML_DIR)],
            "equipedFlag": dict(d["flag"])}


def _deco_nametags(st):
    d = _deco(st)
    return {"nameTagsModel": [{"nameTagId": i}
                              for i in decoration.ids("nameTags", CONTENT_GATE, XML_DIR)],
            "equippedNameTag": {"nameTagId": d["nameTag"]}}


def _deco_advisors(st):
    """One AdvisorInfo per advisor. An advisor with no contract row still appears -
    the panel lists what exists and reads contractUntilAt to decide the state, so
    omitting it would hide the advisor rather than show it as un-contracted."""
    d = _deco(st)
    out = []
    for i in decoration.ids("advisors", CONTENT_GATE, XML_DIR):
        c = d["contracts"].get(str(i), {})
        out.append({"advisorId": i,
                    "contractUntilAt": c.get("until", ""),
                    "remainExtendCount": c.get("remainExtend", decoration.EXTEND_COUNT)})
    return {"advisorList": out}


def _deco_full(st):
    d = _deco(st)
    return {
        "flagInfo": _deco_flags(st),
        "nameTagInfo": _deco_nametags(st),
        "mapSkinInfo": {"mapSkinList": [
            {"skinId": i, "isFavorite": i in d["favoriteMapSkins"], "owned": True}
            for i in decoration.ids("mapSkins", CONTENT_GATE, XML_DIR)]},
        "advisorInfo": _deco_advisors(st),
        "loginSkinInfo": {"loginSkinList": decoration.ids("loginSkins", CONTENT_GATE, XML_DIR)},
        # appliedMapSkinData is Dictionary<int,int> and the only map-skin API taking a
        # second number is SetMapSkin(resMapSkin, probability), so it is read here as
        # skin id -> weight. One equipped skin is that skin at 100.
        "equipInfo": {"appliedMapSkinData": {str(d["mapSkin"]): 100},
                      "appliedAdvisor": d["advisor"],
                      "appliedLoginSkin": d["loginSkin"],
                      "loginSceneIllustData": decoration.login_scene(d["loginSkin"], XML_DIR)},
    }


def r_decoration(body, st):
    return _deco_full(st)


def r_flag_inventory(body, st):
    return _deco_flags(st)


def r_flag_set(body, st):
    d = _deco(st)
    fid = body_int(body.get("id") or body.get("flagId"), 0)
    if fid in decoration.ids("flags", CONTENT_GATE, XML_DIR) or fid == 0:
        d["flag"] = {"flagId": fid, "season": body_int(body.get("season"), 0)}
        save_state(st)
    return dict(d["flag"])


def r_nametag_inventory(body, st):
    return _deco_nametags(st)


def r_nametag_set(body, st):
    d = _deco(st)
    nid = body_int(body.get("id") or body.get("nameTagId"), 0)
    if nid in decoration.ids("nameTags", CONTENT_GATE, XML_DIR) or nid == 0:
        d["nameTag"] = nid
        save_state(st)
    return {"nameTagId": d["nameTag"]}


def r_map_skin_equip(body, st):
    d = _deco(st)
    sid = body_int(body.get("skinId"), 0)
    if sid in decoration.ids("mapSkins", CONTENT_GATE, XML_DIR):
        d["mapSkin"] = sid
        save_state(st)
    return _deco_full(st)


def r_map_skin_favorite(body, st):
    d = _deco(st)
    sid = body_int(body.get("skinId"), 0)
    fav = d["favoriteMapSkins"]
    if body.get("set", True):
        if sid not in fav:
            fav.append(sid)
    elif sid in fav:
        fav.remove(sid)
    save_state(st)
    return _deco_full(st)


def r_map_skin_buy(body, st):
    """Owned already, so this only charges. Refusing outright would leave the buy
    button dead; charging keeps the token economy honest for anyone who cares."""
    sid = body_int(body.get("skinId"), 0)
    if body.get("useSkinToken"):
        price = decoration.token_price("mapSkins", sid, "SkinTokenPrice", XML_DIR)
        if price and srv._item_count(st, decoration.SKIN_TOKEN) >= price:
            srv._take_item(st, decoration.SKIN_TOKEN, price)
    _deco(st)["mapSkin"] = sid if sid in decoration.ids("mapSkins", CONTENT_GATE, XML_DIR) \
        else _deco(st)["mapSkin"]
    save_state(st)
    return {"skinId": sid, "playerCash": st.get("cash", 0),
            "playerSkinToken": srv._item_count(st, decoration.SKIN_TOKEN),
            "playerPremiumSkinToken": 0}


def r_login_skin_equip(body, st):
    d = _deco(st)
    sid = body_int(body.get("skinId"), 0)
    if sid in decoration.ids("loginSkins", CONTENT_GATE, XML_DIR):
        d["loginSkin"] = sid
        save_state(st)
    return decoration.login_scene(d["loginSkin"], XML_DIR) or {}


def r_login_scene_illust(body, st):
    return decoration.login_scene(_deco(st)["loginSkin"], XML_DIR) or {}


def _advisor_response(st, aid):
    c = _deco(st)["contracts"].get(str(aid), {})
    return {"advisorId": aid, "contractUntilAt": c.get("until", ""),
            "remainExtendCount": c.get("remainExtend", decoration.EXTEND_COUNT),
            "playerSkinToken": srv._item_count(st, decoration.SKIN_TOKEN),
            "advisorInfo": _deco_advisors(st)}


def r_advisor_contract(body, st):
    d = _deco(st)
    aid = body_int(body.get("advisorId"), 0)
    if aid in decoration.ids("advisors", CONTENT_GATE, XML_DIR):
        price = decoration.token_price("advisors", aid, "ContractPrice", XML_DIR) or 0
        if price:
            srv._take_item(st, decoration.SKIN_TOKEN, min(price, srv._item_count(st, decoration.SKIN_TOKEN)))
        d["contracts"][str(aid)] = {"until": decoration.contract_until(),
                                    "remainExtend": decoration.EXTEND_COUNT}
        save_state(st)
    return _advisor_response(st, aid)


def r_advisor_extend(body, st):
    """Extends from the current expiry, not from now - extending early must not throw
    away the time already paid for."""
    d = _deco(st)
    aid = body_int(body.get("advisorId"), 0)
    c = d["contracts"].get(str(aid))
    if c and c.get("remainExtend", 0) > 0:
        price = decoration.token_price("advisors", aid, "ExtendPrice", XML_DIR) or 0
        if price:
            srv._take_item(st, decoration.SKIN_TOKEN, min(price, srv._item_count(st, decoration.SKIN_TOKEN)))
        try:
            base = datetime.datetime.strptime(c["until"], "%Y-%m-%dT%H:%M:%S.000Z")
        except (KeyError, ValueError):
            base = None
        c["until"] = decoration.contract_until(base, decoration.EXTEND_DAYS)
        c["remainExtend"] -= 1
        save_state(st)
    return _advisor_response(st, aid)


def r_advisor_timeout(body, st):
    """The client reports a contract it believes has run out; drop it and fall back to
    the default advisor so the lobby is never left with nobody standing there."""
    d = _deco(st)
    aid = body_int(body.get("advisorId"), 0)
    d["contracts"].pop(str(aid), None)
    if d["advisor"] == aid:
        d["advisor"] = decoration.DEFAULT_ADVISOR
    save_state(st)
    return _advisor_response(st, aid)


def r_advisor_equip(body, st):
    d = _deco(st)
    aid = body_int(body.get("advisorId"), 0)
    if aid in decoration.ids("advisors", CONTENT_GATE, XML_DIR):
        d["advisor"] = aid
        save_state(st)
    return _deco_full(st)


def register(app, server_module):
    global srv
    srv = server_module
    srv.DECORATION_OVERRIDES = handlers()


def handlers():
    return {
        "/decoration": r_decoration,
        "/decoration/map-skin/equip": r_map_skin_equip,
        "/decoration/map-skin/buy": r_map_skin_buy,
        "/decoration/map-skin/favorite": r_map_skin_favorite,
        "/decoration/login-skin/equip": r_login_skin_equip,
        "/decoration/advisor/contract": r_advisor_contract,
        "/decoration/advisor/extend": r_advisor_extend,
        "/decoration/advisor/equip": r_advisor_equip,
        "/decoration/advisor/timeout": r_advisor_timeout,
        "/flag/inventory": r_flag_inventory,
        "/flag/equipedFlag": lambda b, st: dict(_deco(st)["flag"]),
        "/flag/set": r_flag_set,
        "/nameTag/inventory": r_nametag_inventory,
        "/nameTag/set": r_nametag_set,
        "/player/get-login-scene-illust-data": r_login_scene_illust,
    }


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

    full = r_decoration({}, st)
    for k in ("flagInfo", "nameTagInfo", "mapSkinInfo", "advisorInfo", "loginSkinInfo"):
        assert full[k], f"{k} empty - the player owns no cosmetics"
    assert full["advisorInfo"]["advisorList"], "an advisor with no contract must still be listed"

    # An equip must persist on the save, not on a throwaway dict.
    skin = decoration.ids("mapSkins", CONTENT_GATE, XML_DIR)[0]
    r_map_skin_equip({"skinId": skin}, st)
    assert st["decoration"]["mapSkin"] == skin, "the equip did not reach the save"

    # A contract is granted, then extended from its own expiry - not from now.
    adv = decoration.ids("advisors", CONTENT_GATE, XML_DIR)[0]
    r_advisor_contract({"advisorId": adv}, st)
    first = st["decoration"]["contracts"][str(adv)]["until"]
    r_advisor_extend({"advisorId": adv}, st)
    c = st["decoration"]["contracts"][str(adv)]
    assert c["until"] > first, "extending early threw away the time already paid for"
    assert c["remainExtend"] == decoration.EXTEND_COUNT - 1, c

    # A timed-out contract falls back to the default advisor, never to nobody.
    st["decoration"]["advisor"] = adv
    r_advisor_timeout({"advisorId": adv}, st)
    assert st["decoration"]["advisor"] == decoration.DEFAULT_ADVISOR, "the lobby lost its advisor"

    paths = handlers()
    assert len(paths) == 15, f"{len(paths)} routes registered"
    assert all(callable(h) for h in paths.values())
    print(f"decoration_routes self-check ok ({len(paths)} routes)")
