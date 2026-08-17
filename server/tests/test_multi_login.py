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

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"
playerdb.init()

import server
import routes.player_routes as pr   # handler reads ITS import-copy of ADOPT_LONE_SAVE

GOOGLE, GUEST = 1, 4   # Constants.AccountType


def _login(login_id, acct_type):
    server.CURRENT_LOGIN_ID.set("")
    body = {"id": login_id, "type": acct_type}
    out = server.r_login(body, server.load_state())
    return out, playerdb.uid_for_token(out["accessToken"])


def check_multiplayer_is_the_default():
    assert server.MULTIPLAYER, "multi-account must be on without an env var"
    print("ok default: KGC_MULTIPLAYER on by default")


def _seed_lone_legacy_save():
    """Stand in for a server that has run single-player: one save, no accounts."""
    st = server.copy.deepcopy(server.DEFAULT_PLAYER)
    st["uid"] = "legacy-0001"
    st["gold"] = 777777
    playerdb.save("legacy-0001", st)
    playerdb.set_active("legacy-0001")
    assert playerdb.account_count() == 0 and playerdb.count() == 1


def check_a_lone_save_is_not_adopted_by_default():
    """A wiped-then-rebuilt server must not hand its leftover save to the next
    Guest. This is the regression: a fresh Guest login landed on the old test save."""
    _seed_lone_legacy_save()
    assert not server.ADOPT_LONE_SAVE, "adoption must be opt-in"
    _, uid = _login("Guest_stranger", GUEST)
    assert uid != "legacy-0001", "a stranger's Guest login was given the existing save"
    assert playerdb.load("legacy-0001")["gold"] == 777777, "the lone save was touched"
    playerdb.delete(uid)
    print("ok no-adopt: a fresh Guest gets its own save, not the leftover one")


def check_first_login_adopts_the_lone_existing_save():
    _seed_lone_legacy_save()
    pr.ADOPT_LONE_SAVE = True                       # KGC_ADOPT_LONE_SAVE=1
    out, uid = _login("Google_alice", GOOGLE)
    pr.ADOPT_LONE_SAVE = False
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


def check_empty_id_login_is_refused_in_multiplayer():
    """A client that lost its guest id must not be handed the active save - that
    is how a re-login looked like "my account became KingBug/NewPlayer"."""
    server.CURRENT_LOGIN_ID.set("")
    server.CURRENT_UID.set(None)
    with playerdb._conn() as c:
        n_sessions = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    out = server.r_login({"id": "", "type": GUEST}, server.load_state())
    assert out.get("success") is False, "empty-id login must be refused in multiplayer"
    with playerdb._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == n_sessions, \
            "refused login must not create a session"
    print("ok refuse: an id-less login is refused instead of stealing the active save")


def check_single_player_override_still_works():
    """KGC_MULTIPLAYER=0 must pin everyone to the active save, the old behaviour."""
    saved = pr.MULTIPLAYER
    try:
        pr.MULTIPLAYER = False
        playerdb.set_active("legacy-0001")
        _, uid = _login("Someone_new", GOOGLE)
        assert uid == "legacy-0001", "single-player mode minted a separate save"
    finally:
        pr.MULTIPLAYER = saved
    print("ok override: KGC_MULTIPLAYER=0 keeps one shared save")


if __name__ == "__main__":
    check_multiplayer_is_the_default()
    check_a_lone_save_is_not_adopted_by_default()
    check_first_login_adopts_the_lone_existing_save()
    check_a_different_account_gets_its_own_save()
    check_same_id_restores_same_save_on_another_device()
    check_empty_id_login_is_refused_in_multiplayer()
    check_single_player_override_still_works()
    print("\nall multi-account login checks passed")
