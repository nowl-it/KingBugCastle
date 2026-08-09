"""What must hold before this server is exposed to the internet.

Each check here corresponds to a way a public deployment gets owned or knocked over,
not to a feature. The recurring trap is the loopback fallback: behind a Cloudflare
Tunnel, an nginx proxy, or any port-forward that rewrites the source, EVERY request
arrives from 127.0.0.1, so "allow loopback" means "allow the internet".
"""
import pathlib
import sys
import tempfile

_SERVER = pathlib.Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb

playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "players.db"
playerdb.init()

import server                                       # noqa: E402
from fastapi.testclient import TestClient           # noqa: E402

# TestClient's default peer is the literal "testclient", which is NOT loopback and
# would fake a pass on every loopback check.
LOCAL = lambda: TestClient(server.app, client=("127.0.0.1", 40000))
REMOTE = lambda: TestClient(server.app, client=("203.0.113.9", 40000))

ADMIN_PATH = "/admin/api/players"


def _reset():
    server.ADMIN_TOKEN = None
    for a in playerdb.admin_list():
        playerdb.admin_delete(a["username"])


def check_admin_open_to_loopback_only_when_nothing_is_configured():
    _reset()
    assert LOCAL().get(ADMIN_PATH).status_code == 200
    assert REMOTE().get(ADMIN_PATH).status_code == 403
    print("ok: bare server - loopback only")


def check_a_token_replaces_the_loopback_fallback():
    _reset()
    server.ADMIN_TOKEN = "s3cret-token"
    assert LOCAL().get(ADMIN_PATH).status_code == 403, \
        "loopback bypassed a configured token"
    assert REMOTE().get(ADMIN_PATH, headers={"x-admin-token": "wrong"}).status_code == 403
    assert REMOTE().get(ADMIN_PATH, headers={"x-admin-token": "s3cret-token"}).status_code == 200
    print("ok: token required from everyone, including loopback")


def check_an_admin_account_closes_the_loopback_hole():
    """The regression this file exists for.

    serve_public.sh accepts a dashboard ACCOUNT instead of KGC_ADMIN_TOKEN. The game
    port's guard only understood the token, so an account-only deployment left it
    with nothing to check - and behind a tunnel the loopback fallback let every
    remote player rewrite or delete any save through :8080.
    """
    _reset()
    playerdb.admin_create("root", "correct horse battery")
    assert LOCAL().get(ADMIN_PATH).status_code == 403, \
        "loopback still open while an admin account exists"
    assert REMOTE().get(ADMIN_PATH).status_code == 403

    token = playerdb.admin_login("root", "correct horse battery")
    assert token, "admin_login refused the correct password"
    c = REMOTE()
    c.cookies.set(server.ADMIN_COOKIE, token)
    assert c.get(ADMIN_PATH).status_code == 200, "a signed-in operator was locked out"
    # The dashboard proxies with the header rather than a cookie.
    assert REMOTE().get(ADMIN_PATH, headers={"x-admin-token": token}).status_code == 200
    assert REMOTE().get(ADMIN_PATH, headers={"x-admin-token": "nope"}).status_code == 403

    playerdb.admin_logout(token)
    assert REMOTE().get(ADMIN_PATH, headers={"x-admin-token": token}).status_code == 403, \
        "a logged-out session still worked"
    print("ok: admin account required, session honoured, logout revokes")


def check_no_session_cannot_reach_another_players_save():
    """A request with no token, or a forged one, must not land on someone's save.

    `load_state()` used to fall back to `playerdb.active()` - the save the operator
    last selected in the dashboard - for any request it could not resolve. On a
    public port that means anyone who can reach it reads AND writes that save with
    no credential at all: `POST /player/rename` with a garbage token renamed the
    active player's castle. Multiplayer mode now hands those requests a throwaway
    save instead; single-player keeps the fallback, where there is nobody to
    impersonate.
    """
    _reset()
    import state
    assert state.MULTIPLAYER, "this check is about the multiplayer default"

    alice, bob = REMOTE(), REMOTE()
    ta = server.aes_decrypt(alice.post("/auth/register", json={"id": "hard-alice"}).content)["accessToken"]
    tb = server.aes_decrypt(bob.post("/auth/register", json={"id": "hard-bob"}).content)["accessToken"]
    ua = playerdb.uid_for_token(ta)
    assert ua and playerdb.uid_for_token(tb) != ua, "the two accounts share a save"

    st = playerdb.load(ua)
    st.update(gold=777777, castleName="AliceCastle")
    playerdb.save(ua, st)
    playerdb.set_active(ua)                     # the dashboard's selection

    # Alice's own session still sees her save.
    own = server.aes_decrypt(alice.get("/player", headers={"accesstoken": ta}).content)
    assert own["gold"] == 777777, f"a valid session lost its save: {own.get('gold')}"

    # An attacker with no session sees nothing of hers, and cannot write to it.
    for headers, label in (({}, "no token"), ({"accesstoken": "garbage"}, "forged token")):
        seen = server.aes_decrypt(bob.get("/player", headers=headers).content)
        assert seen.get("gold") != 777777, f"{label} read the active player's save"
        bob.post("/player/rename", json={"userName": "PWNED", "castleName": "PWNED"},
                 headers=headers)
        assert playerdb.load(ua)["castleName"] == "AliceCastle", \
            f"{label} overwrote the active player's save"
    print("ok isolation: a request with no session can neither read nor write another save")


