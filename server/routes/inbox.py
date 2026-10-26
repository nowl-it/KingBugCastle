"""Inbox, which the client calls Post: GET /post lists mail, POST /post/receive claims.

Mail lives on the save, so it persists and disappears once claimed, and the reward is
applied to player state on claim - the send -> receive -> grant flow is real, not
cosmetic.

`PostData.title/text` are LOCALIZATION KEYS, not literals: an unresolved key renders
as the client's "You got a gift" default. Custom literal text goes out under an
`@raw:` prefix which the native XIGNCODE stub's `PostListItem.Set` hook strips before
writing the label - no CDN Strings rebuild needed. `_process_posts` is what puts the
prefix on, so anything the dashboard sends is shown verbatim.

These three are direct `@app` routes rather than DYNAMIC_OVERRIDES entries: GET /post
has no request body to dispatch on, and /admin/sendmail answers plain JSON to the
dashboard rather than an AES envelope to the game.

Uses the `register(app, srv)` pattern.

    python3 inbox.py     # self-check
"""
import json

from common import admin_log, now_iso
from rewards import _WIRE_TYPE
from fastapi import Request
from fastapi.responses import JSONResponse, Response
from state import load_state, save_state

srv = None      # the live server module, set by register()


def _default_posts():
    return [{
        "id": 1, "type": "Normal",
        "title": "NOwL Private Server",
        "text": "Chào mừng đến private server! Thư test custom title/text. Nhận 1000 Vàng nhé.",
        "rewardType": "Gold", "rewardId": 0, "rewardAmount": 1000,
        "untilAt": now_iso(30),
    }]


def get_st_posts(st):
    if "posts" not in st:
        st["posts"] = _default_posts()
    return st["posts"]


def _ensure_raw_prefix(s: str) -> str:
    return s if s.startswith("@raw:") else "@raw:" + s


def _process_posts(posts: list) -> list:
    out = []
    for p in posts:
        p = dict(p)
        if isinstance(p.get("title"), str):
            p["title"] = _ensure_raw_prefix(p["title"])
        if isinstance(p.get("text"), str):
            p["text"] = _ensure_raw_prefix(p["text"])
        # Translate the server's reward vocabulary to the client's so the icon
        # resolves correctly ("Unit" → "Card", "Item" → "InventoryItem", etc.).
        rt = p.get("rewardType")
        if rt and rt in _WIRE_TYPE:
            p["rewardType"] = _WIRE_TYPE[rt]
        out.append(p)
    return out


def claim(st, post_id=0, receive_all=False):
    """Claim mail and grant what it carries. Returns (claimed_posts, wire_reward_list).

    Reward grant goes through srv._grant_reward, which is the same path the mission
    and shop claims use - Artifact/Treasure/Accessory are deliberately NOT granted
    into state there (it trips ArtifactOptionUI); gift those as an Item reward box.

    Duplicate overcome-track heroes (dimension/incarnation) come back as
    Dimension/IncarnationOvercome with count = the NEW TOTAL, because the client's
    reward handler assigns `card.overcome = count` outright (it does not add) - same
    convention as the gacha path. A brand-new overcome hero keeps its Card entry (so
    the client AddCards it) plus a companion overcome line, since the client-side
    Card handler creates the card with overcome 0."""
    posts = get_st_posts(st)
    claimed = [p for p in posts if receive_all or p["id"] == post_id]
    reward_list = []
    for p in claimed:
        amt = p.get("rewardAmount", 0)
        rt = p.get("rewardType", "")
        rid = p.get("rewardId", 0)
        upgraded = srv._grant_reward(st, rt, rid, amt)
        if amt or rid:
            entry = {"type": rt, "id": rid, "count": amt}
            if rt in ("Unit", "Card") and rid:
                wt = srv._overcome_wire_type(rid)
                c = st.get("cards", {}).get(str(rid))
                if wt and c and c.get("overcome", 0) > 0:
                    if upgraded:
                        # duplicate: absolute overcome replaces the Unit entry
                        entry = {"type": wt, "id": rid, "count": c["overcome"]}
                    else:
                        # first grant: Card entry creates the client-side card,
                        # companion entry carries the 1-star overcome onto it
                        reward_list.append(entry)
                        entry = {"type": wt, "id": rid, "count": c["overcome"]}
            reward_list.append(entry)
    st["posts"] = [p for p in posts if p not in claimed]
    save_state(st)
    return claimed, reward_list


