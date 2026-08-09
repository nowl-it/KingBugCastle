"""Territory: the plot, its labor economy, hunting parties and the trade shop.

Twenty-seven routes answered an empty model, so the whole tab opened onto an empty
plot that could not be built on. What is here is the real economy: labor accrues per
hour from what is standing, buildings cost labor + gold from master data, hunting pays
its own reward table, and the trade shop is priced in inventory items.

`_terr` seeds a level 1 town hall on first access. Level 0 is the "not built yet"
placeholder and gives a stored-labor cap of 0, so a plot starting there could never
bank the labor a first upgrade costs and would be permanently stuck.

Uses the `register(app, srv)` pattern; `srv` is the live server module, so the reward
and inventory helpers it owns resolve at request time.

    python3 territory_routes.py     # self-check
"""
import datetime

import territory
from common import admin_log, body_int, body_list, now_iso
from config import CONTENT_GATE, XML_DIR
from state import save_state

srv = None      # the live server module, set by register()


def _terr(st):
    """The player's territory, seeded with a level 1 town hall on first access.

    Level 0 is the "not built yet" placeholder: starting there gives a stored-labor
    cap of 0, so the player could never bank the labor a first upgrade costs and the
    plot would be permanently stuck."""
    t = st.setdefault("territory", {})
    if "buildings" not in t:
        t.update({"buildings": territory.starting_layout(XML_DIR), "storedLabor": 0,
                  "lastLaborAt": now_iso(0), "stored": [], "hunting": [],
                  "levelSync": [], "tradeShop": [], "equippedSkin": 0})
    return t


def _terr_labor(st):
    """Current labor, rebased so the accrual clock restarts from now."""
    t = _terr(st)
    labor, _ = territory.accrued_labor(t.get("storedLabor", 0), t.get("lastLaborAt", ""),
                                       t["buildings"], xml_dir=XML_DIR)
    t["storedLabor"] = labor
    t["lastLaborAt"] = now_iso(0)
    return labor


def _terr_at(t, pos):
    """The building at a slot. Coerces here rather than in each caller: every
    territory route that names a slot resolves it through this one function, and a
    slot sent as null or a string used to raise before the caller saw it."""
    pos = body_int(pos, -1)
    return next((b for b in t["buildings"] if b["posIndex"] == pos), None)


def r_territory_fetch(body, st):
    t = _terr(st)
    labor = _terr_labor(st)
    sk, default = territory.skins(CONTENT_GATE, XML_DIR)
    if not t.get("equippedSkin"):
        t["equippedSkin"] = default
    save_state(st)
    return {"labor": labor, "storedLabor": labor,
            "buildingDatas": t["buildings"], "lastLaborAt": t["lastLaborAt"],
            "statBuffPers": t.get("statBuffPers", []),
            "storedBuildings": t["stored"], "playerHuntingData": t["hunting"],
            "playerLevelSyncData": t["levelSync"],
            "tickets": [], "playerTradeShopItemData": t["tradeShop"],
            "passEndedAt": "", "skins": sk, "equippedSkin": t["equippedSkin"],
            # The lobby's own territory summary still reads these two.
            "buildingPoints": st.get("buildingPoints", 25),
            "maxLabor": territory.max_stored_labor(t["buildings"], XML_DIR)}


def r_territory(body, st):
    return r_territory_fetch(body, st)


def _terr_pay(st, bid):
    """Charge a build/upgrade. Returns None on success, else why it was refused."""
    c = territory.cost(bid, XML_DIR)
    labor = _terr_labor(st)
    if labor < c["labor"]:
        return f"not enough labor ({labor} < {c['labor']})"
    if st.get("gold", 0) < c["gold"]:
        return f"not enough gold ({st.get('gold', 0)} < {c['gold']})"
    _terr(st)["storedLabor"] = labor - c["labor"]
    st["gold"] = st.get("gold", 0) - c["gold"]
    return None


