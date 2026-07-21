#!/usr/bin/env python3
"""KGC private server emulator.

Reconstructed from il2cpp dump (RestAPI class + Awesomepiece.Model + route strings).
Implements the full login critical path so the client boots past the title screen,
plus a generic dispatcher that returns a wire-valid ResponseModel for all ~284
endpoints. Player save is a single editable JSON in state/player.json with full
state persistence for cards, decks, inventory, missions, and game loop.

Run:  uvicorn server:app --host 0.0.0.0 --port 8080
"""
import asyncio, contextvars, json, time, copy, secrets, datetime, pathlib, hashlib, os, sys
import playerdb
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, HTMLResponse
from Crypto.Cipher import AES

AES_KEY = b"b53019bb76da6b34"

LOG_BUF = []

def admin_log(*args):
    msg = datetime.datetime.now().strftime("%H:%M:%S") + " " + " ".join(str(a) for a in args)
    LOG_BUF.append(msg)
    if len(LOG_BUF) > 500:
        LOG_BUF[:] = LOG_BUF[-400:]
    print(*args, file=sys.stderr)

def aes_encrypt(payload: dict) -> bytes:
    # Space-pad to 16-byte blocks (NOT PKCS7): the client's Newtonsoft JSON reader
    # throws "Additional text after JSON" on non-whitespace trailing bytes, but
    # tolerates trailing spaces. (Confirmed via JsonReaderException at runtime.)
    raw = json.dumps(payload).encode()
    if len(raw) % 16:
        raw += b" " * (16 - len(raw) % 16)
    return AES.new(AES_KEY, AES.MODE_ECB).encrypt(raw)

def aes_decrypt(data: bytes) -> dict:
    # Some request bodies (e.g. /deck/set) arrive as ASCII hex text of the
    # ciphertext, not raw binary - matches the "encryptedWithHex" header name
    # literally. Endpoints with meaningful POST bodies need this; GET-only /
    # body-ignoring endpoints never exposed the bug. Detect and unwrap first.
    if len(data) % 2 == 0 and all(c in b"0123456789abcdefABCDEF" for c in data):
        try:
            data = bytes.fromhex(data.decode("ascii"))
        except ValueError:
            pass
    # Tolerant of any padding scheme the client uses (PKCS7, space, or null):
    # decode the first JSON object and ignore trailing pad bytes.
    raw = AES.new(AES_KEY, AES.MODE_ECB).decrypt(data)
    text = raw.decode("utf-8", "ignore").lstrip()
    return json.JSONDecoder().raw_decode(text)[0]

ROOT = pathlib.Path(__file__).parent
G = ROOT / "generated"
MODELS = json.loads((G / "models.json").read_text())
ROUTE_MODELS = json.loads((G / "route_models.json").read_text())
ROUTE_MODELS.update({
    "/treasure": {"method": "Treasure", "response": "TreasureResultResponseModel"},
    "/treasure/equip": {"method": "TreasureEquip", "response": "TreasureResultResponseModel"},
    "/treasure/add-exp": {"method": "TreasureAddExp", "response": "TreasureResultResponseModel"},
    "/treasure/dismantle": {"method": "TreasureDismantle", "response": "TreasureResultResponseModel"},
    "/treasure/release-equip": {"method": "TreasureReleaseEquip", "response": "TreasureResultResponseModel"},
    "/treasure/set-state": {"method": "TreasureSetState", "response": "TreasureResultResponseModel"},
    "/treasure/overcome": {"method": "TreasureOvercome", "response": "TreasureResultResponseModel"},
})
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Player state lives in state/players.db (SQLite, WAL). The old JSON files are
# imported once and then left alone as a cold backup - they are NOT read again.
_migrated = playerdb.migrate_from_json(STATE_DIR)
if _migrated:
    admin_log(f"[state] migrated {_migrated} player(s) from JSON into {playerdb.DB_PATH.name}")

# All response data that isn't request-time-computed logic lives under data/ as
# JSON - editable without touching code, and the shape mirrors what a future
# SQL migration would look like (one table/row per file/key).
DATA_DIR = ROOT / "data"
RCFG = json.loads((DATA_DIR / "response_config.json").read_text())
STATIC_OVERRIDES = json.loads((DATA_DIR / "static_overrides.json").read_text())
ITEM_TEMPLATES = json.loads((DATA_DIR / "item_templates.json").read_text())

PATCH_FOLDER = RCFG["server"]["patchFolder"]
SERVER_VERSION = RCFG["server"]["serverVersion"]

# Multiple routes sharing one canonical static payload (avoids duplicating the
# same blob under several keys in static_overrides.json).
_STATIC_ALIASES = {
    "/shop/refreshDailyShop": "/shop",
    "/decoration/advisor/contract": "/decoration",
    "/decoration/advisor/equip": "/decoration",
    "/decoration/advisor/extend": "/decoration",
    "/decoration/map-skin/equip": "/decoration",
    "/decoration/map-skin/buy": "/decoration",
    "/decoration/map-skin/favorite": "/decoration",
    "/decoration/login-skin/equip": "/decoration",
}
for _alias, _canonical in _STATIC_ALIASES.items():
    STATIC_OVERRIDES[_alias] = STATIC_OVERRIDES[_canonical]

