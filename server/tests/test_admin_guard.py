"""/admin can rewrite or delete any save, and the server binds 0.0.0.0 for remote
players - so it must not be reachable by them.

Rules: an admin account exists -> its session cookie is required from everyone;
no account -> loopback only. serve_public.sh refuses to start without an admin
account, because behind a tunnel every request looks like loopback.
"""
import sys, pathlib, tempfile

_SERVER = pathlib.Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)


def client(ip="127.0.0.1"):
    """TestClient with an explicit peer address - its default is the literal
    "testclient", which is not loopback and would fake a passing guard test."""
    from fastapi.testclient import TestClient
    import server
    return TestClient(server.app, client=(ip, 55000))


def main():
    import playerdb
    playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "t.db"
    playerdb.init()
    playerdb.save("dev-0001", {"uid": "dev-0001"})
    import server

    # No admin account configured: loopback allowed, remote refused.
    assert client().get("/admin/api/info").status_code == 200, "loopback admin must work"
    r = client("203.0.113.7").get("/admin/api/info")
    assert r.status_code == 403, f"remote admin allowed without an account: {r.status_code}"

    # An admin account exists: its session is required from everyone, loopback too.
    playerdb.admin_create("boss", "correct horse battery staple")
    assert client().get("/admin/api/info").status_code == 403, "session not enforced on loopback"
    assert client("203.0.113.7").get("/admin/api/info").status_code == 403, \
        "no-session remote request allowed once an account exists"
    assert client("203.0.113.7").get(
        "/admin/api/info", headers={"x-admin-token": "bogus"}).status_code == 403, \
        "bogus session accepted"
    tok = playerdb.admin_login("boss", "correct horse battery staple")
    assert tok, "admin_login refused the fresh account"
    assert client("203.0.113.7").get(
        "/admin/api/info", cookies={"kgc_admin": tok}).status_code == 200, "valid session rejected"

    # A destructive route is behind the same guard, not just the read-only one.
    r = client("203.0.113.7").post("/admin/api/players/delete", json={"uid": "dev-0001"})
    assert r.status_code == 403, "player deletion reachable without a session"
    assert playerdb.load("dev-0001") is not None, "player was deleted despite 403"

    # The game API stays open - remote players must still be able to play.
    assert client("203.0.113.7").get("/player").status_code == 200, "game API wrongly gated"

    print("ok: admin guarded (loopback-only, or session when an account exists); game API still open")


if __name__ == "__main__":
    main()
