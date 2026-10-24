"""Skin-mod equip: use a skin without owning it.

The modded client stubs GameManager.HasSkin to true (build_private.py "has-skin"),
so it sends /card/equipSkin for skins the save never had. The handler must accept
those and persist only currentSkin - the point of the mod is equipping WITHOUT
gaining ownership. A nonexistent id must still be refused, so currentSkin can never
hold garbage the client cannot render.
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
one_account()          # multiplayer mode does not mint a save; give load_state() one
import server

UNIT = 10000
SKIN = 1000001         # real Skin in Skins.xml, Unit="10000"


def _fresh():
    st = server.load_state()
    st.setdefault("cards", {})[str(UNIT)] = {
        "unitId": UNIT, "level": 1, "exp": 0, "potentialTier": 0, "skins": [],
        "favoriteSkinIds": [], "currentSkin": 0, "randomSkinApply": False, "soul": 0}
    server.save_state(st)
    return st


def test_equip_without_owning():
    _fresh()
    out = server.r_card_equip_skin({"unit": UNIT, "skin": SKIN}, server.load_state())
    st = server.load_state()
    assert st["cards"][str(UNIT)]["currentSkin"] == SKIN, "unowned skin did not persist"
    assert st["cards"][str(UNIT)]["skins"] == [], "equipping granted ownership"
    assert out["currentSkin"] == SKIN, "response does not echo the equipped skin"
    print(f"ok equip: skin {SKIN} equipped while unowned, ownership not granted")


def test_unknown_skin_refused():
    _fresh()
    server.r_card_equip_skin({"unit": UNIT, "skin": 9999999}, server.load_state())
    assert server.load_state()["cards"][str(UNIT)]["currentSkin"] == 0, \
        "a nonexistent skin was persisted as currentSkin"
    print("ok guard: nonexistent skin id refused")


def test_reset_to_default_still_works():
    _fresh()
    server.r_card_equip_skin({"unit": UNIT, "skin": SKIN}, server.load_state())
    server.r_card_equip_skin({"unit": UNIT, "skin": 0}, server.load_state())
    assert server.load_state()["cards"][str(UNIT)]["currentSkin"] == 0
    print("ok reset: skin 0 unequips back to the default")


if __name__ == "__main__":
    test_equip_without_owning()
    test_unknown_skin_refused()
    test_reset_to_default_still_works()
    print("\nall skin-mod checks passed")
