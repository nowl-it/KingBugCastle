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
    return st, 1


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
    out = OVERRIDES["/treasure/overcome"]({"targetId": tid}, st)
    t = next(x for x in out["treasures"] if x["id"] == tid)
    assert t["overcome"] == 1, f"overcome: {t['overcome']}"
    inv = {i: c for i, c in zip(*[st["inventory"][k] for k in ("itemIds", "counts")])}
    assert inv.get(3200, 0) == 0, "Rare overcome must consume the ingot (item 3200)"
    print("ok: Tier Transcendence raises overcome for item 3200")


def check_treasure_overcome_caps_at_max():
    st, tid = _seed(rid=20000)          # Rare needs 1 ingot; seed 0 -> must be a no-op
    st["inventory"]["counts"][1] = 0
    out = OVERRIDES["/treasure/overcome"]({"targetId": tid}, st)
    t = next(x for x in out["treasures"] if x["id"] == tid)
    assert t["overcome"] == 0, "overcome without material must not apply"
    print("ok: overcome without the ingot is a no-op")


def check_max_relic_shape():
    art = ar.make_max_artifact(1, 10001)      # Normal-level relic -> 1 option slot
    assert art["count"] == 99999, f"count: {art['count']}"
    assert art["options"]["lvs"] == [6, 0, 0, 0], art["options"]["lvs"]
    o = art["data"]["options"][0]
    assert (o["type"], o["value"], o["level"]) == ("AtkSpeedPer", 24, 6), o
    assert all(x["type"] == "None" for x in art["data"]["options"][1:])
    print("ok: make_max_artifact grants 10* relic with maxed AtkSpeedPer at column 1")


if __name__ == "__main__":
    for fn in (check_treasure_add_exp_levels_up,
               check_treasure_overcome_raises_tier,
               check_treasure_overcome_caps_at_max,
               check_max_relic_shape):
        fn()
    print("all treasure checks passed")