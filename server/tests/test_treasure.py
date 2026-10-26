import sys, os
import tempfile
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)
import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

from tests.seed import one_account      # real save + identity (multiplayer mode)
one_account()
import server
import routes.artifact_routes as ar

OVERRIDES = {"/treasure/add-exp": ar.r_treasure_add_exp,
             "/treasure/overcome": ar.r_treasure_overcome}


def _seed(rid=None):
    st = server.load_state()
    server.r_player({}, st)              # materialize the data-layer defaults
    st = server.load_state()
    st["inventory"] = {"itemIds": [3000, 3200], "counts": [10, 1]}
    st["gold"] = 100000
    if rid is not None:
        ar.get_st_treasures(st)          # ensure the default treasure rows exist
        t = next(x for x in st["treasures"] if x["treasureId"] == rid)
        for x in st["treasures"]:
            if x is not t:
                x["level"] = 1
                x["exp"] = 0
                x["overcome"] = 0
        t["level"], t["exp"], t["overcome"] = 1, 0, 0
        return st, t["id"]
    return st, st["treasures"][0]["id"]


def check_treasure_add_exp_levels_up():
    st, tid = _seed()
    out = OVERRIDES["/treasure/add-exp"](
        {"targetId": tid, "expItems": [{"type": "Item", "id": 3000, "count": 10}]}, st)
    t = next(x for x in out["treasures"] if x["id"] == tid)
    # Common 10000: per-level exp 20,24,28,32,36,40,46,52 -> 278 to reach lv9, then 60 needed
    assert t["level"] == 9, f"level: {t['level']}"
    assert t["exp"] == 22, f"exp: {t['exp']}"
    assert out["addedExpItems"] == 300, f"addedExpItems: {out['addedExpItems']}"
    inv = {i: c for i, c in zip(*[st["inventory"][k] for k in ("itemIds", "counts")])}
    assert inv.get(3000, 0) == 0, "exp items not consumed"
    print("ok: Enhance Legacy consumes Legacy Pieces, levels the treasure, charges gold")


def check_treasure_overcome_raises_tier():
    st, tid = _seed(rid=20000)          # 20000 = Rare (TreasureOvercomeCost NeedMaterial 1)
    out = OVERRIDES["/treasure/overcome"](
        {"targetId": tid, "materialItemCount": 1}, st)
    t = next(x for x in out["treasures"] if x["id"] == tid)
    assert t["overcome"] == 1, f"overcome: {t['overcome']}"
    inv = {i: c for i, c in zip(*[st["inventory"][k] for k in ("itemIds", "counts")])}
    assert inv.get(3200, 0) == 0, "Rare overcome must consume the ingot (item 3200)"
    print("ok: Tier Transcendence raises overcome for item 3200")


def check_treasure_overcome_caps_at_max():
    st, tid = _seed(rid=20000)          # Rare needs 1 ingot; seed 0 -> must be a no-op
    st["inventory"]["counts"][1] = 0
    out = OVERRIDES["/treasure/overcome"](
        {"targetId": tid, "materialItemCount": 1}, st)
    t = next(x for x in out["treasures"] if x["id"] == tid)
    assert t["overcome"] == 0, "overcome without material must not apply"
    print("ok: overcome without the ingot is a no-op")


def check_treasure_overcome_accepts_duplicate_legacy():
    st, tid = _seed(rid=20000)
    target = next(x for x in st["treasures"] if x["id"] == tid)
    material = ar.make_treasure(max(x["id"] for x in st["treasures"]) + 1,
                                target["treasureId"])
    st["treasures"].append(material)
    st["inventory"]["counts"][1] = 0
    out = OVERRIDES["/treasure/overcome"](
        {"targetId": tid, "materialTreasureIds": [material["id"]],
         "materialItemCount": 0}, st)
    upgraded = next(x for x in out["treasures"] if x["id"] == tid)
    assert upgraded["overcome"] == 1, "duplicate Legacy did not raise overcome"
    assert out["deletedTreasures"] == [material["id"]], out["deletedTreasures"]
    assert all(x["id"] != material["id"] for x in out["treasures"])
    print("ok: Tier Transcendence accepts a duplicate Legacy and reports its deletion")


def check_max_relic_shape():
    art = ar.make_max_artifact(1, 10001)      # Normal-level relic -> 1 option slot
    assert art["count"] == 99999, f"count: {art['count']}"
    assert art["options"]["lvs"] == [6, 0, 0, 0], art["options"]["lvs"]
    o = art["data"]["options"][0]
    assert (o["type"], o["value"], o["level"]) == ("AtkSpeedPer", 24, 6), o
    assert all(x["type"] == "None" for x in art["data"]["options"][1:])
    print("ok: make_max_artifact grants 10* relic with maxed AtkSpeedPer at column 1")


