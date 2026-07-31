"""Clan: a clan of one.

Twenty-eight clan routes answered an empty model, so a clan could be created but
never read back, renamed, chatted in, or left. The create route itself handed the
founder Constants.ClanRole.Member1 instead of Master, which hides every management
control from the person who just made the clan.

The invariant worth holding is that `clan` stays null until one exists:
GameManager.HasClan() reads it, and a fake clan object would show every account a
clan it does not have.
"""
import sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import playerdb
playerdb.DB_PATH = Path(tempfile.mkdtemp()) / "players.db"

from tests.seed import one_account
one_account()          # multiplayer mode does not mint a save; give load_state() one
import server


def _fresh():
    st = server.load_state()
    st.pop("clan", None)
    st["clanId"] = 0
    st["clanName"] = ""
    server.save_state(st)
    return st


def _create(name="BugClan"):
    _fresh()
    return server.r_clan_create({"name": name, "markId": 3, "intro": "hi"},
                                server.load_state())


def check_no_clan_reads_null():
    out = server.r_clan({}, _fresh())
    assert out["clan"] is None, "an account in no clan was handed a clan object"
    assert out["role"] == 0, f"role {out['role']} with no clan"
    assert not out["clanRaidEnabled"], "clan raid enabled without a clan"
    print("ok empty: no clan reads null, role 0")


def check_founder_is_master():
    out = _create()
    assert out["role"] == server.CLAN_MASTER, \
        f"the founder got role {out['role']}, not Master ({server.CLAN_MASTER})"
    m = out["clan"]["members"][0]
    assert m["role"] == server.CLAN_MASTER, "the member list disagrees with the role"
    assert m["accountId"] == out["clan"]["masterAccountId"], \
        "the master account id does not match the only member"
    assert out["clan"]["memberCount"] == 1
    assert not out["clan"]["canMandateMaster"], \
        "offered to hand the clan to somebody who does not exist"
    print(f"ok founder: role {out['role']}, one member, mandate offered = False")


def check_create_is_idempotent():
    first = _create("One")
    second = server.r_clan_create({"name": "Two"}, server.load_state())
    assert second["clan"]["name"] == "One", \
        "creating again replaced the existing clan"
    assert second["clan"]["id"] == first["clan"]["id"]
    print("ok create: a second create leaves the existing clan alone")


def check_fields_persist():
    _create()
    for route, key, value, read in (
            ("/clan/modify-name", "name", "Renamed", "name"),
            ("/clan/modifyIntro", "intro", "an intro", "intro"),
            ("/clan/modifyNotice", "notice", "a notice", "notice"),
            ("/clan/modifyMark", "markId", 7, "markId"),
            ("/clan/modifyJoinType", "joinType", 2, "joinType")):
        server.DYNAMIC_OVERRIDES[route]({key: value}, server.load_state())
        got = server.r_clan({}, server.load_state())["clan"][read]
        assert got == value, f"{route} left {read} as {got!r}, expected {value!r}"
    assert server.load_state()["clanName"] == "Renamed", \
        "the player's cached clan name did not follow the rename"
    print("ok fields: name, intro, notice, mark and join type all stick")


def check_chat_round_trip():
    _create()
    server.r_clan_chat({"message": "first"}, server.load_state())
    server.r_clan_chat({"message": "second"}, server.load_state())
    chats = server.r_clan_fetch_chat({}, server.load_state())["chats"]
    assert [c["message"] for c in chats] == ["first", "second"], f"got {chats}"
    assert [c["seqId"] for c in chats] == [1, 2], "sequence ids are not consecutive"
    assert server.r_clan_seq({}, server.load_state())["seqId"] == 2

    server.r_clan_delete_chat({"seqId": 1}, server.load_state())
    left = server.r_clan_fetch_chat({}, server.load_state())["chats"]
    assert [c["message"] for c in left] == ["second"], f"delete left {left}"

    server.r_clan_chat({}, server.load_state())
    assert len(server.r_clan_fetch_chat({}, server.load_state())["chats"]) == 1, \
        "an empty message was posted"
    print("ok chat: posts, sequences, deletes, and refuses an empty line")


