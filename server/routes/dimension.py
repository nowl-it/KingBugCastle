"""Dimension heroes: sync levels and overcome.

CardResponseModel carries a `dimensionUnit` sub-model that the server never filled,
so it arrived null for every hero. For an ordinary hero that is correct; for a
dimension hero (Units.xml `IsDimensionUnit`) it leaves the sync panel with no level,
no gauge and no next cost, and neither of its two routes did anything.

Two separate tracks, two separate currencies:

  sync level  0..DimensionLevelMax, paid in 차원의 잔향 (item 10010), the per-level
              price coming from DimensionLevelCost. Each level grants the stat step
              listed in that unit's own DimensionStat.
  overcome    0..OvercomeMax, paid in 차원 영웅 돌파권 (item 10020), one per step.

The cost table used to be dev-confirmed folklore (2.5k -> 54k, 250k total) because it
was not in any XML; it is in DimensionUnitConstants.xml now, so it is read, not typed.

    python3 dimension.py     # self-check
"""
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XML = ROOT / "xml_live"

REMNANT = 10010   # 차원의 잔향 - pays for sync levels
TICKET = 10020    # 차원 영웅 돌파권 - pays for overcome steps
CORE = 10000      # 차원의 핵

_cache = {}


def _consts(xml_dir):
    key = str(xml_dir)
    if key not in _cache:
        root = ET.parse(Path(xml_dir) / "DimensionUnitConstants.xml").getroot()
        _cache[key] = {
            "overcomeMax": int(root.findtext("OvercomeMax", 0)),
            "levelMax": int(root.findtext("DimensionLevelMax", 0)),
            "cost": {int(c.get("Level")): int(c.get("Value"))
                     for c in root.findall("DimensionLevelCost/Cost")},
        }
    return _cache[key]


def level_max(xml_dir=DEFAULT_XML):
    return _consts(xml_dir)["levelMax"]


def overcome_max(xml_dir=DEFAULT_XML):
    return _consts(xml_dir)["overcomeMax"]


def next_cost(level, xml_dir=DEFAULT_XML):
    """Remnants to reach level+1. 0 at the cap, which is what the panel shows as
    'maxed' - a missing level must not read as free."""
    return _consts(xml_dir)["cost"].get(int(level), 0)


def total_cost(xml_dir=DEFAULT_XML):
    return sum(_consts(xml_dir)["cost"].values())


_dimension_ids_cache = {}


def dimension_unit_ids(xml_dir=DEFAULT_XML):
    """Every unit flagged IsDimensionUnit, including the 200xxxxx enemy variants -
    the flag is what the panel keys on, not the id range."""
    key = str(xml_dir)
    if key not in _dimension_ids_cache:
        root = ET.parse(Path(xml_dir) / "Units.xml").getroot()
        _dimension_ids_cache[key] = {int(u.get("ID")) for u in root
                                     if u.get("ID") and (u.findtext("IsDimensionUnit") or "").strip().lower() == "true"}
    return _dimension_ids_cache[key]


def model(unit_id, level=0, gauge=0, overcome=0, xml_dir=DEFAULT_XML):
    """DimensionUnitModel, or None for a hero that has no dimension form."""
    if int(unit_id) not in dimension_unit_ids(xml_dir):
        return None
    return {"unitId": int(unit_id), "overcome": int(overcome),
            "dimensionLevel": int(level), "dimensionGauge": int(gauge),
            "dimensionNextLevelCost": next_cost(level, xml_dir)}


def _self_check():
    lmax, omax = _consts(DEFAULT_XML)["levelMax"], overcome_max()
    assert lmax > 0 and omax > 0
    costs = _consts(DEFAULT_XML)["cost"]
    assert sorted(costs) == list(range(lmax)), \
        f"cost table covers {sorted(costs)}, expected one entry per level below {lmax}"
    assert all(v > 0 for v in costs.values()), "a sync level is free"
    # Monotonic: a later level must never be cheaper, or the panel's 'next cost'
    # reads as a discount for waiting.
    assert all(costs[i] <= costs[i + 1] for i in range(lmax - 1)), "the cost curve dips"
    assert next_cost(lmax) == 0, "the level cap still charges"

    ids = dimension_unit_ids()
    assert ids, "no unit is flagged IsDimensionUnit"
    for uid in (10790, 10800, 10810):
        assert uid in ids, f"unit {uid} is a known dimension hero but is not flagged"
    assert model(10260) is None, "an ordinary hero was given a dimension model"
    m = model(10790, level=3)
    assert m["dimensionNextLevelCost"] == costs[3]

    print(f"ok: {len(ids)} dimension units, sync to {lmax} for {total_cost()} remnants, "
          f"overcome to {omax}")


if __name__ == "__main__":
    _self_check()
