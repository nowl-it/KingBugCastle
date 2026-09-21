"""Unit tests for cli/transfer_account.py."""
import copy
import json
import sys
import tempfile
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
import server
from transfer_account import transfer_account


def test_transfer_account():
    # Use isolated temp DB
    temp_dir = Path(tempfile.mkdtemp())
    playerdb.DB_PATH = temp_dir / "players.db"
    playerdb.init()

    # 1. Seed source player
    src_uid = "p-src123"
    src_st = copy.deepcopy(server.DEFAULT_PLAYER)
    src_st["uid"] = src_uid
    src_st["name"] = "HeroSource"
    src_st["castleName"] = "CastleSource"
    src_st["level"] = 88
    src_st["gold"] = 999999
    src_st["cash"] = 88888
    src_st["accountId"] = 10
    src_st["cards"] = {"10000": {"unitId": 10000, "level": 20}, "10010": {"unitId": 10010, "level": 20}}
    src_st["riftCrystals"] = [{"id": 1, "rarity": 5}]
    playerdb.save(src_uid, src_st)
    playerdb.bind_login("login_src", src_uid)

    # 2. Seed target player
    dst_uid = "p-dst456"
    dst_st = copy.deepcopy(server.DEFAULT_PLAYER)
    dst_st["uid"] = dst_uid
    dst_st["name"] = "HeroTargetOld"
    dst_st["level"] = 1
    dst_st["gold"] = 100
    dst_st["accountId"] = 25
    playerdb.save(dst_uid, dst_st)
    playerdb.bind_login("login_dst", dst_uid)
    playerdb.bind_session("dummy_token", dst_uid)

    # 3. Dry-run test
    res_dry = transfer_account(src_uid, dst_uid, dry_run=True)
    assert res_dry["status"] == "dry_run"
    assert playerdb.load(dst_uid)["gold"] == 100

    # 4. Actual transfer
    res = transfer_account(src_uid, dst_uid)
    assert res["status"] == "success"

    # Check target data
    saved_dst = playerdb.load(dst_uid)
    assert saved_dst["uid"] == dst_uid
    assert saved_dst["accountId"] == 25, "Must preserve target unique accountId"
    assert saved_dst["name"] == "HeroSource"
    assert saved_dst["castleName"] == "CastleSource"
    assert saved_dst["level"] == 88
    assert saved_dst["gold"] == 999999
    assert saved_dst["cash"] == 88888
    assert len(saved_dst["cards"]) == 2
    assert len(saved_dst["riftCrystals"]) == 1
    assert saved_dst["hasFreeRename"] is True

    # Check sessions were cleared
    assert playerdb.uid_for_token("dummy_token") is None

    # Check accounts table preserved
    assert playerdb.uid_for_login("login_dst") == dst_uid
    assert playerdb.uid_for_login("login_src") == src_uid

    # 5. Idempotent check (already done)
    res_again = transfer_account(src_uid, dst_uid)
    assert res_again["status"] == "already_done"

    # 6. Force transfer
    res_force = transfer_account(src_uid, dst_uid, force=True)
    assert res_force["status"] == "success"

    print("ALL TESTS PASSED!")


if __name__ == "__main__":
    test_transfer_account()
