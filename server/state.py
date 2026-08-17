"""Which player a request belongs to, and how a save is read and written.

Every handler funnels through load_state/save_state, so they cannot stay in
server.py if handlers are to move out of it.

DEFAULT_PLAYER is filled in by server.py at import time via `use_default_player()`
rather than built here: it is assembled from data/default_player.json plus the
content-gated hero/artifact/treasure lists, which need master data this module has
no business knowing about.

    python3 state.py     # self-check
"""
import contextvars
import copy
import os

import playerdb
from common import admin_log

# Set per request from the `accesstoken` header (see the resolve_player middleware).
# None = no session -> fall back to the admin-selected active player, which is
# what every single-player setup and the whole pre-login boot sequence relies on.
CURRENT_UID = contextvars.ContextVar("current_uid", default=None)

# Set per request by the serialize_state_writes middleware, for the registration
# rate limit.
CURRENT_IP = contextvars.ContextVar("current_ip", default="-")

# Each login id (Guest_xxx, or a Google/Apple account id) gets its own save, and
# the same id restores the same save on any device - that is what makes the server
# multi-account and cross-device. Default on. The one hazard it carries is that a
# Guest id regenerates when the app is reinstalled with its cache cleared, minting
# a fresh empty save that looks like lost progress - which is exactly the problem a
# stable Google/Apple id solves, and why those logins exist. Force the old
# single-player behaviour (everyone -> the active save) with KGC_MULTIPLAYER=0.
MULTIPLAYER = os.environ.get("KGC_MULTIPLAYER", "1") != "0"
MAX_PLAYERS = int(os.environ.get("KGC_MAX_PLAYERS") or 200)
# One-shot single-player -> multiplayer migration, see server._uid_for_login.
# Off by default: once the migration is done it is indistinguishable from a hijack,
# and it silently handed a fresh Guest the leftover test save.
ADOPT_LONE_SAVE = os.environ.get("KGC_ADOPT_LONE_SAVE") == "1"

DEFAULT_PLAYER = {}


def use_default_player(template):
    """server.py hands over the assembled new-save template."""
    DEFAULT_PLAYER.clear()
    DEFAULT_PLAYER.update(template)


def new_save(uid=None):
    st = copy.deepcopy(DEFAULT_PLAYER)
    if uid is not None:
        st["uid"] = uid
    return st


def load_state():
    """State of the player this request belongs to.

    Identity comes from the `accesstoken` header, bound to a uid at login.

    In MULTIPLAYER mode a request with no valid session gets a throwaway save, NOT
    the active player's: falling back to `playerdb.active()` there means anyone who
    can reach the port reads and writes whichever save the dashboard last selected,
    with no token at all. (Found 2026-07-31 by probing from a non-loopback peer -
    `POST /player/rename` with a garbage token renamed the active player's castle.)

    Single-player mode keeps the old behaviour on purpose: there is one save, the
    admin UI and the pre-login boot both need to see it, and there is nobody to
    impersonate.
    """
    uid = CURRENT_UID.get()
    if not uid and not MULTIPLAYER:
        uid = playerdb.active()
    if uid:
        st = playerdb.load(uid)
        if st is not None:
            return st
    st = new_save()
    if MULTIPLAYER:
        # Nothing to serve yet: an empty database plus a pre-login request (CDN,
        # boot, admin UI). Persisting the default here would mint a save nobody
        # logged into, and _uid_for_login would then hand that phantom to the next
        # Guest - which is exactly how a wiped server came back holding dev-0001.
        # Saves are created by /auth/register only.
        st["_ephemeral"] = True
        return st
    uid = st.get("uid") or "dev-0001"
    playerdb.save(uid, st)
    playerdb.set_active(uid)
    return st


def save_state(st):
    if st.pop("_ephemeral", False):
        return          # a pre-login placeholder; a real write always has a session
    playerdb.save(st.get("uid") or "dev-0001", st)


def patch_state(st, updates):
    st.update(updates)
    save_state(st)


# --- Registration rate limit --------------------------------------------------
# Account ids are client-chosen and unauthenticated, so /auth/register is an open
# "create a save" endpoint. MAX_PLAYERS caps the total; this caps the RATE, so one
# host cannot burn the whole budget in a loop before anyone notices.
# ponytail: in-process sliding window, so each uvicorn gets its own allowance and a
# restart forgets. Two processes and a human operator - that is accurate enough.
# Move the counter into the DB if this ever fronts real traffic.
NEW_PLAYER_PER_IP = int(os.environ.get("KGC_NEW_PLAYER_PER_IP") or 5)
NEW_PLAYER_WINDOW = int(os.environ.get("KGC_NEW_PLAYER_WINDOW") or 3600)
_new_player_hits = {}


def registration_allowed(ip, now=None):
    import time
    now = time.time() if now is None else now
    hits = [t for t in _new_player_hits.get(ip, []) if now - t < NEW_PLAYER_WINDOW]
    if len(hits) >= NEW_PLAYER_PER_IP:
        _new_player_hits[ip] = hits
        return False
    hits.append(now)
    _new_player_hits[ip] = hits
    if len(_new_player_hits) > 1000:      # bound the dict: drop hosts with no live hits
        for k in [k for k, v in _new_player_hits.items()
                  if not any(now - t < NEW_PLAYER_WINDOW for t in v)]:
            del _new_player_hits[k]
    return True


def announce():
    admin_log("[state] identity mode: " + (
        "multiplayer (account id -> own save)" if MULTIPLAYER
        else "single-player (everyone -> active save)"))


if __name__ == "__main__":
    import pathlib, tempfile
    playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    playerdb.init()

    use_default_player({"uid": "dev-0001", "gold": 5, "cards": {"1": {"level": 1}}})
    assert new_save("x")["uid"] == "x"
    a, b = new_save(), new_save()
    a["cards"]["1"]["level"] = 99
    assert b["cards"]["1"]["level"] == 1, "new_save must deep-copy the template"

    # The regression this file exists to hold: an empty DB plus a pre-login request
    # must not create a save, or the next Guest login inherits it.
    assert MULTIPLAYER, "test assumes the default"
    st = load_state()
    assert st.get("_ephemeral") and playerdb.count() == 0, "a phantom save was minted"
    save_state(st)
    assert playerdb.count() == 0, "the placeholder was persisted"

    # The security invariant: identity comes from the session, never from whichever
    # save the dashboard has selected. Falling back to playerdb.active() here let
    # anyone who could reach the port read and write it with no token at all.
    playerdb.save("real-1", {"uid": "real-1", "gold": 7})
    playerdb.set_active("real-1")
    assert load_state().get("_ephemeral"), "a session-less request reached the active save"

    CURRENT_UID.set("real-1")
    got = load_state()
    assert got["gold"] == 7 and "_ephemeral" not in got
    patch_state(got, {"gold": 8})
    assert playerdb.load("real-1")["gold"] == 8
    CURRENT_UID.set(None)

    hits = [registration_allowed("1.2.3.4", now=1000.0) for _ in range(NEW_PLAYER_PER_IP + 2)]
    assert hits[:NEW_PLAYER_PER_IP] == [True] * NEW_PLAYER_PER_IP and not any(hits[NEW_PLAYER_PER_IP:])
    assert registration_allowed("1.2.3.4", now=1000.0 + NEW_PLAYER_WINDOW + 1), \
        "the window never reopens"
    print("state self-check ok")
