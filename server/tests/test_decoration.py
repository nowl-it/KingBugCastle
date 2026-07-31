"""Decoration: flags, name tags, map skins, login skins, advisors.

The tab was one static payload with five empty lists, so nothing was owned and
nothing equipped stuck. The parts worth guarding are the ones that fail quietly:

  * content gating - an ungated map skin names a Prefab the deployed client has no
    Addressables entry for, and the map then loads with no background at all;
  * equipping something that does not exist - the panel shows an empty slot rather
    than refusing, so a bad id looks like a rendering bug;
  * advisor extension - extending early must add to the remaining time, not restart
    the clock from now, or the player loses whatever they had already paid for.
"""
import datetime, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import decoration
from tests.seed import one_account
one_account()          # multiplayer needs a session; load_state() has no fallback
import server


def _fresh():
    st = server.load_state()
    st.pop("decoration", None)
    st["inventory"] = {"itemIds": [], "counts": []}
    server.save_state(st)
    return st


def _until(out):
    return datetime.datetime.strptime(out["contractUntilAt"], "%Y-%m-%dT%H:%M:%S.000Z")


def check_everything_is_owned():
    out = server.r_decoration({}, _fresh())
    for key, sub, field in (("flagInfo", "flagsModel", "flags"),
                            ("nameTagInfo", "nameTagsModel", "nameTags"),
                            ("mapSkinInfo", "mapSkinList", "mapSkins"),
                            ("advisorInfo", "advisorList", "advisors")):
        want = len(decoration.ids(field, server.CONTENT_GATE, server.XML_DIR))
        assert len(out[key][sub]) == want, f"{field}: {len(out[key][sub])} of {want} listed"
    assert out["loginSkinInfo"]["loginSkinList"] == \
        decoration.ids("loginSkins", server.CONTENT_GATE, server.XML_DIR)
    assert all(s["owned"] for s in out["mapSkinInfo"]["mapSkinList"]), "a map skin is unowned"
    print("ok owned: every flag, name tag, map skin, login skin and advisor is listed")


def check_content_gate_holds():
    """Nothing above the deployed client's build code may be listed."""
    out = server.r_decoration({}, _fresh())
    els = decoration.entries("mapSkins", server.XML_DIR)
    for s in out["mapSkinInfo"]["mapSkinList"]:
        mv = decoration._min_version(els[s["skinId"]])
        assert mv <= server.CONTENT_GATE, f"map skin {s['skinId']} needs build {mv}"
    # Nothing is above the current build, so that pass alone is vacuous - check the
    # gate is actually load-bearing by asking it for an older client.
    old = decoration.ids("mapSkins", 156000, server.XML_DIR)
    assert len(old) < len(els), "the gate lets everything through at an old build"
    print(f"ok gate: {len(els)} map skins at build {server.CONTENT_GATE}, "
          f"{len(old)} at 156000")


def check_equip_persists_and_is_validated():
    st = _fresh()
    real = decoration.ids("mapSkins", server.CONTENT_GATE, server.XML_DIR)[-1]
    server.r_map_skin_equip({"skinId": real}, st)
    applied = server.r_decoration({}, server.load_state())["equipInfo"]["appliedMapSkinData"]
    assert applied == {str(real): 100}, f"applied map skin is {applied}"

    server.r_map_skin_equip({"skinId": 999999}, server.load_state())
    applied = server.r_decoration({}, server.load_state())["equipInfo"]["appliedMapSkinData"]
    assert applied == {str(real): 100}, "a map skin that does not exist was equipped"

    server.r_flag_set({"id": 999999}, server.load_state())
    assert server.load_state()["decoration"]["flag"]["flagId"] == 0, "equipped a bogus flag"
    flag = decoration.ids("flags", server.CONTENT_GATE, server.XML_DIR)[1]
    got = server.r_flag_set({"id": flag, "season": 71}, server.load_state())
    assert got == {"flagId": flag, "season": 71}
    assert server.r_flag_inventory({}, server.load_state())["equipedFlag"] == got
    print(f"ok equip: map skin {real} and flag {flag} stuck, bogus ids refused")


def check_login_skin_carries_its_illustration():
    """The lobby positions the illustration from these fields - an empty illust name
    leaves the login scene blank."""
    st = _fresh()
    sid = next(i for i in decoration.ids("loginSkins", server.CONTENT_GATE, server.XML_DIR)
               if decoration.login_scene(i, server.XML_DIR)["illust"])
    out = server.r_login_skin_equip({"skinId": sid}, st)
    assert out["illust"], f"login skin {sid} equipped with no sprite"
    assert out["scale"] > 0, "a zero scale renders the illustration invisible"
    assert server.r_login_scene_illust({}, server.load_state()) == out
    print(f"ok login skin: {sid} -> {out['illust']}")


