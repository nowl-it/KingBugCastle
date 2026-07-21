"""Two PROCESSES hammering the same player must not lose or corrupt writes.

This is the failure the JSON-file store had: :8080 and :8443 are separate
processes, threading.Lock guards nothing between them, and write_text() is not
atomic - so one side's save clobbered the other's, or left a truncated file.
"""
import os, subprocess, sys, tempfile, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

WORKER = r'''
import sys, playerdb, pathlib
playerdb.DB_PATH = pathlib.Path(sys.argv[1])
tag, n = sys.argv[2], int(sys.argv[3])
for i in range(n):
    with playerdb.write_lock():      # what server.py's middleware holds per request
        st = playerdb.load("p") or {"uid": "p"}
        st[tag] = i                  # each worker owns its own key
        playerdb.save("p", st)
'''

def main():
    db = pathlib.Path(tempfile.mkdtemp()) / "c.db"
    import playerdb
    playerdb.DB_PATH = db
    playerdb.init()
    playerdb.save("p", {"uid": "p"})

    w = pathlib.Path(tempfile.mkdtemp()) / "w.py"
    w.write_text(WORKER)
    N = 60
    env = {**os.environ, "PYTHONPATH": str(pathlib.Path(__file__).resolve().parent.parent)}
    procs = [subprocess.Popen([sys.executable, str(w), str(db), tag, str(N)], env=env)
             for tag in ("a", "b")]
    for p in procs:
        assert p.wait() == 0, "worker crashed (sqlite lock contention?)"

    st = playerdb.load("p")
    assert st is not None, "state vanished under concurrent writes"
    assert st["uid"] == "p", f"state corrupted: {st}"
    # Both processes' last write survived -> no truncation, no lost row.
    assert st.get("a") == N - 1, f"process A's writes lost: a={st.get('a')}"
    assert st.get("b") == N - 1, f"process B's writes lost: b={st.get('b')}"
    print(f"ok: 2 processes x {N} writes each, both survived, state intact")

if __name__ == "__main__":
    main()
