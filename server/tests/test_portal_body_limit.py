"""The standalone Player Portal must enforce the shared streaming body cap."""
import sys
import types
from pathlib import Path

import anyio
import httpx
from fastapi import FastAPI


_SERVER = Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

import security


async def _post_chunked(app, chunks):
    async def body():
        for chunk in chunks:
            yield chunk

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post("/body", content=body(),
                                 headers={"content-type": "application/json"})


async def _get(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/status")


def test_chunked_body_is_rejected_before_fastapi_parses_it():
    app = FastAPI()
    app.add_middleware(security.CappedBodyMiddleware, max_body=10)

    @app.post("/body")
    async def body(payload: dict):
        return payload

    response = anyio.run(_post_chunked, app, [b'{"value":', b'"too-long"}'])
    assert response.status_code == 413
    assert response.json() == {"error": "request body too large"}


def test_small_chunked_body_still_reaches_the_handler():
    app = FastAPI()
    app.add_middleware(security.CappedBodyMiddleware, max_body=10)

    @app.post("/body")
    async def body(payload: dict):
        return payload

    response = anyio.run(_post_chunked, app, [b'{"x":', b'123}'])
    assert response.status_code == 200
    assert response.json() == {"x": 123}


def test_bodyless_get_survives_base_http_middleware():
    """The cap must not synthesize an early disconnect while a response streams."""
    app = FastAPI()
    security.register_public(app)

    @app.get("/status")
    async def status():
        return {"ok": True}

    response = anyio.run(_get, app)
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_portal_registration_installs_the_public_body_boundary():
    app = FastAPI()
    security.register_portal(app)
    assert any(middleware.cls is security.CappedBodyMiddleware
               for middleware in app.user_middleware)


def test_public_registration_installs_rate_and_body_boundaries():
    app = FastAPI()
    security.register_public(app)
    layers = [(middleware.cls, middleware.kwargs.get("dispatch"))
              for middleware in app.user_middleware]
    assert [dispatch.__name__ if dispatch else cls.__name__ for cls, dispatch in layers] == [
        "CappedBodyMiddleware", "rate_limit",
    ]


def test_game_request_rejections_wrap_the_state_lock(monkeypatch):
    app = FastAPI()
    server_module = types.SimpleNamespace()
    monkeypatch.setattr(security, "srv", server_module)
    security.register(app, server_module)

    layers = [(middleware.cls, middleware.kwargs.get("dispatch"))
              for middleware in app.user_middleware]
    assert [dispatch.__name__ if dispatch else cls.__name__ for cls, dispatch in layers] == [
        "guard_admin", "rate_limit", "CappedBodyMiddleware", "serialize_state_writes",
    ]