def check_chat_is_trimmed():
    """The client re-reads the whole list on every refresh, so it cannot grow forever."""
    _create()
    for i in range(150):
        server.r_clan_chat({"message": f"m{i}"}, server.load_state())
    chats = server.r_clan_fetch_chat({}, server.load_state())["chats"]
    assert len(chats) == 100, f"{len(chats)} messages kept"
    assert chats[-1]["message"] == "m149", "trimming dropped the newest, not the oldest"
    print(f"ok trim: {len(chats)} kept, newest retained")


def check_role_names_replace_not_append():
    _create()
    server.r_clan_role_name({"role": 1, "name": "Recruit"}, server.load_state())
    server.r_clan_role_name({"role": 1, "name": "Veteran"}, server.load_state())
    names = server.r_clan({}, server.load_state())["clan"]["roleNames"]
    assert len(names) == 1, f"role 1 has {len(names)} names: {names}"
    assert names[0]["name"] == "Veteran"
    server.r_clan_role_name({"role": 1, "name": ""}, server.load_state())
    assert not server.r_clan({}, server.load_state())["clan"]["roleNames"], \
        "clearing a rank name left the entry behind"
    print("ok roles: renaming a rank replaces its entry")


def check_raid_decks():
    _create()
    server.r_clan_raid_deck({"index": 0, "deck": [10260, 10150], "name": "A"},
                            server.load_state())
    server.r_clan_raid_deck({"index": 1, "deck": [10300], "name": "B"},
                            server.load_state())
    out = server.r_clan_raid_deck({}, server.load_state())
    assert [d["name"] for d in out["decks"]] == ["A", "B"], f"got {out['decks']}"
    assert out["bestDeck"]["deck"] == [10260, 10150]

    server.r_clan_raid_delete_deck({"index": 0}, server.load_state())
    out = server.r_clan_raid_deck({}, server.load_state())
    assert [d["name"] for d in out["decks"]] == ["B"], "the wrong deck was deleted"
    assert out["decks"][0]["index"] == 0, "indexes were not closed up after a delete"
    print("ok raid decks: saved, listed, deleted and re-indexed")


def check_raid_damage_keeps_the_best():
    _create()
    server.r_clan_raid_end({"damage": 5000}, server.load_state())
    server.r_clan_raid_end({"damage": 100}, server.load_state())
    state = server.r_clan_raid_state({}, server.load_state())
    assert state["totalDamage"] == 5000, f"damage fell back to {state['totalDamage']}"
    assert len(state["memberDamages"]) == 1
    print("ok raid: a worse run does not lower the recorded damage")


def check_leaving_disbands():
    _create()
    out = server.r_clan_leave({}, server.load_state())
    assert out["clan"] is None, "leaving left the clan behind"
    assert out["role"] == 0
    assert server.load_state()["clanId"] == 0
    assert not server.r_clan_fetch_chat({}, server.load_state())["chats"], \
        "chat survived the clan being disbanded"
    print("ok leave: a clan of one disbands, taking its chat with it")


def check_management_routes_do_not_crash_without_a_clan():
    """Every route must answer something the panel can render even with no clan."""
    _fresh()
    for path, fn in server.DYNAMIC_OVERRIDES.items():
        if not path.startswith("/clan"):
            continue
        if path == "/clan/create":
            continue
        out = fn({}, server.load_state())
        assert isinstance(out, dict), f"{path} returned {type(out)}"
    print("ok safety: every clan route answers with no clan present")


if __name__ == "__main__":
    check_no_clan_reads_null()
    check_founder_is_master()
    check_create_is_idempotent()
    check_fields_persist()
    check_chat_round_trip()
    check_chat_is_trimmed()
    check_role_names_replace_not_append()
    check_raid_decks()
    check_raid_damage_keeps_the_best()
    check_leaving_disbands()
    check_management_routes_do_not_crash_without_a_clan()
    print("\nall clan checks passed")
