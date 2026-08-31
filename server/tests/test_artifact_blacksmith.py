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
                and info["fromType"] == "ShopCommon"
                and info["level"] == "Normal"
                and artifact_routes._tier_upgrade_id(aid) is not None)


def _fresh_blacksmith_state():
    aid = _normal_with_upgrade()
    piece_id = next(piece_id for piece_id, info in artifact_routes._artifact_meta().items()
                    if info["type"] == "Piece" and info["root"] == aid)
    st = server.load_state()
    relic = server.make_artifact(1, aid)
    relic["count"] = 0
    relic["data"]["options"][0].update({"level": 1, "value": 4})
    relic["options"]["lvs"][0] = 1
    piece = server.make_artifact(2, piece_id)
    piece["count"] = 3
    st["artifacts"] = [relic, piece]
    st["dustCount"] = 1_000
    st["gold"] = 10_000
    st["equippedArtifacts"] = []
    assert artifact_routes.ensure_artifact_state(st)
    expected_pieces = {piece_id for piece_id, info in artifact_routes._artifact_meta().items()
                       if info["type"] == "Piece" and info["minVersion"] <= artifact_routes.CONTENT_GATE}
    assert expected_pieces <= {artifact["artifactId"] for artifact in st["artifacts"]}
    server.save_state(st)
    return aid, piece_id


def check_craft_merge_and_polish():
    aid, piece_id = _fresh_blacksmith_state()
    st = server.load_state()
    relic = st["artifacts"][0]
    piece = next(a for a in st["artifacts"] if a["artifactId"] == piece_id)

    crafted = server.r_artifact_crafting({"targetId": piece["id"], "useDust": False}, st)
    assert not crafted.get("msg")
    st = server.load_state()
    relic = next(a for a in st["artifacts"] if a["id"] == relic["id"])
    piece = next(a for a in st["artifacts"] if a["artifactId"] == piece_id)
    assert relic["count"] == 1 and piece["count"] == 1 and st["dustCount"] == 1_000

    crafted = server.r_artifact_crafting({"targetId": piece["id"], "useDust": True}, st)
    assert not crafted.get("msg")
    st = server.load_state()
    relic = next(a for a in st["artifacts"] if a["id"] == relic["id"])
    piece = next(a for a in st["artifacts"] if a["artifactId"] == piece_id)
    assert relic["count"] == 2 and piece["count"] == 0 and st["dustCount"] == 975

    # Common relic option ranks cost 10, 20, then 30 polish points.
    for count, wanted_level in ((1, 2), (2, 3), (3, 4)):
        polished = server.r_artifact_polish(
            {"targetId": relic["id"], "index": 0,
             "polishItemIds": [901], "polishItemCounts": [count]},
            server.load_state(),
        )
        assert not polished.get("msg")
        relic = next(a for a in server.load_state()["artifacts"] if a["id"] == relic["id"])
        assert relic["data"]["options"][0]["level"] == wanted_level

    st = server.load_state()
    relic = next(a for a in st["artifacts"] if a["id"] == relic["id"])
    assert relic["options"]["lvs"][0] == 4 and relic["polishPoint"] == 0
    stone = next(a for a in st["artifacts"] if a["artifactId"] == 901)
    assert stone["count"] == 99993

    moved = server.r_artifact_replace_option_slot_idx(
        {"targetId": relic["id"], "index": 0, "replacedOptionSlotIdx": [2],
         "polishItemIds": [903], "polishItemCounts": [2]},
        st,
    )
    assert not moved.get("msg")
    st = server.load_state()
    relic = next(a for a in st["artifacts"] if a["id"] == relic["id"])
    assert relic["data"]["options"][0]["targets"] == [2]
    assert relic["options"]["targets"][0]["idx"] == [2] and relic["polishPoint"] == 0

    merged = server.r_artifact_merge(
        {"targetId": relic["id"], "materialId": relic["id"]},
        server.load_state(),
    )
    assert not merged.get("msg")
    upgraded_id = artifact_routes._tier_upgrade_id(aid)
    st = server.load_state()
    assert next(a for a in st["artifacts"] if a["id"] == relic["id"])["count"] == 0
    upgraded = next(a for a in st["artifacts"] if a["artifactId"] == upgraded_id)
    assert upgraded["count"] == 1 and st["gold"] == 9_600
    print("ok Blacksmith: piece crafting, paid merge, polish, and position move persist")


if __name__ == "__main__":
    check_craft_merge_and_polish()
