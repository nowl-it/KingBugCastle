#!/usr/bin/env python3
"""KGC private server emulator.

Reconstructed from il2cpp dump (RestAPI class + Awesomepiece.Model + route strings).
Implements the full login critical path so the client boots past the title screen,
plus a generic dispatcher that returns a wire-valid ResponseModel for all ~284
endpoints. Player save is a single editable JSON in state/player.json with full
state persistence for cards, decks, inventory, missions, and game loop.

Run:  uvicorn server:app --host 0.0.0.0 --port 8080
"""
import asyncio, contextvars, json, time, copy, secrets, datetime, pathlib, hashlib, os, sys, random
import shutil, subprocess
from contextlib import asynccontextmanager, suppress

_HERE = pathlib.Path(__file__).resolve().parent
for _p in (_HERE, _HERE / "routes", _HERE / "builders", _HERE / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)
import playerdb
import rewardbox
import shop
import missions
import challenge
import territory
import decoration
import dimension
import attendance
import babel
import clan
import colosseum
import player_events
# import mini_games
import roster
import rift
import accessory
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, HTMLResponse
from crypto import aes_encrypt, aes_decrypt, encrypted_response

ALL_ROGUE_LIKE_DLCS = [
    {"dlc": 2400, "tier": 2},  # Altar of Death (6)
    {"dlc": 2410, "tier": 2},  # Altar of Immortality (7)
    {"dlc": 2420, "tier": 2},  # Altar of Domination (8)
]

# Shared primitives now live in common.py so domain modules can use them without
# importing server.py back. Re-exported under their old names: every handler below,
# and the tests, call them unqualified.
from common import (LOG_BUF, admin_log, trace, now_iso, next_reset_iso,
                    body_int, body_list, body_str, date_default)

# Cross-account reads (boards, matchmaking, player lookup) live in roster.py. Kept
# under their old private names so handlers and srv.* lookups did not have to move.
from roster import (all_states as _all_states, board as _board, current_uid as _current_uid,
                    deck_units as _deck_units, leaderboard as _leaderboard,
                    opponents as _opponents, player_by_id as _player_by_id,
                    rank_row as _rank_row)

# Paths, response config and the content gate live in config.py - a domain module
# needs RCFG/XML_DIR and cannot import server.py back. Re-exported under their old
# names so every handler below reads unqualified.
from config import (ROOT, DATA_DIR, STATE_DIR, MODELS, RCFG, STATIC_OVERRIDES,
                    ITEM_TEMPLATES, CONFIG_FILE, PATCH_FOLDER, SERVER_VERSION,
                    CONTENT_GATE, XML_DIR)
import config

ROUTE_MODELS = config.load_route_models()
STATE_DIR.mkdir(parents=True, exist_ok=True)

# Player level cap - client Constants.PlayerMaxLevel = 100
MAX_PLAYER_LEVEL = 100

# Player state lives in state/players.db (SQLite, WAL). The old JSON files are
# imported once and then left alone as a cold backup - they are NOT read again.
_migrated = playerdb.migrate_from_json(STATE_DIR)
if _migrated:
    admin_log(f"[state] migrated {_migrated} player(s) from JSON into {playerdb.DB_PATH.name}")
admin_log(f"[gate] serverVersion {SERVER_VERSION} -> content gate {CONTENT_GATE}")
admin_log(f"[xml] master data dir: {XML_DIR} ({len(list(XML_DIR.iterdir()))} files)")

# Identity, the save template and the read/write path live in state.py so handler
# modules can persist without importing server.py back. Re-exported under their old
# names; _registration_allowed keeps its underscore because tests reach for it.
from state import (CURRENT_UID, CURRENT_IP, MULTIPLAYER, MAX_PLAYERS, ADOPT_LONE_SAVE,
                   NEW_PLAYER_PER_IP, NEW_PLAYER_WINDOW,
                   load_state, save_state, patch_state,
                   registration_allowed as _registration_allowed)
import state
state.announce()

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
            is_unreleased = min_ver and int(min_ver.group(1)) > CONTENT_GATE
            if not visible and not summoner and not is_unreleased:
                ids.append(uid)
    return ids

ALL_HERO_IDS = _all_hero_ids()

