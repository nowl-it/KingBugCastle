"""Strip the packer's `System.exit(1)` from its Java stub (GenesisApp.java).

The XIGNCODE NEO stub's Application class does:

    static { try { System.loadLibrary("<packer>"); }
             catch (UnsatisfiedLinkError e) { System.exit(1); } }

Under redroid the packer's JNI_OnLoad fails (bytehook_init returns 3, INITERR_SYM -
it cannot resolve symbols through ndk_translation), ART turns that into an
UnsatisfiedLinkError, and the catch kills the process ~100ms after start: a
crash-restart loop with no tombstone and no linker error in logcat. Stock, unmodified
v171.1.00 does this too, so it is not caused by repacking.

**The class names rotate every build** - v171.0.01 shipped
`edu/ngrinesi/dichalanga` + `org/canesiss/ustintisic`, v171.1.00 ships
`edu/ongesste/ratererisi` + `io/yssicata/ngenengrat`. This used to hardcode the
v171.0.01 pair, so on any other build it printed "not found" and patched nothing -
and the loop came back looking like a brand-new bug. Find the file by what it
CONTAINS instead. Same lesson as locating the packer .so by its SONAME rather than
its (also rotating) filename.
"""
import re
import sys
from pathlib import Path

EXIT_CALL = "invoke-static {v0}, Ljava/lang/System;->exit(I)V"


def _stubs(dec_path):
    """Every smali file that force-exits the process from a loadLibrary catch."""
    out = []
    for f in dec_path.rglob("*.smali"):
        txt = f.read_text(encoding="utf-8", errors="replace")
        if "System;->exit" in txt and "loadLibrary" in txt:
            out.append(f)
    return sorted(out)


def patch(dec_dir):
    dec_path = Path(dec_dir)
    files = _stubs(dec_path)
    if not files:
        print("[patch_genesis] No packer stub found (System.exit already patched or absent), skipping.")
        return
    n = 0
    for f in files:
        txt = f.read_text(encoding="utf-8")
        # `return-void` in place of the call: the catch block already ends in a goto
        # that returns, so the method stays verifiable.
        new = txt.replace(EXIT_CALL, "return-void")
        if new == txt:
            hit = re.search(r".*System;->exit.*", txt)
            raise SystemExit(f"[-] {f.name}: exit call not in the expected form: "
                             f"{hit.group(0).strip() if hit else '?'}")
        f.write_text(new, encoding="utf-8")
        print(f"[+] Stripped System.exit in {f.relative_to(dec_path)}")
        n += 1
    return n


if __name__ == "__main__":
    print(f"[+] patched {patch(sys.argv[1])} packer stub(s)")