def next_reset_iso(days=1):
    """Next UTC-midnight rollover boundary, `days` out.

    `tomorrow` / `nextWeek` are DERIVED, never served from stored state.
    Scene_Lobby.Update polls `if (now >= playerData.tomorrow_) FetchNextDay()`
    once a second, and FetchNextDay re-runs the whole login + lobby fetch chain.
    A stored value is frozen at account-creation time, so the check goes
    permanently true and the client re-logins at 1 Hz forever.
    """
    midnight = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (midnight + datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def now_iso(delta_days=0):
    return (datetime.datetime.utcnow() + datetime.timedelta(days=delta_days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

# Set per request from the `accesstoken` header (see resolve_player middleware).
# None = no session -> fall back to the admin-selected active player, which is
# what every single-player setup and the whole pre-login boot sequence relies on.
CURRENT_UID = contextvars.ContextVar("current_uid", default=None)

# Auto-creating a save for an unknown account id is right for a real multi-player
# server and wrong for a single-player one, where a reinstall or a cleared cache
# would mint a fresh empty save and look exactly like losing your progress.
MULTIPLAYER = os.environ.get("KGC_MULTIPLAYER") == "1"
MAX_PLAYERS = int(os.environ.get("KGC_MAX_PLAYERS") or 200)
admin_log(f"[state] identity mode: {'multiplayer (account id -> own save)' if MULTIPLAYER else 'single-player (everyone -> active save)'}")

def load_state():
    """State of the player this request belongs to.

    Identity comes from the `accesstoken` header, bound to a uid at login. With
    no session (pre-login boot, CDN, admin UI) this is the active player.
    """
    uid = CURRENT_UID.get() or playerdb.active()
    if uid:
        st = playerdb.load(uid)
        if st is not None:
            return st
    st = copy.deepcopy(DEFAULT_PLAYER)
    uid = st.get("uid", "dev-0001")
    playerdb.save(uid, st)
    playerdb.set_active(uid)
    return st

def save_state(st):
    playerdb.save(st.get("uid", "dev-0001"), st)

def patch_state(st, updates):
    st.update(updates)
    save_state(st)

# Prefer user-edited master data in server/xml_live, then CDN-synced.
_XML_LIVE = ROOT / "xml_live"
XML_DIR = _XML_LIVE if _XML_LIVE.is_dir() else ROOT.parent / "xml" / PATCH_FOLDER
assert XML_DIR.is_dir(), f"XML master data not found: {XML_DIR}"
admin_log(f"[xml] master data dir: {XML_DIR} ({len(list(XML_DIR.iterdir()))} files)")

def _all_hero_ids():
    """Playable heroes = <Type>Player</Type>, id 1xxxx, from Units.xml."""
    import re
    txt = (XML_DIR / "Units.xml").read_text(encoding="utf-8")
    ids = []
    for blk in re.split(r'(?=<Unit ID=)', txt):
        m = re.match(r'<Unit ID="(\d+)"', blk)
        if not m:
            continue
        uid = int(m.group(1))
        t = re.search(r'<Type>(\w+)</Type>', blk)
        if t and t.group(1) == "Player" and 10000 <= uid < 20000:
            visible = re.search(r'<Visible>(false|False)</Visible>', blk)
            summoner = re.search(r'<Summoner>', blk)
            min_ver = re.search(r'<MinVersion>(\d+)</MinVersion>', blk)
            is_unreleased = min_ver and int(min_ver.group(1)) > 170100
            if not visible and not summoner and not is_unreleased:
                ids.append(uid)
    return ids

ALL_HERO_IDS = _all_hero_ids()

def _all_artifact_ids():
    """Real collectible artifacts (Type=Artifact) from Artifacts.xml, Root/
    Normal tier only (King/God/KingGod tier IDs are the same artifact at
    higher quality, not separate items). Excludes FromType=Special (Ghidra:
    ResourceArtifact.FromType enum value 5) - these are synthesis-stone
    materials (e.g. id 501/511/598, "합성석"), and live testing (2026-07-02)
    confirmed InventoryPanel.GetArtifactItems NullReferenceExceptions trace
    to exactly these 3 IDs; ResourceBase<ResourceArtifact>.Get() apparently
    never registers FromType=Special entries in its lookup dictionary."""
    import re
    txt = (XML_DIR / "Artifacts.xml").read_text(encoding="utf-8")
    txt = re.sub(r'<!--.*?-->', '', txt, flags=re.DOTALL)
    ids = []
    for blk in re.split(r'(?=<Artifact ID=)', txt):
        m = re.match(r'<Artifact ID="(\d+)"', blk)
        if not m:
            continue
        aid = int(m.group(1))
        t = re.search(r'<Type>(\w+)</Type>', blk)
        if not t or t.group(1) != "Artifact":
            continue
        from_type = re.search(r'<FromType>(\w+)</FromType>', blk)
        if from_type and from_type.group(1) in ("Special", "RogueLike", "RogueLikeBuildingArtifact", "Event"):
            continue
        min_ver = re.search(r'<MinVersion>(\d+)</MinVersion>', blk)
        if min_ver and int(min_ver.group(1)) > 170100:
            continue
        level_m = re.search(r'<Level>(.*?)</Level>', blk)
        level = level_m.group(1) if level_m else "Normal"
        if aid not in ids:
            ids.append(aid)
            
        # Store level info for option generation
        if not hasattr(_all_artifact_ids, 'levels'):
            _all_artifact_ids.levels = {}
        _all_artifact_ids.levels[aid] = level

    return ids, getattr(_all_artifact_ids, 'levels', {})

def _all_treasure_ids():
    """Real treasures from Treasures.xml, excluding unreleased (MinVersion)."""
    import re
    txt = (XML_DIR / "Treasures.xml").read_text(encoding="utf-8")
    txt = re.sub(r'<!--.*?-->', '', txt, flags=re.DOTALL)
    ids = []
    for blk in re.split(r'(?=<Treasure ID=)', txt):
        m = re.match(r'<Treasure ID="(\d+)"', blk)
        if not m:
            continue
        min_ver = re.search(r'<MinVersion>(\d+)</MinVersion>', blk)
        if min_ver and int(min_ver.group(1)) > 170100:
            continue
        tid = int(m.group(1))
        if tid == 20099:
            continue
        ids.append(tid)
    return ids

def _all_rift_weapon_ids():
    """Real rift weapons from RiftWeapons.xml (one per class/role, 6 total)."""
    import re
    txt = (XML_DIR / "RiftWeapons.xml").read_text(encoding="utf-8")
    txt = re.sub(r'<!--.*?-->', '', txt, flags=re.DOTALL)
    return [int(m) for m in re.findall(r'<RiftWeapon ID="(\d+)"', txt)]

def _rift_building_count():
    """How many altars a rift crystal carries a level for.

    Buildings.xml holds two ranges: the 6 in-battle altars (ids 0-5) and the
    upgradeable altars (ids 100+) that `BuildingName_0..N` name and that
    RiftWeaponBuffs.xml's `Building` attribute indexes into ("building indexes :
    제단 인덱스 (Buildings.xml id)" per that file's own header).

    `RiftCrystalModel.buildingLevels` is one level per altar in that second range,
    positioned by each entry's own `<Index>` (0-8), not by its id. `GetMaxBuildingIdx`
    (v171 RVA 0x2CCA1B4) walks the whole list and returns the index of the largest
    value, so a list shorter than the altar count silently hides every altar past its
    end - which is why a 3-element list always resolved to altar 0 ("Rift Crystal of
    Hero") no matter what the crystal was meant to be.

    Parsed with ElementTree, not a regex: Buildings.xml quotes its attributes with
    single quotes, so the `ID="..."` pattern the other loaders here use matches nothing
    and would silently report zero altars.
    """
    import xml.etree.ElementTree as _ET
    root = _ET.parse(XML_DIR / "Buildings.xml").getroot()
    idxs = [int(b.findtext("Index") or -1) for b in root
            if (b.findtext("Name") or "").startswith("BuildingName_")]
    assert idxs, "Buildings.xml has no BuildingName_* altars - rift crystals would be empty"
    return max(idxs) + 1

def _all_inventory_item_ids():
    """Consumables/keys/tokens/boxes from InventoryItems.xml."""
    import re
    txt = (XML_DIR / "InventoryItems.xml").read_text(encoding="utf-8")
    txt = re.sub(r'<!--.*?-->', '', txt, flags=re.DOTALL)
    return [int(m) for m in re.findall(r'<InventoryItem ID="(\d+)"', txt)]

ALL_ITEM_IDS = _all_inventory_item_ids()

# Seed data (player identity/currencies, card template, deck presets) lives in
# data/default_player.json - editable without touching code, simulates a DB
# seed row. Only used to build state/player.json on first boot; after that
# the live file is the source of truth.
SEED = json.loads((ROOT / "data" / "default_player.json").read_text())
INV_COUNT = SEED["invCount"]

# God account: own every hero, level 30. Units.xml only defines Tier='1'
# potential (ReqLevel=16, matches Constants.PotentialTier.Max=1 in the client) -
# level 30 >= 16 so potentialTier=1 (awakened) is correct. An earlier retest
# blamed potentialTier=1 for the DeckPanel boot crash, but Ghidra (2026-07-02,
# arm32 dump.cs FUN_01e1a018) proved the real cause was deck length vs.
# DeckPanel.currentDeck's fixed 6-slot UI array (see DEFAULT_DECKS below) -
# potentialTier was never the culprit, that test just happened to run before
# the deck-length fix was in place.
DEFAULT_CARDS = {
    str(uid): {"unitId": uid, **SEED["cardTemplate"]}
    for uid in ALL_HERO_IDS
}

# Ghidra-confirmed (2026-07-02, arm32 dump.cs offsets, FUN_01e1a018/DeckPanel.
# ReloadDeck @0x1e1a018): the loop bound is DeckPanel.currentDeck (UnitCard[]
# @0xa4), a Unity-prefab-FIXED-size UI array, not server data - it indexes
# PlayerData.currentDeck (our deck array, int[] @0x5c on PlayerData) with that
# fixed bound, so our deck must be >= DeckPanel's fixed UI slot count or it
# throws IndexOutOfRangeException. WorldPanel.ReloadLobbyDeck (@0x21f4b98) is
# the mirror case: it loops over OUR deck length and indexes its own fixed
# lobbyDeckObjects/lobbyDeckParents/lobbyDeckUnitName arrays, so our deck must
# be <= that fixed UI slot count. Testing deck=6 now to find where both fixed
# sizes actually land (previous 5-vs-6 flip-flop was guesswork, not verified
# against decompiled bounds).
DEFAULT_DECKS = SEED["decks"]
DECK_SLOTS = len(DEFAULT_DECKS[0]["deck"])

def _pad_deck(deck, potential):
    # Client (DraggableUnitCard.SwapCard, Ghidra-confirmed) crashes on drag-swap
    # into an occupied slot with an unhandled IndexOutOfRangeException (GetIndex
    # FromCurrentDeck returns -1 for the dragged card, used unguarded as an array
    # index). Whatever partial/corrupt deck state exists at that moment still
    # gets persisted via /deck/set before the crash - e.g. deck:[] wipes the
    # active preset, which then breaks DeckPanel.ReloadDeck on next boot
    # (needs len==DECK_SLOTS, see above). Pad/truncate every incoming write so
    # the stored deck can never violate that invariant, regardless of what
    # broken state the client sends.
    deck = (list(deck) + [0] * DECK_SLOTS)[:DECK_SLOTS]
    potential = (list(potential) + [0] * DECK_SLOTS)[:DECK_SLOTS]
    return deck, potential

DEFAULT_PLAYER = {
    **SEED["player"],
    "accountCreatedAt": now_iso(0),
    "lastHeartTime": now_iso(0), "tomorrow": now_iso(1), "nextWeek": now_iso(7),
    "cards": DEFAULT_CARDS,
    "decks": DEFAULT_DECKS,
    "defaultPotential": {"unit": [], "potential": []},
    "inventory": {"itemIds": list(ALL_ITEM_IDS), "counts": [INV_COUNT] * len(ALL_ITEM_IDS)},
    "inventoryItems": {},
    "tutorialKeyValues": [],
    "missions": [{"missionId": 1, "value": 1, "goalValue": 10, "clear": False, "createdAt": now_iso(0), "untilAt": now_iso(86400)}],
    "eventFlag": 0,
    "tokens": [],
}

_game_store = {}

def build_model(name, overlay=None):
    out = {}
    spec = MODELS.get(name)
    if spec:
        for f in spec["fields"]:
            out[f["name"]] = f["default"]
    else:
        out = {"code": 0, "msg": ""}
    out["code"] = 200
    out["msg"] = None
    out["success"] = True
    if overlay:
        out.update(overlay)
    return out

def card_to_dict(c):
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": c.get("potentialTier", 0),
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": 0, "playerCash": 0, "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": c.get("potentialTier", 0),
        "isLevelSynced": False, "isTemporaryRecruited": False,
        "createdAt": now_iso(-30),
    }

def cards_list(st):
    return [card_to_dict(c) for c in st.get("cards", {}).values()]

# The client's account id for the request being handled: `?id=` on /auth/auth,
# or `id` in the /auth/register body. Only r_login reads it.
CURRENT_LOGIN_ID = contextvars.ContextVar("current_login_id", default=None)

def _uid_for_login(login_id, prev_token):
    """Which player a login belongs to.

    Order: known account id -> the session the presented token already belongs to
    (/auth/login carries a token, not an id) -> new player, but only in
    multiplayer mode -> the active player.
    """
    uid = playerdb.uid_for_login(login_id) or playerdb.uid_for_token(prev_token)
    if uid and playerdb.load(uid) is not None:
        return uid
    if MULTIPLAYER and login_id:
        uid = "p-" + hashlib.sha1(login_id.encode()).hexdigest()[:12]
        if playerdb.load(uid) is None:
            # The account id is client-supplied and unauthenticated, so anyone who
            # can reach /auth/register can mint saves. Cap it - without this a loop
            # fills the disk.
            if playerdb.count() >= MAX_PLAYERS:
                admin_log(f"[auth] refused new player: at KGC_MAX_PLAYERS={MAX_PLAYERS}")
                return playerdb.active()
            st = copy.deepcopy(DEFAULT_PLAYER)
            st["uid"] = uid
            st["accountCreatedAt"] = now_iso(0)
            playerdb.save(uid, st)
            admin_log(f"[auth] new player {uid}")
        playerdb.bind_login(login_id, uid)
        return uid
    return playerdb.active()

def r_login(body, st):
    # All date-ish fields must be non-null parseable strings: HandleAuthResponse
    # does DateTime.Parse on expiredAt / serverTime / blockedUntilAt -> null throws
    # ArgumentNullException.
    login_id = CURRENT_LOGIN_ID.get() or body.get("id") or ""
    # No bind_login() here: in single-player mode _uid_for_login falls back to the
    # ACTIVE player, and recording that as "account X owns save Y" would pin every
    # account that ever logged in to it - permanently, so a later switch to
    # multiplayer would still hand them all the same save. Only the multiplayer
    # branch, which actually owns the account, writes that mapping.
    uid = _uid_for_login(login_id, body.get("token"))
    token = "DEV." + secrets.token_hex(16)
    playerdb.bind_session(token, uid)   # every later request identifies via this
    CURRENT_UID.set(uid)                # rest of THIS request is already this player
    # login_id is a bearer credential (whoever presents it gets that save), and
    # admin_log feeds the dashboard log view - record a fingerprint, not the id.
    fp = hashlib.sha1(login_id.encode()).hexdigest()[:8] if login_id else "-"
    admin_log(f"[auth] login id#{fp} -> uid={uid}")
    return {
        "accessToken": token,
        "expiredAt": now_iso(7),
        "seed": secrets.token_hex(8),
        "serverTime": now_iso(0),
        "blockedUntilAt": now_iso(0),
        "blockedComment": "",
        "loginId": uid,
    }



def _get_building_data(st):
    presets = st.get("buildingData", st.get("buildingPresets", [{"buildingLevels": [0]*6} for _ in range(5)]))
    # WorldPanel.<GameStart>d__349.MoveNext (Ghidra RVA 0x220BC48) indexes
    # response.buildingData once per entry in a static building-type registry
    # (Buildings.xml defines 6 types, IDs 0-5) - fewer buildingData entries
    # than that throws ArgumentOutOfRangeException on literally the first
    # battle-start attempt. Pad (never truncate) so the index always resolves.
    if len(presets) < 10:
        presets = list(presets) + [{"buildingLevels": [0]*6} for _ in range(10 - len(presets))]
    return presets

def r_building_save(body, st):
    preset = body.get("preset", 0)
    levels = body.get("levels", [0] * 6)
    presets = _get_building_data(st)
    while len(presets) <= preset:
        presets.append({"buildingLevels": [0]*6})
    presets[preset]["buildingLevels"] = levels
    st["buildingPresets"] = presets
    save_state(st)
    return {"buildingPoint": st.get("buildingPoints", 25), "buildingData": presets}

def r_building_reset_point(body, st):
    preset = body.get("preset", 0)
    presets = _get_building_data(st)
    while len(presets) <= preset:
        presets.append({"buildingLevels": [0]*6})
    presets[preset]["buildingLevels"] = [0] * 6
    st["buildingPresets"] = presets
    save_state(st)
    return {"buildingPoint": st.get("buildingPoints", 25), "buildingData": presets}



# ProfilePanel.ReloadChallenge indexes invasion/difficulty records per
# unlockedDifficulty tier (up to 15) -> a shorter list throws
# IndexOutOfRangeException, aborting Reload() before name/avatar/clan/date ever
# get set (root cause of the whole profile-popup bug batch).
_PC = RCFG["player"]
_INVASION_THEMES = [t for a, b in _PC["invasionThemeRanges"] for t in range(a, b)]
# Theme 16 (Invasion I-1) requires ReqPrevThemeDifficulty=3 on the PREVIOUS theme (15,
# the last Story chapter) - ThemeSelectPanel.IsThemeLocked looks this up by ID-1 in the
# same invasionDifficultyRecords dictionary (no separate "story difficulty" field exists
# on PlayerDataResponseModel). Without a record for 15, the lookup returns 0 < 3 -> locked,
# and OnSelectTheme silently falls back to theme=1 instead of refusing selection.
_PREREQ_THEMES = [15]

def r_player(body, st):
    # Field set matches PlayerDataResponseModel exactly (dump.cs @0x18-0xC4) - any
    # extra key here is dead weight the client silently ignores (Newtonsoft default),
    # and any missing real field risks an NRE downstream. Ghidra-verified 2026-07-03:
    # buildingPoint/altarPoints/altarLevels/difficultyRecords/season/semiSeason/
    # pvpEnabled/seasonUntilAtDates/nextSeasonStartAtDates/score/tier/rank/bestScore/
    # bestTier/loseCount/theme/deckRecordDifficulty do NOT exist on this model - they
    # were dead fields from an earlier draft. Altar/building data belongs on
    # BuildingResponseModel (/player/building*), not here.
    d = _PC["defaults"]
    ld = _PC["listDefaults"]
    unlocked = _PC["invasionUnlockedDifficulty"]
    return {
        "accountId": st.get("accountId", d["accountId"]),
        "name": st.get("name", d["name"]), "castleName": st.get("castleName", d["castleName"]),
        "kingPostfix": 0, "castlePostfix": 0,
        "uid": st.get("uid", "dev-0001"), "accountType": st.get("accountType", d["accountType"]),
        "cash": st.get("cash", d["cash"]), "paidCash": st.get("paidCash", d["paidCash"]),
        "gold": st.get("gold", d["gold"]), "level": st.get("level", d["level"]),
        "exp": st.get("exp", d["exp"]), "heart": st.get("heart", d["heart"]),
        "treasureCapacity": 9999, "capacity": 9999, "maxCapacity": 9999,
        "lastHeartTime": st.get("lastHeartTime", now_iso(0)),
        "bestClearedStage": st.get("bestClearedStage", d["bestClearedStage"]),
        "bestClearedTheme": st.get("bestClearedTheme", d["bestClearedTheme"]),
        "bestClearedHardStage": st.get("bestClearedHardStage", d["bestClearedHardStage"]),
        "bestClearedHardTheme": st.get("bestClearedHardTheme", d["bestClearedHardTheme"]),
        "currentDeckPreset": st.get("currentDeckPreset", d["currentDeckPreset"]),
        "playedCount": st.get("playedCount", d["playedCount"]),
        "winCount": st.get("winCount", d["winCount"]),
        "rogueLikePlayedCount": st.get("rogueLikePlayedCount", d["rogueLikePlayedCount"]),
        "rogueLikeCleared": st.get("rogueLikeCleared", d["rogueLikeCleared"]),
        "invasionDifficultyRecords": [
            # difficulty = highest CLEARED tier (GetInvasionClearedDifficulty reads
            # .First(theme).difficulty) - must be `unlocked`, not the loop var, or the
            # first per-theme record reports cleared=1 and content gates (accessory@6,
            # riftweapon@11) stay locked. The d-loop only pads list length for
            # ProfilePanel.ReloadChallenge's per-tier indexing.
            {"theme": i, "difficulty": unlocked, "unlockedDifficulty": unlocked}
            for i in _INVASION_THEMES + _PREREQ_THEMES
            for d in range(1, unlocked + 1)
        ],
        "eventModeRecord": st.get("eventModeRecord", [ld["eventModeRecordValue"]] * ld["eventModeRecordCount"]),
        "rogueLikeBuildingChallengeLevelRecord": st.get(
            "rogueLikeBuildingChallengeLevelRecord",
            [ld["rogueLikeBuildingChallengeLevelRecordValue"]] * ld["rogueLikeBuildingChallengeLevelRecordCount"]),
        "rogueLikeGameIndex": st.get("rogueLikeGameIndex", d["rogueLikeGameIndex"]),
        "dimensionRiftGameIndex": st.get("dimensionRiftGameIndex", d["dimensionRiftGameIndex"]),
        "currentRanking": st.get("currentRanking", [ld["currentRankingValue"]] * ld["currentRankingCount"]),
        "currentHardRanking": st.get("currentHardRanking", [ld["currentHardRankingValue"]] * ld["currentHardRankingCount"]),
        "tomorrow": next_reset_iso(1),
        "nextWeek": next_reset_iso(7),
        "hasFreeRename": st.get("hasFreeRename", d["hasFreeRename"]),
        "eventFlag": st.get("eventFlag", d["eventFlag"]),
        "eventPlayedCount": st.get("eventPlayedCount", 0),
        "clanAttendance": st.get("clanAttendance", d["clanAttendance"]),
        "tokens": st.get("tokens", []),
        # profileIconId must be a real Unit ID (ResourceBase<Unit>.Get lookup) - a
        # non-resolving id gives a blank/white avatar.
        "keyValues": st.get("keyValues", [{"key": "profileIconId", "value": d["profileIconId"]}]) + [
            # AccessorySubStatGrade.Set() opens with GetKeyValueInt("AccessoryRenewal")
            # and SetActive(false)s the whole grade badge unless it is 1 - which is
            # why substats rendered with no tier. It is the ONLY reader of the flag
            # (verified by scanning every reference to the literal), so turning it
            # on enables the badge and nothing else. Tier itself is
            # Utility.LowerBound(AccessorySubStatScoreRange, score), thresholds from
            # AccessoryConstants.xml: 1, 4.5, 8.5, 13.5, 18.5, 22.5, 26.5.
            {"key": "AccessoryRenewal", "value": "1"},
            {"key": "InventoryCount_Treasure", "value": "999"},
            {"key": "InventoryCount_Accessory", "value": "999"},
            {"key": "InventoryCount_RiftWeapon", "value": "999"},
            {"key": "InventoryCount_RiftCrystal", "value": "999"},
            {"key": "InventoryCount_AccessoryPreset", "value": "999"},
        ],
        "attendedCustomEvents": st.get("attendedCustomEvents", []),
        "customEventDatas": st.get("customEventDatas", []),
        "eventMissionData": st.get("eventMissionData", []),
        "eventData": st.get("eventData", []),
        "rogueLikeBoughtDlcs": st.get("rogueLikeBoughtDlcs", []),
        "accountCreatedAt": st.get("accountCreatedAt", now_iso(0)),
    }

def r_game_start(body, st):
    print(f"  [GAME/START] body={body}")
    gc = RCFG["gameStart"]
    theme = body.get("theme", 1)
    stage = body.get("stage", 1)
    heart_cost = gc["heartCostLow"] if theme <= gc["heartCostThemeThreshold"] else gc["heartCostHigh"]
    heart = max(0, st.get("heart", 999) - heart_cost)
    st["heart"] = heart
    gid = secrets.token_hex(8)
    _game_store[gid] = {"theme": theme, "stage": stage, "heartCost": heart_cost}
    save_state(st)
    # The client loops over rankingStageUnits up to 6 times (Deck size).
    # Provide 6 valid units (10260) spread out to avoid physics explosions.
    ranking_stage_units = [{"x": i, "y": i, "unitId": 10260, "level": 1} for i in range(6)]
    return {
        "heart": heart,
        "lastHeartTime": st.get("lastHeartTime", now_iso(0)),
        "buildingData": _get_building_data(st),
        "cards": cards_list(st),
        "gameId": gid,
        "eventFlag": st.get("eventFlag", 0),
        "rankingStageUnits": ranking_stage_units,
    }

def r_game_complete(body, st):
    gc = RCFG["gameComplete"]
    gid = body.get("gameId", "")
    win = body.get("win", False)
    theme = body.get("theme", 1)
    stage = body.get("stage", 1)
    _game_store.pop(gid, None)
    add_gold = gc["baseGold"] + theme * gc["goldPerTheme"] + (gc["winBonusGold"] if win else 0)
    add_exp = gc["baseExp"] + theme * gc["expPerTheme"]
    st["gold"] += add_gold
    st["exp"] += add_exp
    if win:
        st["winCount"] = st.get("winCount", 0) + 1
        if theme > st.get("bestClearedTheme", 0):
            st["bestClearedTheme"] = theme
            st["bestClearedStage"] = stage
        elif theme == st.get("bestClearedTheme", 0) and stage > st.get("bestClearedStage", 0):
            st["bestClearedStage"] = stage
    st["playedCount"] = st.get("playedCount", 0) + 1
    if st.get("exp", 0) >= gc["expPerLevel"]:
        st["level"] += st["exp"] // gc["expPerLevel"]
        st["exp"] = st["exp"] % gc["expPerLevel"]
    save_state(st)
    out = {"addGold": add_gold, "addExp": add_exp,
           "playerGold": st["gold"], "playerLevel": st["level"], "playerExp": st["exp"]}
    out.update(gc["fixed"])
    return out

def r_card_all(body, st):
    return {"cards": cards_list(st)}

def r_card_upgrade(body, st):
    unit_id = body.get("unitId", 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["level"] += 1
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": 1, "exp": 0, "potentialTier": 0,
                        "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
                        "randomSkinApply": False, "soul": 0})
    player_gold = st.get("gold", 0)
    player_cash = st.get("cash", 0)
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": c.get("potentialTier", 0),
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": player_gold, "playerCash": player_cash,
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": c.get("potentialTier", 0),
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }

