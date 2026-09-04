"""Dashboard cookie mutations must not accept a browser request from another origin."""
import sys
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

import dashboard
from fastapi import HTTPException


class _Request:
    class url:
        scheme = "https"

    headers = {"host": "admin.example.test", "origin": "https://evil.example.test"}


def test_dashboard_rejects_cross_site_origin(monkeypatch):
    monkeypatch.setattr(dashboard, "TRUST_PROXY", False)
    try:
        dashboard._same_origin(_Request())
    except HTTPException as error:
        assert error.status_code == 403
    else:
        raise AssertionError("cross-site dashboard request was accepted")


def test_dashboard_accepts_its_own_forwarded_https_origin(monkeypatch):
    class Request(_Request):
        headers = {
            "host": "admin.example.test",
            "origin": "https://admin.example.test",
            "x-forwarded-proto": "https",
        }

    monkeypatch.setattr(dashboard, "TRUST_PROXY", True)
    dashboard._same_origin(Request())


def test_dashboard_cookie_is_secure_only_for_the_browser_facing_https_scheme(monkeypatch):
    class Request(_Request):
        headers = {"host": "admin.example.test", "x-forwarded-proto": "https"}

    monkeypatch.setattr(dashboard, "TRUST_PROXY", True)
    assert dashboard._cookie_is_secure(Request())

    Request.headers["x-forwarded-proto"] = "http"
    assert not dashboard._cookie_is_secure(Request())

    monkeypatch.setattr(dashboard, "TRUST_PROXY", False)
    Request.url.scheme = "https"
    assert dashboard._cookie_is_secure(Request())


def test_dashboard_login_sets_the_secure_cookie_flag_for_a_proxied_https_request(monkeypatch):
    class Request:
        class client:
            host = "198.51.100.10"

        class url:
            scheme = "http"

        headers = {"host": "admin.example.test", "x-forwarded-proto": "https"}

    monkeypatch.setattr(dashboard, "TRUST_PROXY", True)
    monkeypatch.setattr(dashboard.playerdb, "admin_login", lambda *_args: "admin-session")
    dashboard._login_hits.clear()
    response = dashboard.api_login(Request(), {"username": "operator", "password": "secret"})
    assert "secure" in response.headers["set-cookie"].lower()


def test_dashboard_static_fallback_cannot_escape_the_export_root():
    try:
        dashboard.ui_path("../../dashboard.py", _Request())
    except HTTPException as error:
        assert error.status_code == 404
    else:
        raise AssertionError("static dashboard fallback exposed a source file")


def test_dashboard_static_fallback_still_serves_an_exported_page():
    response = dashboard.ui_path("players", _Request())
    assert Path(response.path).resolve() == dashboard.UI_ROOT / "players.html"