def register(app, server_module):
    global srv
    srv = server_module

    @app.post("/admin/sendmail")
    async def admin_send_mail(request: Request):
        st = load_state()
        try:
            raw = await srv._read_capped(request)
        except ValueError:
            return JSONResponse({"error": "request body too large"}, status_code=413)
        try:
            body = json.loads(raw) if raw else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        if not isinstance(body, dict):
            return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
        if "posts" not in st:
            st["posts"] = []
        next_id = max((p["id"] for p in st["posts"]), default=0) + 1
        st["posts"].append({
            "id": next_id,
            "type": body.get("type", "Normal"),
            "title": body.get("title", ""),
            "text": body.get("text", ""),
            "rewardType": body.get("rewardType", ""),
            "rewardId": body.get("rewardId", 0),
            "rewardAmount": body.get("rewardAmount", 0),
            "untilAt": now_iso(body.get("untilDays", 30)),
        })
        save_state(st)
        return {"code": 200, "success": True, "postId": next_id}

    @app.get("/post")
    async def post_list_direct(request: Request):
        st = load_state()
        host = request.headers.get("host", "?")
        admin_log(f"[{host}] DIRECT GET /post -> PostResponseModel")
        payload = {"code": 200, "msg": None, "success": True,
                   "posts": _process_posts(get_st_posts(st))}
        return Response(srv.aes_encrypt(payload), media_type="application/json",
                        headers={"encryptedWithHex": "true"})

    @app.post("/post/receive")
    async def post_receive_direct(request: Request):
        st = load_state()
        host = request.headers.get("host", "?")
        try:
            raw = await srv._read_capped(request)
        except ValueError:
            return JSONResponse({"error": "request body too large"}, status_code=413)
        body = {}
        if raw:
            try:
                body = srv.aes_decrypt(raw)
            except Exception:
                try:
                    body = json.loads(raw)
                except Exception:
                    pass
        got, reward_list = claim(st, body.get("postId", 0), body.get("receiveAll", False))
        admin_log(f"[{host}] DIRECT POST /post/receive claimed={len(got)} "
                  f"-> PostReceiveResponseModel")
        # PostReceiveResponseModel is only `rewardListResponseData` - top-level
        # playerGold/Cash/Heart here would be parsed into nothing, and the client
        # does NOT re-fetch after a claim. HandleRewardListResponseData pushes a
        # non-null treasureResult through HandleTreasureResult, which rebuilds the
        # inventory cache from `inventories` (and merges treasures); without it a
        # claimed item only shows up after a game restart.
        payload = {
            "code": 200, "msg": None, "success": True,
            "rewardListResponseData": {
                "rewardList": srv._wire_rewards(reward_list),
                "artifactResult": None,
                "treasureResult": {
                    "treasures": srv.get_st_treasures(st),
                    "deletedTreasures": [],
                    "playerGold": st.get("gold", 0),
                    "playerCash": st.get("cash", 0),
                    "inventories": srv._inventory_models(st),
                    "addedExpItems": 0,
                },
                "accessoryResult": None,
            },
        }
        return Response(srv.aes_encrypt(payload), media_type="application/json",
                        headers={"encryptedWithHex": "true"})


def handlers():
    """No DYNAMIC_OVERRIDES entries - all three routes are direct @app routes."""
    return {}


if __name__ == "__main__":
    import pathlib as _pl
    import sys
    import tempfile

    import playerdb
    playerdb.DB_PATH = _pl.Path(tempfile.mkdtemp()) / "t.db"
    playerdb.init()
    import server                                        # noqa: E402
    register(server.app, sys.modules["server"])

    st = server.copy.deepcopy(server.DEFAULT_PLAYER)
    st["uid"] = "t"
    playerdb.save("t", st)
    playerdb.set_active("t")

    posts = get_st_posts(st)
    assert posts, "an empty inbox on a fresh save"

    # Titles must go out prefixed, or the client renders them as localization keys.
    wire = _process_posts(posts)
    assert all(p["title"].startswith("@raw:") for p in wire), wire
    assert _ensure_raw_prefix("@raw:x") == "@raw:x", "the prefix must not double up"

    # Claiming grants, and the mail is gone afterwards.
    gold = st.get("gold", 0)
    got, rewards = claim(st, posts[0]["id"])
    assert len(got) == 1 and rewards, (got, rewards)
    assert st["gold"] == gold + 1000, "the claimed gold never reached the save"
    assert get_st_posts(st) == [], "a claimed mail came back"

    # Claiming nothing must not pay.
    got, rewards = claim(st, 999)
    assert got == [] and rewards == []
    assert st["gold"] == gold + 1000, "claiming nothing still paid"

    print("inbox self-check ok (3 direct routes)")
