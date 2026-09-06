"""Roguelike run persistence and the shop's bookkeeping routes.

The roguelike run lives entirely client-side as one opaque serialised string. The
static placeholder always answered with an empty save, so every run was lost the
moment the app closed - the one thing these routes exist to prevent.

The shop routes here buy nothing; they store the player's own choices. The trap is
the treasure wish list: an id that is not a treasure comes back as a blank row in
the panel, so it has to be rejected on the way in rather than on the way out.
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


def _fresh():
    st = server.load_state()
    for k in ("rogueLike", "treasureWishList", "customPickups", "restoreNeededIaps"):
        st.pop(k, None)
    st["cash"] = 0
    server.save_state(st)
    return server.load_state()


def check_a_run_survives_a_reload():
    _fresh()
    blob = '{"floor":7,"runes":[1,2,3]}'
    server.r_rogue_save({"themeId": 5000, "rogueLikeSaveData": blob,
                         "state": "InGame", "saveVersion": 3}, server.load_state())
    out = server.r_rogue_load({"themeId": 5000}, server.load_state())
    assert out["rogueLikeSaveData"] == blob, f"loaded {out['rogueLikeSaveData']!r}"
    assert out["state"] == "InGame" and out["saveVersion"] == 3
    print("ok save: the run blob comes back intact")


def check_an_incomplete_dimension_rift_run_is_discarded():
    _fresh()
    blob = '{"floorInWorld":1,"cards":[],"fieldUnits":[],"resStages":[]}'
    server.r_rogue_save({"themeId": 2100, "rogueLikeSaveData": blob,
                         "state": "0", "saveVersion": 2}, server.load_state())
    out = server.r_rogue_load({"themeId": 2100}, server.load_state())
    assert out["state"] == "DELETE" and out["rogueLikeSaveData"] == "", \
        "an incomplete run was handed to the scene loader"
    valid = '{"floorInWorld":1,"cards":[{"unitId":10000}],"resStages":[]}'
    server.r_rogue_save({"themeId": 2100, "rogueLikeSaveData": valid,
                         "state": "0", "saveVersion": 3}, server.load_state())
    assert server.r_rogue_load({"themeId": 2100}, server.load_state())["rogueLikeSaveData"] == valid, \
        "a valid Dimension Rift run was discarded"
    print("ok invalid save: incomplete Dimension Rift run is discarded")


def check_runs_do_not_bleed_between_themes():
    _fresh()
    server.r_rogue_save({"themeId": 5000, "rogueLikeSaveData": "a"}, server.load_state())
    server.r_rogue_save({"themeId": 5100, "rogueLikeSaveData": "b"}, server.load_state())
    assert server.r_rogue_load({"themeId": 5000}, server.load_state())["rogueLikeSaveData"] == "a"
    assert server.r_rogue_load({"themeId": 5100}, server.load_state())["rogueLikeSaveData"] == "b"
    print("ok themes: two modes keep separate runs")


def check_the_card_snapshot_is_kept_separately():
    """The snapshot freezes the roster a run started with, so a lobby upgrade
    mid-run cannot change it. Saving the run must not wipe it."""
    _fresh()
    server.r_rogue_snapshot({"themeId": 5000, "ownCardSnapshot": "roster"},
                            server.load_state())
    server.r_rogue_save({"themeId": 5000, "rogueLikeSaveData": "run"}, server.load_state())
    out = server.r_rogue_load({"themeId": 5000}, server.load_state())
    assert out["rogueLikeOwnCardSnapshot"] == "roster", \
        "saving the run cleared the roster snapshot"
    assert out["rogueLikeSaveData"] == "run"
    print("ok snapshot: roster and run are stored independently")


def check_deleting_a_run_moves_the_game_index():
    _fresh()
    server.r_rogue_save({"themeId": 5000, "rogueLikeSaveData": "x"}, server.load_state())
    before = server.load_state().get("rogueLikeGameIndex", 0)
    out = server.r_rogue_delete({"rogueLikeThemeId": 5000}, server.load_state())
    assert out["rogueLikeGameIndex"] == before + 1, \
        "the game index did not move - the next run collides with the deleted one"
    assert server.r_rogue_load({"themeId": 5000}, server.load_state())["rogueLikeSaveData"] == "", \
        "the deleted run is still there"
    print(f"ok delete: index {before} -> {out['rogueLikeGameIndex']}, run cleared")


def check_reviving_in_a_run_costs_cash():
    st = _fresh()
    price = server.RCFG["gameComplete"]["revivePrice"]
    out = server.r_rogue_revive({}, server.load_state())
    assert "msg" in out, "a broke player was revived for free"

    st = server.load_state()
    st["cash"] = price
    server.save_state(st)
    server.r_rogue_revive({}, server.load_state())
    assert server.load_state()["cash"] == 0, "the revive was free"
    print(f"ok revive: {price} cash, refused when broke")


def check_the_ad_revive_is_not_offered():
    out = server.r_rogue_can_revive_by_ad({}, server.load_state())
    assert out["canReviveByAd"] is False, "an ad revive was offered with no ad network"
    print("ok ad revive: reported unavailable, not left empty")


def check_roguelike_statistics_invent_nothing():
    out = server.r_rogue_statistics({}, server.load_state())
    assert out["rogueLikeMissionStatistics"] == [], "clear rates were invented"
    print("ok stats: no fabricated clear rates")


def check_the_wish_list_rejects_things_that_are_not_treasures():
    _fresh()
    real = server.ALL_TREASURE_IDS[0]
    server.r_save_treasure_wish_list(
        {"wishList": {"Common": [real, 999999], "Rare": [], "Special": []}},
        server.load_state())
    out = server.r_treasure_wish_list({}, server.load_state())
    assert out["wishList"]["Common"] == [real], \
        f"stored {out['wishList']['Common']} - a non-treasure draws a blank row"
    assert set(out["wishList"]) == set(server.TREASURE_RARITIES), \
        f"the wish list is missing a rarity: {sorted(out['wishList'])}"
    print(f"ok wish list: treasure {real} kept, 999999 dropped")


def check_the_wish_list_accepts_numeric_rarity_keys():
    """Newtonsoft writes an enum key as its name but reads a number too, so the
    client may send either."""
    _fresh()
    real = server.ALL_TREASURE_IDS[1]
    server.r_save_treasure_wish_list({"wishList": {"2": [real]}}, server.load_state())
    assert server.r_treasure_wish_list({}, server.load_state())["wishList"]["Rare"] == [real], \
        "a numeric rarity key was dropped"
    print("ok rarity keys: \"2\" reads as Rare")


def check_custom_pickups_are_per_banner():
    _fresh()
    server.r_save_custom_pickups({"shopItemId": 11, "customPickups": [10260, 10150]},
                                 server.load_state())
    server.r_save_custom_pickups({"shopItemId": 12, "customPickups": [10300]},
                                 server.load_state())
    assert server.r_custom_pickups({"shopItemId": 11}, server.load_state())["customPickups"] \
        == [10260, 10150]
    assert server.r_custom_pickups({"shopItemId": 12}, server.load_state())["customPickups"] \
        == [10300], "two banners share one pick list"
    assert server.r_custom_pickups({"shopItemId": 99}, server.load_state())["customPickups"] == []
    print("ok pickups: each banner keeps its own picks")


def check_nothing_is_owed_by_the_store():
    _fresh()
    out = server.r_iap_restore_add({"productId": "pack1"}, server.load_state())
    assert out["restoreNeededIaps"] == [], \
        "a purchase was recorded as owed - the shop stays blocked while one is pending"
    server.r_iap_restore_remove({"productId": "pack1"}, server.load_state())
    print("ok iap: nothing pending, the shop is not blocked")


def check_every_route_answers():
    _fresh()
    for path, fn in server.DYNAMIC_OVERRIDES.items():
        if not (path.startswith("/rogueLike") or path.startswith("/shop/")
                or path.startswith("/test/")):
            continue
        out = fn({}, server.load_state())
        assert isinstance(out, dict), f"{path} returned {type(out)}"
    print("ok safety: every roguelike/shop/test route answers on a fresh save")


if __name__ == "__main__":
    check_a_run_survives_a_reload()
    check_an_incomplete_dimension_rift_run_is_discarded()
    check_runs_do_not_bleed_between_themes()
    check_the_card_snapshot_is_kept_separately()
    check_deleting_a_run_moves_the_game_index()
    check_reviving_in_a_run_costs_cash()
    check_the_ad_revive_is_not_offered()
    check_roguelike_statistics_invent_nothing()
    check_the_wish_list_rejects_things_that_are_not_treasures()
    check_the_wish_list_accepts_numeric_rarity_keys()
    check_custom_pickups_are_per_banner()
    check_nothing_is_owed_by_the_store()
    check_every_route_answers()
    print("\nall roguelike/shop checks passed")
