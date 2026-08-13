"""Everything that reads ACROSS accounts: leaderboards, matchmaking, player lookup.

A board is the one place a private server stops being single-player. Every board used
to answer an empty model, so each rendered as a blank list with no row for the player
either - and an empty `ranking` with a filled `playerRank` is not the same thing:
several panels scan the list to find themselves and show "unranked" when they cannot.

server.py re-exports these under their old private names (`_leaderboard`, `_board`,
`_opponents`, ...) so the handlers that call them did not have to move.

# ponytail: each call json-parses every player row. Fine at MAX_PLAYERS=200 for
# panels opened by hand; add a cached score index if the population ever grows.

    python3 roster.py     # self-check
"""
import playerdb
from config import PLAYER_DEFAULTS as _PC
from decoration import block as _deco
from state import CURRENT_UID

srv = None      # the live server module, set by register()


def current_uid():
    return CURRENT_UID.get() or playerdb.active()


def all_states(st):
    """(uid, state) for every registered player, the current one taken from the
    live `st` so its this-request edits show, not a stale DB read."""
    me = current_uid()
    out, seen = [], False
    for uid, s, _ in playerdb.all_players():
        if s is None:
            continue
        if uid == me:
            s, seen = st, True
        out.append((uid, s))
    if not seen:
        out.append((me, st))
    return out


def leaderboard(st, row_fn, score_key="score", player_key="playerRank",
                ranking_key="ranking"):
    """One row per account, sorted by score desc with real ranks, plus the current
    player's own row. `row_fn(state)` builds the score-bearing row for any player."""
    me = current_uid()
    rows = [(uid, row_fn(s)) for uid, s in all_states(st)]
    rows.sort(key=lambda ur: ur[1].get(score_key, 0), reverse=True)
    ranking, mine = [], None
    for i, (uid, r) in enumerate(rows, 1):
        r["rank"] = i
        ranking.append(r)
        if uid == me:
            mine = dict(r)
    return {ranking_key: ranking, player_key: mine or (ranking[0] if ranking else row_fn(st))}


def opponents(st, n, build, fallback=True):
    """Up to n real other players as opponents. With `fallback`, a solo server
    offers yourself (what the mode's own practice match does); without it, an empty
    list (for slots the client bot-fills)."""
    me = current_uid()
    others = [s for uid, s, _ in playerdb.all_players() if s is not None and uid != me]
    picks = others[:n] or ([st] if fallback else [])
    return [build(s) for s in picks]


def player_by_id(target_id, st):
    """Resolve a player by their accountId (the client's `targetId`). Unknown or
    absent id -> the current player, since a solo server has only the one."""
    if target_id:
        for uid, s, _ in playerdb.all_players():
            if s is not None and int(s.get("accountId", 0) or 0) == int(target_id):
                return s
    return st


def rank_row(st, score=0, extra=None):
    d = _PC["defaults"]
    deco = _deco(st)
    row = {"rank": 1, "score": int(score),
           "accountId": st.get("accountId", d["accountId"]),
           "userName": st.get("name", d["name"]),
           "castleName": st.get("castleName", d["castleName"]),
           "kingPostfix": 0, "castlePostfix": 0,
           "flagId": deco["flag"]["flagId"], "nameTagId": deco["nameTag"],
           "profileIcon": d["profileIconId"], "tier": 0}
    row.update(extra or {})
    return row


def board(st, score_of, extra_of=None, player_key="playerRank"):
    """A board across every account. `score_of(state)` and `extra_of(state)` build
    the per-player score and cosmetics; leaderboard sorts and ranks them."""
    def row_fn(s):
        return rank_row(s, score_of(s), extra_of(s) if extra_of else None)
    return leaderboard(st, row_fn, player_key=player_key)


def deck_units(st):
    """The current preset's hero ids. The board draws these as portraits, so an empty
    list is a row of blank slots - fall back to the first non-empty preset rather than
    show nothing when the selected one has never been filled.

    Never return an empty list: RankingItem.Set loops a fixed 6-slot portrait array and
    calls SetSprite(image, null) per slot, and Image.set_sprite(null) throws - a player
    with no deck (test accounts, pre-invasion saves) makes the whole ranking panel crash.
    The fallback is the seed deck (all starters exist in every save)."""
    decks = st.get("decks") or []
    cur = st.get("currentDeckPreset", 0)
    order = ([decks[cur]] if cur < len(decks) else []) + list(decks)
    for deck in order:
        units = deck.get("deck", []) if isinstance(deck, dict) else deck
        got = [u for u in units if isinstance(u, int) and u]
        if got:
            return got
    return [10000, 10010, 10020, 10030, 10040, 10050]


# --- The ten boards -----------------------------------------------------------

def r_ranking(body, st):
    """The generic board. `score` is a long here and `deck` replaces the cosmetics."""
    d = _PC["defaults"]
    def row_fn(s):
        return {"score": int(s.get("bestClearedTheme", 0)) * 100
                                 + int(s.get("bestClearedStage", 0)),
                "accountId": s.get("accountId", d["accountId"]),
                "userName": s.get("name", d["name"]),
                "castleName": s.get("castleName", d["castleName"]),
                "kingPostfix": 0, "castlePostfix": 0,
                "deck": deck_units(s)}
    out = leaderboard(st, row_fn)
    out["rankingType"] = str(body.get("rankingType", ""))
    return out