def r_card_fast_upgrade(body, st):
    unit_id = body.get("unitId", 0)
    target_level = body.get("targetLevel", 1)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["level"] = target_level
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": target_level, "exp": 0, "potentialTier": 0,
                        "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
                        "randomSkinApply": False, "soul": 0})
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": c.get("potentialTier", 0),
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": c.get("potentialTier", 0),
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }

def r_card_use_candy(body, st):
    unit_id = body.get("unitId", 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["level"] += 1
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": 1})
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": c.get("potentialTier", 0),
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": c.get("potentialTier", 0),
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }

def r_card_upgrade_potential(body, st):
    unit_id = body.get("unitId", 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        cards[key]["potentialTier"] = min(20, cards[key].get("potentialTier", 0) + 1)
        save_state(st)
    c = cards.get(key, {"unitId": unit_id, "level": 1})
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": c["potentialTier"],
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": c["potentialTier"],
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }

def r_card_buy_skin(body, st):
    unit_id = body.get("unitId", 0)
    skin_id = body.get("skinId", 0)
    cards = st.setdefault("cards", {})
    key = str(unit_id)
    if key in cards:
        skins = cards[key].setdefault("skins", [])
        if skin_id not in skins:
            skins.append(skin_id)
        cards[key]["currentSkin"] = skin_id
        save_state(st)
    return {"unitId": unit_id, "level": 0, "exp": 0, "potentialTier": 0,
            "skins": [skin_id], "favoriteSkinIds": [], "currentSkin": skin_id,
            "randomSkinApply": False, "playerGold": 0, "playerCash": 0, "soul": 0}

