"""
Clan APIs - create, manage, chat, raid
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import get, post


# --- Info ---

def fetch_clan() -> dict:
    """GET /clan - thông tin clan của mình"""
    return get("/clan")


def fetch_other_clan(clan_id: int) -> dict:
    """GET /clan/info - xem thông tin clan khác"""
    return get("/clan/info", params={"clanId": clan_id})


def search_clan(keyword: str, tags: list = None, search_start_offset: int = 0) -> dict:
    """POST /clan/search"""
    return post("/clan/search", {
        "keyword": keyword,
        "tags": tags or [],
        "searchStartOffset": search_start_offset
    })


def get_clan_ranking() -> dict:
    """GET /clan/ranking"""
    return get("/clan/ranking")


def get_clan_point_ranking(weekly: bool = False) -> dict:
    """GET /ranking/clan-point-ranking?weekly={bool}"""
    return get("/ranking/clan-point-ranking", params={"weekly": str(weekly).lower()})


# --- Management ---

def create_clan(name: str, tag: str, mark: int, join_type: int = 0, intro: str = "") -> dict:
    """POST /clan/create"""
    return post("/clan/create", {"name": name, "tag": tag, "mark": mark, "joinType": join_type, "intro": intro})


def leave_clan() -> dict:
    """POST /clan/leave"""
    return post("/clan/leave")


def delete_clan() -> dict:
    """POST /clan/delete"""
    return post("/clan/delete")


def request_join_clan(clan_id: int) -> dict:
    """POST /clan/requestJoin"""
    return post("/clan/requestJoin", {"clanId": clan_id})


def process_join_request(target_id: int, accept: bool) -> dict:
    """POST /clan/processRequestJoin"""
    return post("/clan/processRequestJoin", {"targetId": target_id, "accept": accept})


def ban_member(target_id: int) -> dict:
    """POST /clan/banMember"""
    return post("/clan/banMember", {"targetId": target_id})


def change_master(target_id: int) -> dict:
    """POST /clan/changeMaster"""
    return post("/clan/changeMaster", {"targetId": target_id})


def mandate_master(target_id: int) -> dict:
    """POST /clan/mandateMaster (ủy quyền)"""
    return post("/clan/mandateMaster", {"targetId": target_id})


def change_member_role(target_id: int, role: int) -> dict:
    """POST /clan/changeMemberRole"""
    return post("/clan/changeMemberRole", {"targetId": target_id, "role": role})


def modify_clan_name(name: str) -> dict:
    """POST /clan/modify-name"""
    return post("/clan/modify-name", {"name": name})


def modify_clan_intro(intro: str) -> dict:
    """POST /clan/modifyIntro"""
    return post("/clan/modifyIntro", {"intro": intro})


def modify_clan_notice(notice: str) -> dict:
    """POST /clan/modifyNotice"""
    return post("/clan/modifyNotice", {"notice": notice})


def modify_clan_join_type(join_type: int) -> dict:
    """POST /clan/modifyJoinType - 0=Open, 1=Approval, 2=Closed"""
    return post("/clan/modifyJoinType", {"joinType": join_type})


def modify_clan_mark(mark: int) -> dict:
    """POST /clan/modifyMark"""
    return post("/clan/modifyMark", {"mark": mark})


def modify_clan_tag(tag: str) -> dict:
    """POST /clan/modifyTag"""
    return post("/clan/modifyTag", {"tag": tag})


def change_clan_role_name(role: int, name: str) -> dict:
    """POST /clan/changeRoleName"""
    return post("/clan/changeRoleName", {"role": role, "name": name})


# --- Chat ---

def send_clan_chat(message: str) -> dict:
    """POST /clan/chat"""
    return post("/clan/chat", {"message": message})


def fetch_clan_chat(seq_id: int = 0) -> dict:
    """POST /clan/fetchChat"""
    return post("/clan/fetchChat", {"seqId": seq_id})


def refresh_clan_chat() -> dict:
    """POST /clan/refreshChat"""
    return post("/clan/refreshChat")


def delete_clan_chat(seq_id: int) -> dict:
    """POST /clan/deleteChat"""
    return post("/clan/deleteChat", {"seqId": seq_id})


def get_current_seq() -> dict:
    """GET /clan/currentSeq"""
    return get("/clan/currentSeq")


# --- Support ---

def request_support(unit_id: int) -> dict:
    """POST /clan/requestSupport"""
    return post("/clan/requestSupport", {"unitId": unit_id})


def give_support(all_members: bool = True) -> dict:
    """POST /clan/support?all={bool}"""
    return post("/clan/support", params={"all": str(all_members).lower()})


# --- Attendance ---

def clan_attendance_check() -> dict:
    """POST /clan/attendance"""
    return post("/clan/attendance")


# --- Raid ---

def fetch_clan_raid() -> dict:
    """GET /clan/raid - thông tin clan raid"""
    return get("/clan/raid")


def fetch_clan_raid_state() -> dict:
    """GET /clan/raid/currentState"""
    return get("/clan/raid/currentState")


def fetch_clan_raid_best_decks() -> dict:
    """GET /clan/raid/best-deck"""
    return get("/clan/raid/best-deck")


def fetch_clan_raid_supporters() -> dict:
    """GET /clan/raid/support"""
    return get("/clan/raid/support")


def set_raid_support_unit(unit_id: int) -> dict:
    """POST /clan/raid/support?unitId={id}"""
    return post("/clan/raid/support", params={"unitId": unit_id})


def end_clan_raid(battle_result: dict) -> dict:
    """POST /clan/raid/end"""
    return post("/clan/raid/end", battle_result)


def set_clan_raid_deck(deck_idx: int, cards: list, deck_name: str = "") -> dict:
    """POST /clan/raid/deck"""
    return post("/clan/raid/deck", {"deckIdx": deck_idx, "cards": cards, "deckName": deck_name})


def set_clan_raid_deck_name(deck_idx: int, deck_name: str) -> dict:
    """POST /clan/raid/deck-name?deckIdx={i}&deckName={name}"""
    return post("/clan/raid/deck-name", params={"deckIdx": deck_idx, "deckName": deck_name})


def delete_clan_raid_deck(deck_idx: int) -> dict:
    """POST /clan/raid/delete-deck?deckIdx={i}"""
    return post("/clan/raid/delete-deck", params={"deckIdx": deck_idx})


if __name__ == "__main__":
    import json
    print("=== Fetch Clan ===")
    try:
        result = fetch_clan()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error (cần login): {e}")
