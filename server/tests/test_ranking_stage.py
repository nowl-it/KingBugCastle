"""/game/start must not fabricate ranking-stage enemy units.

The response used to hardcode `rankingStageUnits` (6x a chosen unit id), which
the client deployed as the enemy of the "Measure Combat Power" battle - so a
real hero appeared there instead of the stage's own spawns. The field is gone
entirely: the client falls back to the stage data.
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


def check_no_fabricated_ranking_units():
    st = server.load_state()
    out = server.GAME_OVERRIDES["/game/start"]({"theme": 1, "stage": 1}, st)
    assert "rankingStageUnits" not in out, "ranking stage units must not be hardcoded"
    assert out["gameId"], "the rest of the start response is intact"
    print("ok: /game/start sends no fabricated ranking stage units")


if __name__ == "__main__":
    check_no_fabricated_ranking_units()
    print("\nall game start checks passed")