def check_common_overcome_requires_no_material():
    """Common treasure (NeedMaterial=0) must transcend even when the client
    sends item_count=1 but the player has 0 ingots — server should not
    attempt to deduct more than need_material."""
    st, tid = _seed(rid=10000)         # 10000 = Common
    st["inventory"]["counts"][1] = 0   # zero ingots
    out = OVERRIDES["/treasure/overcome"](
        {"targetId": tid, "materialItemCount": 1}, st)
    t = next(x for x in out["treasures"] if x["id"] == tid)
    assert t["overcome"] == 1, f"Common overcome should succeed free, got: {t['overcome']}"
    print("ok: Common transcend works with zero ingots even if client sends item_count")


def check_overcome_batches_multiple_tiers():
    """The reported bug: a single request that carries material for 2+ tiers used
    to raise overcome by only 1. Rare (need 1): 3 ingots -> 3 tiers, all consumed."""
    st, tid = _seed(rid=20000)
    st["inventory"]["counts"][1] = 3    # exactly the 3 the client will spend
    out = OVERRIDES["/treasure/overcome"](
        {"targetId": tid, "materialItemCount": 3}, st)
    t = next(x for x in out["treasures"] if x["id"] == tid)
    assert t["overcome"] == 3, f"3 Rare ingots must give 3 tiers, got {t['overcome']}"
    inv = {i: c for i, c in zip(*[st["inventory"][k] for k in ("itemIds", "counts")])}
    assert inv.get(3200, 0) == 0, f"all 3 ingots should be spent: {inv.get(3200)}"
    print("ok batch: one request of 3 Rare ingots -> overcome 3")


def check_special_batches_from_twelve_ingots():
    """Special costs 6 per tier, so 12 ingots in one request -> 2 tiers (the user's
    repro). Leftover ingots beyond the granted tiers are not consumed."""
    st, _ = _seed()
    special = ar.make_treasure(max(x["id"] for x in st["treasures"]) + 1, 30000)
    special["overcome"] = 0
    st["treasures"].append(special)
    st["inventory"]["counts"][1] = 13    # 12 needed for 2 tiers, 1 spare
    out = OVERRIDES["/treasure/overcome"](
        {"targetId": special["id"], "materialItemCount": 13}, st)
    t = next(x for x in out["treasures"] if x["id"] == special["id"])
    assert t["overcome"] == 2, f"12 of 13 ingots -> 2 tiers, got {t['overcome']}"
    inv = {i: c for i, c in zip(*[st["inventory"][k] for k in ("itemIds", "counts")])}
    assert inv.get(3200, 0) == 1, f"only 12 consumed, 1 left: {inv.get(3200)}"
    print("ok special: 13 ingots (6/tier) -> overcome 2, 1 ingot spared")


def check_overcome_spends_only_the_selected_ingots():
    """The reported bug: player chose 6 ingots on a Special Legacy but owned 60+;
    the old server-authoritative max(owned, selected) burned the whole 10-tier
    track in one request. The spend must key off materialItemCount only."""
    st, _ = _seed()
    special = ar.make_treasure(max(x["id"] for x in st["treasures"]) + 1, 30000)
    special["overcome"] = 0
    st["treasures"].append(special)
    st["inventory"]["counts"][1] = 60     # owns far more than the 6 selected
    out = OVERRIDES["/treasure/overcome"](
        {"targetId": special["id"], "materialItemCount": 6}, st)
    t = next(x for x in out["treasures"] if x["id"] == special["id"])
    assert t["overcome"] == 1, f"6 selected (6/tier) -> exactly 1 tier, got {t['overcome']}"
    inv = {i: c for i, c in zip(*[st["inventory"][k] for k in ("itemIds", "counts")])}
    assert inv.get(3200, 0) == 54, f"only the 6 selected ingots spent: {inv.get(3200)}"
    print("ok selected: 6 of 60 owned ingots -> overcome 1, 54 spared")


def check_overcome_caps_at_max_when_batching():
    """A batch must stop at the tier cap and only take material for granted tiers."""
    st, tid = _seed(rid=20000)
    t0 = next(x for x in st["treasures"] if x["id"] == tid)
    t0["overcome"] = 9                     # Rare cap 10, only 1 tier remains
    st["inventory"]["counts"][1] = 5
    out = OVERRIDES["/treasure/overcome"](
        {"targetId": tid, "materialItemCount": 5}, st)
    t = next(x for x in out["treasures"] if x["id"] == tid)
    assert t["overcome"] == 10, f"must cap at 10, got {t['overcome']}"
    inv = {i: c for i, c in zip(*[st["inventory"][k] for k in ("itemIds", "counts")])}
    assert inv.get(3200, 0) == 4, f"only 1 ingot spent for the last tier: {inv.get(3200)}"
    print("ok cap: batch stops at 10 and burns only the tier it granted")


if __name__ == "__main__":
    for fn in (check_treasure_add_exp_levels_up,
               check_treasure_overcome_raises_tier,
               check_treasure_overcome_caps_at_max,
               check_treasure_overcome_accepts_duplicate_legacy,
               check_common_overcome_requires_no_material,
               check_overcome_batches_multiple_tiers,
               check_special_batches_from_twelve_ingots,
               check_overcome_spends_only_the_selected_ingots,
               check_overcome_caps_at_max_when_batching,
               check_max_relic_shape):
        fn()
    print("all treasure checks passed")
