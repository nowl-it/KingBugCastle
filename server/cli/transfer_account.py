"""Transfer player save data from one account UID to another on the KGC server.

Default:
    Source: p-f5c46011ecf1
    Target: p-757f50460ed8

Usage:
    python3 cli/transfer_account.py
    python3 cli/transfer_account.py --src p-f5c46011ecf1 --dst p-757f50460ed8
    python3 cli/transfer_account.py --dry-run
    python3 cli/transfer_account.py --force
"""
import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import playerdb


def transfer_account(src_uid: str, dst_uid: str, force: bool = False, dry_run: bool = False):
    playerdb.init()

    meta_key = f"transfer_{src_uid}_to_{dst_uid}"

    # 1. Idempotency check: has this transfer already completed?
    if not force and not dry_run:
        with playerdb._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key=?", (meta_key,)).fetchone()
            if row:
                print(f"[transfer] Transfer {src_uid} -> {dst_uid} was already completed at {row[0]}. Skipping.")
                return {"status": "already_done", "completed_at": row[0]}

    print(f"[transfer] Initiating transfer: {src_uid} -> {dst_uid} (dry_run={dry_run}, force={force})")

    # 2. Check and resolve source account
    src_st = playerdb.load(src_uid)
    if src_st is None:
        # Check if src_uid is a login_id instead
        resolved_src = playerdb.uid_for_login(src_uid)
        if resolved_src:
            print(f"[transfer] Source '{src_uid}' matched login_id -> resolving to uid '{resolved_src}'")
            src_uid = resolved_src
            src_st = playerdb.load(src_uid)

    if src_st is None:
        # Diagnostic: dump existing players and accounts
        with playerdb._conn() as c:
            players_sample = c.execute("SELECT uid, json_extract(data, '$.name') FROM players LIMIT 50").fetchall()
            accounts_sample = c.execute("SELECT login_id, uid FROM accounts LIMIT 50").fetchall()
        print(f"[transfer] ERROR: Source player '{src_uid}' not found in players table!")
        print(f"[transfer] Total players in DB: {playerdb.count()}")
        print(f"[transfer] Sample players in DB: {players_sample}")
        print(f"[transfer] Sample accounts in DB: {accounts_sample}")
        raise RuntimeError(f"Source player '{src_uid}' not found in database.")

    # 3. Check and resolve target account
    dst_st = playerdb.load(dst_uid)
    if dst_st is None:
        # Check if dst_uid is a login_id instead
        resolved_dst = playerdb.uid_for_login(dst_uid)
        if resolved_dst:
            print(f"[transfer] Target '{dst_uid}' matched login_id -> resolving to uid '{resolved_dst}'")
            dst_uid = resolved_dst
            dst_st = playerdb.load(dst_uid)

    target_account_id = None
    if dst_st is not None:
        target_account_id = dst_st.get("accountId")
        print(f"[transfer] Found existing target player '{dst_uid}' (name: {dst_st.get('name')}, "
              f"level: {dst_st.get('level')}, accountId: {target_account_id})")
    else:
        target_account_id = playerdb.next_account_id()
        print(f"[transfer] Target player '{dst_uid}' does not exist in players table yet. "
              f"Will be created with accountId: {target_account_id}")

    # Check linked logins
    with playerdb._conn() as c:
        src_logins = [r[0] for r in c.execute("SELECT login_id FROM accounts WHERE uid=?", (src_uid,)).fetchall()]
        dst_logins = [r[0] for r in c.execute("SELECT login_id FROM accounts WHERE uid=?", (dst_uid,)).fetchall()]
    print(f"[transfer] Source '{src_uid}' linked logins: {src_logins}")
    print(f"[transfer] Target '{dst_uid}' linked logins: {dst_logins}")

    # Summaries before transfer
    src_summary = {
        "uid": src_uid,
        "name": src_st.get("name"),
        "castleName": src_st.get("castleName"),
        "level": src_st.get("level"),
        "gold": src_st.get("gold"),
        "cash": src_st.get("cash"),
        "heroes_count": len(src_st.get("cards", {})),
        "rift_crystals_count": len(src_st.get("riftCrystals", [])),
        "cleared_stage": src_st.get("bestClearedStage"),
        "cleared_theme": src_st.get("bestClearedTheme"),
    }
    dst_before = {
        "uid": dst_uid,
        "name": dst_st.get("name") if dst_st else None,
        "level": dst_st.get("level") if dst_st else None,
        "gold": dst_st.get("gold") if dst_st else None,
        "cash": dst_st.get("cash") if dst_st else None,
        "heroes_count": len(dst_st.get("cards", {})) if dst_st else 0,
    }
    print(f"[transfer] Source stats: {json.dumps(src_summary, indent=2)}")
    print(f"[transfer] Target stats BEFORE: {json.dumps(dst_before, indent=2)}")

    if dry_run:
        print("[transfer] DRY-RUN enabled. Exiting without modifying database.")
        return {"status": "dry_run", "source": src_summary, "target_before": dst_before}

    # 4. Database backup
    backup_file = playerdb._backup("transfer")
    print(f"[transfer] Created database snapshot backup: {backup_file}")

    # 5. Build new target state
    new_st = copy.deepcopy(src_st)
    new_st["uid"] = dst_uid
    if target_account_id:
        new_st["accountId"] = target_account_id
    new_st["hasFreeRename"] = True

    # 6. Save target player state and invalidate old sessions
    playerdb.save(dst_uid, new_st)
    playerdb.end_sessions_for(dst_uid)

    # 7. Record completion in meta table
    now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with playerdb._conn() as c:
        c.execute("INSERT INTO meta (key, value) VALUES (?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (meta_key, now_str))

    # 8. Verification
    verify_st = playerdb.load(dst_uid)
    if verify_st is None:
        raise RuntimeError(f"Verification failed: target player '{dst_uid}' could not be loaded after save!")

    dst_after = {
        "uid": dst_uid,
        "name": verify_st.get("name"),
        "castleName": verify_st.get("castleName"),
        "level": verify_st.get("level"),
        "gold": verify_st.get("gold"),
        "cash": verify_st.get("cash"),
        "accountId": verify_st.get("accountId"),
        "heroes_count": len(verify_st.get("cards", {})),
        "rift_crystals_count": len(verify_st.get("riftCrystals", [])),
        "cleared_stage": verify_st.get("bestClearedStage"),
        "cleared_theme": verify_st.get("bestClearedTheme"),
        "hasFreeRename": verify_st.get("hasFreeRename"),
    }
    print(f"[transfer] Target stats AFTER: {json.dumps(dst_after, indent=2)}")

    # Derived table verification
    with playerdb._conn() as c:
        card_rows = c.execute("SELECT COUNT(*) FROM player_cards WHERE uid=?", (dst_uid,)).fetchone()[0]
        item_rows = c.execute("SELECT COUNT(*) FROM player_items WHERE uid=?", (dst_uid,)).fetchone()[0]
    print(f"[transfer] Derived tables for '{dst_uid}': player_cards={card_rows}, player_items={item_rows}")

    print(f"=== [✓] Successfully transferred data from '{src_uid}' to '{dst_uid}'! ===")
    return {
        "status": "success",
        "source": src_summary,
        "target_before": dst_before,
        "target_after": dst_after,
        "backup": str(backup_file) if backup_file else None,
        "completed_at": now_str,
    }


def main():
    parser = argparse.ArgumentParser(description="Transfer KGC player save data from one account to another.")
    parser.add_argument("--src", default="p-f5c46011ecf1", help="Source account UID (default: p-f5c46011ecf1)")
    parser.add_argument("--dst", default="p-757f50460ed8", help="Target account UID (default: p-757f50460ed8)")
    parser.add_argument("--force", action="store_true", help="Force transfer even if already marked completed in meta")
    parser.add_argument("--dry-run", action="store_true", help="Inspect without modifying the database")
    args = parser.parse_args()

    try:
        transfer_account(src_uid=args.src, dst_uid=args.dst, force=args.force, dry_run=args.dry_run)
    except Exception as e:
        print(f"[transfer] FAILED: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
