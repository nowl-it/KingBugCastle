"""The shop: listing, buying, and the nine routes that store the player's own choices.

`/shop` is both GET-list and POST-buy on one path (the same split `/accessory` uses).
respond() does not pass the verb down, so a request carrying an itemId is a purchase
and a bare one is a listing - self-correcting if the client ever POSTs just to refresh.

Nine more routes answered an empty model. None of them buy anything: they are where
the player's choices live - which treasures they want out of a box, which heroes they
pinned to a custom-pickup banner, and which purchases the store still owes them.

Prices, limits and rewards come from ShopItems.xml via shop.py; this is the state on
top. Uses the `register(app, srv)` pattern.

    python3 shop_routes.py      # self-check
"""
import shop
import gacha
from common import admin_log, body_int, body_list, next_reset_iso, now_iso
from config import CONTENT_GATE, STATIC_OVERRIDES, XML_DIR
from state import save_state

srv = None      # the live server module, set by register()

def _get_srv():
    global srv
    if srv is None:
        import sys
        srv = sys.modules.get("server")
    return srv

def _gacha_keys(st):
    """key item id -> total keys held. A gacha scroll's key item is the scroll
    itself (Gacha 2007's KeyItem is shop item 305; 300/301/302 key themselves),
    so the client's GachaKey.id is the shop item id, and every banner sharing the
    scroll (all pickup gachas share 305) counts the same entry."""
    return st.setdefault("gachaKeys", {})


def _gacha_keys_models(st):
    """Wire shape: [{id, count}] with int ids, as GachaKey deserializes."""
    return [{"id": int(k), "count": v} for k, v in sorted(_gacha_keys(st).items())]


def _build_gacha_ceil(gacha_el, st):
    """Build BuyResponseModel.gachaCeil dict: {poolId_or_gachaId: current_stack}."""
    gss = st.get("gachaStacks", {})
    ceil_dict = {str(k): int(v) for k, v in gss.items() if str(k).isdigit()}
    import xml.etree.ElementTree as ET
    import pathlib
    try:
        tree = ET.parse(pathlib.Path(XML_DIR) / "Gachas.xml")
        for g in tree.findall("Gacha"):
            gid = g.get("ID")
            for ce in g.findall("GachaCeil"):
                key = ce.get("Key")
                if key:
                    pool_id = ce.get("PoolID") or gid
                    if pool_id:
                        val_text = ce.text
                        target_attr = ce.get("Target")
                        limit = int(val_text) if (val_text and val_text.isdigit()) else (int(target_attr) if (target_attr and target_attr.isdigit()) else 100)
                        cur_stack = gss.get(key, gss.get(str(pool_id), gss.get(str(gid), 0)))
                        if limit > 0 and cur_stack >= limit:
                            cur_stack = cur_stack % limit
                        ceil_dict[key] = cur_stack
    except Exception as e:
        pass
    return ceil_dict


def _shop_buys(st):
    """itemId (as a string key, so it survives a JSON round-trip) -> times bought."""
    return st.setdefault("shopBuys", {})

def r_shop(body, st):
    """List the shop, or buy from it.

    GetShop and BuyShopItem share the /shop path (GET lists, POST buys) - the same
    split /accessory uses. Rather than depend on the verb, which respond() does not
    pass down, a request carrying an itemId or gachaId is a purchase/roll; a bare one is a listing.
    That is also self-correcting if the client ever POSTs /shop just to refresh."""
    base = dict(STATIC_OVERRIDES["/shop"])
    if body:
        admin_log(f"[shop DEBUG] body keys={list(body.keys())} body={body}")
    if body.get("itemId") or body.get("gachaId"):
        base.update(_shop_buy(body, st))
        save_state(st)
    base.update(shop.build(CONTENT_GATE, _shop_buys(st), now_iso(0), XML_DIR))
    base["nextRefreshTime"] = next_reset_iso(1)
    base["playerGold"] = st.get("gold", 0)
    base["playerCash"] = st.get("cash", 0)
    base["playerHeart"] = st.get("heart", 0)
    gss = st.get("gachaStacks", {})
    # Sync legacy pity with Ceil pool ID for old users
    if "5052" in gss and "231052" not in gss:
        gss["231052"] = gss["5052"]
    if "3999" in gss and "131000" not in gss:
        gss["131000"] = gss["3999"]
        
    base["gachaStacks"] = [{"gachaId": int(k), "stack": v}
                           for k, v in gss.items() if str(k).isdigit()]
    base["availableTimeLimitGachas"] = [8001, 2007, 5052]
    base["gachaKeys"] = [{"id": int(k), "count": v}
                         for k, v in st.get("gachaKeys", {}).items()]
    return base

