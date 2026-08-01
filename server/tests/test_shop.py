"""Shop listing and purchase.

/shop used to answer with every list empty, so every tab in the game was blank and
nothing could be bought. These checks cover the two ways that can silently come back:
the listing filtering everything out, and a purchase that grants without charging (or
charges without granting).

Temp DB: playerdb.DB_PATH is redirected BEFORE server is imported.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import shop
from tests.seed import one_account
one_account()          # multiplayer needs a session; load_state() has no fallback
import server


def _fresh(gold=0, cash=0):
    st = server.load_state()
    st["inventory"] = {"itemIds": [], "counts": []}
    st["shopBuys"] = {}
    st["gold"], st["cash"] = gold, cash
    server.save_state(st)
    return st


def _first_priced(bucket, kind):
    """The first listed item in `bucket` paid for with `kind`, with a real reward."""
    out = server.r_shop({}, server.load_state())
    for row in out[bucket]:
        el = shop.find(row["itemId"], server.XML_DIR)
        if shop.price_of(el)[0] == kind and shop.rewards_of(el):
            return row["itemId"], el
    raise AssertionError(f"no {kind}-priced item with a reward in {bucket}")


def check_listing_not_empty():
    out = server.r_shop({}, _fresh())
    filled = {k: len(v) for k, v in out.items() if isinstance(v, list) and v}
    assert out["dailyItems"], "the daily shop is empty"
    assert out["goldItems"], "the gold shop is empty"
    assert out["arenaShopItems"], "the arena shop is empty"
    assert out["nextRefreshTime"], "nextRefreshTime is unset - the client shows no timer"
    print(f"ok listing: {sum(filled.values())} rows across {len(filled)} buckets")


def check_gold_purchase_charges_and_grants():
    item_id, el = _first_priced("dailyItems", "gold")
    price = shop.price_of(el)[2]
    rewards = shop.rewards_of(el)
    st = _fresh(gold=price * 3)
    server.r_shop({"itemId": item_id}, st)
    st = server.load_state()
    assert st["gold"] == price * 2, f"gold went {price * 3} -> {st['gold']}, expected {price * 2}"
    for r in rewards:
        if r["type"] == "Item":
            assert server._item_count(st, r["id"]) == r["count"], \
                f"item {r['id']}: have {server._item_count(st, r['id'])}, expected {r['count']}"
    assert st["shopBuys"][str(item_id)] == 1
    print(f"ok gold buy: item {item_id} cost {price}, granted {len(rewards)} reward(s)")


def check_insufficient_funds_is_refused():
    item_id, el = _first_priced("dailyItems", "gold")
    price = shop.price_of(el)[2]
    st = _fresh(gold=price - 1)
    out = server.r_shop({"itemId": item_id}, st)
    st = server.load_state()
    assert st["gold"] == price - 1, f"gold changed on a refused purchase: {st['gold']}"
    assert not st.get("shopBuys"), f"a refused purchase still counted: {st.get('shopBuys')}"
    assert out.get("msg"), "a refused purchase returned no message"
    print(f"ok refusal: {price - 1} gold cannot buy a {price} item ({out['msg']})")


def check_buy_limit_holds():
    """BuyLimit is what stops a one-per-day item being bought forever.

    Searched across every bucket and every price kind, not just gold: the current
    season's gold-priced rows happen to be unlimited, and narrowing to them made this
    check silently skip - a limit that is never exercised is a limit that is not
    tested."""
    out = server.r_shop({}, _fresh())
    target = None
    for bucket, rows in out.items():
        if not isinstance(rows, list) or bucket == "gachaItems":
            continue
        for row in rows:
            if not isinstance(row, dict) or "itemId" not in row:
                continue
            el = shop.find(row["itemId"], server.XML_DIR)
            kind, cur, amt = shop.price_of(el)
            if 0 < shop._int(el, "BuyLimit", -1) <= 5 and kind in ("gold", "cash", "item"):
                target = (row["itemId"], el, kind, cur, amt)
                break
        if target:
            break
    assert target, "no limited, priced item anywhere in the shop - cannot test BuyLimit"
    item_id, el, kind, cur, unit = target
    limit = shop._int(el, "BuyLimit", -1)

    st = _fresh(gold=10 ** 9, cash=10 ** 9)
    if kind == "item":
        server._grant_reward(st, "Item", cur, unit * (limit + 5))
    server.save_state(st)

    for _ in range(limit):
        server.r_shop({"itemId": item_id}, server.load_state())
    st = server.load_state()
    assert st["shopBuys"][str(item_id)] == limit, \
        f"only {st['shopBuys'].get(str(item_id))} of {limit} purchases went through"
    purse = (st["gold"], st["cash"], server._item_count(st, cur) if kind == "item" else 0)

    out = server.r_shop({"itemId": item_id}, server.load_state())
    st = server.load_state()
    assert st["shopBuys"][str(item_id)] == limit, "bought past BuyLimit"
    assert (st["gold"], st["cash"],
            server._item_count(st, cur) if kind == "item" else 0) == purse, \
        "charged for a purchase past BuyLimit"
    assert out.get("soldOut"), "past BuyLimit but not reported soldOut"
    print(f"ok buy limit: item {item_id} ({kind}) capped at {limit}")


def check_refresh_clears_daily_only():
    daily_id, el = _first_priced("dailyItems", "gold")
    st = _fresh(gold=10 ** 9)
    server.r_shop({"itemId": daily_id}, st)
    st = server.load_state()
    st["shopBuys"]["999999"] = 5          # a non-daily row must survive the refresh
    server.save_state(st)
    server.r_shop_refresh({}, server.load_state())
    st = server.load_state()
    assert str(daily_id) not in st["shopBuys"], "refresh did not clear the daily buy count"
    assert st["shopBuys"].get("999999") == 5, "refresh cleared a non-daily buy count"
    print(f"ok refresh: daily item {daily_id} buyable again, other counts kept")


def check_unknown_item_is_harmless():
    st = _fresh(gold=1000)
    out = server.r_shop({"itemId": 999999999}, st)
    assert server.load_state()["gold"] == 1000, "charged for an item that does not exist"
    assert out.get("msg")
    print("ok unknown item: refused, nothing charged")


def check_no_free_lunch_on_token_shops():
    """A token-priced row must be denominated in a real inventory item, or buying it
    costs nothing and the arena/clan shops become infinite."""
    out = server.r_shop({}, _fresh())
    for bucket in ("arenaShopItems", "clanShopItems", "challengeShopItems",
                   "eventShopItems", "hardModeShopItems"):
        for row in out[bucket]:
            el = shop.find(row["itemId"], server.XML_DIR)
            kind, cur, amt = shop.price_of(el)
            assert kind != "free", f"{bucket} item {row['itemId']} is free"
            if kind == "item":
                assert cur > 0 and amt > 0, f"{bucket} item {row['itemId']}: {cur} x{amt}"
    print("ok token shops: every row has a real price")


def check_gacha_scroll_buy_does_not_freeze():
    """Buying a gacha scroll must answer with `gachas` present (never absent): the
    client's BuyGachaButtonGroup.HandleUnitGachaResult dereferences ret.gachas and
    NREs on a missing field, leaving the buy modal up and the whole UI frozen
    (observed live on v171.1.00). The scroll's own id is the GachaKey id the pickup
    banners count (every pickup gacha's <KeyItem> is scroll 305 itself), and the
    count must survive into the next shop listing."""
    out = server.r_shop({}, _fresh())
    item_id = None
    for row in out.get("gachaItems", []):
        el = shop.find(row["itemId"], server.XML_DIR)
        kind = shop.price_of(el)[0]
        if shop.rewards_of(el) == [] and el.findtext("Type") == "Gacha" and kind == "cash":
            item_id = row["itemId"]
            break
    assert item_id, "no cash-priced gacha-scroll row to buy"

    st = _fresh(cash=10 ** 6)
    out = server.r_shop({"itemId": item_id}, st)
    assert "gachas" in out, "buy response has no `gachas` - the client NREs on it"
    assert out["gachas"] == []
    keys = {k["id"]: k["count"] for k in out.get("gachaKeys", [])}
    assert keys.get(item_id) == 1, f"scroll buy did not grant key {item_id}: {keys}"

    st = server.load_state()
    assert st["gachaKeys"].get(str(item_id)) == 1, "key count did not persist"
    again = server.r_shop({}, server.load_state())
    keys = {k["id"]: k["count"] for k in again.get("gachaKeys", [])}
    assert keys.get(item_id) == 1, "persisted key missing from the next listing"
    print(f"ok gacha scroll: item {item_id} -> key {item_id}, gachas present, count carried")


if __name__ == "__main__":
    check_listing_not_empty()
    check_gold_purchase_charges_and_grants()
    check_insufficient_funds_is_refused()
    check_buy_limit_holds()
    check_refresh_clears_daily_only()
    check_unknown_item_is_harmless()
    check_no_free_lunch_on_token_shops()
    check_gacha_scroll_buy_does_not_freeze()
    print("\nall shop checks passed")
