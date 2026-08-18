"""Invasion + challenge-mode routes: claim lists, per-theme claims, the challenge
track (Season 71 Story-Challenge boss sits on theme 4100), and the daily tier.

Reward grants share the mission vocabulary (Key names a ShopItem), so they route
through rewards._grant_mission_reward via srv.
"""
from common import admin_log, body_int, now_iso
from config import RCFG, XML_DIR
from state import save_state
import challenge

srv = None      # live server module, injected via register()


def register(app, server_module):
    global srv
    srv = server_module
    srv.CHALLENGE_OVERRIDES = handlers()


def handlers():
    return {
        "/invasion/reward": r_invasion_reward,
        "/invasion/reward-all": r_invasion_reward_all,
        "/invasion/receive-all": r_invasion_reward_all,
        "/challenge/info": r_challenge_info,
        "/challenge/reward": r_challenge_reward,
        "/challenge/daily": r_challenge_daily,
    }


def _invasion_rewards():
    """The full claimable table, keyed by (theme, difficulty).

    The entry id encodes both: 101 is theme 1 difficulty 1, 6905 is theme 69
    difficulty 5. Each section lists tag-named rewards (Cash, Key, InventoryItem,
    Artifact, ...) with ID/Count attributes."""
    import xml.etree.ElementTree as _ET
    root = _ET.parse(XML_DIR / "InvasionRewards.xml").getroot()
    out = {}
    for e in root:
        if not e.get("ID"):
            continue
        rid = int(e.get("ID"))
        theme, diff = divmod(rid, 100)
        sections = {}
        for sec in ("Rewards", "PassRewards"):
            node = e.find(sec)
            sections[sec] = [] if node is None else [
                {"type": t.tag, "id": int(t.get("ID", 0)), "count": int(t.get("Count", 1))}
                for t in node]
        out[(theme, diff)] = sections
    return out


INVASION_REWARDS = _invasion_rewards()
admin_log(f"[invasion] {len(INVASION_REWARDS)} theme/difficulty reward rows")


def _invasion_claimed(st):
    """theme -> bitmask of claimed difficulties, matching the client's `rewardState`."""
    return st.setdefault("invasionRewardState", {})


def _invasion_grant(st, rewards):
    """Apply one invasion reward row. Shares the mission reward mapping - the tag
    names are the same vocabulary (Key names a ShopItem, Artifact is display-only)."""
    out = []
    for r in rewards:
        t = r["type"]
        if t == "InventoryItem":
            srv._grant_reward(st, "Item", r["id"], r["count"])
            out.append({"type": "Item", "id": r["id"], "count": r["count"]})
        elif t in ("Cash", "Gold", "Heart"):
            srv._grant_reward(st, t, 0, r["count"])
            out.append({"type": t, "id": 0, "count": r["count"]})
        elif t == "Card":
            out.append(srv._grant_mission_reward(st, {"type": "CardOrSoul", **r}))
        elif t == "Key":
            out.append(srv._grant_mission_reward(st, {"type": "Key", **r}))
        else:
            # Artifact / Treasure_Special / NewUnitGachaItem: shown, not written into
            # state, per the existing _grant_reward policy.
            out.append({"type": t, "id": r["id"], "count": r["count"]})
    return out


def _invasion_claim(st, theme, difficulty, with_pass):
    """Claim one theme/difficulty. Returns the reward list; empty if not eligible."""
    unlocked = RCFG["player"]["invasionUnlockedDifficulty"]
    if not (1 <= difficulty <= unlocked):
        return []
    row = INVASION_REWARDS.get((theme, difficulty))
    if row is None:
        return []
    mask = _invasion_claimed(st).get(str(theme), 0)
    bit = 1 << (difficulty - 1)
    if mask & bit:
        return []
    rewards = _invasion_grant(st, row["Rewards"])
    if with_pass:
        rewards += _invasion_grant(st, row["PassRewards"])
    _invasion_claimed(st)[str(theme)] = mask | bit
    return rewards


