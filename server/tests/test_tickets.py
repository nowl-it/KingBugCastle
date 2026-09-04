"""Focused Phase-2 wallet checks without FastAPI TestClient.

The host's TestClient transport hangs independently of portal code, so these
exercise the persistence boundary directly: that is where duplicate postbacks,
caps, and cross-listener correctness actually live.
"""
import pathlib
import sys
import tempfile

_SERVER = pathlib.Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

import playerdb


def _fresh_db():
    temp = tempfile.TemporaryDirectory()
    playerdb.DB_PATH = pathlib.Path(temp.name) / "players.db"
    playerdb.init()
    playerdb.save("ticket-user", {"uid": "ticket-user", "name": "Ticket King"})
    playerdb.bind_login("Guest_TICKET", "ticket-user")
    return temp


def check_provider_reward_is_idempotent_and_cooldown_limited():
    temp = _fresh_db()
    try:
        session = playerdb.ticket_start_provider_session("Guest_TICKET", now=1_000)
        earned = playerdb.ticket_credit_from_provider("gam", "txn-1", session,
                                                      ip="198.51.100.8", now=1_010)
        assert earned["credited"] and earned["balance"] == 1
        replay = playerdb.ticket_credit_from_provider("gam", "txn-1", session,
                                                      ip="198.51.100.8", now=1_020)
        assert replay["duplicate"] and replay["balance"] == 1
        rejected = playerdb.ticket_credit_from_provider("gam", "txn-2", session,
                                                        ip="198.51.100.8", now=1_030)
        assert rejected["status"] == "cooldown" and rejected["balance"] == 1
        assert len(playerdb.ticket_history("Guest_TICKET")) == 1
        print("ok tickets: postback replay cannot mint an extra ticket; cooldown is durable")
    finally:
        temp.cleanup()


def check_caps_block_new_video_sessions():
    temp = _fresh_db()
    try:
        playerdb.ticket_status("Guest_TICKET", now=2_000)
        with playerdb._conn() as c:
            c.execute("UPDATE ticket_wallets SET balance=? WHERE login_id=?", (10, "Guest_TICKET"))
        try:
            playerdb.ticket_start_provider_session("Guest_TICKET", now=2_000)
            raise AssertionError("wallet cap did not block video")
        except playerdb.TicketUnavailable as e:
            assert e.code == "wallet_full"
        with playerdb._conn() as c:
            c.execute("UPDATE ticket_wallets SET balance=0,earned_day=?,earned_today=? WHERE login_id=?",
                      (playerdb._ticket_day(2_000), 20, "Guest_TICKET"))
        try:
            playerdb.ticket_start_provider_session("Guest_TICKET", now=2_000)
            raise AssertionError("daily cap did not block video")
        except playerdb.TicketUnavailable as e:
            assert e.code == "daily_limit"
        print("ok tickets: wallet and daily caps block new video sessions")
    finally:
        temp.cleanup()


if __name__ == "__main__":
    check_provider_reward_is_idempotent_and_cooldown_limited()
    check_caps_block_new_video_sessions()
    print("all ticket wallet checks passed")
