"""CDN serving: the real patch-set bundles, the XML bundle, and patch queries.

`_CDN_FILES` is the real patch set cloned byte-for-byte from the Awesomepiece CDN
(https://kgc-cdn-1.awesomepiece.com/patch/LIVE/<patchFolder>/ANDROID/) - guaranteed
version-compatible with the client, so UpdatePatchSetList loads the manifest and
validates hashes without error. AssetHash.txt confirms format <name>:<md5>_<size>;
the manifest is the "ANDROID" file.

Used via `register(app, srv)`: `srv` is the live server module (for SERVER_VERSION,
ROUTE_MODELS and PATCH_FOLDER).
"""
import pathlib

from fastapi import Request
from fastapi.responses import Response

from common import admin_log
from config import ROOT

srv = None      # the live server module, set by register()


def _load_cdn_files():
    real_cdn = ROOT / "real_cdn"
    return ({p.name: p.read_bytes() for p in real_cdn.iterdir()}
            if real_cdn.is_dir() else {})


_CDN_FILES = _load_cdn_files()
admin_log(f"[cdn] cloned {len(_CDN_FILES)} real patch files: {sorted(_CDN_FILES)}")


def register(app, server_module):
    global srv
    srv = server_module
    app.add_api_route("/", health, methods=["GET"])
    app.add_api_route("/patch/{path:path}", cdn_patch, methods=["GET"])
    app.add_api_route("/x2/xls.cgi", cdn_xls_cgi, methods=["GET"])


def health():
    return {"server": "kgc-private", "version": srv.SERVER_VERSION,
            "routes": len(srv.ROUTE_MODELS), "patchFolder": srv.PATCH_FOLDER}


async def cdn_patch(path: str, request: Request):
    host = request.headers.get("host", "?")
    fname = path.split("/")[-1]
    data = _CDN_FILES.get(fname)
    admin_log(f"[{host}] CDN GET /patch/{path} -> {'HIT' if data is not None else 'MISS'}")
    if data is None:
        return Response(status_code=404)
    if fname in ("PatchVersion.txt", "AssetHash.txt"):
        return Response(data, media_type="text/plain")
    return Response(data, media_type="application/octet-stream")


async def cdn_xls_cgi(request: Request):
    """Handle CDN patch-query requests: /x2/xls.cgi?p=XXXX&q=base64data"""
    host = request.headers.get("host", "?")
    q = request.query_params.get("q", "")
    p = request.query_params.get("p", "")
    admin_log(f"[{host}] CDN XLS query p={p} q_len={len(q)}")
    return Response(srv.PATCH_FOLDER.encode(), media_type="text/plain")