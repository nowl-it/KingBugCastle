"""Focused Phase-5 persistence proof: donation notes never auto-credit tickets."""
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
    playerdb.save("donate-user", {"uid": "donate-user", "name": "Donate King", "posts": []})
    playerdb.bind_login("google_donate", "donate-user")
    return temp


def check_note_credit_and_audit():
    temp = _fresh_db()
    try:
        submitted = playerdb.donation_submit(
            "google_donate", "Đã chuyển MoMo, mã giao dịch 1234", now=1_000)
        assert submitted["donationId"] > 0
        assert playerdb.ticket_status("google_donate", now=1_001)["balance"] == 0, \
            "a donation note must never grant tickets automatically"
        donation = playerdb.donations()[0]
        assert donation["note"].endswith("1234") and donation["creditedAt"] is None

        credited = playerdb.admin_credit_tickets(
            "google_donate", 3, "verified MoMo transfer", "operator", submitted["donationId"], now=1_010)
        assert credited["balance"] == 3
        settled = playerdb.donations()[0]
        assert settled["creditedBy"] == "operator" and settled["creditedTickets"] == 3
        history = playerdb.ticket_history("google_donate")
        assert history[0]["delta"] == 3 and history[0]["reason"] == "admin_topup"
        assert history[0]["eventId"] == f"donation:{submitted['donationId']}"
        try:
            playerdb.admin_credit_tickets(
                "google_donate", 3, "retry", "operator", submitted["donationId"], now=1_011)
            raise AssertionError("a donation was credited twice")
        except ValueError as error:
            assert "already credited" in str(error)
        print("ok donate: note stays unpaid until one audited admin credit")
    finally:
        temp.cleanup()


def check_manual_topup_and_validation():
    temp = _fresh_db()
    try:
        topped = playerdb.admin_credit_tickets("google_donate", 2, "event thank-you", "operator", now=2_000)
        assert topped["balance"] == 2
        assert playerdb.ticket_history("google_donate")[0]["eventId"] == "event thank-you"
        for note in ("", "x" * 1_001):
            try:
                playerdb.donation_submit("google_donate", note, now=2_001)
                raise AssertionError("invalid donation note accepted")
            except ValueError:
                pass
        print("ok donate: manual top-up is explicit and note validation is bounded")
    finally:
        temp.cleanup()


if __name__ == "__main__":
    check_note_credit_and_audit()
    check_manual_topup_and_validation()
    print("all donation checks passed")