def _card_view(c, st):
    """Standard card response shape (no level mutation)."""
    return {
        "unitId": c["unitId"], "level": c.get("level", 1), "exp": c.get("exp", 0),
        "potentialTier": c.get("potentialTier", 0),
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0),
        "soul": c.get("soul", 0),
        "originLevel": c.get("level", 1), "originPotentialTier": c.get("potentialTier", 0),
        "isLevelSynced": False, "isTemporaryRecruited": False, "createdAt": now_iso(-30),
    }

def r_card_equip_skin(body, st):
    # EquipSkinRequestModel = {unit, skin}  (NOT unitId/skinId)
    unit_id = body.get("unit", body.get("unitId", 0))
    skin_id = body.get("skin", body.get("skinId", 0))
    cards = st.setdefault("cards", {})
    c = cards.get(str(unit_id))
    if c is not None and (skin_id == 0 or skin_id in c.get("skins", [])):
        c["currentSkin"] = skin_id
        save_state(st)
    return _card_view(c or {"unitId": unit_id, "currentSkin": skin_id}, st)

def r_card_set_skin_favorite(body, st):
    # CardSkinEtcRequestModel = {unitId, skinId, flag}
    unit_id = body.get("unitId", body.get("unit", 0))
    skin_id = body.get("skinId", body.get("skin", 0))
    flag = body.get("flag", True)
    cards = st.setdefault("cards", {})
    c = cards.get(str(unit_id))
    if c is not None:
        fav = c.setdefault("favoriteSkinIds", [])
        if flag and skin_id not in fav:
            fav.append(skin_id)
        elif not flag and skin_id in fav:
            fav.remove(skin_id)
        save_state(st)
    return _card_view(c or {"unitId": unit_id}, st)

def r_card_set_random_skin(body, st):
    # CardSkinEtcRequestModel = {unitId, skinId, flag}
    unit_id = body.get("unitId", body.get("unit", 0))
    flag = body.get("flag", True)
    cards = st.setdefault("cards", {})
    c = cards.get(str(unit_id))
    if c is not None:
        c["randomSkinApply"] = bool(flag)
        save_state(st)
    return _card_view(c or {"unitId": unit_id}, st)

def r_deck(body, st):
    decks = st.get("decks", DEFAULT_DECKS)
    deck_infos = [{"deck": d["deck"], "potential": d.get("potential", []),
                   "firstComerIndex": d.get("firstComerIndex", 0)} for d in decks]
    return {"deckInfos": deck_infos, "defaultPotentialInfo": st.get("defaultPotential", {"unit": [], "potential": []})}

def r_deck_set(body, st):
    preset_idx = body.get("presetIdx", 0)
    decks = st.setdefault("decks", list(DEFAULT_DECKS))
    admin_log(f"[DECK/SET] preset={preset_idx} body_keys={list(body.keys())}")
    deck, potential = _pad_deck(body.get("deck", []), body.get("potential", []))
    first_comer = body.get("firstComerIndex", 0)
    while len(decks) <= preset_idx:
        decks.append({"deck": [0] * DECK_SLOTS, "potential": [0] * DECK_SLOTS, "firstComerIndex": 0})
    decks[preset_idx] = {"deck": deck, "potential": potential, "firstComerIndex": first_comer}
    st["decks"] = decks
    save_state(st)
    return {"deckInfos": [{"deck": d["deck"], "potential": d.get("potential", []),
                           "firstComerIndex": d.get("firstComerIndex", 0)} for d in decks],
            "defaultPotentialInfo": st.get("defaultPotential", {"unit": [], "potential": []})}

def r_deck_set_potential(body, st):
    preset_idx = body.get("presetIdx", 0)
    idx = body.get("idx", 0)
    unit_id = body.get("unitId", 0)
    potential = body.get("potential", 0)
    decks = st.setdefault("decks", list(DEFAULT_DECKS))
    admin_log(f"[DECK/SET-POTENTIAL] preset={preset_idx} idx={idx} unitId={unit_id} potential={potential}")
    while len(decks) <= preset_idx:
        decks.append({"deck": [0] * DECK_SLOTS, "potential": [0] * DECK_SLOTS, "firstComerIndex": 0})
    while len(decks[preset_idx]["deck"]) <= idx:
        decks[preset_idx]["deck"].append(0)
    decks[preset_idx]["deck"][idx] = unit_id
    while len(decks[preset_idx]["potential"]) <= idx:
        decks[preset_idx]["potential"].append(0)
    decks[preset_idx]["potential"][idx] = potential
    st["decks"] = decks
    save_state(st)
    return r_deck({}, st)

def r_deck_set_all_potential(body, st):
    potentials = body.get("potentials", [])
    st["defaultPotential"] = {"unit": [p.get("unitId", 0) for p in potentials],
                               "potential": [p.get("potential", 0) for p in potentials]}
    save_state(st)
    return r_deck({}, st)

def r_player_inventory(body, st):
    inv = st.get("inventory", {"itemIds": [], "counts": []})
    return {"itemIds": inv.get("itemIds", []), "counts": inv.get("counts", [])}

def r_mission(body, st):
    return {"missions": st.get("missions", []), "missionGoal": 0, "missionKeyStack": 0}

def r_mission_reward_all(body, st):
    st["missions"] = []
    save_state(st)
    return {"missions": [], "missionGoal": 0, "missionKeyStack": 0}

def r_event_cache(body, st):
    return {"events": []}

def r_pvp_info(body, st):
    c = RCFG["pvpInfo"]
    out = {"seasonUntilAtDates": [now_iso(n) for n in c["seasonDayOffsets"]],
           "nextSeasonStartAtDates": [now_iso(n) for n in c["nextSeasonDayOffsets"]]}
    out.update(c["fixed"])
    return out

def r_colosseum(body, st):
    c = RCFG["colosseum"]
    out = {"seasonUntilAtDates": [now_iso(n) for n in c["seasonDayOffsets"]],
           "nextSeasonStartAtDates": [now_iso(n) for n in c["nextSeasonDayOffsets"]]}
    out.update(c["fixed"])
    return out


ALL_ARTIFACT_IDS, ARTIFACT_LEVELS = _all_artifact_ids()
ALL_TREASURE_IDS = _all_treasure_ids()
ALL_RIFT_WEAPON_IDS = _all_rift_weapon_ids()



# Ghidra ROOT CAUSE (2026-07-02, ResourceArtifactOption.GetValue crash):
# ArtifactOptionUI.Init's loop gate is `uVar8 < targets.Count` (top-level
# ArtifactOptions.targets, NOT types/lvs). Only when the gate is open does it call
# GetValue(types[i], lvs[i], ...) which does a Dictionary["AtkSpeedPer"] style
# lookup - "None" is never a registered key, so ANY slot reached with type="None"
# throws KeyNotFoundException. Fix: targets.Count must equal opt_count exactly, so
# the loop's else/hide branch (which never touches types/lvs) handles slots
# opt_count..3 instead of trying to look up "None". types_list/lvs_list stay
# padded to optionSlots (loop only ever reads indices < opt_count from them, so
# the tail values are never touched, but keep them present per the JSON schema).
#
# positionIcons (icon highlighting) separately requires: idx values 1-based
# (FUN_02e91408 = List<int>.IndexOf), and BOTH idx (nested struct list) and lvs
# (parallel list) must stay UNIFORM in length/value across all sent slots or the
# client's JSON parser corrupts subsequent fields (live-verified both ways).
# idx > 1 element still crashes for unknown reasons - capped at safePositions.
def make_artifact(i, art_id):
    t = ITEM_TEMPLATES["artifact"]
    level = ARTIFACT_LEVELS.get(art_id, "Normal")
    opt_count = t["optCountByLevel"].get(level, 1)
    types_pool = t["typesPool"]
    max_roll_lvs = t["maxRollLvs"]
    safe_positions = t["safePositions"]

    opt_data = []
    types_list = []
    lvs_list = []
    targets_list = []
    locks = []

    for idx in range(opt_count):
        ty = types_pool[idx % len(types_pool)]
        opt_data.append({"targets": safe_positions, "type": ty, "value": 24, "level": max_roll_lvs})
        types_list.append(ty)
        targets_list.append({"idx": safe_positions})
        lvs_list.append(max_roll_lvs)
        locks.append(False)

    for idx in range(opt_count, 4):
        opt_data.append({"targets": safe_positions, "type": "None", "value": 0, "level": 0})
        types_list.append("None")
        lvs_list.append(0)
        locks.append(False)

    return {
        "id": i,
        "artifactId": art_id,
        "count": t["count"],
        "polishPoint": t["polishPoint"],
        "data": {"options": opt_data},
        "options": {
            "targets": targets_list,
            "types": types_list,
            "lvs": lvs_list
        },
        "optionLock": locks,
        "customType": t["customType"],
        "createdAt": now_iso()
    }

