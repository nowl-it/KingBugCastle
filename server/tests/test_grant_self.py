"""Focused Phase-3 checks at the ticket/save persistence boundary.

FastAPI TestClient hangs in this host, so these exercise the ownership point of
the feature directly: one transaction must debit the wallet and append game mail.
"""
import pathlib
import sys
import tempfile
import threading

_SERVER = pathlib.Path(__file__).resolve().parent.parent
if str(_SERVER) not in sys.path:
    sys.path.insert(0, str(_SERVER))

import playerdb


def _fresh_db():
    temp = tempfile.TemporaryDirectory()
    playerdb.DB_PATH = pathlib.Path(temp.name) / "players.db"
    playerdb.init()
    playerdb.save("grant-user", {"uid": "grant-user", "name": "Grant King", "posts": []})
    playerdb.bind_login("Guest_GRANT", "grant-user")
    return temp


def _set_balance(login_id, count, now=1_000):
    playerdb.ticket_status(login_id, now=now)
    with playerdb._conn() as c:
        c.execute("UPDATE ticket_wallets SET balance=? WHERE login_id=?", (count, login_id))


def check_grant_debits_once_and_creates_mail():
    temp = _fresh_db()
    try:
        _set_balance("Guest_GRANT", 1)
        result = playerdb.ticket_redeem_grant("Guest_GRANT", "Gold", 0, 50_000, "Gold", now=1_010)
        assert result["balance"] == 0 and result["postId"] == 1
        post = playerdb.load("grant-user")["posts"][-1]
        assert post["rewardType"] == "Gold" and post["rewardAmount"] == 50_000
        assert not post["title"].startswith("@raw:"), "inbox adds the prefix only on the wire"
        history = playerdb.ticket_history("Guest_GRANT")
        assert len(history) == 1 and history[0]["delta"] == -1 and history[0]["reason"] == "grant"
        try:
            playerdb.ticket_redeem_grant("Guest_GRANT", "Gold", 0, 50_000, "Gold", now=1_020)
            raise AssertionError("empty wallet allowed another grant")
        except playerdb.TicketUnavailable as e:
            assert e.code == "insufficient_tickets"
        assert len(playerdb.load("grant-user")["posts"]) == 1
        print("ok grants: one ticket creates exactly one paid mailbox reward")
    finally:
        temp.cleanup()


def check_concurrent_grants_cannot_overspend_or_duplicate_mail():
    temp = _fresh_db()
    try:
        _set_balance("Guest_GRANT", 1)
        start = threading.Barrier(3)
        outcomes = []

        def redeem():
            start.wait()
            try:
                playerdb.ticket_redeem_grant("Guest_GRANT", "Gold", 0, 50_000, "Gold")
                outcomes.append("granted")
            except playerdb.TicketUnavailable:
                outcomes.append("empty")

        threads = [threading.Thread(target=redeem), threading.Thread(target=redeem)]
        for thread in threads:
            thread.start()
        start.wait()
        for thread in threads:
            thread.join()
        assert sorted(outcomes) == ["empty", "granted"], outcomes
        assert playerdb.ticket_status("Guest_GRANT")["balance"] == 0
        assert len(playerdb.load("grant-user")["posts"]) == 1
        print("ok grants: concurrent requests cannot overspend a ticket or duplicate mail")
    finally:
        temp.cleanup()


def check_missing_game_save_keeps_ticket():
    temp = _fresh_db()
    try:
        playerdb.bind_login("Guest_MISSING", "no-longer-here")
        _set_balance("Guest_MISSING", 1)
        try:
            playerdb.ticket_redeem_grant("Guest_MISSING", "Gold", 0, 50_000, "Gold")
            raise AssertionError("missing game save received a grant")
        except ValueError as e:
            assert "enter the game" in str(e)
        assert playerdb.ticket_status("Guest_MISSING")["balance"] == 1
        assert playerdb.ticket_history("Guest_MISSING") == []
        print("ok grants: missing save refuses before a ticket is consumed")
    finally:
        temp.cleanup()


if __name__ == "__main__":
    check_grant_debits_once_and_creates_mail()
    check_concurrent_grants_cannot_overspend_or_duplicate_mail()
    check_missing_game_save_keeps_ticket()
    print("all self-grant checks passed")
