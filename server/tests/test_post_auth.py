"""POST /auth must mint a session exactly like GET /auth.

v173 sends the account Auth as **POST /auth** (the live client shows zero GET
/auth traffic). The route_models fallback answered an empty AuthResponseModel
(no accessToken), so logout -> guest re-login ran Login token-less, r_login
refused it, and the client fell onto the throwaway template save - the
"KingBug/BugCastle" ghost account. This pins the POST route to the same mint.
"""
import copy
import sys
import tempfile
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
import server

GUEST = 4   # Constants.AccountType


def test_post_auth_mints_for_a_returning_guest():
    temp_dir = Path(tempfile.mkdtemp())
    playerdb.DB_PATH = temp_dir / "players.db"
    playerdb.init()

    from fastapi.testclient import TestClient
    guest = "guest-post-auth-ci"
    with TestClient(server.app, client=("10.7.7.7", 55000)) as tc:
        registered = tc.post("/auth/register", json={"id": guest, "type": GUEST})
        assert server.aes_decrypt(registered.content).get("success") is True

        # returning-guest auth: id in the JSON body (the v173 REST call shape)
        auth = tc.post("/auth", json={"id": guest, "cookie": "x",
                                      "platform": "Android"})
        out = server.aes_decrypt(auth.content)
        assert out.get("success") is True, out
        token = out.get("accessToken")
        assert token, "POST /auth must mint a session token"
        uid = playerdb.uid_for_token(token)
        assert uid and uid.startswith("p-"), uid

        # id in the query string must work too (mirrors GET /auth?id=...)
        queryy = tc.post(f"/auth?id={guest}")
        out2 = server.aes_decrypt(queryy.content)
        assert out2.get("success") is True and out2.get("accessToken"), out2

        # an unknown, ungranted Guest id must NOT mint through POST /auth
        denied = tc.post("/auth", json={"id": "guest-unknown"})
        assert server.aes_decrypt(denied.content).get("success") is False