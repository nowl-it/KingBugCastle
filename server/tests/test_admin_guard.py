"""/admin can rewrite or delete any save, and the server binds 0.0.0.0 for remote
players - so it must not be reachable by them.

Rules: KGC_ADMIN_TOKEN set -> the token is required from everyone; unset ->
loopback only. serve_public.sh refuses to start without a token, because behind a
tunnel every request looks like loopback.
"""
import os, sys, pathlib, tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


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

    # No token configured: loopback allowed, remote refused.
    server.ADMIN_TOKEN = None
    assert client().get("/admin/api/info").status_code == 200, "loopback admin must work"
    r = client("203.0.113.7").get("/admin/api/info")
    assert r.status_code == 403, f"remote admin allowed without a token: {r.status_code}"

    # Token configured: required from everyone, including loopback.
    server.ADMIN_TOKEN = "s3cret"
    assert client().get("/admin/api/info").status_code == 403, "token not enforced on loopback"
    assert client("203.0.113.7").get("/admin/api/info").status_code == 403
    assert client("203.0.113.7").get(
        "/admin/api/info", headers={"x-admin-token": "s3cret"}).status_code == 200, "valid token rejected"
    assert client("203.0.113.7").get(
        "/admin/api/info", headers={"x-admin-token": "wrong"}).status_code == 403, "wrong token accepted"

    # A destructive route is behind the same guard, not just the read-only one.
    r = client("203.0.113.7").post("/admin/api/players/delete", json={"uid": "dev-0001"})
    assert r.status_code == 403, "player deletion reachable without the token"
    assert playerdb.load("dev-0001") is not None, "player was deleted despite 403"

    # The game API stays open - remote players must still be able to play.
    assert client("203.0.113.7").get("/player").status_code == 200, "game API wrongly gated"

    server.ADMIN_TOKEN = None
    print("ok: admin guarded (loopback-only, or token when set); game API still open")


if __name__ == "__main__":
    main()
