"""Inventory routes: the player's item list and the three use-item handlers.

Plain items are spent and echoed back; reward boxes are opened server-side (the
client reads the result panel from addedRewardList, NOT rewardList - the box
panel's MoveNext passes the field at offset 0x38 to ShowResultPanel and all
Handle*Result calls); skin boxes name their own prize.
"""
from common import body_int
from state import save_state

srv = None      # live server module, injected via register()


def register(app, server_module):
    global srv
    srv = server_module
    srv.INVENTORY_OVERRIDES = handlers()


def handlers():
    return {
        "/player/getInventory": r_player_inventory,
        "/player/useInventory": r_use_inventory,
        "/player/use-reward-box-inventory-item": r_use_reward_box,
        "/player/use-skin-box-inventory-item": r_use_skin_box,
        "/player/receive-skin-box-alternate-reward": r_use_skin_box,
    }


def r_player_inventory(body, st):
    from routes.shop_routes import _get_gacha_key_ids
    inv = st.get("inventory", {"itemIds": [], "counts": []})
    gacha_keys = _get_gacha_key_ids()
    out_ids, out_counts = [], []
    for i, c in zip(inv.get("itemIds", []), inv.get("counts", [])):
        if i not in gacha_keys:
            out_ids.append(i)
            out_counts.append(c)
    return {"itemIds": out_ids, "counts": out_counts}


def r_use_inventory(body, st):
    """Consume a plain inventory item.

    InventoryItems.xml carries no effect payload (only tooltip/category metadata), and
    the client applies the visible effect itself off that metadata, so the server's job
    is to spend the item and hand back the authoritative inventory.
    ponytail: no per-item effect table; add one if an item turns out to need server state."""
    item_id = body.get("itemID") or body.get("itemId") or 0
    srv._take_item(st, item_id, body_int(body.get("count"), 1, lo=1))
    save_state(st)
    return {"playerHeart": st.get("heart", 0), "eventFlag": 0,
            "inventoryItems": srv._inventory_models(st)}


def r_use_reward_box(body, st):
    item_id = body.get("itemId") or body.get("itemID") or 0
    rewards = srv._open_reward_box(st, item_id, body.get("selectIdx"),
                                   body_int(body.get("count"), 1, lo=1))
    save_state(st)

    non_acc_rewards = [r for r in rewards if r.get("type") != "Accessory"]
    acc_rewards = [r for r in rewards if r.get("type") == "Accessory"]
    # The client reads the result panel from UseRewardBoxInventoryItemResponseModel.addedRewardList
    # (field at offset 0x38), NOT rewardList (offset 0x30).  The game's MoveNext state machine
    # passes [x21, #0x38] to ShowResultPanel and all Handle*Result calls.
    resp = {"rewardList": srv._reward_list_data([]),
            "addedRewardList": srv._reward_list_data(non_acc_rewards),
            "boxRewardInventory": {"id": item_id, "count": srv._item_count(st, item_id)}}

    if acc_rewards:
        new_ids = {r["id"] for r in acc_rewards}
        all_accs = st.get("accessories", [])
        resp["addedRewardList"]["accessoryResult"] = {
            "accessories": [a for a in all_accs if a.get("id") in new_ids],
            "deletedAccessories": [],
            "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "inventories": srv._inventory_models(st),
            "addedExpItems": 0,
        }

    if any(r.get("type") == "Artifact" for r in rewards):
        art_ids = [r["id"] for r in rewards if r.get("type") == "Artifact"]
        arts = srv.get_st_artifacts(st)
        new_arts = [a for a in arts if a.get("artifactId") in art_ids]

        resp["addedRewardList"]["artifactResult"] = {
            "results": new_arts,
            "polishItemAdded": False,
            "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "changeEquipped": False,
            "equippedArtifacts": srv._resolve_equipped_artifacts(st)
        }

    return resp


def r_use_skin_box(body, st):
    """Skin boxes name their own prize: the client sends the skin the player picked."""
    item_id = body.get("itemId") or body.get("itemID") or 0
    skin_id = body.get("skinId") or 0
    spent = srv._take_item(st, item_id, 1)
    if spent and skin_id:
        unit = str(skin_id // 1000)
        card = st.setdefault("cards", {}).get(unit)
        if card is not None and skin_id not in card.setdefault("skins", []):
            card["skins"].append(skin_id)
    save_state(st)
    return {"rewardList": srv._reward_list_data(
                [{"type": "Skin", "id": skin_id, "count": 1}] if spent else []),
            "skin": skin_id,
            "boxRewardInventory": {"id": item_id, "count": srv._item_count(st, item_id)}}