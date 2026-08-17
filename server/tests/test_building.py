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


if __name__ == "__main__":
    check_client_shaped_save_persists()
    print("\nall building checks passed")