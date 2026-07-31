"""Reward boxes and inventory item use.

Before this existed, every box the game hands out (mail, missions, shops, events)
piled up in the inventory with no way to open it - /player/use-reward-box-inventory-item
fell through to the auto-generated empty model.

Runs against a temp DB: playerdb.DB_PATH is redirected BEFORE server is imported,
otherwise the checks create and mutate players in the live save.
"""
import os, sys, tempfile, random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
_tmp = tempfile.mkdtemp()
playerdb.DB_PATH = Path(_tmp) / "players.db"

import rewardbox
from tests.seed import one_account
one_account()          # multiplayer mode does not mint a save; give load_state() one
import server


def _fresh():
    st = server.load_state()
    st["inventory"] = {"itemIds": [], "counts": []}
    st["accessories"] = []
    st["gold"] = 0
    return st


def check_take():
    st = _fresh()
    server._grant_reward(st, "Item", 8000, 5)
    assert server._item_count(st, 8000) == 5
    assert server._take_item(st, 8000, 2) == 2
    assert server._item_count(st, 8000) == 3
    # Overspending clamps to what is there and clears the row instead of going negative.
    assert server._take_item(st, 8000, 99) == 3
    assert server._item_count(st, 8000) == 0
    assert 8000 not in st["inventory"]["itemIds"]
    assert server._take_item(st, 8000, 1) == 0
    print("ok take: grant, spend, clamp, row removal")


def check_fixable_box():
    """Box 8300 is Fixable with a single Min/Max InventoryItem reward."""
    st = _fresh()
    server._grant_reward(st, "Item", 8300, 1)
    rewards = server._open_reward_box(st, 8300)
    assert rewards, "fixable box 8300 returned nothing"
    assert server._item_count(st, 8300) == 0, "the box itself was not consumed"
    got = [r for r in rewards if r["type"] == "Item"]
    assert got, f"no item reward in {rewards}"
    for r in got:
        assert server._item_count(st, r["id"]) == r["count"], \
            f"item {r['id']}: inventory has {server._item_count(st, r['id'])}, reward said {r['count']}"
    print(f"ok fixable: box 8300 -> {[(r['id'], r['count']) for r in got]}")


def check_accessory_box():
    """Box 6000 is Fixable FixedAccessory - the accessories must land in state."""
    st = _fresh()
    server._grant_reward(st, "Item", 6000, 1)
    before = len(server.get_st_accessories(st))
    rewards = server._open_reward_box(st, 6000)
    accs = server.get_st_accessories(st)
    added = accs[before:]
    assert added, "no accessory was granted"
    assert len([r for r in rewards if r["type"] == "Accessory"]) == len(added)
    ids = [a["id"] for a in added]
    assert len(set(ids)) == len(ids), f"duplicate accessory instance ids {ids}"
    for a in added:
        assert a["data"]["mainStat"], f"accessory {a['id']} has no main stat"
        assert a["subStats"] and a["subStatScores"]
    print(f"ok accessory: box 6000 -> {len(added)} accessories, ids {ids}")


def check_ids_never_collide():
    """Opening two accessory boxes back to back must not reuse instance ids -
    a duplicate id makes equip target the wrong item."""
    st = _fresh()
    server._grant_reward(st, "Item", 6000, 2)
    server._open_reward_box(st, 6000)
    server._open_reward_box(st, 6000)
    ids = [a["id"] for a in server.get_st_accessories(st)]
    assert len(set(ids)) == len(ids), f"instance ids collided across two opens: {ids}"
    print(f"ok ids: {len(ids)} accessories, all distinct")


def check_selectable_box():
    """Box 5600 is Selectable RewardCount=1 - ticking everything still yields one."""
    st = _fresh()
    boxes = rewardbox.load_boxes(server.XML_DIR)
    box = boxes[5600]
    assert box["type"] == "Selectable"
    n = len(box["rewards"])
    server._grant_reward(st, "Item", 5600, 1)
    sel = [False] * n
    sel[3] = True
    rewards = server._open_reward_box(st, 5600, sel)
    assert len(rewards) == box["count"], f"got {len(rewards)}, RewardCount is {box['count']}"
    assert rewards[0]["id"] == int(box["rewards"][3]["ID"]), \
        f"selected index 3 ({box['rewards'][3]['ID']}) but got {rewards[0]['id']}"
    print(f"ok selectable: box 5600 idx 3 -> {rewards}")


def check_card_or_soul():
    """A CardOrSoul reward grants the hero if missing, soul if already owned."""
    st = _fresh()
    box = rewardbox.load_boxes(server.XML_DIR)[5600]
    unit = int(box["rewards"][0]["ID"])
    st.setdefault("cards", {}).pop(str(unit), None)
    server._grant_reward(st, "Item", 5600, 2)
    server._open_reward_box(st, 5600, [True] + [False] * (len(box["rewards"]) - 1))
    assert str(unit) in st["cards"], f"hero {unit} was not granted"
    soul_before = st["cards"][str(unit)].get("soul", 0)
    server._open_reward_box(st, 5600, [True] + [False] * (len(box["rewards"]) - 1))
    assert st["cards"][str(unit)]["soul"] > soul_before, \
        "second copy of an owned hero did not convert to soul"
    print(f"ok CardOrSoul: hero {unit} granted, then soul {soul_before} -> "
          f"{st['cards'][str(unit)]['soul']}")


def check_use_inventory():
    st = _fresh()
    server._grant_reward(st, "Item", 8000, 3)
    server.save_state(st)
    out = server.r_use_inventory({"itemID": 8000, "count": 1}, server.load_state())
    assert any(i["id"] == 8000 and i["count"] == 2 for i in out["inventoryItems"]), \
        f"inventoryItems did not reflect the spend: {out['inventoryItems']}"
    assert out["playerHeart"] == server.load_state().get("heart", 0)
    print("ok useInventory: item spent, inventory returned as List<InventoryItem>")


def check_missing_box_is_harmless():
    """An unknown box id must not raise - it is client-supplied."""
    st = _fresh()
    server._grant_reward(st, "Item", 999999, 1)
    assert server._open_reward_box(st, 999999) == []
    print("ok unknown box id: no reward, no exception")


def check_routes_registered():
    for p in ("/player/useInventory", "/player/use-reward-box-inventory-item",
              "/player/use-skin-box-inventory-item",
              "/player/receive-skin-box-alternate-reward"):
        assert p in server.OVERRIDES, f"{p} is not wired into OVERRIDES"
    print("ok routes: 4 use-item routes registered")


if __name__ == "__main__":
    random.seed(7)
    check_take()
    check_fixable_box()
    check_accessory_box()
    check_ids_never_collide()
    check_selectable_box()
    check_card_or_soul()
    check_use_inventory()
    check_missing_box_is_harmless()
    check_routes_registered()
    print("\nall reward-box checks passed")