def r_territory_build(body, st):
    """Place a new building, or upgrade the one already at that slot.

    /territory/build carries an id, /territory/upgrade-building only a posIndex - both
    land here because both resolve to "the next level of what belongs at this slot"."""
    t = _terr(st)
    pos = body_int(body.get("posIndex"), 0)
    existing = _terr_at(t, pos)
    if body.get("id"):
        bid = body_int(body.get("id"), 0)
    elif existing:
        bid = existing["buildingId"] + 1
        if territory.level(bid) > territory.max_level(bid, XML_DIR):
            return {**r_territory_fetch({}, st), "msg": "already at max level"}
    else:
        return {**r_territory_fetch({}, st), "msg": "nothing to upgrade at this slot"}

    if bid not in territory.buildings(XML_DIR):
        return {**r_territory_fetch({}, st), "msg": f"no such building {bid}"}
    why = _terr_pay(st, bid)
    if why:
        return {**r_territory_fetch({}, st), "msg": why}

    secs = 0 if body.get("immediately") else territory.upgrade_seconds(bid, XML_DIR)
    end = now_iso(0) if not secs else (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=secs)
    ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    if existing:
        existing["buildingId"] = bid
        existing["upgradeEndAt"] = end
    else:
        t["buildings"].append({"buildingId": bid, "posIndex": pos, "assignedUnits": [],
                               "upgradeEndAt": end, "lastTokenAt": "", "data": ""})
    save_state(st)
    admin_log(f"[territory] slot {pos} -> building {bid}, done at {end}")
    out = r_territory_fetch({}, st)
    out.update({"buildingCore": 0, "townHallCore": 0, "gold": st.get("gold", 0),
                "cash": st.get("cash", 0), "seasonalToken": 0, "refreshRet": None})
    return out


def r_territory_upgrade_now(body, st):
    return r_territory_build({**body, "immediately": True}, st)


def r_territory_remove(body, st):
    t = _terr(st)
    b = _terr_at(t, body.get("posIndex", -1))
    if b:
        t["buildings"].remove(b)
        save_state(st)
    return r_territory_fetch({}, st)


def r_territory_store(body, st):
    """Move a building off the plot into storage. Only <CanStore> ones may go."""
    t = _terr(st)
    b = _terr_at(t, body.get("posIndex", -1))
    if b and territory.can_store(b["buildingId"], XML_DIR):
        t["buildings"].remove(b)
        t["stored"].append({"buildingId": b["buildingId"], "count": 1})
        save_state(st)
    return r_territory_fetch({}, st)


def r_territory_unstore(body, st):
    t = _terr(st)
    bid = body_int(body.get("buildingId"), 0)
    pos = body_int(body.get("posIndex"), 0)
    row = next((s for s in t["stored"] if s["buildingId"] == bid), None)
    if row and _terr_at(t, pos) is None:
        row["count"] -= 1
        if row["count"] <= 0:
            t["stored"].remove(row)
        t["buildings"].append({"buildingId": bid, "posIndex": pos, "assignedUnits": [],
                               "upgradeEndAt": "", "lastTokenAt": "", "data": ""})
        save_state(st)
    return r_territory_fetch({}, st)


def r_territory_replace(body, st):
    """Swap two slots. Both may be empty, one, or neither."""
    t = _terr(st)
    a, b = _terr_at(t, body.get("posIndex", -1)), _terr_at(t, body.get("targetPosIndex", -1))
    if a is not None and b is not None:
        a["posIndex"], b["posIndex"] = b["posIndex"], a["posIndex"]
    elif a is not None and body.get("targetPosIndex") is not None:
        a["posIndex"] = body_int(body.get("targetPosIndex"), a["posIndex"])
    save_state(st)
    return r_territory_fetch({}, st)


def r_territory_collect_labor(body, st):
    """Bank the accrued labor. `amount` moves it into the spendable pool."""
    labor = _terr_labor(st)
    save_state(st)
    return {"labor": labor, "storedLabor": labor}


def r_territory_assign(body, st):
    """Assign heroes to a building, capped by its <MaxUnitAssignCount>.

    A hero may only work one building at a time, so assigning them here removes them
    from wherever they were - otherwise the same hero could stack the labor bonus on
    every building at once."""
    t = _terr(st)
    b = _terr_at(t, body.get("posIndex", -1))
    if b is None:
        return r_territory_fetch({}, st)
    units = body_list(body.get("unitIds") or body.get("units"), int)
    cap = territory.spec(b["buildingId"], "MaxUnitAssignCount", 0, XML_DIR)
    units = units[:cap]
    for other in t["buildings"]:
        if other is not b:
            other["assignedUnits"] = [u for u in other.get("assignedUnits", [])
                                      if u not in units]
    b["assignedUnits"] = units
    save_state(st)
    out = r_territory_fetch({}, st)
    out["assignedUnits"] = units
    return out