def _all_artifact_ids():
    """Real collectible artifacts (Type=Artifact) from Artifacts.xml, Root/
    Normal tier only (King/God/KingGod tier IDs are the same artifact at
    higher quality, not separate items). Excludes FromType=Special (Ghidra:
    ResourceArtifact.FromType enum value 5) - these are synthesis-stone
    materials (e.g. id 501/511/598, the fusion stone), and live testing (2026-07-02)
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
        if min_ver and int(min_ver.group(1)) > CONTENT_GATE:
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
        if min_ver and int(min_ver.group(1)) > CONTENT_GATE:
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
    altar index (Buildings.xml id)" per that file's own header).

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
# awakening is a single tier: 0 = not awakened, 1 = awakened (max).
# Seed potentialTier=0 (default_player.json cardTemplate) so fresh heroes do NOT
# show the awakened badge (client renders "CardPotentialTier_{tier}"); the client
# only enables the awaken button at level >= ReqLevel(16) and tier < Max(1).
# An earlier retest blamed potentialTier=1 for the DeckPanel boot crash, but
# Ghidra (2026-07-02, arm32 dump.cs FUN_01e1a018) proved the real cause was deck
# length vs. DeckPanel.currentDeck's fixed 6-slot UI array (see DEFAULT_DECKS
# below) - potentialTier was never the culprit, that test just happened to run
# before the deck-length fix was in place.
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
# Every "pad this list up to the index the client asked for" loop needs a ceiling.
# The index is client-supplied and unauthenticated, so without one a single request
# naming preset 999999999 makes the server allocate until it dies.
DECK_PRESETS = len(DEFAULT_DECKS)
BUILDING_PRESETS = 10          # _get_building_data pads to this
from clan import CLAN_RAID_DECKS

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
    potential = [max(0, p) if isinstance(p, int) else 0 for p in potential]
    potential = (potential + [0] * DECK_SLOTS)[:DECK_SLOTS]
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
    # Dominion tutorial #40 builds its free Chamber, then the Inn it unlocks.
    "tutorialKeyValues": [],
    "missions": [{"missionId": 1, "value": 1, "goalValue": 10, "clear": False, "createdAt": now_iso(0), "untilAt": now_iso(86400)}],
    "eventFlag": 0,
    "tokens": [],
}
# state.load_state() needs the template, and it is only complete here - the hero,
# item and deck lists above are content-gated against master data.
state.use_default_player(DEFAULT_PLAYER)

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
    if spec:
        # AFTER the overlay, not before. The client hands date-shaped strings to
        # DateTime.Parse, which throws on null AND on "" - and the nulls do not only
        # come from unset defaults. data/static_overrides.json writes some literally
        # (`"eventPackageItemsUntilAt": null`) and a handler writes `"passEndedAt": ""`,
        # so filling defaults alone left seven routes still carrying an unparseable
        # value. A handler that means "no deadline" has to say so with a date, because
        # null is not something the client can read.
        for f in spec["fields"]:
            if f["jtype"] == "string" and not out.get(f["name"]):
                out[f["name"]] = date_default(f["name"], now_iso) or out.get(f["name"])
    return out

def card_to_dict(c):
    tier = c.get("potentialTier", 0)
    if c["level"] >= 16 and tier == 0:
        tier = 1
    return {
        "unitId": c["unitId"], "level": c["level"], "exp": c.get("exp", 0),
        "potentialTier": tier,
        "skins": c.get("skins", []), "favoriteSkinIds": c.get("favoriteSkinIds", []),
        "currentSkin": c.get("currentSkin", 0), "randomSkinApply": c.get("randomSkinApply", False),
        "playerGold": 0, "playerCash": 0, "soul": c.get("soul", 0),
        "originLevel": c["level"], "originPotentialTier": tier,
        "isLevelSynced": False, "isTemporaryRecruited": False,
        "createdAt": now_iso(-30),
        # Null for an ordinary hero, which is correct; a dimension hero needs it or
        # its sync panel opens with no level, no gauge and no next cost.
        "dimensionUnit": dimension.model(c["unitId"], c.get("dimensionLevel", 0),
                                         c.get("dimensionGauge", 0),
                                         c.get("overcome", 0), XML_DIR),
    }

def cards_list(st):
    return [card_to_dict(c) for c in st.get("cards", {}).values()]

# The client's account id for the request being handled: `?id=` on /auth/auth,
# or `id` in the /auth/register body. Only r_login reads it.
CURRENT_LOGIN_ID = contextvars.ContextVar("current_login_id", default=None)

def counters(st):
    """Server-side progress tallies for the mission conditions this server can see.

    Only the routes below write here, so a counter can never advance for something
    that did not actually go through the server - see missions.py on why a mission it
    cannot observe stays unclaimable rather than being marked complete."""
    return st.setdefault("counters", {})

def bump(st, key, n=1, sub=None):
    c = counters(st)
    if sub is None:
        c[key] = c.get(key, 0) + n
    else:
        d = c.setdefault(key, {})
        d[str(sub)] = d.get(str(sub), 0) + n

def _claimed_missions(st):
    return set(st.setdefault("claimedMissions", []))

# Routes whose mere occurrence is a mission condition. Kept as a table applied in
# respond() rather than an increment inside each handler, because several of these
# paths share one handler (every /artifact/* mutation returns r_artifact_result), so
# per-handler bumps could not tell them apart.
_PATH_COUNTERS = {
    "/artifact/crafting": "artifactCraft",
    "/artifact/merge": "artifactMerge",
    "/artifact/dismantle": "artifactDismantle",
    "/artifact/polish": "artifactPolish",
    "/artifact/set-reroll": "artifactReforge",
    "/artifact/smart-reroll": "artifactReforge",
    "/artifact/gacha": "artifactGacha",
    "/accessory/dismantle": "accessoryDismantle",
    "/accessory/add-exp": "accessoryLevelUp",
    "/player/heart/recover": "chargeHeart",
    "/pvp/matching": "playArena",
    "/colosseum": "playArena",
    "/clan/requestSupport": "clanSupport",
    "/clan/support": "clanSupport",
}


ALL_ARTIFACT_IDS, ARTIFACT_LEVELS = _all_artifact_ids()
ALL_TREASURE_IDS = _all_treasure_ids()
ALL_RIFT_WEAPON_IDS = _all_rift_weapon_ids()



from routes.artifact_routes import (make_artifact, make_max_artifact, make_accessory,
    make_treasure, make_rift_weapon, make_rift_crystal,
    load_corruption_accessories, get_st_artifacts, get_st_treasures,
    get_st_accessories, _resolve_equipped_artifacts,
    _repair_rift_crystals, _acc_perscore)

# Dynamic overrides: routes whose response genuinely depends on request-time
# state/body (auth tokens, st.get() reads, mutations) or config wiring. Pure
# literal responses live in data/static_overrides.json instead (merged in below).
def _tutorial_key_values(st):
    """Tutorial progress persisted by the client/server, without forced skips."""
    return list(st.get("tutorialKeyValues") or [])


DYNAMIC_OVERRIDES = {
    "/auth/checkPatchVersion": lambda b, st: {"patchVersion": SERVER_VERSION},
    "/auth/getPatchFolder": lambda b, st: {"patchFolder": PATCH_FOLDER},
    "/auth/xcdSeed": lambda b, st: {"seed": secrets.token_hex(8), "serverTime": now_iso(0)},
    "/player/currencies": lambda b, st: {"gold": st.get("gold", 0), "cash": st.get("cash", 0), "heart": st.get("heart", 0)},
    "/player/tutorial-status": lambda b, st: {"keyValues": _tutorial_key_values(st)},
    "/player/tutorial/complete": lambda b, st: {"keyValues": _tutorial_key_values(st)},
    "/player/add-inventory-count": lambda b, st: {
        "playerCash": st.get("cash", 0),
        "inventoryCount": 999
    },
    "/player/heart/recover": lambda b, st: {"heart": st.get("heart", 999), "lastHeartTime": now_iso(0)},
    # GameManager.usePatch is hardcoded to 1 in the binary, so this answer is
    # advisory only - but it has to be the truthful one, since the CDN check runs
    # either way and we serve real cloned bundles.
    "/auth/usePatch": lambda b, st: {"usePatch": True},
    "/kgc-ranking": roster.r_ranking,
    "/ranking/ranking": roster.r_ranking,
    "/ranking/pvp-ranking": roster.r_ranking,
    "/ranking/pvp-league-ranking": roster.r_ranking,
    "/ranking/pvp-hall-of-fame": roster.r_ranking,
    "/ranking/colosseum-ranking": roster.r_ranking,
    "/ranking/colosseum-league-ranking": roster.r_ranking,
    "/ranking/colosseum-hall-of-fame": roster.r_ranking,
    "/ranking/dimension-rift-ranking": roster.r_ranking,
    "/ranking/challenge-mode-ranking": roster.r_ranking,
    "/ranking/clan-point-ranking": roster.r_ranking,
    "/ranking/roguelike-ranking": roster.r_ranking,
    "/ranking/roguelike-building-ranking": roster.r_ranking,
    "/clan/ranking": roster.r_ranking,
    "/stock-event/ranking": roster.r_ranking,
    "/seasonal-event/april-fools/reward": lambda b, st: {
        "rewardListResponseData": _reward_list_data([])},
    # /test/* are the client's own dev buttons. They exist in the build, so they
    # must answer, but nothing here is meant to rewrite a save from a debug menu.
    "/player/tutorial/progress-mission": lambda b, st: {
        "keyValues": _tutorial_key_values(st)},
    # One-way telemetry: posted, never read back.
    **rift.handlers(),
    **clan.handlers(),
    "/accessory": accessory.r_accessory_equip,
    "/accessory/equip": accessory.r_accessory_equip,
    "/accessory/equip-tutorial": accessory.r_accessory_equip_tutorial,
    "/accessory/release-equip": accessory.r_accessory_release,
    "/accessory/add-exp": accessory.r_accessory_add_exp,
    "/accessory/dismantle": accessory.r_accessory_dismantle,
    "/accessory/set-state": accessory.r_accessory_set_state,
    "/accessory/set-state-all": accessory.r_accessory_set_state,
    "/accessory/change-sub-stat": accessory.r_accessory_change_sub_stat,
    "/accessory/preset": accessory.r_accessory_preset_list,
    "/accessory/set-preset": accessory.r_accessory_set_preset,
    "/accessory/set-preset-name": accessory.r_accessory_set_preset_name,
    # The v171 client uses both spellings of the battle-start route.
}

SERVER_START_TIME = time.time()

# A public server holds other people's progress. Cron is the textbook answer and
# nobody sets it up, so this runs in-process; playerdb.backup_if_due does the
# due-check under the cross-process lock, which is what stops :8080 and :8443 both
# firing. KGC_BACKUP_HOURS=0 turns it off (use your own backups instead).
BACKUP_HOURS = float(os.environ.get("KGC_BACKUP_HOURS") or 24)


async def _periodic_backup_loop(interval):
    while True:
        try:
            # to_thread: the lock and the copy are blocking, and this must not
            # stall the event loop while a player is mid-request.
            dst = await asyncio.to_thread(playerdb.backup_if_due, interval)
            if dst:
                admin_log(f"[state] backup -> {dst.name}")
        except Exception as e:
            admin_log(f"[state] backup failed: {type(e).__name__}: {e}")
        await asyncio.sleep(min(3600, interval))


@asynccontextmanager
async def _lifespan(_app):
    """Own the backup worker for the complete ASGI application lifetime."""
    if BACKUP_HOURS <= 0:
        admin_log("[state] automatic backups off (KGC_BACKUP_HOURS=0)")
        yield
        return

    task = asyncio.create_task(_periodic_backup_loop(BACKUP_HOURS * 3600))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="KGC private server", version=SERVER_VERSION, lifespan=_lifespan)
_STATE_GATE = asyncio.Lock()

import security
security.register(app, sys.modules[__name__])
from security import (TRUST_PROXY, client_ip, _admin_ok, guard_admin,
                      RATE_LIMIT, RATE_WINDOW, RATE_BAN_AFTER, RATE_BAN_SECONDS,
                      IPTABLES_BAN, _rate_hits, _banned, _ban_strikes,
                      _iptables_rule, _unban_later, _ban, _rate_ok, rate_limit,
                      MAX_BODY, serialize_state_writes,
                      ADMIN_COOKIE)

# Google login web flow (client's Google button -> /glogin -> deep link back).
import google_login
google_login.register(app)
admin_log(f"[auth] google login {'ENABLED' if google_login.enabled() else 'not configured'}")

async def _read_capped(request):
    """The body, refusing to buffer more than MAX_BODY of it.

    The Content-Length middleware covers every real client request, but a chunked
    upload declares no length - and `request.body()` buffers the whole thing before
    anyone can check it. Reading the stream ourselves means an attacker gets one
    MAX_BODY allocation, not one per gigabyte they feel like sending.
    """
    return await security.read_capped_body(request, MAX_BODY)


async def respond(path: str, request: Request):
    st = load_state()
    host = request.headers.get("host", "?")
    try:
        raw = await _read_capped(request)
    except ValueError as e:
        admin_log(f"[limit] {path}: {e}")
        return JSONResponse({"error": "request body too large"}, status_code=413)
    body = {}
    if raw:
        try:
            body = aes_decrypt(raw)
        except Exception:
            try:
                body = json.loads(raw)
            except Exception:
                if path == "/deck/set":
                    admin_log(f"[DECK/SET DECRYPT FAIL] raw_len={len(raw)}")
                body = {}
    # A body of `5`, `"x"` or `[1,2]` is valid JSON but not an object, and every
    # handler below indexes it like a dict. Coerce here rather than guarding each
    # one: `/auth/register` with a bare integer body reached `body.get("id")` and
    # 500'd, which the client cannot parse (it wants the AES envelope) - it sits on
    # the loading screen instead of failing.
    if not isinstance(body, dict):
        body = {}
    # Many routes carry their arguments in the query string, not the body:
    # /territory/upgrade-building?posIndex={0}, /card?cardId={0}, /player/other?targetId={0}.
    # Handlers only ever saw the body, so every one of those arrived as an empty dict
    # and the request looked like it had no arguments at all. Body wins on a clash,
    # since a route that sends both means the body.
    if request.query_params:
        merged = {}
        for k, v in request.query_params.items():
            if v.lstrip("-").isdigit():
                merged[k] = int(v)
            elif v.lower() in ("true", "false"):
                merged[k] = v.lower() == "true"
            else:
                merged[k] = v
        merged.update(body)
        body = merged

    info = ROUTE_MODELS.get(path, {"response": "ResponseModel", "method": None})
    resp_model = info["response"]
    if path == "/shop" and (body.get("itemId") or body.get("gachaId")):
        resp_model = "BuyResponseModel"
    # /auth/auth carries the account id as ?id=, /auth/register as body.id.
    if path.startswith("/auth/"):
        CURRENT_LOGIN_ID.set(request.query_params.get("id") or body.get("id") or "")
    if path in _PATH_COUNTERS:
        bump(st, _PATH_COUNTERS[path])
        save_state(st)
    try:
        overlay = OVERRIDES[path](body, st) if path in OVERRIDES else None
    except Exception as e:
        # One player sending one bad body must not 500 - the client cannot parse a
        # FastAPI error page (it expects the AES envelope) and would sit on the
        # loading screen. Fall back to the route's empty model, which is the same
        # shape it would get from a route with no handler.
        admin_log(f"[HANDLER ERROR] {path}: {type(e).__name__}: {e}")
        overlay = None
    if overlay is None and path not in ROUTE_MODELS:
        # Every route the v171 client can call is now mapped (route_models.json plus
        # data/route_models_extra.json), so reaching here means either a route the
        # string-table scan missed or a client newer than this server.
        admin_log(f"[UNKNOWN PATH] {request.method} {path}")
    payload = build_model(resp_model, overlay)
    
    # Auto-fill common player state variables if the model expects them and the
    # handler didn't explicitly override them. Missing currencies freeze the client.
    auto_fields = {
        "playerGold": lambda: st.get("gold", 0),
        "playerCash": lambda: st.get("cash", 0),
        "playerHeart": lambda: st.get("heart", 0),
        "playerLevel": lambda: st.get("level", 1),
        "playerExp": lambda: st.get("exp", 0),
    }
    for field, get_val in auto_fields.items():
        if field in payload and (not overlay or field not in overlay):
            payload[field] = get_val()

    trace(f"[{host}] {request.method} {path} -> {info.get('response')}")
    return Response(aes_encrypt(payload), media_type="application/json", headers={"encryptedWithHex": "true"})

def make_handler(path):
    async def h(request: Request):
        return await respond(path, request)
    return h

# ── Admin, Inbox, Direct routes ──
# Registered before ROUTE_MODELS so they take priority over the generic dispatcher.
# One crystal per weapon, each pointed at a different altar so the set actually covers
# distinct options instead of six copies of "Rift Crystal of Hero".
DEFAULT_RIFT_CRYSTALS = [make_rift_crystal(i + 1, rwid, main_idx=i)
                         for i, rwid in enumerate(ALL_RIFT_WEAPON_IDS)]

import admin_api
import inbox
import direct_routes
import decoration_routes
# pvp.handlers() reads srv.r_ack at register time (a colosseum fallback), before
# the route modules below are wired - so r_ack is pulled in here, not via the loop.
from routes.player_routes import r_ack
import pvp
import territory_routes
import shop_routes
import seasonal
import mini_games
import rift
admin_api.register(app, sys.modules[__name__])
inbox.register(app, sys.modules[__name__])
_admin_changed = playerdb.backfill_account_ids()
if _admin_changed:
    admin_log(f"[accounts] backfilled {_admin_changed} duplicate/missing accountId(s)")
decoration_routes.register(app, sys.modules[__name__])
pvp.register(app, sys.modules[__name__])
territory_routes.register(app, sys.modules[__name__])
shop_routes.register(app, sys.modules[__name__])
seasonal.register(app, sys.modules[__name__])
roster.register(app, sys.modules[__name__])
mini_games.register(app, sys.modules[__name__])
rift.register(app, sys.modules[__name__])
# Last: its /pvp/info reads srv.PVP_OVERRIDES, which pvp.register above installs.
direct_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(DECORATION_OVERRIDES)
DYNAMIC_OVERRIDES.update(MINI_GAME_OVERRIDES)
DYNAMIC_OVERRIDES.update(PVP_OVERRIDES)
DYNAMIC_OVERRIDES.update(TERRITORY_OVERRIDES)
DYNAMIC_OVERRIDES.update(SHOP_OVERRIDES)
DYNAMIC_OVERRIDES.update(SEASONAL_OVERRIDES)
DYNAMIC_OVERRIDES.update(RANKING_OVERRIDES)
DYNAMIC_OVERRIDES.update(rift.handlers())
import rewards
import routes.missions_routes as missions_routes
import routes.game_routes as game_routes
import routes.card_routes as card_routes
import routes.inventory_routes as inventory_routes
import routes.challenge_routes as challenge_routes
import routes.player_routes as player_routes
import routes.artifact_routes as artifact_routes
import routes.seasonal_events_routes as seasonal_events_routes
import routes.attendance_routes as attendance_routes
rewards.set_srv(sys.modules[__name__])
missions_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(MISSION_OVERRIDES)
game_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(GAME_OVERRIDES)
card_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(CARD_OVERRIDES)
inventory_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(INVENTORY_OVERRIDES)
challenge_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(CHALLENGE_OVERRIDES)
player_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(PLAYER_OVERRIDES)
artifact_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(ARTIFACT_OVERRIDES)
seasonal_events_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(SEASONAL_EVENTS_OVERRIDES)
attendance_routes.register(app, sys.modules[__name__])
DYNAMIC_OVERRIDES.update(ATTENDANCE_OVERRIDES)

# Every extracted handler is re-exported here under the name it had while it lived in
# this file. The tests and the dashboard reach for `server.r_shop`, `server.r_clan`,
# `server.r_territory_fetch` and 80 more; rewriting 36 test files to chase a handler
# between modules is churn that would have to happen again on the next extraction, and
# it is also what makes a handler moving out of here a silent breakage rather than a
# failed import. One loop, one place to look.
for _mod in (clan, pvp, shop_routes, roster, seasonal, mini_games,
             territory_routes, decoration_routes, inbox, direct_routes, rewards,
             missions_routes, game_routes, card_routes, inventory_routes, challenge_routes, player_routes, artifact_routes,
             seasonal_events_routes, attendance_routes):
    for _n in dir(_mod):
        # Handlers and their helpers, plus the module's own SHOUTY constants
        # (CLAN_MASTER, TYCOON_TOKENS, JOURNEY_LAST, ...) which callers pin against.
        if _n.startswith("__") or _n in ("srv", "app"):
            continue
        if _n.startswith(("r_", "get_st_", "_")) or _n.isupper():
            globals().setdefault(_n, getattr(_mod, _n))
del _mod, _n

# OVERRIDES is what respond() dispatches on, and it is built HERE - after every
# handler group has been merged into DYNAMIC_OVERRIDES. It used to be built right
# after the DYNAMIC_OVERRIDES literal, which was correct until the decoration and
# mini-game handlers moved into their own modules and merged in below: the snapshot
# had already been taken, so ~30 routes silently answered an empty model. Nothing
# caught it, because route_coverage was reading DYNAMIC_OVERRIDES rather than the
# table that actually dispatches.
#
# Pure-literal routes (no st/body dependency) load straight from JSON; wrap each in a
# lambda returning the same shared dict (build_model only reads it via .update(),
# never mutates it, so no copy is needed).
OVERRIDES = {path: (lambda b, st, r=resp: r) for path, resp in STATIC_OVERRIDES.items()}
OVERRIDES.update(DYNAMIC_OVERRIDES)
assert set(DYNAMIC_OVERRIDES) <= set(OVERRIDES), "a handler group registered too late"

import cdn
cdn.register(app, sys.modules[__name__])

for _r in ROUTE_MODELS:
    app.add_api_route(_r, make_handler(_r), methods=["GET", "POST", "PUT"])

@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT"])
async def catch_all(full_path: str, request: Request):
    return await respond("/" + full_path, request)
