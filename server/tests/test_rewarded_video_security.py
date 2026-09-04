"""Browser callbacks must never mint a player-portal ticket."""
from pathlib import Path
import sys
import tempfile

from fastapi import FastAPI
from fastapi import HTTPException
import pytest


_SERVER = Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

import playerdb


class _Request:
    def __init__(self, token):
        self.headers = {}
        self.cookies = {"kgc_player": token}


def test_browser_rewarded_completion_is_disabled_without_provider_proof():
    with tempfile.TemporaryDirectory() as temp_dir:
        previous_db = playerdb.DB_PATH
        try:
            playerdb.DB_PATH = Path(temp_dir) / "players.db"
            playerdb.init()

            import playerportal
            previous_ad_unit = playerportal.GAM_REWARDED_AD_UNIT_PATH
            playerportal.GAM_REWARDED_AD_UNIT_PATH = "/123/test-rewarded"
            app = FastAPI()
            playerportal.register(app)
            playerdb.save("player-1", {"uid": "player-1", "name": "Player"})
            playerdb.bind_login("Guest_VIDEO", "player-1")
            playerdb.portal_guest_access("Guest_VIDEO", "video_user", "safe-password")
            token, *_ = playerdb.portal_password_login("video_user", "safe-password")
            request = _Request(token)
            routes = {route.path: route.endpoint for route in app.routes
                      if getattr(route, "path", "") in {
                          "/portal/api/ticket/video/start",
                          "/portal/api/ticket/video/complete",
                      }}

            with pytest.raises(HTTPException) as start:
                routes["/portal/api/ticket/video/start"](request)
            assert start.value.status_code == 503
            with pytest.raises(HTTPException) as complete:
                routes["/portal/api/ticket/video/complete"](request, {"sessionId": "forged"})
            assert complete.value.status_code == 503
            assert playerdb.ticket_status("Guest_VIDEO")["balance"] == 0
        finally:
            if "playerportal" in locals():
                playerportal.GAM_REWARDED_AD_UNIT_PATH = previous_ad_unit
            playerdb.DB_PATH = previous_db
