"""Two clients with different account ids must get two different saves.

Identity is the `accesstoken` header, which the client sends on every request
(Web.Get/Post take it as a parameter and HandleWebHeader attaches it). It is
bound to a uid at /auth/register|auth|login.

Guard on the other side too: with KGC_MULTIPLAYER unset, an unknown account id
must NOT mint a fresh save - on a single-player setup that looks exactly like
losing your progress after a reinstall.
"""
import os, sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def main():
    os.environ["KGC_MULTIPLAYER"] = "1"
    # Point playerdb at a throwaway DB BEFORE server imports it - otherwise this
    # test creates real players in the live save.
    import tempfile, playerdb
    playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    playerdb.init()
    playerdb.save("dev-0001", {"uid": "dev-0001"})
    import server

    # Two accounts log in -> two distinct uids, each with its own row.
    uid_a = server._uid_for_login("device-AAA", None)
    uid_b = server._uid_for_login("device-BBB", None)
    assert uid_a != uid_b, "two account ids collapsed onto one save"
    assert playerdb.load(uid_a) and playerdb.load(uid_b), "player rows not created"

    # Same account id again -> same uid, no second save.
    assert server._uid_for_login("device-AAA", None) == uid_a, "re-login created a new save"

    # A token resolves back to its player, and only to its player.
    playerdb.bind_session("tok-a", uid_a)
    playerdb.bind_session("tok-b", uid_b)
    assert playerdb.uid_for_token("tok-a") == uid_a
    assert playerdb.uid_for_token("tok-b") == uid_b
    assert playerdb.uid_for_token("nope") is None, "unknown token must not resolve"

    # load_state() follows the request's identity.
    tok = server.CURRENT_UID.set(uid_b)
    assert server.load_state()["uid"] == uid_b, "load_state ignored the request identity"
    server.CURRENT_UID.reset(tok)
    assert server.load_state()["uid"] == playerdb.active(), "no session must fall back to active"

    # Single-player mode: an unknown id must reuse the active save, not mint one.
    server.MULTIPLAYER = False
    before = playerdb.count()
    assert server._uid_for_login("device-UNKNOWN", None) == playerdb.active()
    assert playerdb.count() == before, "single-player mode created a save for an unknown id"

    print(f"ok: {uid_a} / {uid_b} isolated; token routing and single-player guard hold")


if __name__ == "__main__":
    main()
