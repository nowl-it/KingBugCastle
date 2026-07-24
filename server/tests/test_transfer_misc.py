"""Account transfer and the last handful of odds and ends.

Account transfer is the only one of these with teeth: the code IS the security
model, so it has to be single-use, expiring, and useless when guessed. Everything
else is shape - most of these models are lists the client zips together by index,
and a null list is a NullReference before the panel ever gets to notice it is
empty.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

import server


def check_a_transfer_code_moves_one_save():
    st = server.load_state()
    code = server.r_transfer_issue({}, st)["userId"]
    assert code and len(code) >= 8, f"code {code!r} is too short to be a credential"
    assert server._transfer_lookup(code) == st["uid"], "the code does not find its save"
    out = server.r_transfer_redeem({"code": code}, server.load_state())
    assert out.get("accessToken"), f"redeeming a valid code failed: {out}"
    assert playerdb.uid_for_token(out["accessToken"]) == st["uid"], \
        "the session points at a different save"
    print(f"ok transfer: code {code} redeems to uid {st['uid']}")


def check_a_code_is_single_use():
    st = server.load_state()
    code = server.r_transfer_issue({}, st)["userId"]
    server.r_transfer_redeem({"code": code}, server.load_state())
    again = server.r_transfer_redeem({"code": code}, server.load_state())
    assert again.get("success") is False, "the same code transferred the save twice"
    assert "accessToken" not in again
    print("ok single use: a spent code is refused")


def check_an_expired_code_is_refused():
    st = server.load_state()
    server.r_transfer_issue({}, st)
    st = server.load_state()
    st["transfer"]["expiresAt"] = server.now_iso(-1)
    server.save_state(st)
    code = st["transfer"]["code"]
    assert server._transfer_lookup(code) is None, "an expired code still resolves"
    assert server.r_transfer_redeem({"code": code}, server.load_state()) \
        .get("success") is False
    print("ok expiry: a stale code is refused")


def check_a_guessed_code_gets_nothing():
    for guess in ("", "AAAAAAAA", "0", None):
        out = server.r_transfer_redeem({"code": guess}, server.load_state())
        assert "accessToken" not in out, f"code {guess!r} logged somebody in"
    print("ok guessing: no code but the real one works")


def check_issuing_again_replaces_the_old_code():
    st = server.load_state()
    first = server.r_transfer_issue({}, st)["userId"]
    second = server.r_transfer_issue({}, server.load_state())["userId"]
    assert first != second, "two issues produced the same code"
    assert server._transfer_lookup(first) is None, \
        "the previous code still works - two live codes for one save"
    print("ok reissue: the previous code stops working")


def check_list_models_are_never_null():
    """Each of these is zipped by index client-side; a null list is an NRE."""
    st = server.load_state()
    ev = server.r_event_mode({}, st)
    assert len(ev) == 6 and all(isinstance(v, list) for v in ev.values()), \
        f"event mode returned {ev}"
    wiki = server.r_wiki({}, st)
    for k, v in wiki.items():
        if k == "riftWeaponArchives":
            assert isinstance(v, list)
            continue
        assert v["wikiElements"] == [] and v["percentage"] == 0, f"{k} = {v}"
    assert isinstance(server.r_cumulative_purchase({}, st)["states"], dict)
    assert isinstance(server.r_cloud_run_services({}, st)["services"], list)
    print(f"ok shapes: {len(ev)} event-mode lists, {len(wiki) - 1} wiki categories")


def check_the_wiki_archive_round_trips():
    st = server.load_state()
    st.pop("riftWeaponArchives", None)
    server.save_state(st)
    wid = server.DEFAULT_RIFT_WEAPONS[0]["id"]
    out = server.r_wiki_archive({"riftWeaponId": wid}, server.load_state())
    assert [w["id"] for w in out["riftWeapons"]] == [wid], f"archived {out['riftWeapons']}"

    server.r_wiki_archive({"riftWeaponId": wid}, server.load_state())
    assert len(server.load_state()["riftWeaponArchives"]) == 1, \
        "archiving the same weapon twice made two entries"

    server.r_wiki_archive_delete({"riftWeaponId": wid}, server.load_state())
    assert server.load_state()["riftWeaponArchives"] == [], "the delete left it behind"
    print(f"ok archive: weapon {wid} in, deduped, out")


def check_pass_reroll_counts_up():
    st = server.load_state()
    st.pop("passRerollCount", None)
    server.save_state(st)
    first = server.r_pass_reroll_mission({}, server.load_state())["rerollCount"]
    second = server.r_pass_reroll_mission({}, server.load_state())["rerollCount"]
    assert (first, second) == (1, 2), f"counted {first} then {second}"
    print("ok pass reroll: the counter moves")


def check_every_new_route_answers():
    for path in ("/auth/usePatch", "/game/eventMode",
                 "/game/check-dimension-rift-complete-success", "/kg-wiki/insert-wiki",
                 "/pass/reroll-mission", "/shop-event/cumulative-purchase",
                 "/shop-event/cumulative-purchase/claim", "/api/cloud-run/services",
                 "/api/cloud-run/default-ranking", "/kgc-main", "/kgc-ranking",
                 "/seasonal-event/april-fools/reward"):
        out = server.DYNAMIC_OVERRIDES[path]({}, server.load_state())
        assert isinstance(out, dict), f"{path} returned {type(out)}"
    print("ok safety: every newly wired route answers")


if __name__ == "__main__":
    check_a_transfer_code_moves_one_save()
    check_a_code_is_single_use()
    check_an_expired_code_is_refused()
    check_a_guessed_code_gets_nothing()
    check_issuing_again_replaces_the_old_code()
    check_list_models_are_never_null()
    check_the_wiki_archive_round_trips()
    check_pass_reroll_counts_up()
    check_every_new_route_answers()
    print("\nall transfer/misc checks passed")
