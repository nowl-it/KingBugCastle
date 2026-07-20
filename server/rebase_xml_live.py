#!/usr/bin/env python3
"""Rebuild server/xml_live from a pristine snapshot, then replay our mods.

For the *republish* case: the devs rewrote the SAME CDN patch folder in place
(seen 2026-07-20 on 2026_07_14), so there is no new folder to trigger
refresh_master_data.py's diff. This wipes xml_live from a fresh pristine clone and
re-applies every local edit via local_mods - the mods live in ONE place
(server/local_mods.py), shared with refresh_master_data.py. Hand-merging 143 files
is not repeatable; this is.

Usage:  python3 rebase_xml_live.py [pristine_dir]     (default ../xml_history/2026_07_14)
        python3 rebase_xml_live.py --check            self-test the mods, touch nothing

NOT re-applied on purpose: the old hand-written Cathy (10800/10810) translations.
The republish shipped official text for those keys, and ours named 10810
"Ophelia / Iron Lady" - the official data says 10810 is Alessia Nosferatu, Cathy's
own vampire form. Ours was wrong; pristine wins.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import local_mods

ROOT = pathlib.Path(__file__).resolve().parent
XML_LIVE = ROOT / "xml_live"
DEFAULT_PRISTINE = ROOT.parent / "xml_history" / "2026_07_14"


def _copy_lf(src, dst):
    """Copy CRLF-normalized to LF - the CDN ships CRLF, xml_live is LF (matches
    refresh_master_data.norm), so a file the mods don't touch still lands as LF."""
    dst.write_bytes(src.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n"))


def main():
    pristine = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PRISTINE
    assert pristine.is_dir(), f"pristine snapshot not found: {pristine}"
    files = sorted(p for p in pristine.iterdir() if p.is_file())
    assert len(files) > 100, f"{pristine} holds only {len(files)} files - wrong dir?"

    XML_LIVE.mkdir(exist_ok=True)
    for src in files:
        _copy_lf(src, XML_LIVE / src.name)

    n, warns = local_mods.apply(str(XML_LIVE))
    for w in warns:
        print("  \033[33mWARN\033[0m " + w)
    assert not warns, "mod anchors moved - fix local_mods.py before shipping (see WARN above)"

    # Strings comments break Localizer for the whole locale; fail here, not mid-rebuild.
    for name in ("Strings_VI.xml", "Strings_EN_US.xml"):
        assert "<!--" not in (XML_LIVE / name).read_text(encoding="utf-8"), \
            f"{name} contains an XML comment - it would break the locale"

    print(f"[*] re-based {len(files)} files from {pristine}; {n} mod edit(s) applied")
    print("[!] next: python3 server/rebuild_xml_bundle.py, restart uvicorn, "
          "clear the device UnityCache")


if __name__ == "__main__":
    if "--check" in sys.argv:
        local_mods._check()
    else:
        local_mods._check()
        main()
