"""Altar (building) allocation must persist.

The client saves altar levels as BuildingRequestModel {levels, preset}. The
handler used to read a `buildingData` key the client never sends, so the
allocation vanished and every battle ran with zero altar effects.
"""
import sys, tempfile
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

from tests.seed import one_account
one_account()
import server


def check_client_shaped_save_persists():
    st = server.load_state()
    out = server.PLAYER_OVERRIDES["/player/building/save"](
        {"levels": [15, 10, 0, 0, 0, 0], "preset": 0, "buildingPoint": 25}, st)
    got = out["buildingData"][0]["buildingLevels"]
    assert got == [15, 10, 0, 0, 0, 0], f"allocation dropped: {got}"
    assert out["buildingPoint"] == 25
    live = server.load_state()
    assert live["buildingData"][0]["buildingLevels"] == [15, 10, 0, 0, 0, 0], \
        "allocation did not persist to the save"
    print("ok: {levels, preset} save persists and is served")


def check_negative_pool_clamped():
    st = server.load_state()
    st["buildingPoint"] = -20
    st["buildingPoints"] = 25
    out = server.PLAYER_OVERRIDES["/player/building/save"](
        {"levels": [15, 10, 0, 0, 0, 0], "preset": 0, "buildingPoint": -20}, st)
    assert out["buildingPoint"] == 25, \
        f"negative pool must be raised to cover the allocation: {out['buildingPoint']}"
    live = server.load_state()
    assert live["buildingPoint"] == 25, \
        f"negative pool reached the save un-fixed: {live['buildingPoint']}"
    print("ok: negative buildingPoint is raised to the allocated total (never displays negative)")


def check_pool_never_below_allocated():
    """The client renders remaining points as pool minus the current preset's
    Σlevels - a pool smaller than the allocation (admin-granted levels, or a pool
    clamped after the old negative-save bug) shows NEGATIVE in the altar panel."""
    st = server.load_state()
    st["buildingData"] = [{"buildingLevels": [15, 0, 0, 0, 0, 10]},
                          {"buildingLevels": [10, 15, 0, 0, 0, 0]}]
    st["buildingPoint"] = 0
    server.PLAYER_OVERRIDES["/player"]({}, st)      # login repair path
    live = server.load_state()
    assert live["buildingPoint"] == 25, \
        f"repair must raise the pool to max Σlevels: {live['buildingPoint']}"
    out = server.PLAYER_OVERRIDES["/player/building/save"](
        {"levels": [15, 0, 0, 0, 0, 10], "preset": 0, "buildingPoint": -25}, st)
    assert out["buildingPoint"] == 25, f"save must keep pool >= allocation: {out['buildingPoint']}"
    print("ok: the altar pool can never render negative")


def check_legacy_plural_key_migrates():
    st = server.load_state()
    st["buildingPoint"] = -20
    st["buildingPoints"] = 25
    server.PLAYER_OVERRIDES["/player"]({}, st)
    live = server.load_state()
    assert live["buildingPoint"] == 25, f"plural key did not rescue the pool: {live['buildingPoint']}"
    assert "buildingPoints" not in live, "legacy plural key not retired"
    print("ok: legacy buildingPoints merges into buildingPoint on /player")


def check_retrieve_ember_clears_altars_and_refunds():
    """'Retrieve Ember' = /player/building/resetPoint. It must clear the preset's
    levels AND refund their embers into the pool - the old handler zeroed only the
    pool, so the panel showed pool minus Σlevels (negative) with the altars still
    lit. The client sends BuildingRequestModel {levels, preset} (RestAPI.
    ResetBuildingPoint)."""
    st = server.load_state()
    st["buildingData"] = [{"buildingLevels": [0, 15, 10, 0, 0, 0]}]
    st["buildingPoint"] = 25
    reset = server.PLAYER_OVERRIDES["/player/building/resetPoint"]
    out = reset({"preset": 0}, st)                      # empty body: clear whole preset
    assert out["buildingData"][0]["buildingLevels"] == [0] * 6, "preset not cleared"
    assert out["buildingPoint"] == 50, f"embers not refunded: {out['buildingPoint']}"
    st2 = server.load_state()                           # fresh state for the partial case
    st2["buildingData"] = [{"buildingLevels": [0, 15, 10, 0, 0, 0]}]
    st2["buildingPoint"] = 25
    out = reset({"levels": [0, 10, 0, 0, 0, 0], "preset": 0}, st2)   # partial retrieve
    assert out["buildingData"][0]["buildingLevels"] == [0, 5, 10, 0, 0, 0], \
        f"partial retrieve wrong: {out['buildingData'][0]['buildingLevels']}"
    assert out["buildingPoint"] == 35, f"partial refund wrong: {out['buildingPoint']}"
    print("ok: Retrieve Ember clears the altars and refunds the pool")


if __name__ == "__main__":
    check_client_shaped_save_persists()
    check_negative_pool_clamped()
    check_pool_never_below_allocated()
    check_legacy_plural_key_migrates()
    check_retrieve_ember_clears_altars_and_refunds()
    print("\nall building checks passed")