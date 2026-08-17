"""Reward granting: apply a claimed reward to player state, open reward boxes,
and the inventory helpers the use-item routes share.

Leaf module: imports only leaf modules (config, common, missions, rewardbox).
Server-owned helpers (make_artifact/make_treasure, get_st_*, SEED) are read
through `srv`, which server.py sets after import - same indirection the route
modules use, so there is no import cycle.
"""
from config import XML_DIR
from common import now_iso
import missions
import rewardbox

srv = None      # live server module, set by server.py after import


def set_srv(server_module):
    global srv
    srv = server_module


def _inventory(st):
    return st.setdefault("inventory", {"itemIds": [], "counts": []})


def _inventory_models(st):
    """The inventory as List<InventoryItem> ({id, count}) - the shape the use-item
    responses return, as opposed to the parallel-array shape /player/getInventory uses."""
    from routes.shop_routes import _get_gacha_key_ids
    inv = _inventory(st)
    gacha_keys = _get_gacha_key_ids()
    return [{"id": i, "count": c}
            for i, c in zip(inv.get("itemIds", []), inv.get("counts", [])) if i not in gacha_keys]


def _item_count(st, item_id):
    inv = _inventory(st)
    ids = inv.get("itemIds", [])
    return inv.get("counts", [])[ids.index(item_id)] if item_id in ids else 0


def _take_item(st, item_id, n=1):
    """Spend n of an item. Returns how many were actually spent (0 if the player has none).

    The count is clamped rather than refused: the client sends what its own cached
    inventory believes, and a stale cache should not brick the item behind an error."""
    inv = _inventory(st)
    ids, cnts = inv.setdefault("itemIds", []), inv.setdefault("counts", [])
    if item_id not in ids:
        return 0
    i = ids.index(item_id)
    n = max(0, min(n, cnts[i]))
    cnts[i] -= n
    if cnts[i] <= 0:
        ids.pop(i)
        cnts.pop(i)
    return n


def _next_accessory_id(st):
    return max((a.get("id", 0) for a in srv.get_st_accessories(st)), default=0) + 1


def _open_reward_box(st, item_id, select_idx=None, times=1):
    """Open `times` copies of a reward box item, granting everything it yields.

    Returns the flat reward list for the client's popup. Accessories are appended to
    the player's accessory list here (they are fully specified, unlike artifacts, so
    they do not trip a client panel invariant); treasures stay display-only."""
    spent = _take_item(st, item_id, times)
    rewards = []
    for _ in range(spent):
        got, accs = rewardbox.open_box(item_id, select_idx, XML_DIR,
                                       next_id=_next_accessory_id(st), now=now_iso(0))
        if accs:
            srv.get_st_accessories(st).extend(accs)
        for r in got:
            rt = r["type"]
            if rt in ("Key", "CardOrSoul"):
                # Same tags Missions.xml uses, so share the resolver: a Key names a
                # ShopItem whose <KeyItem> is the real inventory row, and a CardOrSoul
                # converts to soul when the hero is already owned. It grants and returns
                # the reward already in RewardResponseData shape.
                rewards.append(_grant_mission_reward(st, r))
                continue
            if rt not in ("Accessory", "Treasure"):
                _grant_reward(st, rt, r["id"], r["count"])
            rewards.append(r)
    return rewards


# RewardResponseData.type is matched against a fixed vocabulary of strings - the same
# ones the master data uses (InventoryItem / Key / UnitSoulItem / CardSoul / Card /
# Gold / Cash / Heart / Artifact / Treasure / Skin ...), which the client compares in
# ResourceInventoryItem.GetByRewardTypeAndID. **There is no "Item"**: an unmatched type
# resolves to no ResourceInventoryItem, and the reward then renders with a wrong icon
# and a nonsense count in the results popup (what "Temple of Challenge Reward Chest
# gives x999 of the wrong thing" was). The server's own vocabulary is shorter and used
# by _grant_reward; translate at the wire boundary only, so state keys never move.
_WIRE_TYPE = {"Item": "InventoryItem", "Unit": "Card", "UnitSoul": "CardSoul"}


def _wire_rewards(rewards):
    return [{**r, "type": _WIRE_TYPE.get(r.get("type"), r.get("type"))} for r in rewards]


def _reward_list_data(rewards):
    return {"rewardList": _wire_rewards(rewards), "artifactResult": None,
            "treasureResult": None, "accessoryResult": None}


