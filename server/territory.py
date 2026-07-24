"""Territory: buildings, labor, unit assignment, hunting and the trade shop.

Every /territory route answered `{"territories": []}` or an empty model, so the whole
tab was dead - no plot, no labor, nothing to build.

**Building ids encode the level.** `10000`..`10012` is the town hall at levels 0-12,
`10100`..`10106` the next building, and so on: `id // 100 * 100` is the family and
`id % 100` the level. Upgrading is therefore `id + 1`, and a family's top level is the
highest id present. Entries use `Inherit` to carry a base body forward, one level deep.

**Labor** accrues in real time from every placed building's `<LaborGen>` (per hour),
capped by the town hall's `<MaxStoredLabor>`. It is computed from `lastLaborAt` on
read rather than ticked, so nothing depends on the server staying up.

Pure data and arithmetic; server.py owns the state writes.

    python3 territory.py     # self-check
"""
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_XML = ROOT / "xml_live"

TOWN_HALL = 10000          # family base of the town hall, which caps stored labor
_cache = {}


def _root(xml_dir, name):
    key = (str(xml_dir), name)
    if key not in _cache:
        _cache[key] = ET.parse(Path(xml_dir) / name).getroot()
    return _cache[key]


def buildings(xml_dir=DEFAULT_XML):
    """{id: element} with `Inherit` merged in, so every level is fully specified.

    A level entry only lists what changed from the one it inherits, so reading it
    directly makes level 2 of a building look like it generates no labor at all."""
    key = ("b", str(xml_dir))
    if key in _cache:
        return _cache[key]
    raw = {int(c.get("ID")): c for c in _root(xml_dir, "TerritoryBuildings.xml")
           if c.get("ID")}
    merged = {}
    for bid, el in raw.items():
        fields = {}
        parent = raw.get(int(el.get("Inherit"))) if el.get("Inherit") else None
        for src in (parent, el):
            if src is None:
                continue
            for child in src:
                fields[child.tag] = child
        merged[bid] = fields
    _cache[key] = merged
    return merged


