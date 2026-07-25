"""Login binds each account id to its own save, across devices.

The server was single-player: every login collapsed onto the one active save, so a
second account or a second device saw the first player's game. These check the
multi-account flow:

  * a server that has been single-player until now (one save, no bound accounts)
    hands that save to the FIRST login instead of orphaning it - otherwise the
    switch reads as "my progress vanished".
  * a different login id gets its own fresh save.
  * the SAME id restores the SAME save - which is the whole point of a stable
    Google/Apple id: the same account on a new device is the same game.
  * the social type (Google vs Guest) is remembered.

KGC_MULTIPLAYER is on by default now; this asserts that default.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"
playerdb.init()

import server

GOOGLE, GUEST = 1, 4   # Constants.AccountType


def _login(login_id, acct_type):
    server.CURRENT_LOGIN_ID.set("")
    body = {"id": login_id, "type": acct_type}
    out = server.r_login(body, server.load_state())
    return out, playerdb.uid_for_token(out["accessToken"])


def check_multiplayer_is_the_default():
    assert server.MULTIPLAYER, "multi-account must be on without an env var"
    print("ok default: KGC_MULTIPLAYER on by default")


def check_first_login_adopts_the_lone_existing_save():
    # Stand in for a server that has run single-player: exactly one save, no accounts.
    st = server.copy.deepcopy(server.DEFAULT_PLAYER)
    st["uid"] = "legacy-0001"
    st["gold"] = 777777
    playerdb.save("legacy-0001", st)
    playerdb.set_active("legacy-0001")
    assert playerdb.account_count() == 0 and playerdb.count() == 1

    out, uid = _login("Google_alice", GOOGLE)
    assert uid == "legacy-0001", f"first login did not adopt the lone save: {uid}"
    assert playerdb.load(uid)["gold"] == 777777, "the adopted save lost its data"
    assert playerdb.load(uid)["accountType"] == GOOGLE, "login type not recorded"
    print("ok adopt: alice's first Google login carried the 777777-gold save over")


def check_a_different_account_gets_its_own_save():
    _, alice = _login("Google_alice", GOOGLE)
    _, bob = _login("Guest_bob", GUEST)
    assert bob != alice, "bob landed on alice's save"
    playerdb.save(bob, dict(playerdb.load(bob), gold=42))
    assert playerdb.load(alice)["gold"] == 777777, "bob's edit leaked into alice"
    assert playerdb.load(bob)["accountType"] == GUEST
    print(f"ok isolate: alice={alice} bob={bob}, separate saves and types")


def check_same_id_restores_same_save_on_another_device():
    _, first = _login("Guest_bob", GUEST)
    # A "different device" presents no token and no session - only the same id.
    server.CURRENT_UID.set(None)
    _, again = _login("Guest_bob", GUEST)
    assert again == first, "the same id resolved to a different save"
    assert playerdb.load(again)["gold"] == 42, "the restored save is not bob's"
    print("ok restore: same id -> same save from a fresh device")


def check_single_player_override_still_works():
    """KGC_MULTIPLAYER=0 must pin everyone to the active save, the old behaviour."""
    saved = server.MULTIPLAYER
    try:
        server.MULTIPLAYER = False
        playerdb.set_active("legacy-0001")
        _, uid = _login("Someone_new", GOOGLE)
        assert uid == "legacy-0001", "single-player mode minted a separate save"
    finally:
        server.MULTIPLAYER = saved
    print("ok override: KGC_MULTIPLAYER=0 keeps one shared save")


if __name__ == "__main__":
    check_multiplayer_is_the_default()
    check_first_login_adopts_the_lone_existing_save()
    check_a_different_account_gets_its_own_save()
    check_same_id_restores_same_save_on_another_device()
    check_single_player_override_still_works()
    print("\nall multi-account login checks passed")