def check_the_game_api_stays_open():
    """Players are not authenticated at the transport level - only /admin is gated."""
    _reset()
    playerdb.admin_create("root", "correct horse battery")
    for path in ("/", "/patch/AssetHash.txt"):
        assert REMOTE().get(path).status_code == 200, f"{path} got caught by the admin guard"
    _reset()
    print("ok: game + CDN routes unaffected by the admin guard")


def check_oversized_bodies_are_refused():
    """Starlette buffers the whole body before a handler sees it, so with no cap one
    POST is a denial of service. Both shapes matter: a declared Content-Length, and
    a chunked upload that declares nothing."""
    _reset()
    c = LOCAL()
    assert c.post("/player", json={"a": 1}).status_code == 200
    assert c.post("/player", content=b"x" * (server.MAX_BODY + 1000)).status_code == 413

    def chunked():
        for _ in range(20):
            yield b"y" * 100_000
    assert c.post("/player", content=chunked()).status_code == 413, \
        "a chunked upload walked past the Content-Length check"
    print("ok: oversized bodies refused, declared or chunked")


def check_one_address_cannot_hog_the_server():
    _reset()
    server._rate_hits.clear()
    server._banned.clear()
    server._ban_strikes.clear()
    c = LOCAL()
    codes = [c.get("/").status_code for _ in range(server.RATE_LIMIT + 5)]
    assert 429 in codes, "no rate limit at all"
    assert codes[:server.RATE_LIMIT].count(200) == server.RATE_LIMIT, \
        "the limit bit before the configured ceiling"
    # The CDN is exempt: a first launch pulls six bundles back to back.
    assert c.get("/patch/AssetHash.txt").status_code == 200, \
        "rate limit broke the CDN, which every fresh install hammers"
    server._rate_hits.clear()
    print(f"ok: {server.RATE_LIMIT}/{server.RATE_WINDOW}s per address, CDN exempt")


def check_forwarded_ip_is_ignored_unless_trusted():
    """Reading x-forwarded-for by default lets anyone talking to us directly forge
    their address and reset every per-IP limit at will."""
    _reset()
    server._rate_hits.clear()
    fake = {"x-forwarded-for": "198.51.100.7"}

    server.TRUST_PROXY = False
    assert server.client_ip(_req(LOCAL(), fake)) == "127.0.0.1", "forged header was believed"
    server.TRUST_PROXY = True
    assert server.client_ip(_req(LOCAL(), fake)) == "198.51.100.7", \
        "KGC_TRUST_PROXY=1 did not take effect - every player shares one bucket"
    server.TRUST_PROXY = False
    print("ok: x-forwarded-for honoured only with KGC_TRUST_PROXY=1")


class _req:
    """Just enough of a Request for client_ip()."""
    def __init__(self, client, headers):
        self.client = type("c", (), {"host": "127.0.0.1"})()
        self.headers = headers


if __name__ == "__main__":
    check_admin_open_to_loopback_only_when_nothing_is_configured()
    check_a_token_replaces_the_loopback_fallback()
    check_an_admin_account_closes_the_loopback_hole()
    check_no_session_cannot_reach_another_players_save()
    check_the_game_api_stays_open()
    check_oversized_bodies_are_refused()
    check_one_address_cannot_hog_the_server()
    check_forwarded_ip_is_ignored_unless_trusted()
    print("\nall public-hardening checks passed")