def r_pvp_ranking(body, st):
    return board(st, lambda s: s.get("pvpScore", 0),
                 lambda s: {"tier": s.get("pvpTier", 0)})


def r_colosseum_ranking(body, st):
    return board(st, lambda s: s.get("colosseumScore", 0),
                 lambda s: {"tier": s.get("colosseumTier", 0)})


def r_roguelike_ranking(body, st):
    return board(st, lambda s: s.get("rogueLikeScore", 0),
                 lambda s: {"challenge": s.get("rogueLikeChallenge", 0),
                            "building": s.get("rogueLikeBuilding", 0)})


def r_challenge_ranking(body, st):
    def row_fn(s):
        row = rank_row(s, srv._challenge_state(s).get("bestDifficulty", 0))
        # ChallengeModeRankingData has no flag/nameTag/tier but carries a percentile.
        for k in ("flagId", "tier"):
            row.pop(k, None)
        row["rankPer"] = 100.0
        return row
    return leaderboard(st, row_fn)


def r_clan_point_ranking(body, st):
    """Clans are their own entity, and there is exactly one here: the player's.

    ClanRankingResponseModel declares `ranking` + `playerClanRank`. The static
    override this replaced sent `clanRankings` + a null `myClanRanking`, so the board
    read an empty list off a key nobody had filled and the panel showed nothing. Only
    the declared names go out - re-adding the old spellings just recreates the bug in
    the other direction, which is exactly what api_audit flags."""
    row = {"rank": 1, "clanPoint": st.get("clanPoint", 0), "clanTier": 0,
           "battleTier": 0, "clanId": st.get("clanId", 0),
           "clanName": st.get("clanName", ""), "markId": 0}
    return {"ranking": [row] if row["clanId"] else [], "playerClanRank": row}


def r_unit_statistics(body, st):
    """Usage rates across the playerbase. One player means no meaningful sample, and
    inventing one would put fake percentages under real hero names."""
    return {"topPotentialUsage": [], "topTreasureUsage": [], "topAccessoryUsage": []}


def register(app, server_module):
    global srv
    srv = server_module
    srv.RANKING_OVERRIDES = handlers()


def handlers():
    return {
        "/ranking/ranking": r_ranking,
        "/kgc-ranking": r_ranking,
        "/ranking/pvp-ranking": r_pvp_ranking,
        "/ranking/pvp-hall-of-fame": r_pvp_ranking,
        "/ranking/pvp-league-ranking": r_pvp_ranking,
        "/ranking/colosseum-ranking": r_colosseum_ranking,
        "/ranking/colosseum-hall-of-fame": r_colosseum_ranking,
        "/ranking/colosseum-league-ranking": r_colosseum_ranking,
        "/ranking/roguelike-ranking": r_roguelike_ranking,
        "/ranking/roguelike-building-ranking": r_roguelike_ranking,
        "/ranking/dimension-rift-ranking": r_roguelike_ranking,
        "/ranking/challenge-mode-ranking": r_challenge_ranking,
        "/ranking/clan-point-ranking": r_clan_point_ranking,
        # Was a static override sending clanRankings/myClanRanking - the names
        # ClanRankingResponseModel does NOT read. See r_clan_point_ranking.
        "/clan/ranking": r_clan_point_ranking,
        "/statistics/unit": r_unit_statistics,
    }


if __name__ == "__main__":
    import pathlib as _pl
    import sys
    import tempfile

    playerdb.DB_PATH = _pl.Path(tempfile.mkdtemp()) / "t.db"
    playerdb.init()
    import server                                        # noqa: E402
    register(server.app, sys.modules["server"])

    st = server.copy.deepcopy(server.DEFAULT_PLAYER)
    st["uid"] = "t"
    st["accountId"] = 1
    playerdb.save("t", st)
    playerdb.set_active("t")

    out = r_ranking({}, st)
    assert out["ranking"], "an empty board is a blank list"
    assert out["playerRank"], "no row for the player reads as unranked"
    assert out["ranking"][0]["rank"] == 1, out["ranking"][0]

    # A second account must appear on the board, and ranks must be 1..n.
    other = server.copy.deepcopy(st)
    other.update(uid="u2", accountId=2, pvpScore=9999)
    playerdb.save("u2", other)
    b = r_pvp_ranking({}, st)
    assert len(b["ranking"]) == 2, b["ranking"]
    assert [r["rank"] for r in b["ranking"]] == [1, 2], b["ranking"]
    assert b["ranking"][0]["accountId"] == 2, "the higher score must rank first"
    assert b["playerRank"]["accountId"] == 1, "playerRank must be the CURRENT player"

    assert player_by_id(2, st) is not st, "a known accountId must resolve to that save"
    assert player_by_id(0, st) is st, "an unknown id falls back to the current player"
    assert len(opponents(st, 5, lambda s: s["uid"])) == 1, "one other account, one opponent"

    # The clan board must answer under the names ClanRankingResponseModel declares.
    cb = r_clan_point_ranking({}, st)
    assert "ranking" in cb and "playerClanRank" in cb, cb
    assert cb["playerClanRank"] is not None, "a null playerClanRank reads as unranked"

    paths = handlers()
    assert len(paths) == 15, f"{len(paths)} routes registered"
    assert all(callable(h) for h in paths.values())
    print(f"roster self-check ok ({len(paths)} routes)")
