"""Territory: plot, labor economy, assignment, hunting, trade shop.

Every /territory route answered an empty model, so the whole tab was dead.

Labor is the part worth guarding: it is computed from elapsed real time on read
rather than ticked, so the ways it breaks are silent - accruing past the cap, going
negative when a clock jumps backwards, or resetting whenever anything is read.
"""
import datetime, sys, tempfile
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import territory
from tests.seed import one_account
one_account()          # multiplayer needs a session; load_state() has no fallback
import server


def _fresh(gold=10 ** 7):
    st = server.load_state()
    st.pop("territory", None)
    st["inventory"] = {"itemIds": [], "counts": []}
    st["gold"] = gold
    server.save_state(st)
    return st


def check_starting_plot():
    out = server.r_territory_fetch({}, _fresh())
    assert out["buildingDatas"], "a new territory has no buildings"
    hall = out["buildingDatas"][0]
    assert territory.family(hall["buildingId"]) == territory.TOWN_HALL
    assert territory.level(hall["buildingId"]) >= 1, \
        "the plot starts at town hall level 0, which stores no labor and cannot progress"
    assert out["maxLabor"] > 0, "nowhere to store labor on a new plot"
    assert out["equippedSkin"] in out["skins"]
    print(f"ok start: town hall {hall['buildingId']}, cap {out['maxLabor']}, "
          f"{len(out['skins'])} skins")