def _grant_mission_reward(st, r):
    """Apply one Missions.xml reward. Returns it in RewardResponseData shape.

    A `Key` reward names a ShopItem: normally its <KeyItem> inventory row, but the
    artifact boxes have no KeyItem and are counted in artifactBoxKey by box index
    instead, so those go to a different store entirely."""
    rt, rid, amt = r["type"], r["id"], r["count"]
    if rt == "Key":
        item = missions.key_item_for(rid, XML_DIR)
        if item:
            _grant_reward(st, "Item", item, amt)
            return {"type": "Item", "id": item, "count": amt}
        box = missions.artifact_box_for(rid, XML_DIR)
        if box is not None:
            keys = st.setdefault("artifactBoxKey", [0, 0, 0, 0])
            while len(keys) <= box:
                keys.append(0)
            keys[box] += amt
            return {"type": "ArtifactBoxKey", "id": box, "count": amt}
        return {"type": "Key", "id": rid, "count": amt}
    if rt == "CardOrSoul":
        rt = "UnitSoul" if str(rid) in st.get("cards", {}) else "Unit"
    if rt == "CardExp":
        card = st.setdefault("cards", {}).get(str(rid))
        if card is not None:
            card["exp"] = card.get("exp", 0) + amt
        return {"type": "CardExp", "id": rid, "count": amt}
    if rt == "FixedAccessory":
        acc = rewardbox.make_fixed_accessory(rid, _next_accessory_id(st), XML_DIR, now_iso(0))
        if acc:
            srv.get_st_accessories(st).append(acc)
            return {"type": "Accessory", "id": acc["id"], "count": 1}
        return {"type": "FixedAccessory", "id": rid, "count": amt}
    if rt in ("Gold", "Cash", "Heart", "Item", "Unit", "UnitSoul"):
        _grant_reward(st, rt, rid, amt)
    return {"type": rt, "id": rid, "count": amt}


def _grant_reward(st, rt, rid, amt):
    """Apply a claimed mail reward to player state. Currencies, inventory items, and hero
    souls/cards persist here; the client re-fetches /player, /player/getInventory and /card/all
    after a claim so the granted state appears. Treasure is granted as a real owned instance
    (same shape make_treasure builds for the default inventory). Artifact/Accessory stay
    display-only - they trip client panel invariants (see AGENTS.md ArtifactOptionUI crash);
    gift those as an Item reward box (InventoryItems.xml Type=RewardBoxInventory/
    InstantRewardBox) which the player opens.

    Returns True when a duplicate dimension hero was granted (caller should set upgrade=True)."""
    if rt == "Gold":
        st["gold"] = max(0, min(1_000_000_000, st.get("gold", 0) + amt))
    elif rt == "Cash":
        st["cash"] = max(0, min(1_000_000_000, st.get("cash", 0) + amt))
    elif rt == "Heart":
        st["heart"] = max(0, min(100_000, st.get("heart", 0) + amt))
    elif rt == "Item" and rid:
        inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
        ids = inv.setdefault("itemIds", [])
        cnts = inv.setdefault("counts", [])
        if rid in ids:
            cnts[ids.index(rid)] += (amt or 1)
        else:
            ids.append(rid)
            cnts.append(amt or 1)
    elif rt in ("Unit", "Card") and rid:
        cards = st.setdefault("cards", {})
        s_rid = str(rid)
        if s_rid not in cards:
            cards[s_rid] = {"unitId": rid, **srv.SEED["cardTemplate"]}
            # Dimension heroes start at overcome=1 (1 star) on first acquisition
            try:
                import xml.etree.ElementTree as ET
                tree = ET.parse(XML_DIR / "Units.xml")
                for u in tree.findall("Unit"):
                    if u.get("ID") == str(rid) and u.findtext("IsDimensionUnit") == "true":
                        cards[s_rid]["overcome"] = 1
                        break
            except Exception:
                pass
        else:
            c = cards[s_rid]
            is_dim = False
            try:
                import xml.etree.ElementTree as ET
                tree = ET.parse(XML_DIR / "Units.xml")
                for u in tree.findall("Unit"):
                    if u.get("ID") == str(rid) and u.findtext("IsDimensionUnit") == "true":
                        is_dim = True
                        break
            except Exception:
                pass
            if is_dim:
                c["overcome"] = c.get("overcome", 0) + (amt or 1)
                return True
            else:
                c["soul"] = c.get("soul", 0) + 150 * (amt or 1)
    elif rt == "UnitSoul" and rid:
        c = st.setdefault("cards", {}).setdefault(str(rid), {"unitId": rid, **srv.SEED["cardTemplate"]})
        c["soul"] = c.get("soul", 0) + amt
    elif rt == "Treasure" and rid:
        tr = srv.get_st_treasures(st)
        for _ in range(amt or 1):
            new_id = max((t.get("id", 0) for t in tr), default=0) + 1
            tr.append(srv.make_treasure(new_id, rid))
    elif rt == "Artifact" and rid:
        # Grant an artifact instance directly to the player's inventory starting at 0 stars (count=1)
        arts = st.setdefault("artifacts", [])
        existing = next((a for a in arts if a.get("artifactId") == rid), None)
        if existing:
            existing["count"] = existing.get("count", 1) + (amt or 1)
        else:
            new_id = max((t.get("id", 0) for t in arts), default=0) + 1
            art = srv.make_artifact(new_id, rid)
            art["count"] = amt or 1
            arts.append(art)
    elif rt == "SkinToken" and rid:
        # Skin tokens are inventory item 2001
        inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
        ids = inv.setdefault("itemIds", [])
        cnts = inv.setdefault("counts", [])
        if rid in ids:
            cnts[ids.index(rid)] += (amt or 1)
        else:
            ids.append(rid)
            cnts.append(amt or 1)
    elif rt == "Skin" and rid:
        skins = st.setdefault("skins", [])
        if rid not in skins:
            skins.append(rid)
    elif rt == "MapSkin" and rid:
        map_skins = st.setdefault("mapSkins", [])
        if rid not in map_skins:
            map_skins.append(rid)
    return False