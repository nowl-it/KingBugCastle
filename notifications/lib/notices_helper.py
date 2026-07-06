#!/usr/bin/env python3
"""Helper for check_notices.sh - JSON state operations."""
import json, sys

def check_exists():
    last_ids = json.loads(sys.stdin.read()) if not sys.stdin.isatty() else {}
    page_id = sys.argv[2] if len(sys.argv) > 2 else ""
    print("true" if last_ids.get(page_id, False) else "false")

def merge_ids():
    _, _, state_json, ids_file = sys.argv
    last = json.loads(state_json) if state_json != "{}" else {}
    with open(ids_file) as f:
        for line in f:
            last[line.strip()] = True
    print(json.dumps(last))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: notices_helper.py <check|merge> ...", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "check":
        check_exists()
    elif cmd == "merge":
        merge_ids()