def r_territory_hunting_start(body, st):
    t = _terr(st)
    hid = body_int(body.get("huntingId"), 0)
    h = territory.huntings(XML_DIR).get(hid)
    if h is None:
        return {**r_territory_fetch({}, st), "msg": f"no such hunting {hid}"}
    t["hunting"] = [x for x in t["hunting"] if x["huntingId"] != hid]
    t["hunting"].append({"huntingId": hid, "specialCount": 0, "normalCount": 0,
                         "passApplied": False, "shortenPer": 0.0,
                         "startAt": now_iso(0), "endAt": now_iso(0)})
    save_state(st)
    return {**r_territory_fetch({}, st), "playerHuntingData": t["hunting"]}


def r_territory_hunting_end(body, st):
    """Finish a run and pay it out. Ending one that was never started pays nothing."""
    t = _terr(st)
    hid = body_int(body.get("huntingId"), 0)
    row = next((x for x in t["hunting"] if x["huntingId"] == hid), None)
    if row is None:
        return {**r_territory_fetch({}, st), "rewardListData": srv._reward_list_data([])}
    rewards = []
    for r in territory.hunting_rewards(hid, XML_DIR):
        if r["type"] in ("Gold", "Cash", "Heart", "Item"):
            srv._grant_reward(st, r["type"], r["id"], r["count"])
        rewards.append(r)
    t["hunting"].remove(row)
    save_state(st)
    admin_log(f"[territory] hunting {hid} -> {len(rewards)} rewards")
    return {**r_territory_fetch({}, st), "rewardListData": srv._reward_list_data(rewards)}


def r_territory_hunting_stop(body, st):
    t = _terr(st)
    hid = body_int(body.get("huntingId"), 0)
    t["hunting"] = [x for x in t["hunting"] if x["huntingId"] != hid]
    save_state(st)
    return r_territory_fetch({}, st)


def _trade_refused(st, why):
    """A refused buy, in the shape TerritoryBuyTradeShopItemResponseModel declares.

    Returning the whole-territory payload here sent `playerTradeShopItemData` while
    the buy model reads `tradeShopItemData`, so the panel took a refusal as an empty
    shop rather than a message."""
    return {"msg": why, "tradeShopItemData": _terr(st)["tradeShop"],
            "rewardListResponseData": srv._reward_list_data([]),
            "consumedListData": srv._reward_list_data([])}


def r_territory_trade_buy(body, st):
    """Buy from the trade shop. Priced in inventory items, per currency index."""
    _, items = territory.trade_shop(xml_dir=XML_DIR)
    uid = body_int(body.get("uid") if body.get("uid") is not None else body.get("itemId"), 0)
    item = next((i for i in items if i["id"] == uid or i["itemId"] == uid), None)
    if item is None:
        return _trade_refused(st, f"no such trade item {uid}")
    t = _terr(st)
    row = next((r for r in t["tradeShop"] if r["uid"] == item["id"]), None)
    bought = row["buyCount"] if row else 0
    if item["buyLimit"] >= 0 and bought >= item["buyLimit"]:
        return _trade_refused(st, "buy limit reached")
    currencies, _ = territory.trade_shop(xml_dir=XML_DIR)
    idx = body_int(body.get("currencyIndex"), item["prices"][0]["index"])
    price = next((p["price"] for p in item["prices"] if p["index"] == idx),
                 item["prices"][0]["price"])
    cur = next((c["id"] for c in currencies if c["index"] == idx), 0)
    if srv._item_count(st, cur) < price:
        return _trade_refused(st, f"not enough of item {cur}")
    srv._take_item(st, cur, price)
    srv._grant_reward(st, "Item", item["itemId"] or item["id"], 1)
    if row:
        row["buyCount"] = bought + 1
    else:
        t["tradeShop"].append({"uid": item["id"], "itemVersion": 0, "buyCount": 1})
    save_state(st)
    # TerritoryBuyTradeShopItemResponseModel declares rewardListResponseData +
    # consumedListData + tradeShopItemData, and nothing else. This used to spread the
    # whole-territory payload, which carries the same shop rows under the name
    # PlayerTerritoryResponseModel uses (`playerTradeShopItemData`) - so a buy
    # answered 200 with the purchase invisible: the panel read the names it declares
    # and found every one of them at its default.
    return {"rewardListResponseData": srv._reward_list_data(
                [{"type": "Item", "id": item["itemId"] or item["id"], "count": 1}]),
            "consumedListData": srv._reward_list_data(
                [{"type": "Item", "id": cur, "count": price}]),
            "tradeShopItemData": t["tradeShop"]}


