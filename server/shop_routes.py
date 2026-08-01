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
from common import admin_log, body_int, body_list, next_reset_iso, now_iso
from config import CONTENT_GATE, STATIC_OVERRIDES, XML_DIR
from state import save_state

srv = None      # the live server module, set by register()

def _gacha_keys(st):
    """key item id -> total keys held. A gacha scroll's key item is the scroll
    itself (Gacha 2007's KeyItem is shop item 305; 300/301/302 key themselves),
    so the client's GachaKey.id is the shop item id, and every banner sharing the
    scroll (all pickup gachas share 305) counts the same entry."""
    return st.setdefault("gachaKeys", {})


def _gacha_keys_models(st):
    """Wire shape: [{id, count}] with int ids, as GachaKey deserializes."""
    return [{"id": int(k), "count": v} for k, v in sorted(_gacha_keys(st).items())]


def _shop_buys(st):
    """itemId (as a string key, so it survives a JSON round-trip) -> times bought."""
    return st.setdefault("shopBuys", {})

def r_shop(body, st):
    """List the shop, or buy from it.

    GetShop and BuyShopItem share the /shop path (GET lists, POST buys) - the same
    split /accessory uses. Rather than depend on the verb, which respond() does not
    pass down, a request carrying an itemId is a purchase; a bare one is a listing.
    That is also self-correcting if the client ever POSTs /shop just to refresh."""
    base = dict(STATIC_OVERRIDES["/shop"])
    if body.get("itemId"):
        base.update(_shop_buy(body, st))
        save_state(st)
    base.update(shop.build(CONTENT_GATE, _shop_buys(st), now_iso(0), XML_DIR))
    base["nextRefreshTime"] = next_reset_iso(1)
    base["playerGold"] = st.get("gold", 0)
    base["playerCash"] = st.get("cash", 0)
    base["playerHeart"] = st.get("heart", 0)
    # gachaKeys in the static base is always [] - carry the player's real key counts
    # so the banner tabs keep showing what they own after the buy screen closes.
    base["gachaKeys"] = [{"id": int(k), "count": v}
                         for k, v in st.get("gachaKeys", {}).items()]
    return base

def _shop_buy(body, st):
    """Charge for a shop item and grant it. Returns the BuyResponseModel-ish extras.

    Real-money items are granted without charging: there is no store behind this
    server, so refusing them would make every package permanently unbuyable."""
    item_id = body_int(body.get("itemId"), 0)
    amount = body_int(body.get("buyAmount"), 1, lo=1)
    el = shop.find(item_id, XML_DIR)
    if el is None:
        admin_log(f"[shop] refused: item {item_id} is not in ShopItems.xml")
        return {"msg": "no such shop item", "soldOut": True}

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
    if el.findtext("Type") == "Gacha" and not rewards:
        keys = _gacha_keys(st)
        total = keys.get(str(item_id), 0) + amount
        keys[str(item_id)] = total
        gacha_keys = [{"id": item_id, "count": total}]
    return {"gachaRewardResponseData": srv._reward_list_data(rewards),
            "inventoryItems": srv._inventory_models(st), "soldOut": False,
            "gachas": [], "gachaKeys": gacha_keys}

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
    """The heroes pinned to a custom-pickup banner, per banner id."""
    banner = str(body.get("shopItemId", body.get("id", 0)) or 0)
    return {"customPickups": list(st.get("customPickups", {}).get(banner, []))}

def r_save_custom_pickups(body, st):
    banner = str(body.get("shopItemId", body.get("id", 0)) or 0)
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
