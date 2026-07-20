"""`tomorrow` must be derived, never served from stored player state.

Scene_Lobby.Update polls `if (now >= playerData.tomorrow_) FetchNextDay()` every
second; a stale stored value makes that true forever -> full login + lobby
re-fetch at 1 Hz (~17 req/s).
"""
import datetime, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import server


def parse(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.000Z")


def main():
    now = datetime.datetime.utcnow()
    tomorrow, next_week = parse(server.next_reset_iso(1)), parse(server.next_reset_iso(7))
    assert tomorrow > now, f"tomorrow already past: {tomorrow}"
    assert (tomorrow.hour, tomorrow.minute, tomorrow.second) == (0, 0, 0), "not a UTC-midnight boundary"
    assert next_week > tomorrow, "nextWeek must be after tomorrow"

    # A stale stored value must not leak into the /player response.
    st = {**server.load_state(), "tomorrow": "2000-01-01T00:00:00.000Z",
          "nextWeek": "2000-01-01T00:00:00.000Z"}
    r = server.r_player({}, st)
    assert parse(r["tomorrow"]) > now, f"stale tomorrow leaked: {r['tomorrow']}"
    assert parse(r["nextWeek"]) > now, f"stale nextWeek leaked: {r['nextWeek']}"
    print(f"ok: tomorrow={r['tomorrow']} nextWeek={r['nextWeek']}")


if __name__ == "__main__":
    main()