def check_labor_accrues_and_caps():
    st = _fresh()
    server.r_territory_fetch({}, st)
    st = server.load_state()
    placed = st["territory"]["buildings"]
    rate = territory.labor_per_hour(placed, server.XML_DIR)
    cap = territory.max_stored_labor(placed, server.XML_DIR)
    assert rate > 0 and cap > 0

    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    hour_ago = (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    st["territory"]["lastLaborAt"] = hour_ago
    st["territory"]["storedLabor"] = 0
    server.save_state(st)
    got = server.r_territory_collect_labor({}, server.load_state())["labor"]
    assert abs(got - rate) <= 1, f"one hour gave {got} labor at {rate}/h"

    st = server.load_state()
    st["territory"]["lastLaborAt"] = (now - datetime.timedelta(days=400)
                                      ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    st["territory"]["storedLabor"] = 0
    server.save_state(st)
    assert server.r_territory_collect_labor({}, server.load_state())["labor"] == cap, \
        "labor accrued past the town hall cap"
    print(f"ok labor: {rate:.0f}/h, capped at {cap}")


def check_clock_going_backwards():
    """A device or host clock that jumps back must not produce negative labor."""
    st = _fresh()
    server.r_territory_fetch({}, st)
    st = server.load_state()
    future = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
              + datetime.timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    st["territory"]["lastLaborAt"] = future
    st["territory"]["storedLabor"] = 42
    server.save_state(st)
    got = server.r_territory_collect_labor({}, server.load_state())["labor"]
    assert got == 42, f"a future timestamp changed labor to {got}"
    print("ok clock: a future lastLaborAt leaves labor untouched")


def check_upgrade_charges_and_advances():
    st = _fresh()
    out = server.r_territory_fetch({}, st)
    before = out["buildingDatas"][0]["buildingId"]
    st = server.load_state()
    st["territory"]["storedLabor"] = 10 ** 6
    server.save_state(st)
    gold_before = server.load_state()["gold"]

    out = server.r_territory_build({"posIndex": 0}, server.load_state())
    assert not out.get("msg"), f"upgrade refused: {out.get('msg')}"
    after = out["buildingDatas"][0]["buildingId"]
    assert after == before + 1, f"building went {before} -> {after}"
    cost = territory.cost(after, server.XML_DIR)
    assert server.load_state()["gold"] == gold_before - cost["gold"], "gold was not charged"
    print(f"ok upgrade: {before} -> {after}, cost {cost}")


def check_upgrade_refused_without_funds():
    st = _fresh(gold=0)
    server.r_territory_fetch({}, st)
    st = server.load_state()
    st["territory"]["storedLabor"] = 0
    st["territory"]["lastLaborAt"] = server.now_iso(0)
    server.save_state(st)
    before = server.load_state()["territory"]["buildings"][0]["buildingId"]
    # Walk to a level that actually costs something - the first ones are free.
    target = next((b for b in sorted(territory.buildings(server.XML_DIR))
                   if territory.family(b) == territory.TOWN_HALL
                   and territory.cost(b, server.XML_DIR)["gold"] > 0), None)
    assert target, "no town hall level costs gold - this check is vacuous"
    st = server.load_state()
    st["territory"]["buildings"][0]["buildingId"] = target - 1
    server.save_state(st)
    out = server.r_territory_build({"posIndex": 0}, server.load_state())
    assert out.get("msg"), "an unaffordable upgrade was allowed"
    assert server.load_state()["territory"]["buildings"][0]["buildingId"] == target - 1, \
        "the building advanced despite the refusal"
    print(f"ok refusal: level {target} refused with no gold ({out['msg']})")


def check_assignment_is_exclusive():
    """A hero may work one building at a time, or the same one stacks its bonus
    on every building at once."""
    st = _fresh()
    server.r_territory_fetch({}, st)
    st = server.load_state()
    st["territory"]["buildings"].append(
        {"buildingId": st["territory"]["buildings"][0]["buildingId"], "posIndex": 1,
         "assignedUnits": [], "upgradeEndAt": "", "lastTokenAt": "", "data": ""})
    server.save_state(st)

    server.r_territory_assign({"posIndex": 0, "unitIds": [10260]}, server.load_state())
    server.r_territory_assign({"posIndex": 1, "unitIds": [10260]}, server.load_state())
    bs = server.load_state()["territory"]["buildings"]
    holders = [b["posIndex"] for b in bs if 10260 in b["assignedUnits"]]
    assert holders == [1], f"hero 10260 is assigned to slots {holders}"
    print("ok assignment: assigning a hero elsewhere releases the old slot")


def check_assignment_respects_cap():
    st = _fresh()
    server.r_territory_fetch({}, st)
    bid = server.load_state()["territory"]["buildings"][0]["buildingId"]
    cap = territory.spec(bid, "MaxUnitAssignCount", 0, server.XML_DIR)
    out = server.r_territory_assign({"posIndex": 0, "unitIds": list(range(1, cap + 5))},
                                    server.load_state())
    assert len(out["assignedUnits"]) == cap, \
        f"assigned {len(out['assignedUnits'])} units to a building capped at {cap}"
    print(f"ok cap: building {bid} holds {cap} unit(s)")


def check_hunting_pays_once():
    st = _fresh()
    server.r_territory_hunting_start({"huntingId": 10101}, server.load_state())
    assert server.load_state()["territory"]["hunting"], "the run was not recorded"
    out = server.r_territory_hunting_end({"huntingId": 10101}, server.load_state())
    got = out["rewardListData"]["rewardList"]
    assert got, "a finished hunting run paid nothing"
    st = server.load_state()
    for r in got:
        if r["type"] == "Item":
            assert server._item_count(st, r["id"]) == r["count"]
    again = server.r_territory_hunting_end({"huntingId": 10101}, server.load_state())
    assert not again["rewardListData"]["rewardList"], "a finished run paid out twice"
    print(f"ok hunting: {got} once, second end is a no-op")


def check_store_and_unstore():
    st = _fresh()
    server.r_territory_fetch({}, st)
    storable = next(b for b in sorted(territory.buildings(server.XML_DIR))
                    if territory.can_store(b, server.XML_DIR))
    st = server.load_state()
    st["territory"]["buildings"].append(
        {"buildingId": storable, "posIndex": 5, "assignedUnits": [],
         "upgradeEndAt": "", "lastTokenAt": "", "data": ""})
    server.save_state(st)

    out = server.r_territory_store({"posIndex": 5}, server.load_state())
    assert not any(b["posIndex"] == 5 for b in out["buildingDatas"]), "slot 5 still occupied"
    assert any(s["buildingId"] == storable for s in out["storedBuildings"]), "not stored"
    out = server.r_territory_unstore({"buildingId": storable, "posIndex": 7},
                                     server.load_state())
    assert any(b["posIndex"] == 7 for b in out["buildingDatas"]), "not placed back"
    assert not out["storedBuildings"], "still in storage after being placed"
    print(f"ok storage: building {storable} stored then placed at slot 7")


def check_trade_shop():
    currencies, items = territory.trade_shop(xml_dir=server.XML_DIR)
    item = items[0]
    idx = item["prices"][0]["index"]
    price = item["prices"][0]["price"]
    cur = next(c["id"] for c in currencies if c["index"] == idx)

    st = _fresh()
    out = server.r_territory_trade_buy({"uid": item["id"], "currencyIndex": idx}, st)
    assert out.get("msg"), "bought with no currency at all"

    st = server.load_state()
    server._grant_reward(st, "Item", cur, price)
    server.save_state(st)
    out = server.r_territory_trade_buy({"uid": item["id"], "currencyIndex": idx},
                                       server.load_state())
    assert not out.get("msg"), f"purchase refused: {out.get('msg')}"
    st = server.load_state()
    assert server._item_count(st, cur) == 0, "the currency was not spent"
    assert server._item_count(st, item["itemId"] or item["id"]) == 1, "nothing was granted"
    print(f"ok trade: item {item['id']} cost {price} of item {cur}")


def check_skin_must_exist():
    st = _fresh()
    server.r_territory_fetch({}, st)
    out = server.r_territory_equip_skin({"skinId": 999999}, server.load_state())
    assert out["equippedSkin"] != 999999, "equipped a skin that does not exist"
    real = out["skins"][-1]
    out = server.r_territory_equip_skin({"skinId": real}, server.load_state())
    assert out["equippedSkin"] == real
    print(f"ok skins: {real} equipped, 999999 refused")


if __name__ == "__main__":
    check_starting_plot()
    check_labor_accrues_and_caps()
    check_clock_going_backwards()
    check_upgrade_charges_and_advances()
    check_upgrade_refused_without_funds()
    check_assignment_is_exclusive()
    check_assignment_respects_cap()
    check_hunting_pays_once()
    check_store_and_unstore()
    check_trade_shop()
    check_skin_must_exist()
    print("\nall territory checks passed")