def check_advisor_contract_and_extend():
    st = _fresh()
    aid = next(i for i in decoration.ids("advisors", server.CONTENT_GATE, server.XML_DIR)
               if decoration.token_price("advisors", i, "ExtendPrice", server.XML_DIR))
    first = server.r_advisor_contract({"advisorId": aid}, st)
    assert first["remainExtendCount"] == decoration.EXTEND_COUNT
    end = _until(first)
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    assert end > now, "a fresh contract is already expired"

    second = server.r_advisor_extend({"advisorId": aid}, server.load_state())
    assert _until(second) - end == datetime.timedelta(days=decoration.EXTEND_DAYS), \
        "extending restarted the clock instead of adding to the remaining time"
    assert second["remainExtendCount"] == decoration.EXTEND_COUNT - 1

    for _ in range(decoration.EXTEND_COUNT):
        last = server.r_advisor_extend({"advisorId": aid}, server.load_state())
    assert last["remainExtendCount"] == 0, "extended past the cap"
    capped = _until(last)
    again = server.r_advisor_extend({"advisorId": aid}, server.load_state())
    assert _until(again) == capped, "an extension past the cap still added time"
    print(f"ok advisor: {aid} contracted {decoration.CONTRACT_DAYS}d, "
          f"{decoration.EXTEND_COUNT} extends then capped")


def check_advisor_timeout_falls_back():
    st = _fresh()
    aid = decoration.ids("advisors", server.CONTENT_GATE, server.XML_DIR)[-1]
    server.r_advisor_contract({"advisorId": aid}, st)
    server.r_advisor_equip({"advisorId": aid}, server.load_state())
    assert server.load_state()["decoration"]["advisor"] == aid
    server.r_advisor_timeout({"advisorId": aid}, server.load_state())
    d = server.load_state()["decoration"]
    assert str(aid) not in d["contracts"], "the expired contract survived"
    assert d["advisor"] == decoration.DEFAULT_ADVISOR, \
        "the lobby was left with no advisor after one timed out"
    print(f"ok timeout: {aid} expired, fell back to {decoration.DEFAULT_ADVISOR}")


def check_map_skin_buy_charges_tokens():
    st = _fresh()
    sid = next(i for i in decoration.ids("mapSkins", server.CONTENT_GATE, server.XML_DIR)
               if decoration.token_price("mapSkins", i, "SkinTokenPrice", server.XML_DIR))
    price = decoration.token_price("mapSkins", sid, "SkinTokenPrice", server.XML_DIR)
    server._grant_reward(st, "Item", decoration.SKIN_TOKEN, price + 5)
    server.save_state(st)
    out = server.r_map_skin_buy({"skinId": sid, "useSkinToken": True}, server.load_state())
    assert out["playerSkinToken"] == 5, f"{price} tokens should have been spent, left {out['playerSkinToken']}"
    assert out["skinId"] == sid
    print(f"ok buy: map skin {sid} charged {price} skin tokens")


def check_favorites_toggle():
    st = _fresh()
    sid = decoration.ids("mapSkins", server.CONTENT_GATE, server.XML_DIR)[2]
    server.r_map_skin_favorite({"skinId": sid, "set": True}, st)
    lst = server.r_decoration({}, server.load_state())["mapSkinInfo"]["mapSkinList"]
    assert next(s for s in lst if s["skinId"] == sid)["isFavorite"]
    server.r_map_skin_favorite({"skinId": sid, "set": False}, server.load_state())
    lst = server.r_decoration({}, server.load_state())["mapSkinInfo"]["mapSkinList"]
    assert not next(s for s in lst if s["skinId"] == sid)["isFavorite"]
    assert not any(s["isFavorite"] for s in lst), "unfavouriting left something marked"
    print(f"ok favorites: {sid} toggles both ways")


if __name__ == "__main__":
    check_everything_is_owned()
    check_content_gate_holds()
    check_equip_persists_and_is_validated()
    check_login_skin_carries_its_illustration()
    check_advisor_contract_and_extend()
    check_advisor_timeout_falls_back()
    check_map_skin_buy_charges_tokens()
    check_favorites_toggle()
    print("\nall decoration checks passed")
