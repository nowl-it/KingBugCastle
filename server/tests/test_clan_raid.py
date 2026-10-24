"""Guard the v174.1.00 Clan Raid responses.

The raid routes used to answer the wrong shape: `/clan/raid` returned a flat
{bossId, bossHp, phase} where the client reads ClanRaidResponseModel.clanRaid (a
nested ClanRaidModel), and the sibling handlers spelled their keys as
decks/memberDamages/supports/bestDeck while the models declare
clanRaidDeckInfos/members/supporters/bestDecks. The panel opened, read nulls, and
showed nothing - the "renamed-key" bug class api_audit.py exists to catch.

These are `test_*` so CI collects them (test_route_coverage.py's `check_*` only run
as a script). They pin each raid route to its RestAPI model's field names and prove
the persistent battle loop (damage -> remainHp -> killBoss -> advance) moves state.
"""
import json, sys
from pathlib import Path

_SERVER = Path(__file__).resolve().parent.parent
for _p in (_SERVER, _SERVER / "routes", _SERVER / "builders", _SERVER / "cli"):
    _sp = str(_p)
    if _sp not in sys.path:
        sys.path.insert(0, _sp)

import playerdb
# playerdb.DB_PATH is left alone at module scope; the stateful test redirects it via
# monkeypatch so the temp DB is undone after the test (same contract as
# test_v174_routes.py).

import config
import server
import state
import clan

RAID_MODELS = {
    "/clan/raid":             "ClanRaidResponseModel",
    "/clan/raid/deck":        "ClanRaidDeckInfoResponseModel",
    "/clan/raid/best-deck":   "ClanRaidBestDeckResponseModel",
    "/clan/raid/deck-name":   "ClanRaidDeckInfoResponseModel",
    "/clan/raid/delete-deck": "ClanRaidDeckInfoResponseModel",
    "/clan/raid/currentState": "ClanRaidMemberDamageSumResponseModel",
    "/clan/raid/end":         "ClanRaidResponseModel",
    "/clan/raid/support":     "ClanRaidSupportResponseModel",
}


def _declared(model):
    spec = json.loads((config.GENERATED / "models.json").read_text())[model]
    return {f["name"] for f in spec["fields"]}


def test_raid_routes_mapped_to_real_models():
    routes = config.load_route_models()
    for path, resp in RAID_MODELS.items():
        assert path in routes, f"{path} is not routed"
        assert routes[path]["response"] == resp, \
            f"{path} -> {routes[path]['response']}, expected {resp}"


def test_raid_handlers_send_no_shadow_keys():
    """No-clan handlers must answer only names their model declares (build_model adds
    `success`). A `decks`/`supports`/`memberDamages` key here is the bug returning."""
    for path, resp in RAID_MODELS.items():
        out = server.OVERRIDES[path]({}, {})
        allowed = _declared(resp) | {"success"}
        shadow = set(out) - allowed
        assert not shadow, f"{path} sends undeclared keys {sorted(shadow)} for {resp}"


def test_raid_battle_loop_persists_and_advances(tmp_path, monkeypatch):
    monkeypatch.setattr(playerdb, "DB_PATH", tmp_path / "raid.db")
    playerdb.init()
    state.use_default_player({"uid": "r", "name": "R", "castleName": "C", "level": 3})
    st = state.new_save("r")
    clan.r_clan_create({"name": "Ours"}, st)

    info = clan.r_clan_raid({}, st)["clanRaid"]
    assert info is not None
    assert set(info) >= {"clanId", "score", "killCount", "stage", "round", "boss",
                         "remainHp", "battleStartedAt", "decks", "bossList",
                         "seasonEndRank", "goldBonusTier"}
    assert set(info["bossList"]) == {42200, 42500}
    assert info["battleStartedAt"], "DateTime.Parse throws on a null date"
    hp0 = info["remainHp"]

    # partial damage drops remainHp and persists into the clan record
    end = clan.r_clan_raid_end({"damage": 1000, "isPracticeBattle": False}, st)
    assert end["killBoss"] is False
    assert end["clanRaid"]["remainHp"] == hp0 - 1000
    assert clan._raid(st)["remainHp"] == hp0 - 1000

    # a practice battle does not count
    before = clan._raid(st)["remainHp"]
    clan.r_clan_raid_end({"damage": 5000, "isPracticeBattle": True}, st)
    assert clan._raid(st)["remainHp"] == before

    # overkill kills the boss: killCount up, round advances, HP resets to full
    cur = clan._raid(st)["remainHp"]
    kill = clan.r_clan_raid_end({"damage": cur + 1, "isPracticeBattle": False}, st)
    assert kill["killBoss"] is True
    after = clan._raid(st)
    assert after["killCount"] == 1
    assert after["round"] == 2
    assert after["remainHp"] == clan._raid_max_hp(1)

    # decks persist under the model field name, not the old `decks`
    decks = clan.r_clan_raid_deck({"deckIdx": 0, "deck": [10000, 10010]}, st)
    assert "clanRaidDeckInfos" in decks and "decks" not in decks
    assert decks["clanRaidDeckInfos"][0]["deck"]["cards"][0]["unitId"] == 10000

    named = clan.r_clan_raid_deck_name({"deckIdx": 0, "deckName": "Main"}, st)
    assert named["clanRaidDeckInfos"][0]["deckName"] == "Main"

    # currentState / support use the names the models read (members/damageSum, supporters)
    cs = clan.r_clan_raid_state({}, st)
    assert "members" in cs and "damageSum" in cs["members"][0]
    assert "supporters" in clan.r_clan_raid_support({}, st)

    # deleting the slot re-indexes and echoes the list
    left = clan.r_clan_raid_delete_deck({"deckIdx": 0}, st)
    assert left["clanRaidDeckInfos"] == []