def _invasion_pass_index(theme):
    """Client ThemeIdToPassIndex(theme): the `index` field of the RewardData entry
    that a (theme, pass) probe matches. 10 themes share one index."""
    if theme <= 50:
        return 2 * ((theme - 1) // 10)
    return 1 + 2 * ((theme - 51) // 10)


def _invasion_pass_of(theme):
    """Client GetStartEndThemesByPassIndex: the panel pass tab that owns the theme
    (pass 0 = themes 1-5, 2 = 6-10, 4 = 11-15, 6 = 16-20, 1 = 51-55, ...)."""
    if theme <= 50:
        return 2 * ((theme - 1) // 5)
    return 1 + 2 * ((theme - 51) // 5)


def _invasion_entry_mask(st, themes):
    """Fold per-theme 5-bit masks into one RewardData entry's rewardState. The
    client reads bit (difficulty-1) + 5*((theme-1)%10) inside the entry, so each
    theme's bits go at its own 5-bit offset."""
    mask = 0
    for t in themes:
        mask |= _invasion_claimed(st).get(str(t), 0) << (5 * ((t - 1) % 10))
    return mask


def r_invasion_reward(body, st):
    """GET lists what is claimable, POST claims one theme/difficulty.

    Same GET/POST split as /shop and /accessory: a request naming a theme is a claim,
    a bare one is a listing. ReceiveInvasionRewardRequestModel is {theme, difficulty,
    pass}, so `theme` is the discriminator the client already sends.

    The response is InvasionRewardDatasResponseModel: RewardData{index, pass,
    rewardState}. The panel badge (GetReceivableRewardCount) iterates entries per
    pass and, for pass > 0, requires an entry with index == pass (HasInvasionPass),
    so alongside the per-group entries we emit one {index: pass, pass: pass} marker
    per pass 2..7 (passes 0 and 1 already match their own group entries)."""
    if not body.get("theme"):
        themes = sorted({t for (t, d) in INVASION_REWARDS})
        groups = {}
        for t in themes:
            groups.setdefault((_invasion_pass_index(t), _invasion_pass_of(t)), []).append(t)
        datas = [{"index": i, "pass": p, "rewardState": _invasion_entry_mask(st, ts)}
                 for (i, p), ts in sorted(groups.items())]
        extra = {}
        for t in range(1, 21):
            extra.setdefault(_invasion_pass_index(t), []).append(t)
        for i, ts in sorted(extra.items()):
            datas.append({"index": i, "pass": 1,
                          "rewardState": _invasion_entry_mask(st, ts)})
        datas += [{"index": p, "pass": p, "rewardState": 0} for p in range(2, 8)]
        return {"rewardDatas": datas}
    theme = body_int(body.get("theme"), 0)
    rewards = _invasion_claim(st, theme, body_int(body.get("difficulty"), 1),
                              bool(body.get("pass")))
    save_state(st)
    admin_log(f"[invasion] theme {theme} d{body.get('difficulty')} -> {len(rewards)} rewards")
    return {"rewardListData": srv._reward_list_data(rewards),
            "rewardState": _invasion_claimed(st).get(str(theme), 0)
            << (5 * ((theme - 1) % 10))}


def r_invasion_reward_all(body, st):
    """Claim every unclaimed, unlocked difficulty across every theme."""
    with_pass = bool(body.get("pass"))
    rewards = []
    for theme, diff in sorted(INVASION_REWARDS):
        rewards += _invasion_claim(st, theme, diff, with_pass)
    save_state(st)
    admin_log(f"[invasion] receive-all -> {len(rewards)} rewards")
    return {"rewardListData": srv._reward_list_data(rewards), "rewardState": 0}


# Challenge/roguelike themes start at 4000 (the Season 71 Story-Challenge boss 30000000
# sits on theme 4100); the story and invasion themes are all below it.
_CHALLENGE_THEME_MIN = 4000


def _challenge_state(st):
    st.setdefault("challenge", {"bestDifficulty": 0, "clearedBattles": 0,
                                "claimed": [], "dailyClaimedOn": ""})
    return st["challenge"]


def r_challenge_info(body, st):
    cs = _challenge_state(st)
    entries = challenge.track(xml_dir=XML_DIR)
    return {"bestClearedDifficulty": cs["bestDifficulty"],
            "unlockedDifficulty": challenge.unlocked_difficulty(xml_dir=XML_DIR),
            # Parallel to challenge.track()'s document order: 0 = not earned,
            # 1 = earned but unclaimed, 2 = claimed. Re-ordering the track would
            # silently misalign every index the client sends back.
            "rewardStates": [
                2 if i in cs["claimed"] else
                1 if challenge.earned(e, cs["bestDifficulty"], cs["clearedBattles"]) else 0
                for i, e in enumerate(entries)],
            "rewardResponse": None, "seasonEnabled": True,
            "startAt": now_iso(-30), "endAt": now_iso(30)}


def _challenge_grant(st, rewards):
    """Challenge rewards reuse the mission vocabulary, so Key still resolves through
    the ShopItem it names instead of landing in the inventory as item 0."""
    return [srv._grant_mission_reward(st, r) for r in rewards]


def r_challenge_reward(body, st):
    """Claim one track entry, or every earned one when no index is given."""
    cs = _challenge_state(st)
    entries = challenge.track(xml_dir=XML_DIR)
    idx = body.get("index") if body.get("index") is not None else body.get("rewardIdx")
    want = [body_int(idx, -1)] if idx is not None else range(len(entries))
    rewards = []
    for i in want:
        if not (0 <= i < len(entries)) or i in cs["claimed"]:
            continue
        if not challenge.earned(entries[i], cs["bestDifficulty"], cs["clearedBattles"]):
            continue
        rewards += _challenge_grant(st, entries[i]["rewards"])
        cs["claimed"].append(i)
    cs["claimed"].sort()
    save_state(st)
    admin_log(f"[challenge] claimed {len(rewards)} rewards, track {len(cs['claimed'])}/{len(entries)}")
    out = r_challenge_info(body, st)
    out["rewardResponse"] = srv._reward_list_data(rewards)
    return out


def r_challenge_daily(body, st):
    """One claim per UTC day, paying the tier for the best difficulty reached."""
    cs = _challenge_state(st)
    today = now_iso(0)[:10]
    if cs.get("dailyClaimedOn") == today:
        out = r_challenge_info(body, st)
        out["rewardResponse"] = srv._reward_list_data([])
        return out
    tiers = challenge.daily_track(xml_dir=XML_DIR)
    best = cs["bestDifficulty"]
    tier = max((d for d in tiers if d <= best), default=None)
    rewards = _challenge_grant(st, tiers[tier]) if tier is not None else []
    if rewards:
        cs["dailyClaimedOn"] = today
    save_state(st)
    admin_log(f"[challenge] daily tier {tier} -> {len(rewards)} rewards")
    out = r_challenge_info(body, st)
    out["rewardResponse"] = srv._reward_list_data(rewards)
    return out