def make_accessory(i, unit_id=0):
    t = ITEM_TEMPLATES["accessory"]
    return {
        "id": i, "accountId": t["accountId"], "unitId": unit_id, "slot": t["slot"],
        "type": (i % t["typeCount"]) + 1,
        "rarity": t["rarity"], "level": t["level"], "exp": t["exp"], "synergy": t["synergy"], "state": t["state"],
        "data": t["data"], "subStats": t["subStats"], "subStatScores": t["subStatScores"],
        "coolTimeEndAt": t["coolTimeEndAt"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
        "usedThemeList": t["usedThemeList"],
        "isEarlyAccessModeTestAccessory": t["isEarlyAccessModeTestAccessory"],
    }

def _acc_perscore(key):
    # AccessoryConstants.xml: BaseDef/BaseMDef roll in ValuePerScore=20 units; every other
    # substat uses ValueByScore=1. score = summed value / perScore.
    return 20.0 if key in ("BaseDef", "BaseMDef") else 1.0

def load_corruption_accessories():
    """Real 'Corruption II-1' first-clear reward accessories (FixedAccessoryPreset 2000-2003,
    one per type) - the exact items the client grants for clearing the stage that unlocks the
    accessory system. Mirrors AccessoryModel (data.mainStat + data.subStats[{key,value}]) so
    the client renders proper name/stats/grade instead of the 99.9% garbage a fabricated
    template with an invalid mainStat produced."""
    import xml.etree.ElementTree as ET
    root = ET.parse(XML_DIR / "FixedAccessoryPresets.xml").getroot()
    out, inst = [], 1
    for p in root.findall("FixedAccessoryPreset"):
        if p.get("ID", "") not in ("2000", "2001", "2002", "2003"):
            continue
        rolls = [(s.get("Key"), float(s.get("Value"))) for s in p.findall("./SubStats/SubStat")]
        fb = p.find("FixedBonusSubStat")
        if fb is not None:
            rolls.append((fb.get("Key"), float(fb.get("Value"))))
        scores = {}
        for k, v in rolls:
            scores[k] = scores.get(k, 0.0) + v / _acc_perscore(k)
        out.append({
            "id": inst, "accountId": 1, "unitId": 0, "slot": 0,
            "type": int(p.findtext("Type", "1")), "rarity": int(p.findtext("Rarity", "3")),
            "level": int(p.findtext("Level", "20")), "exp": 0,
            "synergy": int(p.findtext("Synergy", "0")), "state": 0,
            "data": {"mainStat": p.findtext("MainStat", "AtkPer"),
                     "subStats": [{"key": k, "value": v} for k, v in rolls]},
            "subStats": list(scores.keys()), "subStatScores": [round(s, 3) for s in scores.values()],
            "coolTimeEndAt": "2000-01-01T00:00:00.000Z",
            "createdAt": now_iso(), "updatedAt": now_iso(),
            "usedThemeList": [], "isEarlyAccessModeTestAccessory": False,
        })
        inst += 1
    return out

def get_st_accessories(st):
    if "accessories" not in st:
        st["accessories"] = copy.deepcopy(DEFAULT_ACCESSORIES)
    return st["accessories"]

def r_accessory(body, st):
    accs = get_st_accessories(st)
    target_id = body.get("targetId", 0)
    unit_id = body.get("unitId", 0)
    if target_id and unit_id:
        for a in accs:
            if a["unitId"] == unit_id:
                a["unitId"] = 0
            if a["id"] == target_id:
                a["unitId"] = unit_id
        save_state(st)
    return {"accessories": accs, "presets": []}

def r_accessory_release(body, st):
    accs = get_st_accessories(st)
    target_id = body.get("targetId", 0)
    if target_id:
        for a in accs:
            if a["id"] == target_id:
                a["unitId"] = 0
        save_state(st)
    return {"accessories": accs, "presets": []}

def r_accessory_result(body, st):
    return {"accessories": get_st_accessories(st), "deletedAccessories": [], "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0), "inventories": [], "addedExpItems": 0}

def make_treasure(i, tr_id):
    t = ITEM_TEMPLATES["treasure"]
    return {
        "id": i, "treasureId": tr_id, "accountId": t["accountId"],
        "level": t["level"], "exp": t["exp"], "overcome": t["overcome"], "unitId": t["unitId"], "state": t["state"],
        "coolTimeEndAt": t["coolTimeEndAt"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
        "usedThemeList": t["usedThemeList"],
        "isEarlyAccessModeTestTreasure": t["isEarlyAccessModeTestTreasure"],
    }

def make_rift_weapon(i, rw_id):
    t = ITEM_TEMPLATES["riftWeapon"]
    return {
        "id": i, "weaponId": rw_id, "buildingIndexes": t["buildingIndexes"],
        "level": t["level"], "rarity": t["rarity"], "broken": t["broken"],
        "subStat": t["subStat"], "state": t["state"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
    }

RIFT_BUILDING_COUNT = _rift_building_count()
# CrystalRarity (ResourceRiftWeaponConstant.CrystalRarity): None=0, Common=1, UnCommon=2,
# Rare=3, Epic=4, Legendary=5. Rarity 0 names the crystal via the key
# `RiftCrystalNameKeyword_None`, which does not exist in any locale - the client then
# renders the raw key. Only 1-5 have a keyword (Faded/Ordinary/King/God/King God).
RIFT_CRYSTAL_RARITIES = {1: "Common", 2: "UnCommon", 3: "Rare", 4: "Epic", 5: "Legendary"}
# Altars cap at level 15 ("You have an Altar with more than 15 points" / the 16 entries
# of RiftWeaponConstants.xml BuildingOptionSlotLevelValue = levels 0..15).
RIFT_BUILDING_MAX_LEVEL = 15

def make_rift_crystal(i, rw_id, main_idx=None):
    t = ITEM_TEMPLATES["riftCrystal"]
    main_idx = t["mainBuildingIdx"] if main_idx is None else main_idx
    main_idx %= max(RIFT_BUILDING_COUNT, 1)
    level = min(int(t["mainBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL)
    other = min(int(t["otherBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL)
    # One level per altar, with the main altar strictly highest: GetMaxBuildingIdx
    # returns the FIRST maximum, so an all-equal list would name every crystal after
    # altar 0 regardless of mainBuildingIdx.
    levels = [other] * RIFT_BUILDING_COUNT
    levels[main_idx] = max(level, other + 1)
    rarity = int(t["rarity"])
    assert rarity in RIFT_CRYSTAL_RARITIES, (
        f"riftCrystal rarity {rarity} has no RiftCrystalNameKeyword_* string; "
        f"valid: {sorted(RIFT_CRYSTAL_RARITIES)}")
    return {
        "id": i, "weaponId": rw_id, "mainBuildingIdx": main_idx,
        "buildingLevels": levels, "rarity": rarity,
        "ceilCount": t["ceilCount"], "state": t["state"],
        "createdAt": now_iso(), "updatedAt": now_iso(),
    }

def _repair_rift_crystals(crystals):
    """Upgrade crystals saved before the shape was understood. Returns True if anything
    changed, so the caller can persist.

    Two legacy defects, both of which the client renders rather than rejects:
      * rarity 0 (CrystalRarity.None) -> the name resolves `RiftCrystalNameKeyword_None`,
        a key that exists in no locale, so the panel shows the raw key;
      * buildingLevels shorter than the altar count -> GetMaxBuildingIdx can only ever
        return an index inside the short list, so every crystal named itself after
        altar 0 and the altars past the end contributed nothing.
    """
    t = ITEM_TEMPLATES["riftCrystal"]
    changed = False
    for c in crystals:
        if c.get("rarity") not in RIFT_CRYSTAL_RARITIES:
            c["rarity"] = int(t["rarity"])
            changed = True
        levels = c.get("buildingLevels") or []
        if len(levels) != RIFT_BUILDING_COUNT:
            main = int(c.get("mainBuildingIdx", 0)) % max(RIFT_BUILDING_COUNT, 1)
            other = min(int(t["otherBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL)
            # Keep whatever levels the save already had; only extend to full width.
            fixed = [min(int(v), RIFT_BUILDING_MAX_LEVEL) for v in levels[:RIFT_BUILDING_COUNT]]
            fixed += [other] * (RIFT_BUILDING_COUNT - len(fixed))
            fixed[main] = max(min(int(t["mainBuildingLevel"]), RIFT_BUILDING_MAX_LEVEL), other + 1)
            c["buildingLevels"] = fixed
            c["mainBuildingIdx"] = main
            changed = True
    return changed

DEFAULT_ARTIFACTS = [make_artifact(i + 1, aid) for i, aid in enumerate(ALL_ARTIFACT_IDS)]
DEFAULT_TREASURES = [make_treasure(i + 1, tid) for i, tid in enumerate(ALL_TREASURE_IDS)]
DEFAULT_ACCESSORIES = load_corruption_accessories() or [make_accessory(i + 1) for i in range(ITEM_TEMPLATES["accessory"]["count"])]
DEFAULT_RIFT_WEAPONS = [make_rift_weapon(i + 1, rwid) for i, rwid in enumerate(ALL_RIFT_WEAPON_IDS)]
ARTIFACT_BY_ID = {a["id"]: a for a in DEFAULT_ARTIFACTS}

# ArtifactRequestModel.targetId = the equipped artifact's instance `id` (dump.cs
# ArtifactRequestModel @0x8 targetId, @0x1C index, @0x20 deckPreset).
# ArtifactResultResponseModel.equippedArtifacts = List<EquippedArtifactData>
# {deckPreset, index, artifact} (dump.cs @0x2C). Persisted server-side as
# {deckPreset, index, artifactId} in state and resolved to a full ArtifactModel
# at response time - storing the id (not the full model) means an equipped slot
# always reflects the artifact's current data if it's ever regenerated.
def _resolve_equipped_artifacts(st):
    out = []
    for e in st.get("equippedArtifacts", []):
        art = ARTIFACT_BY_ID.get(e.get("artifactId"))
        if art:
            out.append({"deckPreset": e.get("deckPreset", 0), "index": e.get("index", 0), "artifact": art})
    return out

def r_artifact_inventory(body, st):
    return {"artifacts": DEFAULT_ARTIFACTS, "dustCount": 99999,
            "equippedArtifacts": _resolve_equipped_artifacts(st), "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0)}

def r_artifact_equip(body, st):
    target_id = body.get("targetId", 0)
    index = body.get("index", 0)
    deck_preset = body.get("deckPreset", 0)
    equipped = [e for e in st.get("equippedArtifacts", [])
                if not (e.get("deckPreset", 0) == deck_preset and e.get("index", 0) == index)]
    if target_id and target_id in ARTIFACT_BY_ID:
        equipped.append({"deckPreset": deck_preset, "index": index, "artifactId": target_id})
    st["equippedArtifacts"] = equipped
    save_state(st)
    return {"artifacts": DEFAULT_ARTIFACTS, "dustCount": 99999,
            "equippedArtifacts": _resolve_equipped_artifacts(st), "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "changeEquipped": True, "polishItemAdded": False,
            "results": []}

def r_artifact_result(body, st):
    return {"artifacts": DEFAULT_ARTIFACTS, "dustCount": 99999,
            "equippedArtifacts": _resolve_equipped_artifacts(st), "playerGold": st.get("gold", 0),
            "playerCash": st.get("cash", 0),
            "changeEquipped": False, "polishItemAdded": False,
            "results": DEFAULT_ARTIFACTS}

def get_st_treasures(st):
    if "treasures" not in st:
        st["treasures"] = copy.deepcopy(DEFAULT_TREASURES)
    return st["treasures"]

def r_treasure(body, st):
    tr = get_st_treasures(st)
    target_id = body.get("targetId", 0)
    unit_id = body.get("unitId", 0)
    if target_id and unit_id:
        for t in tr:
            if t["unitId"] == unit_id:
                t["unitId"] = 0
            if t["id"] == target_id:
                t["unitId"] = unit_id
        save_state(st)
    return {"treasures": tr, "treasureCapacity": 9999, "capacity": 9999, "maxCapacity": 9999, "maxTreasureCount": 9999, "deletedTreasures": [], "inventories": []}

def r_treasure_equip(body, st):
    return r_treasure(body, st)

def r_treasure_release(body, st):
    tr = get_st_treasures(st)
    inv_id = body.get("targetId")
    for t in tr:
        if t["id"] == inv_id:
            t["unitId"] = 0
    save_state(st)
    return r_treasure(body, st)

def r_treasure_add_exp(body, st):
    return {"treasures": get_st_treasures(st), "treasureCapacity": 9999, "capacity": 9999, "maxCapacity": 9999, "maxTreasureCount": 9999, "addExpItems": [], "deletedTreasures": [], "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0), "inventories": [], "addedExpItems": 0}

def r_rift_weapon(body, st):
    rift_crystals = st.setdefault("riftCrystals", [])
    if _repair_rift_crystals(rift_crystals):
        save_state(st)
    return {"riftWeapons": DEFAULT_RIFT_WEAPONS, "equippedWeapons": {}, "riftCrystals": rift_crystals, "deletedRiftWeapons": [], "deletedCrystals": [], "riftGauge": 0, "rewardListResponseData": None, "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0), "playerHeart": st.get("heart", 0), "upgradeState": 0, "equippedWeaponIds": []}

def r_clan(body, st):
    # clan:null -> GameManager.clan stays null -> HasClan() false -> profile's
    # clanInfoBox hidden. A fake clan object here (even self-authored) makes
    # GameManager.HasClan() true for every account, which is wrong for a fresh
    # god account that never joined one.
    return {"clan": None, "role": 0, "requestSupportCooltime": now_iso(-1)}

def r_pass(body, st):
    c = RCFG["pass"]
    out = {"seasonStartAtDate": now_iso(c["seasonStartDayOffset"]),
           "seasonUntilAtDate": now_iso(c["seasonUntilDayOffset"]),
           "nextSeasonStartAtDate": now_iso(c["nextSeasonStartDayOffset"])}
    out.update(c["fixed"])
    return out

def r_territory(body, st):
    return {"territories": [], "labor": 100, "maxLabor": 100, "buildingPoints": st.get("buildingPoints", 25)}

def r_territory_fetch(body, st):
    return {"territories": [], "labor": 100, "maxLabor": 100, "buildingPoints": st.get("buildingPoints", 25),
            "huntingData": None, "restaurantData": None, "tradeShopData": None}


# Dynamic overrides: routes whose response genuinely depends on request-time
# state/body (auth tokens, st.get() reads, mutations) or config wiring. Pure
# literal responses live in data/static_overrides.json instead (merged in below).
DYNAMIC_OVERRIDES = {
    "/auth/checkPatchVersion": lambda b, st: {"patchVersion": SERVER_VERSION},
    "/auth/getPatchFolder": lambda b, st: {"patchFolder": PATCH_FOLDER},
    "/auth": r_login,
    "/auth/login": r_login,
    "/auth/register": r_login,
    "/auth/link": r_login,
    "/auth/xcdSeed": lambda b, st: {"seed": secrets.token_hex(8), "serverTime": now_iso(0)},
    "/player": r_player,
    "/player/currencies": lambda b, st: {"gold": st.get("gold", 0), "cash": st.get("cash", 0), "heart": st.get("heart", 0)},
    "/player/tutorial-status": lambda b, st: {"keyValues": st.get("tutorialKeyValues", [])},
    "/player/tutorial/complete": lambda b, st: {"keyValues": st.get("tutorialKeyValues", [])},
    "/player/getInventory": r_player_inventory,
    "/player/add-inventory-count": lambda b, st: {
        "playerCash": st.get("cash", 0),
        "inventoryCount": 999
    },
    "/player/rename": lambda b, st: {"name": b.get("name", "DevKing")},
    "/player/building": lambda b, st: {"buildingPoint": st.get("buildingPoints", 25), "buildingData": _get_building_data(st)},
    "/player/building/point": lambda b, st: {"buildingPoint": st.get("buildingPoints", 25), "buildingData": _get_building_data(st)},
    "/player/building/save": r_building_save,
    "/player/building/resetPoint": r_building_reset_point,
    "/player/heart/recover": lambda b, st: {"heart": st.get("heart", 999), "lastHeartTime": now_iso(0)},
    "/game/start": r_game_start,
    "/game/complete": r_game_complete,
    "/game/skip": r_game_complete,
    "/card/all": r_card_all,
    "/card/upgrade": r_card_upgrade,
    "/card/fast-upgrade": r_card_fast_upgrade,
    "/card/upgradePotentialTier": r_card_upgrade_potential,
    "/card/useCandy": r_card_use_candy,
    "/card/useUnitExpItem": r_card_use_candy,
    "/card/useUnitSoulItem": r_card_use_candy,
    "/card/useUnitSoulItemToExp": r_card_use_candy,
    "/card/useUnitSoulToExp": r_card_use_candy,
    "/card/buySkin": r_card_buy_skin,
    "/card/equipSkin": r_card_equip_skin,
    "/card/set-random-skin-apply": r_card_set_random_skin,
    "/card/set-skin-favorite": r_card_set_skin_favorite,
    "/deck": r_deck,
    "/deck/set": r_deck_set,
    "/deck/setPotential": r_deck_set_potential,
    "/deck/setAllPotential": r_deck_set_all_potential,
    "/deck/buyDeckSlot": r_deck,
    "/deck/set-deck-slot-name": r_deck,
    "/mission": r_mission,
    "/mission/reward-all": r_mission_reward_all,
    "/eventcache": r_event_cache,
    "/pvp/info": r_pvp_info,
    "/pvp/matching": r_pvp_info,
    "/colosseum": r_colosseum,
    "/colosseum/test-single-play": r_colosseum,
    "/artifact/inventory": r_artifact_inventory,
    "/artifact/equip": r_artifact_equip,
    "/artifact/crafting": r_artifact_result,
    "/artifact/dismantle": r_artifact_result,
    "/artifact/merge": r_artifact_result,
    "/artifact/polish": r_artifact_result,
    "/artifact/gacha": r_artifact_result,
    "/artifact/set-reroll": r_artifact_result,
    "/artifact/smart-reroll": r_artifact_result,
    "/artifact/fetch-reroll": r_artifact_result,
    "/artifact/open-catalyst-box": r_artifact_result,
    "/artifact/set-favorites": r_artifact_result,
    "/treasure": r_treasure,
    "/treasure/equip": r_treasure_equip,
    "/treasure/add-exp": r_treasure_add_exp,
    "/treasure/dismantle": r_treasure,
    "/treasure/equip-tutorial": r_treasure_equip,
    "/treasure/overcome": r_treasure,
    "/treasure/release-equip": r_treasure_release,
    "/treasure/set-state": r_treasure,
    "/rift-weapon": r_rift_weapon,
    "/rift-weapon/upgrade": r_rift_weapon,
    "/rift-weapon/equip": r_rift_weapon,
    "/rift-weapon/release-equip": r_rift_weapon,
    "/rift-weapon/dismantle": r_rift_weapon,
    "/rift-weapon/re-roll": r_rift_weapon,
    "/rift-weapon/reset-weapon": r_rift_weapon,
    "/rift-weapon/set-state": r_rift_weapon,
    "/rift-weapon/set-crystal-state": r_rift_weapon,
    "/rift-weapon/crystal-charge": r_rift_weapon,
    "/rift-weapon/crystal-destroy": r_rift_weapon,
    "/rift-weapon/crystal-inventory": r_rift_weapon,
    "/rift-weapon/buy-rift-gauge": r_rift_weapon,
    "/clan": r_clan,
    "/clan/info": r_clan,
    "/clan/create": lambda b, st: {"clan": {**RCFG["clanCreate"], "id": 1, "name": b.get("name", "DevClan"),
        "masterName": st.get("name", "DevKing")}, "role": 1, "requestSupportCooltime": now_iso(0)},
    "/pass": r_pass,
    "/pass/reward": r_pass,
    "/pass/all-rewards": r_pass,
    "/pass/bonusReward": r_pass,
    "/pass/buyLevel": r_pass,
    "/pass/passEventBooster": r_pass,
    "/territory": r_territory,
    "/territory/fetch": r_territory_fetch,
    "/territory/build": r_territory,
    "/territory/attendance-check": r_territory,
    "/territory/assign-units": r_territory_fetch,
    "/territory/swap-assigned-units": r_territory_fetch,
    "/territory/recover-labor": lambda b, st: {"storedLabor": 100, "lastLaborAt": now_iso(0)},
    "/territory/level-sync/assign": r_territory_fetch,
    "/territory/trade-shop/buy": r_territory_fetch,
    "/accessory": r_accessory,
    "/accessory/equip-tutorial": lambda b, st: {"accessories": get_st_accessories(st)},
    "/accessory/add-exp": r_accessory_result,
    "/accessory/dismantle": lambda b, st: {"accessories": get_st_accessories(st), "deletedAccessories": b.get("accessoryIds", []), "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0), "inventories": [], "addedExpItems": 0},
    "/accessory/release-equip": r_accessory_release,
    "/accessory/set-state-all": r_accessory_result,
    "/accessory/change-sub-stat": r_accessory_result,
    "/accessory/preset": lambda b, st: {"presets": []},
    "/accessory/set-preset": lambda b, st: {"presets": []},
    "/accessory/set-preset-name": lambda b, st: {"presets": []},
}

# Pure-literal routes (no st/body dependency) load straight from JSON; wrap each
# in a lambda returning the same shared dict (build_model only reads from it via
# .update(), never mutates it, so no copy is needed).
OVERRIDES = {path: (lambda b, st, r=resp: r) for path, resp in STATIC_OVERRIDES.items()}
OVERRIDES.update(DYNAMIC_OVERRIDES)

SERVER_START_TIME = time.time()

app = FastAPI(title="KGC private server", version=SERVER_VERSION)
_STATE_GATE = asyncio.Lock()

ADMIN_TOKEN = os.environ.get("KGC_ADMIN_TOKEN")
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}

@app.middleware("http")
async def guard_admin(request: Request, call_next):
    """The 26 /admin routes can rewrite or delete any player's save.

    serve_public.sh binds 0.0.0.0 so remote players can reach the game API - which
    exposes these too. Require KGC_ADMIN_TOKEN when it is set; with no token
    configured, allow loopback only. Note a reverse proxy or tunnel makes every
    request look like loopback, which is why serve_public.sh refuses to start
    without a token.
    """
    if request.url.path.startswith("/admin"):
        if ADMIN_TOKEN:
            sent = request.headers.get("x-admin-token") or request.query_params.get("admin_token") or ""
            if not secrets.compare_digest(sent, ADMIN_TOKEN):
                return JSONResponse({"error": "admin token required"}, status_code=403)
        elif (request.client.host if request.client else None) not in _LOOPBACK:
            return JSONResponse(
                {"error": "admin API is loopback-only; set KGC_ADMIN_TOKEN to allow remote access"},
                status_code=403)
    return await call_next(request)

@app.middleware("http")
async def serialize_state_writes(request: Request, call_next):
    """One request at a time may read-modify-write player state.

    Handlers load state, mutate it and save it as separate steps, so without
    this the :8080 and :8443 processes interleave and one silently discards the
    other's changes. CDN traffic never touches state - skip it, it is the bulk
    of the bytes.
    """
    if request.url.path.startswith("/patch/"):
        return await call_next(request)
    # Resolve identity BEFORE taking the lock: the ContextVar must be set in this
    # task so the child task call_next() spawns inherits it.
    token = CURRENT_UID.set(playerdb.uid_for_token(request.headers.get("accesstoken")))
    try:
        # asyncio.Lock first: flock blocks the thread, so a second request in THIS
        # process waiting on it would freeze the event loop and never let the holder
        # finish. Serialize in-process, then contend with the other process.
        async with _STATE_GATE:
            with playerdb.write_lock():
                return await call_next(request)
    finally:
        CURRENT_UID.reset(token)

@app.get("/")
def health():
    return {"server": "kgc-private", "version": SERVER_VERSION, "routes": len(ROUTE_MODELS), "patchFolder": PATCH_FOLDER}

# Real patch-set files cloned byte-for-byte from Awesomepiece CDN
# (https://kgc-cdn-1.awesomepiece.com/patch/LIVE/<patchFolder>/ANDROID/). These are
# guaranteed version-compatible with the client (they ARE the real bundles), so
# UpdatePatchSetList loads the manifest + validates hashes without error.
# AssetHash.txt confirms format <name>:<md5>_<size>; manifest is the "ANDROID" file.
REAL_CDN = ROOT / "real_cdn"
_CDN_FILES = {p.name: p.read_bytes() for p in REAL_CDN.iterdir()} if REAL_CDN.is_dir() else {}
admin_log(f"[cdn] cloned {len(_CDN_FILES)} real patch files: {sorted(_CDN_FILES)}")

@app.get("/patch/{path:path}")
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

async def respond(path: str, request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    raw = await request.body()
    body = {}
    if raw:
        try:
            body = aes_decrypt(raw)
        except Exception:
            try:
                body = json.loads(raw)
            except Exception:
                if path == "/deck/set":
                    admin_log(f"[DECK/SET DECRYPT FAIL] raw_len={len(raw)} raw_hex={raw[:64].hex()}")
                body = {}
    info = ROUTE_MODELS.get(path, {"response": "ResponseModel", "method": None})
    # /auth/auth carries the account id as ?id=, /auth/register as body.id.
    if path.startswith("/auth/"):
        CURRENT_LOGIN_ID.set(request.query_params.get("id") or body.get("id") or "")
    overlay = OVERRIDES[path](body, st) if path in OVERRIDES else None
    if overlay is None and path not in ROUTE_MODELS:
        model_name = "ResponseModel"
        if "/territory/recover-labor" in path: model_name = "TerritoryRecoverLaborResponseModel"
        elif "/invasion/reward" in path: model_name = "ReceiveInvasionRewardResponseModel"
        elif "/mission/check" in path: model_name = "MissionResponseModel"
        else:
            admin_log(f"[UNKNOWN PATH] {request.method} {path}")
        info = {"response": model_name, "method": None}
    payload = build_model(info["response"], overlay)
    admin_log(f"[{host}] {request.method} {path} -> {info.get('response')}")
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

def make_handler(path):
    async def h(request: Request):
        return await respond(path, request)
    return h

# Direct route handlers - must be registered BEFORE route_models to bypass build_model
@app.get("/accessory")
async def accessory_inventory_direct(request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    admin_log(f"[{host}] DIRECT GET /accessory -> AccessoryInventoryResponseModel")
    payload = {
        "code": 200, "msg": None, "success": True,
        "accessories": get_st_accessories(st)
    }
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

@app.post("/accessory")
async def accessory_equip_direct(request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    raw = await request.body()
    body = {}
    if raw:
        try:
            body = aes_decrypt(raw)
        except Exception:
            try:
                body = json.loads(raw)
            except Exception:
                pass
    admin_log(f"[{host}] DIRECT POST /accessory -> AccessoryResultResponseModel")
    accs = get_st_accessories(st)
    target_ids = body.get("targetIds", [])
    unit_id = body.get("unitId", 0)
    if target_ids and unit_id:
        for a in accs:
            if a["unitId"] == unit_id:
                a["unitId"] = 0
            if a["id"] in target_ids:
                a["unitId"] = unit_id
        save_state(st)
    payload = {
        "code": 200, "msg": None, "success": True,
        "accessories": accs,
        "deletedAccessories": [],
        "playerGold": st.get("gold", 0),
        "playerCash": st.get("cash", 0),
        "inventories": [],
        "addedExpItems": 0
    }
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

@app.get("/rift-weapon")
@app.post("/rift-weapon")
async def rift_weapon_inventory_direct(request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    admin_log(f"[{host}] DIRECT /rift-weapon -> RiftWeaponInventoryResponseModel")
    payload = r_rift_weapon({}, st)
    payload["code"] = 200
    payload["success"] = True
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

@app.get("/invasion/record")
@app.post("/invasion/record")
async def invasion_record_direct(request: Request):
    host = request.headers.get("host", "?")
    admin_log(f"  [{host}] DIRECT /invasion/record -> InvasionRecordsResponseModel")
    
    unlocked = RCFG["player"]["invasionUnlockedDifficulty"]
    themes = [t for a, b in RCFG["player"]["invasionThemeRanges"] for t in range(a, b)] + _PREREQ_THEMES
    records = []
    for t in themes:
        for d in range(1, unlocked + 1):
            records.append({"theme": t, "difficulty": d, "unlockedDifficulty": unlocked})
            
    payload = {
        "code": 200, "msg": None, "success": True,
        "difficultyRecords": records
    }
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

# Inbox (Post) - GET /post lists mail (PostResponseModel.posts), POST /post/receive claims
# (PostReceiveRequestModel{postId,receiveAll} -> PostReceiveResponseModel.rewardListResponseData).
# Mail lives in state so it persists and disappears once claimed. Reward grant is applied to
# player currency on claim so the send->receive->grant flow is real, not cosmetic.
@app.post("/admin/sendmail")
async def admin_send_mail(request: Request):
    st = load_state()
    body = await request.json()
    if "posts" not in st:
        st["posts"] = []
    next_id = max((p["id"] for p in st["posts"]), default=0) + 1
    title = body.get("title", "")
    text = body.get("text", "")
    for f in (title, text):
        if f.startswith("@raw:"):
            f = f[5:]
    st["posts"].append({
        "id": next_id,
        "type": body.get("type", "Normal"),
        "title": title,
        "text": text,
        "rewardType": body.get("rewardType", ""),
        "rewardId": body.get("rewardId", 0),
        "rewardAmount": body.get("rewardAmount", 0),
        "untilAt": now_iso(body.get("untilDays", 30)),
    })
    save_state(st)
    return {"code": 200, "success": True, "postId": next_id}

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

def _grant_reward(st, rt, rid, amt):
    """Apply a claimed mail reward to player state. Currencies, inventory items, and hero
    souls/cards persist here; the client re-fetches /player, /player/getInventory and /card/all
    after a claim so the granted state appears. Complex owned-content (Artifact/Treasure/
    Accessory) is intentionally NOT auto-granted into state - it can trip client panel
    invariants (see AGENTS.md ArtifactOptionUI crash); gift those as an Item reward box
    (InventoryItems.xml Type=RewardBoxInventory/InstantRewardBox) which the player opens."""
    if rt == "Gold":
        st["gold"] = st.get("gold", 0) + amt
    elif rt == "Cash":
        st["cash"] = st.get("cash", 0) + amt
    elif rt == "Heart":
        st["heart"] = st.get("heart", 0) + amt
    elif rt == "Item" and rid:
        inv = st.setdefault("inventory", {"itemIds": [], "counts": []})
        ids = inv.setdefault("itemIds", [])
        cnts = inv.setdefault("counts", [])
        if rid in ids:
            cnts[ids.index(rid)] += (amt or 1)
        else:
            ids.append(rid)
            cnts.append(amt or 1)
    elif rt in ("Unit", "Card") and rid:
        st.setdefault("cards", {}).setdefault(str(rid), {"unitId": rid, **SEED["cardTemplate"]})
    elif rt == "UnitSoul" and rid:
        c = st.setdefault("cards", {}).setdefault(str(rid), {"unitId": rid, **SEED["cardTemplate"]})
        c["soul"] = c.get("soul", 0) + amt

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
        out.append(p)
    return out

@app.get("/post")
async def post_list_direct(request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    admin_log(f"[{host}] DIRECT GET /post -> PostResponseModel")
    payload = {"code": 200, "msg": None, "success": True, "posts": _process_posts(get_st_posts(st))}
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

@app.post("/post/receive")
async def post_receive_direct(request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    raw = await request.body()
    body = {}
    if raw:
        try:
            body = aes_decrypt(raw)
        except Exception:
            try:
                body = json.loads(raw)
            except Exception:
                pass
    posts = get_st_posts(st)
    post_id = body.get("postId", 0)
    receive_all = body.get("receiveAll", False)
    claimed = [p for p in posts if receive_all or p["id"] == post_id]
    reward_list = []
    for p in claimed:
        amt = p.get("rewardAmount", 0)
        rt = p.get("rewardType", "")
        rid = p.get("rewardId", 0)
        _grant_reward(st, rt, rid, amt)
        if amt or rid:
            reward_list.append({"type": rt, "id": rid, "count": amt})
    st["posts"] = [p for p in posts if p not in claimed]
    save_state(st)
    admin_log(f"[{host}] DIRECT POST /post/receive claimed={len(claimed)} -> PostReceiveResponseModel")
    payload = {
        "code": 200, "msg": None, "success": True,
        "rewardListResponseData": {
            "rewardList": reward_list,
            "artifactResult": None, "treasureResult": None, "accessoryResult": None,
        },
        "playerGold": st.get("gold", 0), "playerCash": st.get("cash", 0), "playerHeart": st.get("heart", 0),
    }
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

# Direct PvP handler - must be registered BEFORE route_models to take priority
@app.get("/pvp/info")
@app.post("/pvp/info")
async def pvp_info_direct(request: Request):
    # The response is fixed config, so the request body is never read - don't decrypt it.
    host = request.headers.get("host", "?")
    payload = {"code": 200, "msg": None, "success": True}
    payload.update(RCFG["pvpInfoDirect"])
    admin_log(f"[{host}] PVP DIRECT /pvp/info -> seasonUntilAtDates={len(payload['seasonUntilAtDates'])}")
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

# ── Admin Panel ─────────────────────────────────────────────────────────
# The UI lives in dashboard.py (:8081) - a Vue app served from webui/. This route used
# to render admin.html, but that file has not existed for a long time, so /admin was
# quietly serving a blank page. The /admin/api/* routes below are still live: the
# dashboard proxies them for the server-side views, and creates players through them so
# the "new save" shape stays defined in exactly one place.
DASHBOARD_URL = os.environ.get("KGC_DASHBOARD_URL", "http://127.0.0.1:8081")

# ── Multi-player helpers ──
def _list_players():
    result = []
    for uid, data, updated in playerdb.all_players():
        if data is None:
            result.append({"id": uid, "name": f"[invalid] {uid}", "error": True})
            continue
        result.append({
            "id": uid,
            "name": data.get("name", "Unknown"),
            "uid": data.get("uid", ""),
            "level": data.get("level", 1),
            "gold": data.get("gold", 0),
            "cash": data.get("cash", 0),
            "castleName": data.get("castleName", ""),
            "cards": len(data.get("cards", {})),
            "updatedAt": datetime.datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M"),
        })
    return result

def _load_player_by_id(pid):
    return playerdb.load(pid)

def _save_player_by_id(pid, data):
    playerdb.save(pid, data)

def _delete_player_by_id(pid):
    playerdb.delete(pid)

def _switch_active(pid):
    """Point the game client at player pid."""
    if playerdb.load(pid) is None:
        return False
    playerdb.set_active(pid)
    return True

def _load_or_create_active():
    return load_state()

@app.get("/admin")
async def admin_page():
    return HTMLResponse(
        f'<!doctype html><meta charset="utf-8"><title>KGC admin</title>'
        f'<body style="font:15px system-ui;background:#0b0f17;color:#e6ecf7;padding:40px">'
        f'<h1 style="font-size:18px">The admin UI moved</h1>'
        f'<p>It is now the dashboard at <a style="color:#7aa8ff" href="{DASHBOARD_URL}">{DASHBOARD_URL}</a> '
        f'(<code>python3 server/dashboard.py</code>).</p>'
        f'<p style="color:#6d7c99">This server still serves the <code>/admin/api/*</code> endpoints '
        f'the dashboard calls.</p>')

@app.get("/admin/api/info")
async def admin_info():
    players = _list_players()
    active = playerdb.active()
    return {
        "version": SERVER_VERSION, "patchFolder": PATCH_FOLDER,
        "routes": len(ROUTE_MODELS) + len(OVERRIDES),
        "players": players,
        "playerCount": len(players),
        "activePlayerId": active,
    }

# ── Player CRUD ──
@app.get("/admin/api/players")
async def admin_list_players():
    return {"players": _list_players()}

@app.post("/admin/api/players/create")
async def admin_create_player(body: dict):
    name = body.get("name", "NewPlayer")
    uid = body.get("uid", "player-" + secrets.token_hex(4))
    st = copy.deepcopy(DEFAULT_PLAYER)   # deep: a shallow copy shares nested dicts with the template
    st["name"] = name
    st["uid"] = uid
    st["accountCreatedAt"] = now_iso(0)
    st["lastHeartTime"] = now_iso(0)
    st["tomorrow"] = now_iso(1)
    st["nextWeek"] = now_iso(7)
    _save_player_by_id(uid, st)
    return {"ok": True, "uid": uid}

@app.post("/admin/api/players/delete")
async def admin_delete_player(body: dict):
    pid = body.get("uid", "")
    _delete_player_by_id(pid)
    # playerdb.active() falls back to the first remaining row on its own.
    return {"ok": True}

@app.post("/admin/api/players/switch")
async def admin_switch_player(body: dict):
    pid = body.get("uid", "")
    if _switch_active(pid):
        return {"ok": True}
    return {"ok": False, "error": "Player not found"}

@app.get("/admin/api/players/{pid}")
async def admin_get_player_by_id(pid: str):
    data = _load_player_by_id(pid)
    if not data:
        return {"error": "not found"}
    return data

@app.post("/admin/api/players/{pid}/save")
async def admin_save_player_by_id(pid: str, body: dict):
    # body may contain partial updates or full state
    existing = _load_player_by_id(pid) or {}
    existing.update(body)
    _save_player_by_id(pid, existing)
    return {"ok": True}

@app.post("/admin/api/players/{pid}/reset")
async def admin_reset_player_by_id(pid: str):
    st = copy.deepcopy(DEFAULT_PLAYER)
    st["uid"] = pid
    _save_player_by_id(pid, st)
    return {"ok": True}

# ── Legacy single-player endpoints (target active) ──
@app.get("/admin/api/player")
async def admin_get_active_player():
    st = _load_or_create_active()
    fields = {
        "accountId": st.get("accountId", 1),
        "uid": st.get("uid", ""),
        "name": st.get("name", ""),
        "castleName": st.get("castleName", ""),
        "level": st.get("level", 1),
        "exp": st.get("exp", 0),
        "gold": st.get("gold", 0),
        "cash": st.get("cash", 0),
        "paidCash": st.get("paidCash", 0),
        "heart": st.get("heart", 0),
        "bestClearedStage": st.get("bestClearedStage", 1),
        "bestClearedTheme": st.get("bestClearedTheme", 1),
        "bestClearedHardStage": st.get("bestClearedHardStage", 1),
        "bestClearedHardTheme": st.get("bestClearedHardTheme", 1),
        "currentDeckPreset": st.get("currentDeckPreset", 0),
        "playedCount": st.get("playedCount", 0),
        "winCount": st.get("winCount", 0),
        "hasFreeRename": st.get("hasFreeRename", True),
        "buildingPoints": st.get("buildingPoints", 25),
        "accountCreatedAt": st.get("accountCreatedAt", ""),
        "lastHeartTime": st.get("lastHeartTime", ""),
        "tomorrow": st.get("tomorrow", ""),
        "nextWeek": st.get("nextWeek", ""),
        "eventFlag": st.get("eventFlag", 0),
        "cards": st.get("cards", {}),
        "decks": st.get("decks", []),
        "inventory": st.get("inventory", {"itemIds": [], "counts": []}),
        "equippedArtifacts": st.get("equippedArtifacts", []),
        "buildingPresets": st.get("buildingPresets", []),
        "altarPoints": st.get("altarPoints", []),
        "altarLevels": st.get("altarLevels", []),
        "tokens": st.get("tokens", []),
        "missions": st.get("missions", []),
        "tutorialKeyValues": st.get("tutorialKeyValues", []),
    }
    return fields

SKIP_KEYS = {"cards", "inventory", "decks", "equippedArtifacts", "buildingPresets",
              "altarPoints", "altarLevels", "tokens"}

@app.post("/admin/api/player/save")
async def admin_save_active_player(body: dict):
    st = _load_or_create_active()
    for k in ("name", "castleName", "level", "exp", "bestClearedStage", "bestClearedTheme",
              "bestClearedHardStage", "bestClearedHardTheme", "playedCount", "winCount",
              "hasFreeRename", "currentDeckPreset", "gold", "cash", "paidCash", "heart",
              "buildingPoints"):
        if k in body:
            st[k] = body[k]
    for k in ("tomorrow", "nextWeek", "accountCreatedAt", "lastHeartTime"):
        if k in body:
            st[k] = body[k]
    for k in ("inventory", "tokens", "buildingPresets", "altarPoints", "altarLevels",
              "missions", "tutorialKeyValues", "eventFlag"):
        if k in body:
            st[k] = body[k]
    save_state(st)
    return {"ok": True}

@app.post("/admin/api/player/reset")
async def admin_reset_active_player():
    st = copy.deepcopy(DEFAULT_PLAYER)
    st["uid"] = playerdb.active() or st.get("uid", "dev-0001")   # reset the data, keep the identity
    save_state(st)
    return {"ok": True}

@app.post("/admin/api/heroes/save")
async def admin_save_heroes(body: dict):
    st = _load_or_create_active()
    if "cards" in body:
        st["cards"] = body["cards"]
    save_state(st)
    return {"ok": True}

@app.post("/admin/api/heroes/give-all")
async def admin_give_all_heroes():
    st = _load_or_create_active()
    template = {
        "level": 30, "exp": 0, "potentialTier": 1,
        "skins": [], "favoriteSkinIds": [], "currentSkin": 0,
        "randomSkinApply": False, "soul": 999
    }
    cards = st.setdefault("cards", {})
    for hid in ALL_HERO_IDS:
        sid = str(hid)
        if sid not in cards:
            cards[sid] = {"unitId": hid, **template}
    save_state(st)
    return {"ok": True, "count": len(cards)}

@app.post("/admin/api/decks/save")
async def admin_save_decks(body: dict):
    st = _load_or_create_active()
    if "decks" in body:
        st["decks"] = body["decks"]
    save_state(st)
    return {"ok": True}

@app.post("/admin/api/artifacts/give-all")
async def admin_give_all_artifacts():
    return {"ok": True, "count": len(DEFAULT_ARTIFACTS)}

@app.post("/admin/api/treasures/give-all")
async def admin_give_all_treasures():
    return {"ok": True, "count": len(DEFAULT_TREASURES)}

# One crystal per weapon, each pointed at a different altar so the set actually covers
# distinct options instead of six copies of "Rift Crystal of Hero".
DEFAULT_RIFT_CRYSTALS = [make_rift_crystal(i + 1, rwid, main_idx=i)
                         for i, rwid in enumerate(ALL_RIFT_WEAPON_IDS)]

@app.post("/admin/api/rift-crystals/grant")
async def admin_grant_rift_crystals(request: Request):
    body = await request.json()
    weapon_id = body.get("weaponId", 0)
    st = _load_or_create_active()
    rift_crystals = st.setdefault("riftCrystals", [])
    max_id = max((c["id"] for c in rift_crystals), default=0)
    match = [t for t in DEFAULT_RIFT_CRYSTALS if t["weaponId"] == weapon_id]
    if not match:
        return {"ok": False, "error": f"no template for weaponId {weapon_id}"}
    new = dict(match[0])
    new["id"] = max_id + 1
    new["createdAt"] = now_iso()
    new["updatedAt"] = now_iso()
    rift_crystals.append(new)
    save_state(st)
    return {"ok": True, "crystal": new}

@app.post("/admin/api/state/reload")
async def admin_reload_state():
    _load_or_create_active()
    return {"ok": True}

CONFIG_FILE = DATA_DIR / "response_config.json"

@app.get("/admin/api/config")
async def admin_get_config():
    return json.loads(CONFIG_FILE.read_text())

@app.post("/admin/api/config/save")
async def admin_save_config(body: dict):
    CONFIG_FILE.write_text(json.dumps(body, indent=2))
    global RCFG
    RCFG = body
    return {"ok": True}

@app.get("/admin/api/logs")
async def admin_get_logs():
    return LOG_BUF[-100:]

@app.get("/admin/api/system")
async def admin_system():
    uptime = int(time.time() - SERVER_START_TIME)
    return {
        "version": SERVER_VERSION,
        "patchFolder": PATCH_FOLDER,
        "startTime": datetime.datetime.fromtimestamp(SERVER_START_TIME).strftime("%Y-%m-%d %H:%M:%S"),
        "uptime": uptime,
        "uptimeStr": f"{uptime//3600}h{(uptime%3600)//60}m{uptime%60}s",
        "routeCount": len(ROUTE_MODELS),
        "overrideCount": len(OVERRIDES),
        "playerCount": playerdb.count(),
        "cdmFiles": len(_CDN_FILES),
        "logLines": len(LOG_BUF),
    }

@app.get("/admin/api/routes")
async def admin_routes():
    items = []
    for path, model in sorted(ROUTE_MODELS.items()):
        is_overridden = path in OVERRIDES
        items.append({
            "path": path,
            "model": model.__class__.__name__ if hasattr(model, '__class__') else str(model)[:60],
            "overridden": is_overridden,
        })
    return {"routes": items, "total": len(items)}

@app.get("/admin/api/cdn")
async def admin_cdn():
    items = []
    for name, data in sorted(_CDN_FILES.items()):
        items.append({"name": name, "size": len(data)})
    return {"files": items, "total": len(items)}

@app.post("/admin/api/restart")
async def admin_restart():
    import os, sys
    os.execl(sys.executable, sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080")

for _r in ROUTE_MODELS:
    app.add_api_route(_r, make_handler(_r), methods=["GET", "POST", "PUT"])

@app.get("/x2/xls.cgi")
async def cdn_xls_cgi(request: Request):
    """Handle CDN patch-query requests: /x2/xls.cgi?p=XXXX&q=base64data"""
    host = request.headers.get("host", "?")
    q = request.query_params.get("q", "")
    p = request.query_params.get("p", "")
    admin_log(f"[{host}] CDN XLS query p={p} q_len={len(q)}")
    return Response(PATCH_FOLDER.encode(), media_type="text/plain")

@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT"])
async def catch_all(full_path: str, request: Request):
    return await respond("/" + full_path, request)
