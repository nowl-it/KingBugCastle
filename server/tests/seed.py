"""One seeded account in a temp DB, for the tests that just need a player to exist.

In multiplayer mode - the default - `load_state()` on an empty database hands back an
UNSAVED placeholder and `save_state()` drops it on the floor. That is deliberate:
persisting there would mint a save nobody logged into, and the next Guest would be
handed that phantom. Only /auth/register creates saves.

Multiplayer mode also refuses to fall back to the ACTIVE save for a request with no
session - that fallback was how anyone could read and write the operator's selected
player over a public port with no token at all. So a test needs both halves: a save
in the DB, and an identity pointing at it.

The consequence otherwise is that every write silently disappears, which reads as the
handler being broken. Call `one_account()` right after redirecting DB_PATH and before
importing server, and there is a real save to load - it seeds the row, marks it active
AND binds the ambient identity, which is what a logged-in request would carry.

    import playerdb
    playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"
    from tests.seed import one_account      # or: sys.path juggling as the file does
    one_account()
    import server
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import playerdb


def one_account(uid="dev-0001", account_id=1, **kv):
    """Create, activate and sign into one save, so load_state() returns it.

    Imports server lazily: the caller redirects playerdb.DB_PATH first, and server
    reads it at import time.

    Setting CURRENT_UID is what stands in for the `accesstoken` header a real
    request carries - without it, multiplayer mode has no identity to resolve and
    hands back a throwaway save that save_state() discards. The ContextVar is set
    for the whole process and deliberately never reset: a test module is one
    "session" from the server's point of view.
    """
    playerdb.init()
    import copy

    import server
    import state
    st = copy.deepcopy(server.DEFAULT_PLAYER)
    st["uid"] = uid
    st["accountId"] = account_id
    st.update(kv)
    playerdb.save(uid, st)
    playerdb.set_active(uid)
    state.CURRENT_UID.set(uid)
    return st


if __name__ == "__main__":
    import tempfile

    playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "players.db"
    st = one_account()
    import server
    assert server.load_state()["uid"] == st["uid"], "the seeded save is not the one loaded"
    live = server.load_state()
    live["gold"] = 4321
    server.save_state(live)
    assert server.load_state()["gold"] == 4321, "a write to a seeded save did not persist"
    print("seed self-check ok")
