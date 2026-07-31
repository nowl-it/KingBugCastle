"""Rate-abuse handling: repeated 429s escalate to a temporary ban.

The ban must refuse BEFORE touching the rate table, so a spammer can no longer
burn a state-lock cycle (or the event loop) per request, and it must lift on
its own. The firewall hook is exercised nowhere here - it is opt-in and needs a
sudoers rule that CI must not have.
"""
import os, pathlib, sys, tempfile, time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import playerdb

playerdb.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "players.db"
playerdb.init()

import server                                       # noqa: E402
from fastapi.testclient import TestClient           # noqa: E402

# Other test modules may have imported server.py first with default env, and the
# module globals are read at import time - so pin them directly (same pattern as
# test_public_hardening's server.ADMIN_TOKEN reset).
server.RATE_LIMIT = 5
server.RATE_WINDOW = 60
server.RATE_BAN_AFTER = 2
server.RATE_BAN_SECONDS = 300
server.IPTABLES_BAN = False                          # never touch real firewalls

IP = "198.51.100.7"


def _client():
    return TestClient(server.app, client=(IP, 40000))


def _reset():
    server._rate_hits.clear()
    server._banned.clear()
    server._ban_strikes.clear()


def test_burst_over_limit_gets_429_then_banned():
    _reset()
    c = _client()
    assert [c.get("/").status_code for _ in range(5)] == [200] * 5
    assert c.get("/").status_code == 429       # strike 1
    assert c.get("/").status_code == 429       # strike 2 -> ban
    assert IP in server._banned


def test_banned_ip_is_refused_without_touching_rate_table():
    _reset()
    server._banned[IP] = time.time() + 300
    c = _client()
    assert c.get("/").status_code == 429
    server._rate_hits.clear()                  # fresh window - still banned
    assert c.get("/").status_code == 429
    assert IP in server._banned


def test_ban_expires_on_its_own():
    _reset()
    server._banned[IP] = time.time() - 1       # expired
    assert _client().get("/").status_code == 200
    assert IP not in server._banned


def test_healthy_request_clears_strikes():
    _reset()
    c = _client()
    for _ in range(5):
        c.get("/")
    assert c.get("/").status_code == 429       # strike 1
    server._rate_hits.clear()                  # new window
    assert c.get("/").status_code == 200       # healthy -> strikes reset
    for _ in range(4):
        c.get("/")
    assert c.get("/").status_code == 429       # strike 1 again, not a ban yet
    assert IP not in server._banned


def test_cdn_is_not_rate_limited():
    _reset()
    server._banned[IP] = time.time() + 300
    c = _client()
    assert c.get("/patch/x/manifest").status_code in (200, 404)
