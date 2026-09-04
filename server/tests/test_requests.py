"""Focused Phase-4 tests at the wallet/request/mail transaction boundary."""
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
    playerdb.save("request-user", {"uid": "request-user", "name": "Request King", "posts": []})
    playerdb.bind_login("Guest_REQUEST", "request-user")
    return temp


def _set_balance(count):
    playerdb.ticket_status("Guest_REQUEST", now=1_000)
    with playerdb._conn() as c:
        c.execute("UPDATE ticket_wallets SET balance=? WHERE login_id=?", (count, "Guest_REQUEST"))


def check_submit_approve_and_deny_are_atomic():
    temp = _fresh_db()
    try:
        _set_balance(2)
        submitted = playerdb.ticket_submit_grant_request(
            "Guest_REQUEST", "Xin 20 sách kinh nghiệm", "Item", 100, now=1_010)
        assert submitted["balance"] == 1
        pending = playerdb.grant_requests("pending")
        assert len(pending) == 1 and pending[0]["text"] == "Xin 20 sách kinh nghiệm"

        approved = playerdb.resolve_grant_request(
            submitted["requestId"], "approve", "operator", "Item", 100, 20, "Sách kinh nghiệm", now=1_020)
        assert approved["status"] == "approved" and not approved["refunded"]
        post = playerdb.load("request-user")["posts"][-1]
        assert post["rewardType"] == "Item" and post["rewardId"] == 100 and post["rewardAmount"] == 20
        try:
            playerdb.resolve_grant_request(submitted["requestId"], "deny", "operator", now=1_021)
            raise AssertionError("resolved request was resolved a second time")
        except ValueError as e:
            assert "already resolved" in str(e)

        second = playerdb.ticket_submit_grant_request("Guest_REQUEST", "Không cần nữa", now=1_030)
        assert second["balance"] == 0
        denied = playerdb.resolve_grant_request(second["requestId"], "deny", "operator", deny_reason="Không có trong catalog", now=1_040)
        assert denied["status"] == "denied" and denied["refunded"] and denied["balance"] == 1
        posts = playerdb.load("request-user")["posts"]
        assert "hoàn lại" in posts[-1]["text"]
        history = playerdb.ticket_history("Guest_REQUEST")
        assert [entry["reason"] for entry in history[:3]] == ["refund", "request", "request"]
        print("ok requests: submit spends once; approval mails reward; denial refunds once")
    finally:
        temp.cleanup()


def check_empty_and_concurrent_submit_do_not_lose_tickets():
    temp = _fresh_db()
    try:
        _set_balance(1)
        for bad in ("", "x" * 501):
            try:
                playerdb.ticket_submit_grant_request("Guest_REQUEST", bad, now=2_000)
                raise AssertionError("invalid text was accepted")
            except ValueError:
                pass
        gate = threading.Barrier(3)
        results = []

        def submit():
            gate.wait()
            try:
                playerdb.ticket_submit_grant_request("Guest_REQUEST", "Một yêu cầu", now=2_010)
                results.append("submitted")
            except playerdb.TicketUnavailable:
                results.append("empty")

        threads = [threading.Thread(target=submit), threading.Thread(target=submit)]
        for thread in threads:
            thread.start()
        gate.wait()
        for thread in threads:
            thread.join()
        assert sorted(results) == ["empty", "submitted"], results
        assert len(playerdb.grant_requests("pending")) == 1
        assert playerdb.ticket_status("Guest_REQUEST", now=2_020)["balance"] == 0
        print("ok requests: invalid text and concurrent submit cannot create an unpaid request")
    finally:
        temp.cleanup()


if __name__ == "__main__":
    check_submit_approve_and_deny_are_atomic()
    check_empty_and_concurrent_submit_do_not_lose_tickets()
    print("all request checks passed")
