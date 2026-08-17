"""The ranking measure battle must spawn training dummies, not a real hero.

/game/start answers `rankingStageUnits`, which the client uses as the enemy
deployment for the weekly "Measure Combat Power" battle. It was hardcoded to
10260 (Chung Ah), so the measure screen showed a hero instead of the dummy -
exactly the artifact users reported as "custom content still on the server".
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


def check_ranking_stage_spawns_dummies():
    st = server.load_state()
    out = server.GAME_OVERRIDES["/game/start"]({"theme": 1, "stage": 1}, st)
    units = out["rankingStageUnits"]
    assert len(units) == 6, f"expected 6 ranking stage units, got {len(units)}"
    assert all(u["unitId"] == 99999 for u in units), units
    print("ok: ranking stage spawns 6 training dummies (99999)")


if __name__ == "__main__":
    check_ranking_stage_spawns_dummies()
    print("\nall ranking stage checks passed")
