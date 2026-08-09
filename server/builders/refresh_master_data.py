#!/usr/bin/env python3
"""
One-command master-data refresh for a new game patch.

    python3 server/refresh_master_data.py            # fetch latest, refresh, rebuild
    python3 server/refresh_master_data.py --dry-run  # show changeset, touch nothing
    python3 server/refresh_master_data.py --no-bump  # skip patchFolder bump

Pipeline (replaces the manual steps documented in docs/cdn-master-data.md):
  1. kgc-cli config fetch + extract  -> the latest CDN xml bundle
  2. LF-normalize each file (CDN ships CRLF, xml_live is LF) into server/xml_live
  3. server/local_mods.apply()       -> replay our edits idempotently, warn on conflict
  4. rebuild_xml_bundle.py            -> real_cdn/xml + AssetHash
  5. bump patchFolder in response_config.json to the pulled patch date

What still needs a human: only the WARN lines from step 3 (a dev key that now
collides with ours, or an anchor the dev restructured). Everything else is
mechanical. Version gates + serverVersion are deliberately NOT bumped here - they
track the deployed client APK, not the newest game version (see docs).

After a successful run: restart uvicorn + clear the device UnityCache before launch.
"""
import sys, re, json, subprocess, pathlib, glob, tempfile

ROOT = pathlib.Path(__file__).resolve().parent           # server/
REPO = ROOT.parent
XML_LIVE = ROOT / "xml_live"
KGC_CLI = REPO / "kgc-cli"
CONFIG = ROOT / "data" / "response_config.json"

DRY = "--dry-run" in sys.argv
NO_BUMP = "--no-bump" in sys.argv


def sh(cmd, **kw):
    print("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kw)


def norm(p):  # CRLF -> LF, and delete any lone CR (matches `tr -d '\r'`, how xml_live
    # was first written). A few locale strings carry an in-content lone \r; converting
    # it to \n instead would inject phantom lines and make every diff think DE changed.
    return pathlib.Path(p).read_bytes().replace(b"\r", b"")


def main():
    assert KGC_CLI.exists(), f"kgc-cli not found at {KGC_CLI}"
    assert XML_LIVE.is_dir(), f"xml_live not found at {XML_LIVE}"
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="kgc_refresh_"))
    print(f"[1/5] fetch + extract -> {tmp}")
    sh([str(KGC_CLI), "config", "fetch", "-o", str(tmp)])
    bundle = next(iter(glob.glob(str(tmp / "xml_bundle_*"))), None)
    assert bundle, "kgc-cli config fetch produced no bundle"
    out = tmp / "xml"
    sh([str(KGC_CLI), "config", "extract", "-o", str(out), bundle])

    # detect the pulled patch date from kgc-cli's selection log is noisy; derive from
    # the CDN listing instead (same source check_cdn_update.sh uses).
    patch_date = _latest_patch_date()

    print("[2/5] diff vs xml_live (CR-normalized)")
    changed = []
    for f in sorted(out.glob("*.xml")):
        live = XML_LIVE / f.name
        if not live.exists() or norm(f) != norm(live):
            changed.append(f.name)
    print(f"  {len(changed)} file(s) differ: " + ", ".join(changed[:12]) + (" ..." if len(changed) > 12 else ""))

    if DRY:
        print("[dry-run] stopping - nothing written. Pulled patch:", patch_date)
        return

    print(f"[3/5] LF-normalize {len(changed)} changed file(s) into xml_live")
    for name in changed:
        (XML_LIVE / name).write_bytes(norm(out / name))

    print("[3/5] replay local mods (idempotent)")
    sys.path.insert(0, str(ROOT))
    import local_mods
    n, warns = local_mods.apply(str(XML_LIVE))
    print(f"  applied {n} mod op(s)")
    for w in warns:
        print("  \033[33mWARN\033[0m " + w)
    if warns:
        print("  ^ review the WARN lines above before shipping (dev collision / moved anchor).")

    print("[4/5] rebuild xml bundle")
    sh([sys.executable, str(ROOT / "rebuild_xml_bundle.py")])

    if NO_BUMP or not patch_date:
        print("[5/5] patchFolder bump skipped")
    else:
        # Surgical string replace, not a json.load/dumps round-trip: the file is
        # hand-indented and full of long _comment keys, and re-serializing it turns a
        # one-word bump into a 500-line reformat diff.
        raw = CONFIG.read_text()
        old = json.loads(raw)["server"]["patchFolder"]
        if old != patch_date:
            new = re.sub(r'("patchFolder"\s*:\s*")[^"]+(")', r"\g<1>%s\g<2>" % patch_date, raw, count=1)
            assert json.loads(new)["server"]["patchFolder"] == patch_date, "patchFolder bump did not take"
            CONFIG.write_text(new)
            print(f"[5/5] patchFolder {old} -> {patch_date}")
        else:
            print(f"[5/5] patchFolder already {patch_date}")

    print("\nDone. serverVersion + content gates left as-is (track the client APK, not the game).")
    print("Next: restart uvicorn, clear device UnityCache, then launch.")


def _latest_patch_date():
    import urllib.request, xml.etree.ElementTree as ET
    url = "https://kgc-cdn-1.awesomepiece.com/?prefix=patch/LIVE/&delimiter=/"
    try:
        raw = urllib.request.urlopen(url, timeout=30).read()
    except Exception as e:
        print("  [warn] could not list CDN for patch date:", e)
        return None
    ns = {"s3": "http://doc.s3.amazonaws.com/2006-03-01"}
    dates = []
    for p in ET.fromstring(raw).findall(".//s3:CommonPrefixes/s3:Prefix", ns):
        parts = p.text.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["patch", "LIVE"]:
            dates.append(parts[2])
    return sorted(dates)[-1] if dates else None


if __name__ == "__main__":
    main()