def family(bid):
    return (bid // 100) * 100


def level(bid):
    return bid % 100


def max_level(bid, xml_dir=DEFAULT_XML):
    fam = family(bid)
    return max((level(b) for b in buildings(xml_dir) if family(b) == fam), default=0)


def _num(fields, tag, default=0):
    el = fields.get(tag)
    try:
        return int(float(el.text))
    except (AttributeError, TypeError, ValueError):
        return default


def spec(bid, tag, default=0, xml_dir=DEFAULT_XML):
    """A value from the building's <Specs> block (LaborGen, MaxUnitAssignCount, ...)."""
    fields = buildings(xml_dir).get(bid)
    if not fields:
        return default
    specs = fields.get("Specs")
    if specs is None:
        return default
    el = specs.find(tag)
    try:
        return int(float(el.text))
    except (AttributeError, TypeError, ValueError):
        return default


def cost(bid, xml_dir=DEFAULT_XML):
    """What placing or upgrading to this building level costs."""
    f = buildings(xml_dir).get(bid) or {}
    return {"labor": _num(f, "LaborPrice"), "gold": _num(f, "GoldPrice"),
            "core": _num(f, "CorePrice"), "townHallCore": _num(f, "TownHallCorePrice")}


def upgrade_seconds(bid, xml_dir=DEFAULT_XML):
    """<UpgradeTime> is HH:MM:SS, and can exceed 24h - so it is parsed by hand rather
    than through strptime, which would reject "30:00:00"."""
    el = (buildings(xml_dir).get(bid) or {}).get("UpgradeTime")
    if el is None or not el.text:
        return 0
    parts = [int(p) for p in el.text.strip().split(":")]
    while len(parts) < 3:
        parts.append(0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def can_store(bid, xml_dir=DEFAULT_XML):
    el = (buildings(xml_dir).get(bid) or {}).get("CanStore")
    return el is not None and (el.text or "").strip().lower() == "true"


def max_count(bid, xml_dir=DEFAULT_XML):
    return _num(buildings(xml_dir).get(bid) or {}, "MaxCount", 1)


def unlocked_by(bid, xml_dir=DEFAULT_XML):
    """Building families this level unlocks, from <Specs><UnlockedBuilding>."""
    fields = buildings(xml_dir).get(bid) or {}
    specs = fields.get("Specs")
    if specs is None:
        return []
    el = specs.find("UnlockedBuilding")
    if el is None or not el.text:
        return []
    return [int(x) for x in el.text.replace("\n", "").split(",") if x.strip().isdigit()]


def labor_per_hour(placed, xml_dir=DEFAULT_XML):
    """Total <LaborGen> across placed buildings, plus each one's assignment bonus.

    A unit assigned to a building with UnitAssignmentBenefit=AddLaborGenPer raises that
    building's output; <UnitAssignmentBenefit> names the stat and the benefit value
    lives on the level, so the percentage is read per building rather than assumed."""
    total = 0.0
    for b in placed:
        bid = b.get("buildingId", 0)
        gen = spec(bid, "LaborGen", 0, xml_dir)
        if not gen:
            continue
        fields = buildings(xml_dir).get(bid) or {}
        benefit = fields.get("UnitAssignmentBenefit")
        pct = 0
        if benefit is not None and (benefit.text or "").strip() == "AddLaborGenPer":
            pct = _num(fields, "UnitAssignmentBenefitValue", 10) * len(b.get("assignedUnits") or [])
        total += gen * (1 + pct / 100)
    return total


def max_stored_labor(placed, xml_dir=DEFAULT_XML):
    """The town hall's <MaxStoredLabor>. Without a town hall there is nowhere to store
    labor, so the cap is 0 and generation cannot silently accumulate forever."""
    hall = [b for b in placed if family(b.get("buildingId", 0)) == TOWN_HALL]
    if not hall:
        return 0
    best = max(b["buildingId"] for b in hall)
    return _num(buildings(xml_dir).get(best) or {}, "MaxStoredLabor", 0)


def accrued_labor(stored, last_at, placed, now=None, xml_dir=DEFAULT_XML):
    """Labor now, from what was stored plus real elapsed time. (labor, capped?)

    Computed on read instead of ticked, so it survives the server being down and does
    not need a scheduler."""
    cap = max_stored_labor(placed, xml_dir)
    if not last_at:
        return min(stored, cap), stored > cap
    try:
        then = datetime.datetime.strptime(last_at[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return min(stored, cap), False
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    hours = max(0.0, (now - then).total_seconds() / 3600)
    total = stored + labor_per_hour(placed, xml_dir) * hours
    return int(min(total, cap)), total > cap


def huntings(xml_dir=DEFAULT_XML):
    return {int(c.get("ID")): c for c in _root(xml_dir, "TerritoryHuntings.xml")
            if c.get("ID")}


# Hunting payout tags -> the inventory item they are counted in. Ids pinned by
# NameComment: 700 연금석 (alchemy stone), 8000 균열 장비 신비한 가루 (rift weapon dust),
# 2005 잠식 토큰 (the corruption token the hard-mode runs pay).
_HUNT_ITEMS = {"AlchemyStone": 700, "RiftWeaponDust": 8000, "HardModeToken": 2005}


def hunting_rewards(hid, xml_dir=DEFAULT_XML):
    """What one completed hunting run pays out.

    Two shapes in the file. The Invasion/HardMode/DimensionRift rows name each payout
    in its own tag. The 240 theme rows carry a bare `<RewardAmount>` with no
    `<MainReward>` naming what it is - it is the alchemy stone, which is the hunting
    system's own currency and the only payout those rows have; reading it as nothing
    would leave a majority of the hunting board handing out empty runs."""
    h = huntings(xml_dir).get(int(hid))
    if h is None:
        return []
    out = []
    for tag, item in _HUNT_ITEMS.items():
        el = h.find(tag)
        if el is not None and (el.text or "").strip():
            out.append({"type": "Item", "id": item, "count": int(float(el.text))})
    for tag in ("Gold", "Exp"):
        el = h.find(tag)
        if el is not None and (el.text or "").strip():
            out.append({"type": tag, "id": 0, "count": int(float(el.text))})
    if not out:
        amount = h.findtext("RewardAmount")
        if amount and amount.strip():
            out.append({"type": "Item", "id": _HUNT_ITEMS["AlchemyStone"],
                        "count": int(float(amount))})
    return out


def trade_shop(shop_id=None, xml_dir=DEFAULT_XML):
    """(currencies, items) for a trade shop. Prices are per currency index."""
    shops = {int(c.get("ID")): c for c in _root(xml_dir, "TerritoryTradeShops.xml")
             if c.get("ID")}
    if not shops:
        return [], []
    el = shops[shop_id if shop_id in shops else max(shops)]
    curr = [{"index": int(c.get("Index", 0)), "type": c.get("Type"),
             "id": int(c.get("ID", 0))}
            for c in (el.find("AvailableCurrencies") if el.find("AvailableCurrencies") is not None else [])]
    items = []
    _items = el.find("TradeItems")
    for t in (_items if _items is not None else []):
        prices = [{"index": int(p.get("Index", 0)), "price": int(p.get("Price", 0))}
                  for p in t.findall("Currency")]
        items.append({"type": t.get("Type"), "id": int(t.get("ID", 0)),
                      "itemId": int(t.get("ItemId", 0)),
                      "buyLimit": int(t.get("BuyLimit", -1)), "prices": prices})
    return curr, items


def skins(gate, xml_dir=DEFAULT_XML):
    """Territory skins the deployed client can render, and the default one."""
    out, default = [], 0
    for c in _root(xml_dir, "TerritorySkins.xml"):
        if not c.get("ID"):
            continue
        mv = c.findtext("MinVersion")
        if mv and int(mv) > gate:
            continue
        sid = int(c.get("ID"))
        out.append(sid)
        if (c.findtext("Default") or "").lower() == "true":
            default = sid
    return out, default or (out[0] if out else 0)


def starting_layout(xml_dir=DEFAULT_XML):
    """The plot a brand-new territory starts with: a level 1 town hall at slot 0.

    Level 0 is the "not built yet" placeholder - starting there leaves the player with
    a cap of 0 stored labor and no way to earn the labor a first upgrade costs."""
    return [{"buildingId": TOWN_HALL + 1, "posIndex": 0, "assignedUnits": [],
             "upgradeEndAt": "", "lastTokenAt": "", "data": ""}]


def _self_check():
    b = buildings()
    assert len(b) > 100, f"only {len(b)} territory buildings parsed"
    hall1 = TOWN_HALL + 1
    assert spec(hall1, "LaborGen") > 0, "the level 1 town hall generates no labor"
    # Inherit must be merged, or every level past the first looks empty.
    hall2 = TOWN_HALL + 2
    assert spec(hall2, "LaborGen") > 0, "Inherit was not merged - level 2 has no LaborGen"
    assert max_level(hall1) >= 10, f"town hall tops out at level {max_level(hall1)}"
    assert upgrade_seconds(hall1) == 0, "the level 1 town hall should be instant"
    assert any(upgrade_seconds(i) > 0 for i in b), "no building has an upgrade time"

    placed = starting_layout()
    cap = max_stored_labor(placed)
    assert cap > 0, "the starting layout stores no labor"
    rate = labor_per_hour(placed)
    assert rate > 0, "the starting layout generates no labor"

    # Labor accrues, and never past the cap.
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    then = (now - datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
    got, _ = accrued_labor(0, then, placed, now)
    assert got == int(min(rate * 2, cap)), f"2h of accrual gave {got}, rate is {rate}/h"
    far = (now - datetime.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S")
    assert accrued_labor(0, far, placed, now)[0] == cap, "labor accrued past the cap"
    # A clock that went backwards must not produce negative labor.
    future = (now + datetime.timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S")
    assert accrued_labor(10, future, placed, now)[0] == 10, "a future timestamp moved labor"
    # No town hall means no storage at all.
    assert max_stored_labor([]) == 0

    curr, items = trade_shop()
    assert curr and items, "the trade shop is empty"
    for it in items:
        assert it["prices"], f"trade item {it['id']} has no price"
        for p in it["prices"]:
            assert any(c["index"] == p["index"] for c in curr), \
                f"trade item {it['id']} priced in unknown currency index {p['index']}"
    sk, default = skins(171000)
    assert sk and default in sk, f"skins {sk}, default {default}"
    hs = huntings()
    assert hs, "no hunting missions parsed"
    silent = [h for h in hs if not hunting_rewards(h)]
    assert not silent, f"{len(silent)} hunting missions pay nothing: {silent[:5]}"
    paying = hs
    print(f"ok: {len(b)} buildings, town hall to level {max_level(hall1)}, "
          f"start {rate:.0f} labor/h cap {cap}, {len(items)} trade items, "
          f"{len(paying)}/{len(hs)} huntings pay out, skins {sk}")


if __name__ == "__main__":
    _self_check()
