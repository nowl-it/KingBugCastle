"""Focused proof that Player Dashboard OAuth is isolated from the game ASGI app.

No TestClient: this host's HTTP test transport can hang, while the contract here
is route ownership, redirect URI selection, and the direct callback result.
"""
import base64
import json
import pathlib
import sys
import tempfile

from fastapi import FastAPI

_SERVER = pathlib.Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

import google_login
import playerdb


def _id_token(sub):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


class _Request:
    client = None
    headers = {}


def check_portal_callback_is_a_separate_origin_and_route():
    temp = tempfile.TemporaryDirectory()
    previous = (playerdb.DB_PATH, google_login.CLIENT_ID, google_login.CLIENT_SECRET,
                google_login.PUBLIC_URL, google_login.PORTAL_PUBLIC_URL,
                google_login._exchange_code)
    try:
        playerdb.DB_PATH = pathlib.Path(temp.name) / "players.db"
        playerdb.init()
        playerdb.save("p-google", {"uid": "p-google", "name": "Portal King"})
        playerdb.bind_login("google_42", "p-google")
        google_login.CLIENT_ID = "client"
        google_login.CLIENT_SECRET = "secret"
        google_login.PUBLIC_URL = "https://kingbugcastle.id.vn"
        google_login.PORTAL_PUBLIC_URL = "https://player.kingbugcastle.id.vn"
        google_login._exchange_code = lambda *_: {"id_token": _id_token("42")}

        portal_url = google_login.authorize_url("portal")
        assert "redirect_uri=https%3A%2F%2Fplayer.kingbugcastle.id.vn%2Fportal%2Fapi%2Fauth%2Fgoogle%2Fcallback" in portal_url
        assert google_login.state_target(portal_url.split("state=")[1].split("&")[0]) == "portal"

        game_app, portal_app = FastAPI(), FastAPI()
        google_login.register_game(game_app)
        google_login.register_portal(portal_app)
        game_routes = {route.path for route in game_app.routes}
        portal_routes = {route.path for route in portal_app.routes}
        assert "/glogin/callback" in game_routes
        assert "/portal/api/auth/google/callback" not in game_routes
        assert "/portal/api/auth/google/callback" in portal_routes
        assert "/glogin/callback" not in portal_routes

        response = google_login._complete_callback(
            _Request(), "code", google_login.make_state("portal"), "", "portal")
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "kgc_player=" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
        print("ok portal oauth: distinct callback/origin and portal-only cookie")
    finally:
        (playerdb.DB_PATH, google_login.CLIENT_ID, google_login.CLIENT_SECRET,
         google_login.PUBLIC_URL, google_login.PORTAL_PUBLIC_URL,
         google_login._exchange_code) = previous
        temp.cleanup()


if __name__ == "__main__":
    check_portal_callback_is_a_separate_origin_and_route()
    print("all portal OAuth split checks passed")