def r_territory_equip_skin(body, st):
    t = _terr(st)
    sk, _ = territory.skins(CONTENT_GATE, XML_DIR)
    sid = body_int(body.get("skinId") or body.get("id"), 0)
    if sid in sk:
        t["equippedSkin"] = sid
        save_state(st)
    return r_territory_fetch({}, st)


def r_territory_stat_buffs(body, st):
    return {"statBuffPers": _terr(st).get("statBuffPers", [])}


def register(app, server_module):
    global srv
    srv = server_module
    srv.TERRITORY_OVERRIDES = handlers()


def handlers():
    return {
        "/territory": r_territory,
        "/territory/fetch": r_territory_fetch,
        "/territory/build": r_territory_build,
        "/territory/upgrade-building": r_territory_build,
        "/territory/upgrade-building-immediately": r_territory_upgrade_now,
        "/territory/remove-building": r_territory_remove,
        "/territory/store-building": r_territory_store,
        "/territory/unstore-building": r_territory_unstore,
        "/territory/replace-building": r_territory_replace,
        "/territory/refresh-building": r_territory_fetch,
        "/territory/collect-labor": r_territory_collect_labor,
        "/territory/recover-labor": r_territory_collect_labor,
        "/territory/assign-units": r_territory_assign,
        "/territory/swap-assigned-units": r_territory_assign,
        "/territory/level-sync/assign": r_territory_fetch,
        "/territory/level-sync/reset-timer": r_territory_fetch,
        "/territory/attendance-check": r_territory_fetch,
        "/territory/alchemy-new": r_territory_fetch,
        "/territory/restaurant/claim": r_territory_fetch,
        "/territory/fetch-stat-buffs": r_territory_stat_buffs,
        "/territory/equip-skin": r_territory_equip_skin,
        "/territory/hunting/start": r_territory_hunting_start,
        "/territory/hunting/end": r_territory_hunting_end,
        "/territory/hunting/stop": r_territory_hunting_stop,
        "/territory/hunting/fetch": r_territory_fetch,
        "/territory/hunting/complete-hunting-immediately": r_territory_hunting_end,
        "/territory/trade-shop/buy": r_territory_trade_buy,
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

    out = r_territory_fetch({}, st)
    assert out["buildingDatas"], "an empty plot cannot be built on"
    assert out["maxLabor"] > 0, "a 0 labor cap makes the first upgrade unreachable"
    assert out["lastLaborAt"], "a null date is one the client DateTime.Parses"

    # A slot sent as null or a string must not raise - every route resolves through _terr_at.
    assert _terr_at(_terr(st), None) is None
    assert _terr_at(_terr(st), "0") is not None, "a slot sent as a string must still resolve"

    # An unknown building is refused, and refusing must not charge.
    gold = st["gold"] = 10 ** 9
    _terr(st)["storedLabor"] = 10 ** 6
    assert "no such building" in r_territory_build({"posIndex": 99, "id": 999999999}, st)["msg"]
    assert st["gold"] == gold, "a refused build still took the money"

    # A hero may only work one building at a time.
    t = _terr(st)
    if len(t["buildings"]) >= 2:
        a, b = t["buildings"][0], t["buildings"][1]
        a["assignedUnits"] = [10260]
        r_territory_assign({"posIndex": b["posIndex"], "unitIds": [10260]}, st)
        assert 10260 not in a["assignedUnits"], "the same hero stacked on two buildings"

    # A buy must answer under the names the buy model declares, not the fetch ones.
    _, items = territory.trade_shop(xml_dir=XML_DIR)
    if items:
        it = items[0]
        out = r_territory_trade_buy({"uid": it["id"], "currencyIndex": it["prices"][0]["index"]}, st)
        if "msg" not in out:
            for k in ("rewardListResponseData", "tradeShopItemData"):
                assert k in out, f"a buy did not answer {k} - the panel reads it"

    paths = handlers()
    assert len(paths) == 27, f"{len(paths)} routes registered"
    assert all(callable(h) for h in paths.values())
    print(f"territory_routes self-check ok ({len(paths)} routes)")
