"""Focused Blacksmith contract: craft, merge, and polish change durable relic state."""
import pathlib
import sys
import tempfile

_SERVER = pathlib.Path(__file__).resolve().parent.parent
for _path in (_SERVER, _SERVER / "routes"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import playerdb
playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "players.db"

from tests.seed import one_account
one_account()
import server
from routes import artifact_routes


def _normal_with_upgrade():
    meta = artifact_routes._artifact_meta()
    return next(aid for aid, info in meta.items()
                if info["type"] == "Artifact"
                and info["fromType"] != "Special"
                and info["level"] == "Normal"
                and artifact_routes._tier_upgrade_id(aid) is not None)


def _fresh_blacksmith_state():
    aid = _normal_with_upgrade()
    st = server.load_state()
    st["artifacts"] = [server.make_artifact(1, aid)]
    st["dustCount"] = 1_000
    st["equippedArtifacts"] = []
    assert artifact_routes.ensure_artifact_state(st)
    server.save_state(st)
    return aid


def check_craft_merge_and_polish():
    aid = _fresh_blacksmith_state()
    st = server.load_state()
    relic = st["artifacts"][0]

    crafted = server.r_artifact_crafting({"targetId": relic["id"]}, st)
    assert not crafted.get("msg")
    st = server.load_state()
    relic = next(a for a in st["artifacts"] if a["id"] == relic["id"])
    assert relic["count"] == 2 and st["dustCount"] == 975

    # A normal polishing stone provides exactly the first normal-tier cost (10).
    polished = server.r_artifact_polish(
        {"targetId": relic["id"], "index": 0,
         "polishItemIds": [901], "polishItemCounts": [1]},
        server.load_state(),
    )
    assert not polished.get("msg")
    st = server.load_state()
    relic = next(a for a in st["artifacts"] if a["id"] == relic["id"])
    assert relic["data"]["options"][0]["level"] == 2
    assert relic["options"]["lvs"][0] == 2 and relic["polishPoint"] == 0
    stone = next(a for a in st["artifacts"] if a["artifactId"] == 901)
    assert stone["count"] == 99998

    # One more copy enables the real three-to-one tier transition.
    relic["count"] = 3
    server.save_state(st)
    merged = server.r_artifact_merge({"targetId": relic["id"]}, server.load_state())
    assert not merged.get("msg")
    upgraded_id = artifact_routes._tier_upgrade_id(aid)
    st = server.load_state()
    assert next(a for a in st["artifacts"] if a["id"] == relic["id"])["count"] == 0
    upgraded = next(a for a in st["artifacts"] if a["artifactId"] == upgraded_id)
    assert upgraded["count"] == 1
    print("ok Blacksmith: craft, tier upgrade, and polish persist")


if __name__ == "__main__":
    check_craft_merge_and_polish()
