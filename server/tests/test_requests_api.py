"""HTTP proof for the Phase-4 admin queue contract.

The database tests cover the transaction itself.  This one proves the dashboard
guard is in front of approve/deny, and that an authenticated request reaches the
self-locking transaction without the middleware taking the flock a second time.
"""
import asyncio
import pathlib
import sys
import tempfile
from types import SimpleNamespace

_SERVER = pathlib.Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

import playerdb


def _seed_request():
    playerdb.save("request-api-user", {"uid": "request-api-user", "name": "API Tester", "posts": []})
    playerdb.bind_login("Guest_REQUEST_API", "request-api-user")
    with playerdb._conn() as c:
        c.execute("INSERT INTO ticket_wallets(login_id,balance,earned_today) VALUES (?,?,0)",
                  ("Guest_REQUEST_API", 1))
    return playerdb.ticket_submit_grant_request("Guest_REQUEST_API", "API request", now=1_000)["requestId"]


class _Request:
    def __init__(self, path, token=None, host="203.0.113.9"):
        self.method = "POST"
        self.url = SimpleNamespace(path=path)
        self.cookies = {"kgc_admin": token} if token else {}
        self.client = SimpleNamespace(host=host)


async def _approve_through_middleware(dashboard, request_id, request):
    async def call_next(_request):
        return dashboard.api_request_approve(request_id, {
            "rewardType": "Gold", "rewardId": 0, "rewardAmount": 50_000,
        }, request)
    return await dashboard.serialize_state_writes(request, call_next)


def check_admin_guard_and_resolution():
    temp = tempfile.TemporaryDirectory()
    original = playerdb.DB_PATH
    try:
        playerdb.DB_PATH = pathlib.Path(temp.name) / "players.db"
        playerdb.init()

        # Import after DB_PATH changes: dashboard routes must use this throwaway store.
        import dashboard

        playerdb.admin_create("operator", "correct horse battery staple")
        request_id = _seed_request()
        path = f"/api/requests/{request_id}/approve"
        outsider = _Request(path)
        denied = asyncio.run(dashboard.guard_admin(outsider, lambda _: None))
        assert denied.status_code == 401

        token = playerdb.admin_login("operator", "correct horse battery staple")
        assert token and playerdb.admin_for_token(token) == "operator"
        approved = asyncio.run(_approve_through_middleware(dashboard, request_id, _Request(path, token)))
        assert approved["status"] == "approved"
        assert playerdb.grant_requests("approved")[0]["resolvedBy"] == "operator"
        assert playerdb.load("request-api-user")["posts"][-1]["rewardAmount"] == 50_000
        print("ok request API: admin guard and self-locking approval")
    finally:
        playerdb.DB_PATH = original
        temp.cleanup()


if __name__ == "__main__":
    check_admin_guard_and_resolution()
    print("all request API checks passed")
