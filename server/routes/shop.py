"""The shop, read out of ShopItems.xml.

`/shop` used to answer with every list empty, so every shop tab in the game was
blank and nothing could be bought. ShopItems.xml has 4477 entries covering every
shop the game has ever run, so the work is filtering, not inventing: keep what the
deployed client can render (MinVersion/MaxVersion) and, for the token shops that are
re-cut every season, keep only the newest season.

Pure data - parsing, filtering, pricing, and the reward list. Nothing here touches
player state; server.py spends and grants through its own `_take_item`/`_grant_reward`
so there is one place where inventory changes.

    python3 shop.py     # self-check + a per-bucket summary
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XML = ROOT / "xml_live"

# ShopItem <Type> -> the ShopResponseModel list it belongs in. Types not listed here
# are shops this server does not surface (per-package IAP variants, god-skin sale
# tiers, roguelike DLC): they are cash-only bundles whose contents are not expressible
# as a reward list, so listing them would show a buy button that cannot pay out.
BUCKET = {
    "DailyShop": "dailyItems",
    "Gold": "goldItems",
    "Cash": "cashItems", "CashMine": "cashItems", "Heart": "cashItems",
    "Gacha": "gachaItems", "NewUnitGacha": "gachaItems",
    "ArenaShop": "arenaShopItems",
    "ClanShop": "clanShopItems",
    "EventShop": "eventShopItems",
    "SpecialSeasonalEventShop": "specialEventShopItems",
    "HardModeShop": "hardModeShopItems",
    "ChallengeShop": "challengeShopItems",
    "SkinReturnShop": "skinReturnShopItems",
}

# Which inventory item a shop's <TokenPrice> is denominated in. Confirmed from
# InventoryItems.xml NameComments: 2002 아레나(arena), 2003 연맹전(clan),
# 2004 이벤트(event), 2005 잠식(corruption - HardModeShop gates on
# InvasionDifficultyLimit and the packages that grant HardModeToken are 잠식 packs),
# 2014 챌린지(challenge), 2001 스킨(skin).
TOKEN_ITEM = {
    "ArenaShop": 2002,
    "ClanShop": 2003,
    "EventShop": 2004,
    "SpecialSeasonalEventShop": 2004,
    "HardModeShop": 2005,
    "ChallengeShop": 2014,
    "SkinReturnShop": 2001,
}

# Reward fields that are really "n of this inventory item". The ids are pinned by
# NameComment: 110 경험의 서 is the exp book UnitExpCount is counted in, 130 왕의 증표
# is the soul emblem, and the token ids match TOKEN_ITEM above.
ITEM_REWARD_FIELDS = {
    "UnitExpCount": 110,
    "SoulItemCount": 130,
    "SkinToken": 2001,
    "SeasonalEventToken": 2004,
    "HardModeToken": 2005,
}

_SEASON = re.compile(r"^(.+)_S(\d+)$")
_cache = {}


def _int(el, tag, default=0):
    v = el.findtext(tag)
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def load_items(xml_dir=DEFAULT_XML):
    """Every ShopItem as {id: element}, unfiltered."""
    key = str(xml_dir)
    if key not in _cache:
        root = ET.parse(Path(xml_dir) / "ShopItems.xml").getroot()
        _cache[key] = {int(c.get("ID")): c for c in root if c.get("ID")}
    return _cache[key]


def latest_seasons(items):
    """Newest season number per EventType prefix.

    The token shops are re-cut every season and every past cut is still in the file -
    ArenaShop alone has 70 of them. Listing all of them puts a decade of dead items in
    front of the player, so only the highest season survives. Non-seasonal EventTypes
    (CHALLENGE, HARD_MODE2) have no number and are always kept."""
    out = {}
    for el in items.values():
        m = _SEASON.match(el.findtext("EventType") or "")
        if m:
            out[m.group(1)] = max(out.get(m.group(1), 0), int(m.group(2)))
    return out


def is_current(el, gate, seasons):
    """Whether this entry belongs in the shop the deployed client sees."""
    if (el.findtext("HideInShop") or "").lower() == "true":
        return False
    if (el.findtext("Visible") or "").lower() == "false":
        return False
    min_v, max_v = el.findtext("MinVersion"), el.findtext("MaxVersion")
    if min_v and int(min_v) > gate:
        return False
    if max_v and int(max_v) < gate:
        return False
    m = _SEASON.match(el.findtext("EventType") or "")
    return not m or int(m.group(2)) == seasons.get(m.group(1))


def price_of(el):
    """(kind, item_id, amount). kind is gold/cash/item/money/free.

    `money` is a real-money IAP: there is no store behind this server, so the caller
    grants it without charging rather than refusing the purchase outright."""
    typ = el.findtext("Type") or ""
    if el.find("Price") is not None:
        return "gold", 0, _int(el, "Price")
    if el.find("CashPrice") is not None:
        return "cash", 0, _int(el, "CashPrice")
    if el.find("TokenPrice") is not None:
        return "item", TOKEN_ITEM.get(typ, 2004), _int(el, "TokenPrice")
    ip = el.find("InventoryItemPrice")
    if ip is not None:
        return "item", int(ip.get("ID", 0)), int(ip.get("Count", 1))
    if el.find("SoulItemPrice") is not None:
        return "item", ITEM_REWARD_FIELDS["SoulItemCount"], _int(el, "SoulItemPrice")
    if el.find("MoneyPrice") is not None or el.findtext("ProductID"):
        return "money", 0, _int(el, "MoneyPrice")
    return "free", 0, 0


def rewards_of(el, st=None):
    """What buying this pays out, as {type, id, count} in _grant_reward's vocabulary.

    Artifacts, treasures and skins are reported so the client's reward popup is
    correct, but server.py does not write them into state - the same policy the mail
    rewards follow, because a half-specified artifact trips ArtifactOptionUI."""
    out = []
    for inv in el.findall("InventoryItem"):
        out.append({"type": "Item", "id": int(inv.get("ID", 0)),
                    "count": int(inv.get("Count", 1))})
    for field, item_id in ITEM_REWARD_FIELDS.items():
        n = _int(el, field)
        if n:
            out.append({"type": "Item", "id": item_id, "count": n})
    if el.find("KeyID") is not None:
        out.append({"type": "Item", "id": _int(el, "KeyID"),
                    "count": _int(el, "KeyCount", 1) or 1})
    if el.find("BoxKey") is not None:
        out.append({"type": "Item", "id": _int(el, "BoxKey"), "count": 1})
    for field, rtype in (("Gold", "Gold"), ("Cash", "Cash"), ("Heart", "Heart")):
        n = _int(el, field)
        if n:
            if rtype == "Gold" and st is not None:
                inc_per = _int(el, "IncreaseGoldByClearedChapterPer", 0)
                if inc_per > 0:
                    cleared = int(st.get("bestClearedTheme", 0) or 0)
                    if cleared > 0:
                        n = int(n * ((1.0 + inc_per / 100.0) ** cleared))
            out.append({"type": rtype, "id": 0, "count": n})
    # UnitID = -1 marks a package whose hero the player picks later, through
    # /shop/choice-package-unit. It is a placeholder, not an id, so it grants nothing
    # at purchase time.
    if _int(el, "UnitID") > 0:
        out.append({"type": "Unit", "id": _int(el, "UnitID"), "count": 1})
    for field, rtype in (("ArtifactId", "Artifact"), ("Skin", "Skin"),
                         ("SkinID", "Skin"), ("TerritorySkin", "Skin"),
                         ("LoginSkin", "Skin")):
        n = _int(el, field)
        if n > 0:
            cnt = _int(el, "ArtifactCount", 1) if rtype == "Artifact" else 1
            out.append({"type": rtype, "id": n, "count": cnt or 1})
    # Plural forms are parallel comma lists, e.g. ArtifactIds="10,20" ArtifactCounts="1,2".
    for ids_tag, cnt_tag, rtype in (("ArtifactIds", "ArtifactCounts", "Artifact"),
                                    ("TreasureIds", "TreasureCounts", "Treasure")):
        ids = (el.findtext(ids_tag) or "").split(",")
        cnts = (el.findtext(cnt_tag) or "").split(",")
        for i, s in enumerate(ids):
            s = s.strip()
            if not s.isdigit():
                continue
            c = cnts[i].strip() if i < len(cnts) else "1"
            out.append({"type": rtype, "id": int(s), "count": int(c) if c.isdigit() else 1})
    return out


def to_model(el, buy_count=0, now=""):
    """A ShopItemModel row. BuyLimit -1 means unlimited; 0 buys left is soldOut."""
    limit = _int(el, "BuyLimit", -1)
    return {
        "itemId": int(el.get("ID")),
        "unitId": _int(el, "UnitID"),
        "count": _int(el, "PackageItemCount", 1) or 1,
        "price": price_of(el)[2],
        "discount": False,
        "free": price_of(el)[0] == "free",
        "soldOut": limit >= 0 and buy_count >= limit,
        "doubleChance": False,
        "createdAt": now,
        "untilAt": el.findtext("EndAt") or "",
        "buyCount": buy_count,
        "monthlyBuyCount": buy_count,
    }


def build(gate, buy_counts=None, now="", xml_dir=DEFAULT_XML):
    """Every bucket of ShopResponseModel, filled from the master data."""
    items = load_items(xml_dir)
    seasons = latest_seasons(items)
    buy_counts = buy_counts or {}
    out = {name: [] for name in set(BUCKET.values())}
    for sid, el in sorted(items.items()):
        bucket = BUCKET.get(el.findtext("Type"))
        if not bucket or not is_current(el, gate, seasons):
            continue
        # Skip items that pay out nothing (CashMine 9100-9108, bare Heart 700, stale
        # EventShop rows...). Client ShopItem.Init crashes on their empty reward list
        # (get_Item(0) with Count==0 -> ArgumentOutOfRangeException, v172.0.01
        # lobby-black-screen bug). gachaItems is exempt: a summon's payout comes from
        # Gachas.xml Results, so an empty row there is correct.
        if bucket != "gachaItems" and not rewards_of(el):
            continue
        out[bucket].append(to_model(el, buy_counts.get(str(sid), 0), now))
    for rows in out.values():
        rows.sort(key=lambda r: r["itemId"])
    return out


def find(item_id, xml_dir=DEFAULT_XML):
    return load_items(xml_dir).get(int(item_id))


def _self_check():
    items = load_items()
    assert len(items) > 4000, f"only {len(items)} shop items parsed"
    seasons = latest_seasons(items)
    assert seasons.get("ARENA") and seasons.get("CLAN"), f"no seasonal shops found: {seasons}"
    buckets = build(171000)
    assert buckets["dailyItems"], "the daily shop came out empty"
    assert buckets["goldItems"], "the gold shop came out empty"
    # The season filter is the whole point: without it ArenaShop alone lists 1386.
    assert len(buckets["arenaShopItems"]) < 60, \
        f"season filter did nothing - {len(buckets['arenaShopItems'])} arena items"
    total = sum(len(v) for v in buckets.values())
    for name, rows in buckets.items():
        for r in rows:
            el = items[r["itemId"]]
            kind, cur, amt = price_of(el)
            assert kind in ("gold", "cash", "item", "money", "free"), f"{r['itemId']}: {kind}"
            assert amt >= 0, f"{r['itemId']}: negative price {amt}"
            if kind == "item":
                assert cur, f"{r['itemId']} ({el.findtext('Type')}) priced in item 0"
            rw = rewards_of(el)
            for x in rw:
                assert x["count"] >= 1, f"{r['itemId']}: reward {x} has count < 1"
                assert x["id"] >= 0
    # Nothing should be listed that pays out nothing at all - that is a buy button
    # with no effect, which is worse than the tab being empty. It is also a client
    # crash: ShopItem.Init indexes List.get_Item(0) on the reward list, so an empty
    # one throws ArgumentOutOfRangeException (v172.0.01 lobby-black-screen bug).
    # build() skips them; this asserts the invariant across every non-gacha bucket.
    # gachaItems is exempt: a summon's payout is rolled from Gachas.xml Results, not
    # fixed on the shop row, so an empty reward list there is correct. (gacha.py rolls it.)
    empty = [r["itemId"] for n, rows in buckets.items()
             for r in rows if n != "gachaItems" and not rewards_of(items[r["itemId"]])]
    assert not empty, f"listed items with no reward: {empty}"
    # A version-gated item must actually be excluded.
    gated = [i for i, el in items.items()
             if el.findtext("MinVersion") and int(el.findtext("MinVersion")) > 171000]
    listed = {r["itemId"] for rows in buckets.values() for r in rows}
    leaked = [i for i in gated if i in listed]
    assert not leaked, f"unreleased shop items leaked past the gate: {leaked[:5]}"
    print(f"ok: {len(items)} shop items -> {total} listed at gate 171000; "
          f"seasons {dict(sorted(seasons.items()))}")
    for name in sorted(buckets):
        if buckets[name]:
            print(f"   {name:24s} {len(buckets[name]):3d}")


if __name__ == "__main__":
    _self_check()