def _shop_buy(body, st):
    """Charge for a shop item or gacha banner and grant it. Returns the BuyResponseModel-ish extras."""
    srv = _get_srv()
    item_id = body_int(body.get("itemId"), 0)
    gacha_id_req = body_int(body.get("gachaId"), 0)
    gacha_id = gacha_id_req
    amount = body_int(body.get("buyAmount"), 1, lo=1)
    
    el = shop.find(item_id, XML_DIR)
    gacha_el = gacha._get_gacha(gacha_id_req or item_id, XML_DIR) if (gacha_id_req or item_id) else None

    # Handle direct Gacha banner rolls (where item_id is not in ShopItems.xml)
    if el is None:
        if gacha_el is None:
            admin_log(f"[shop] refused: item {item_id} / gacha {gacha_id_req} is not found")
            return {"msg": "no such shop item or gacha", "soldOut": True}

        gacha_id = int(gacha_el.get("ID"))
        key_item = gacha_el.findtext("KeyItem")
        keys = _gacha_keys(st)
        keys_held = keys.get(str(key_item), 0) if key_item else 0
        use_gold = body.get("gachaUseGold", False)

        if not use_gold and keys_held >= amount:
            keys_held -= amount
            if key_item:
                keys[str(key_item)] = keys_held
            gacha_keys = [{"id": int(key_item), "count": keys_held}] if key_item else []
        else:
            cost_per_pull = 150 if gacha_id in (7000, 103, 201) else 100
            total_cost = cost_per_pull * amount
            if st.get("cash", 0) < total_cost:
                return {"msg": "not enough cash", "soldOut": False}
            st["cash"] = st.get("cash", 0) - total_cost
            gacha_keys = [{"id": int(key_item), "count": keys_held}] if key_item else []

        gachas_result = gacha.roll(gacha_id, amount, st, XML_DIR, item_id)
        for pull in gachas_result:
            # Grant main gacha pulls
            for rg in pull.get("gacha", []):
                rt = rg["type"]
                uid = rg["unitId"]
                if rt == "UnitExp":
                    rt = "UnitSoul"
                srv._grant_reward(st, rt, uid, rg.get("count", 1))
            
            # Grant rewardGacha pulls (which use originReward schema)
            for rg in pull.get("rewardGacha", []):
                origin = rg.get("originReward", {})
                if origin:
                    rt = origin.get("type")
                    uid = origin.get("id")
                    if rt == "UnitExp":
                        rt = "UnitSoul"
                    srv._grant_reward(st, rt, uid, origin.get("count", 1))

        gacha_stacks = []
        gss = st.get("gachaStacks", {})
        if gss:
            for gid_str, cnt in gss.items():
                if str(gid_str).isdigit():
                    gacha_stacks.append({"gachaId": int(gid_str), "stack": cnt})
        actual_gacha_id = gacha_id
        if gacha_id == 103:
            actual_gacha_id = 7000
        gacha_stack_single = {"gachaId": actual_gacha_id, "stack": gss.get(str(actual_gacha_id), 0)} if actual_gacha_id > 0 else None

        return {
            "gachaRewardResponseData": srv._reward_list_data([]),
            "inventoryItems": srv._inventory_models(st),
            "soldOut": False,
            "gachas": gachas_result,
            "gachaKeys": gacha_keys,
            "gachaStack": gacha_stack_single,
            "gachaStacks": gacha_stacks,
            "gachaCeil": _build_gacha_ceil(gacha_el, st),
            "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "playerHeart": st.get("heart", 0),
        }

    buys = _shop_buys(st)
    bought = buys.get(str(item_id), 0)
    limit = shop._int(el, "BuyLimit", -1)
    if limit >= 0 and bought + amount > limit:
        amount = max(0, limit - bought)
        if amount == 0:
            admin_log(f"[shop] refused: item {item_id} at its BuyLimit {limit}")
            return {"msg": "buy limit reached", "soldOut": True}

    kind, cur_id, unit_price = shop.price_of(el)
    cost = unit_price * amount
    if kind == "gold" and st.get("gold", 0) < cost:
        return {"msg": "not enough gold", "soldOut": False}
    if kind == "cash" and st.get("cash", 0) < cost:
        return {"msg": "not enough cash", "soldOut": False}
    if kind == "item" and srv._item_count(st, cur_id) < cost:
        return {"msg": f"not enough of item {cur_id}", "soldOut": False}

    if kind == "gold":
        st["gold"] = st.get("gold", 0) - cost
        srv.bump(st, "useGold", cost)
    elif kind == "cash":
        st["cash"] = st.get("cash", 0) - cost
    elif kind == "item":
        srv._take_item(st, cur_id, cost)
    shop_counter = {"ArenaShop": "useArenaShop", "ClanShop": "useClanShop",
                    "EventShop": "useEventShop"}.get(el.findtext("Type"))
    if shop_counter:
        srv.bump(st, shop_counter, amount)

    rewards = []
    for r in shop.rewards_of(el):
        r = {**r, "count": r["count"] * amount}
        # Artifact/Treasure/Skin are reported for the reward popup but not written
        # into state - the same policy the mail rewards follow.
        if r["type"] not in ("Artifact", "Treasure", "Skin"):
            srv._grant_reward(st, r["type"], r["id"], r["count"])
        rewards.append(r)
    buys[str(item_id)] = bought + amount
    admin_log(f"[shop] bought {item_id} x{amount} for {cost} {kind} -> {len(rewards)} rewards")

    # A gacha scroll (Type Gacha, no <Reward> rows - it is the banner's <KeyItem>
    # itself) grants the player a key for the pickup banners. The response MUST
    # carry the list: BuyGachaButtonGroup.HandleUnitGachaResult dereferences
    # ret.gachas without a null check, and an absent `gachas` made every scroll
    # purchase NRE (client froze with the buy modal up). gachaKeys carries the
    # TOTAL held after the buy - the client's SetGachaKey stores the value.
    gacha_keys = []
    gachas_result = []
    
    shop_type = el.findtext("Type") or ""
    if (shop_type.endswith("Gacha") or shop_type in ("Gacha", "NewUnitGacha", "ArtifactGacha", "TreasureGacha", "SkinGacha")) and not rewards:
        keys = _gacha_keys(st)
        
        # Check if this is a gacha roll. If they sent gachaId, or if it's a known gacha item,
        # we should roll. Actually, we'll just check if it's in Gachas.xml.
        is_roll = True
        gacha_id = body_int(body.get("gachaId"), item_id)
        # Some shop items might be pure scrolls and not actual banners.
        gacha_el = gacha._get_gacha(gacha_id, XML_DIR)

        # TreasureGacha / ArtifactGacha / SkinGacha: ShopItem IDs (370/371/etc) are not gacha IDs.
        # Find the default gacha for this KeyItem when the direct lookup fails.
        if gacha_el is None:
            key_item_id = el.findtext("KeyItem")
            candidates = [key_item_id, str(item_id)] if key_item_id else [str(item_id)]
            for k_id in candidates:
                if not k_id:
                    continue
                for gid, ge in gacha._GACHAS_CACHE.items():
                    if ge.findtext("KeyItem") == k_id and ge.get("Permanent") == "true":
                        gacha_id = gid
                        gacha_el = ge
                        break
                if gacha_el is not None:
                    break
                for gid, ge in gacha._GACHAS_CACHE.items():
                    if ge.findtext("KeyItem") == k_id:
                        gacha_id = gid
                        gacha_el = ge
                        break
                if gacha_el is not None:
                    break

            if gacha_el is None:
                stype = el.findtext("Type") or ""
                type_map = {
                    "TreasureGacha": 3999,
                    "ArtifactGacha": 350,
                    "SkinGacha": 7000,
                    "NewUnitGacha": 303,
                    "UnitGacha": 300,
                    "Gacha": 300,
                }
                if stype in type_map:
                    gacha_id = type_map[stype]
                    gacha_el = gacha._get_gacha(gacha_id, XML_DIR)
        
        if gacha_el is not None:
            # It's a roll!
            key_item = el.findtext("KeyItem") or gacha_el.findtext("KeyItem") or str(item_id)
            # If the user has enough keys, and they didn't explicitly request to use cash/gold, we use keys.
            # But wait, the client already checks if they have keys. If they have keys, it sends a request.
            # If they don't, it asks to use gems. In either case, the request comes here.
            # If the client sent `gachaUseGold` = true, or if they have no keys, we charge cash/gold.
            use_gold = body.get("gachaUseGold", False)
            keys_held = keys.get(str(key_item)) if key_item else keys.get(str(item_id))
            if keys_held is None:
                keys_held = 0
                
            used_keys = False
            if not use_gold and keys_held >= amount:
                # Use keys instead of the cost we just deducted!
                used_keys = True
                keys_held -= amount
                if key_item:
                    keys[str(key_item)] = keys_held
                else:
                    keys[str(item_id)] = keys_held
                gacha_keys = [{"id": int(key_item or item_id), "count": keys_held}]
                
                # Refund the cost we took earlier!
                if kind == "gold":
                    st["gold"] = st.get("gold", 0) + cost
                    srv.bump(st, "useGold", -cost)
                elif kind == "cash":
                    st["cash"] = st.get("cash", 0) + cost
                elif kind == "item":
                    st.setdefault("inventory", {})[str(cur_id)] = st["inventory"].get(str(cur_id), 0) + cost
                    
            if not used_keys:
                # Used cash/gold (which we already deducted)
                gacha_keys = [{"id": int(key_item or item_id), "count": keys_held}]
                
            # Now roll the gacha
            gachas_result = gacha.roll(gacha_id, amount, st, XML_DIR, item_id)
            
            # Grant the rewards to the player's state & populate gachaRewardResponseData
            for pull in gachas_result:
                # Add main gacha pulls
                for rg in pull.get("gacha", []):
                    rt = rg["type"]
                    uid = rg["unitId"]
                    cnt = rg.get("count", 1)
                    rewards.append({"type": rt, "id": uid, "count": cnt})
                    if rt == "UnitExp":
                        rt = "UnitSoul"
                    elif rt == "UnitSoulItem":
                        rt = "Item"
                        if item_id == 301 or item_id == 302:
                            uid = 201
                    srv._grant_reward(st, rt, uid, cnt)

                # Add rewardGacha pulls
                for rg in pull.get("rewardGacha", []):
                    origin = rg.get("originReward", {})
                    if origin:
                        rt = origin.get("type")
                        uid = origin.get("id")
                        cnt = origin.get("count", 1)
                        rewards.append({"type": rt, "id": uid, "count": cnt})
                        if rt == "UnitExp":
                            rt = "UnitSoul"
                        elif rt == "UnitSoulItem":
                            rt = "Item"
                            if item_id == 301 or item_id == 302:
                                uid = 201
                        elif item_id == 303:
                            uid = 202
                        else:
                            uid = 200
                    srv._grant_reward(st, rt, uid, cnt)
        else:
            # Not a banner roll, just buying a scroll (e.g. from event shop)
            total = keys.get(str(item_id), 0) + amount
            keys[str(item_id)] = total
            gacha_keys = [{"id": item_id, "count": total}]

    # Build gachaStack (single object for BuyResponseModel) and gachaStacks (list for ShopResponseModel)
    gss = st.get("gachaStacks", {})
    gacha_stacks = [{"gachaId": int(gid_str), "stack": cnt} for gid_str, cnt in gss.items() if str(gid_str).isdigit()]
    actual_gacha_id = gacha_id
    if gacha_id == 103:
        actual_gacha_id = 7000
    gacha_stack_single = {"gachaId": actual_gacha_id, "stack": gss.get(str(actual_gacha_id), 0)} if actual_gacha_id > 0 else None

    return {"gachaRewardResponseData": srv._reward_list_data(rewards),
            "inventoryItems": srv._inventory_models(st), "soldOut": False,
            "gachas": gachas_result, "gachaKeys": gacha_keys,
            "gachaStack": gacha_stack_single, "gachaStacks": gacha_stacks,
            "gachaCeil": _build_gacha_ceil(gacha_el, st),
            "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "playerHeart": st.get("heart", 0)}

def r_shop_refresh(body, st):
    """Refreshing the daily shop clears its per-item buy counts, which is what makes
    the daily items buyable again."""
    for sid in list(_shop_buys(st)):
        el = shop.find(sid, XML_DIR)
        if el is not None and el.findtext("Type") == "DailyShop":
            _shop_buys(st).pop(sid, None)
    save_state(st)
    return r_shop({}, st)


# --- Shop bookkeeping ---------------------------------------------------------
# Nine shop routes answered an empty model. None of them buy anything - they are the
# places where the player's own choices are stored: which treasures they want out of
# a box, which heroes they pinned to a custom-pickup banner, and which purchases the
# store still owes them.

# ResourceTreasure.Rarity. The wish list is keyed by it, and Newtonsoft writes an
# enum dictionary key as its name, so the keys have to be the names.
TREASURE_RARITIES = ["Common", "Rare", "Special"]

def r_treasure_wish_list(body, st):
    saved = st.get("treasureWishList", {})
    return {"wishList": {r: list(saved.get(r, [])) for r in TREASURE_RARITIES}}

def r_save_treasure_wish_list(body, st):
    """Store the wish list, keeping only ids that are really treasures - a wish for
    something that does not exist comes back as a blank row in the panel."""
    srv = _get_srv()
    sent = body.get("wishList")
    sent = sent if isinstance(sent, dict) else {}
    known = set(srv.ALL_TREASURE_IDS)
    out = {}
    for rarity in TREASURE_RARITIES:
        ids = sent.get(rarity) or sent.get(str(TREASURE_RARITIES.index(rarity) + 1))
        out[rarity] = [i for i in body_list(ids, int) if i in known]
    st["treasureWishList"] = out
    save_state(st)
    return {"wishList": out}

def r_custom_pickups(body, st):
    """The heroes or treasures pinned to a custom-pickup banner, per banner/gacha id."""
    banner = str(body.get("gachaId") or body.get("shopItemId") or body.get("id") or 0)
    return {"customPickups": list(st.get("customPickups", {}).get(banner, []))}

def r_save_custom_pickups(body, st):
    banner = str(body.get("gachaId") or body.get("shopItemId") or body.get("id") or 0)
    picks = [i for i in body_list(body.get("customPickups"), int) if i]
    st.setdefault("customPickups", {})[banner] = picks
    save_state(st)
    return {"customPickups": picks}

def r_shop_choice(body, st):
    """A package that lets the buyer choose - a hero, or which treasure a pickup
    ceiling pays out. The choice is recorded so the panel stops asking; the item
    itself is granted by the purchase route that precedes this."""
    key = "packageChoices" if "unitId" in body else "pickupChoices"
    choice = body_int(body.get("unitId") or body.get("treasureId"), 0)
    if choice:
        st.setdefault(key, {})[str(body.get("shopItemId", 0) or 0)] = choice
        save_state(st)
    return {}

def r_iap_restore_add(body, st):
    """A purchase the store charged for but the server has not yet delivered. There
    is no store here, so nothing is ever owed - but the list has to answer, because
    the client blocks the shop while it believes a restore is pending."""
    return {"restoreNeededIaps": st.get("restoreNeededIaps", [])}

def r_iap_restore_remove(body, st):
    pending = st.get("restoreNeededIaps", [])
    sku = body.get("productId") or body.get("sku")
    st["restoreNeededIaps"] = [p for p in pending if p != sku]
    save_state(st)
    return {"restoreNeededIaps": st["restoreNeededIaps"]}

def r_early_access(body, st):
    """Early-access test windows are dated in EarlyAccessModeInfos.xml and every one
    of them has closed, so there is nothing to enter. Reported as closed rather than
    left empty, which the panel reads as a failed request."""
    srv = _get_srv()
    return {"earlyAccessModeId": 0, "applied": False, "keyValues": srv._key_values(st)}



def register(app, server_module):
    global srv
    srv = server_module
    srv.SHOP_OVERRIDES = handlers()


def handlers():
    return {
        "/shop": r_shop,
        "/shop/iap": r_shop,
        "/shop/caniap": r_shop,
        "/shop/caniap_new": r_shop,
        "/shop/get-restore-needed-iaps": r_shop,
        "/shop/refreshDailyShop": r_shop_refresh,
        "/shop/get-treasure-wish-list": r_treasure_wish_list,
        "/shop/save-treasure-wish-list": r_save_treasure_wish_list,
        "/shop/check-treasure-wish-list-valid": r_treasure_wish_list,
        "/shop/load-custom-pickups": r_custom_pickups,
        "/shop/save-custom-pickups": r_save_custom_pickups,
        "/shop/choice-package-unit": r_shop_choice,
        "/shop/choice-treasure-pickup-ceil": r_shop_choice,
        "/shop/caniap-and-add-to-restore-needed-iaps": r_iap_restore_add,
        "/shop/remove-from-restore-needed-iaps": r_iap_restore_remove,
        "/player/early-access-mode": r_early_access,
        "/player/early-access-mode-code": r_early_access,
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

    out = r_shop({}, st)
    assert out["dailyItems"] and out["goldItems"], "an empty shop list is a blank store"
    assert out["nextRefreshTime"], "a null refresh time is a date the client parses"

    # An unknown item must be refused, not charged for.
    gold = st["gold"] = 999999
    assert _shop_buy({"itemId": 999999999}, st)["soldOut"] is True
    assert st["gold"] == gold, "a refused purchase still took the money"

    # The wish list keeps only real treasures: a wish for nothing is a blank row.
    saved = r_save_treasure_wish_list({"wishList": {"Common": [srv.ALL_TREASURE_IDS[0], 1]}}, st)
    assert saved["wishList"]["Common"] == [srv.ALL_TREASURE_IDS[0]], saved
    assert set(r_treasure_wish_list({}, st)["wishList"]) == set(TREASURE_RARITIES), \
        "Newtonsoft writes the enum key by name - the rarity names are the keys"

    paths = handlers()
    assert len(paths) == 17, f"{len(paths)} routes registered"
    assert all(callable(h) for h in paths.values())
    print(f"shop_routes self-check ok ({len(paths)} routes)")
