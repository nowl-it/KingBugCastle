#!/usr/bin/env python3
"""
Resolve the current bundled client version for tooling that must talk to the
official servers with a fresh ``version`` header (leaderboard poller, CI jobs).

Single source of truth: the ``VERSION`` default in ``api/config.py``. The
ranking API rejects stale client versions *before* evaluating the token
(``403 NotLatestVersion``), so any script that hits it must use the version of
the client this repo actually bundles - never a hardcoded one.

Usage:
    python api/version.py              # -> the bundled version (e.g. 173.1.00)
    python api/version.py 173.1.00     # -> explicit override (CI input wins)

Importable:
    from version import get_bundled_version
"""
import re
import sys
from pathlib import Path

_CONFIG = Path(__file__).resolve().parent / "config.py"

# config.py reads VERSION = os.environ.get("KGC_VERSION", "<default>"). We parse
# the file instead of importing config so the result is never shadowed by a
# KGC_VERSION env var set in the same process.
_PATTERN = re.compile(r'^VERSION\s*=\s*os\.environ\.get\("KGC_VERSION",\s*"([^"]+)"\)', re.MULTILINE)


def get_bundled_version() -> str:
    """Return the client version this repo currently bundles."""
    if not _CONFIG.exists():
        raise RuntimeError(f"cannot find {_CONFIG}")
    m = _PATTERN.search(_CONFIG.read_text(encoding="utf-8"))
    if not m:
        raise RuntimeError(
            f"cannot parse VERSION default from {_CONFIG} "
            '(expected `VERSION = os.environ.get("KGC_VERSION", "x.y.z")`)'
        )
    return m.group(1)


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1]:
        # Explicit override (e.g. a workflow_dispatch input) always wins.
        print(argv[1])
    else:
        print(get_bundled_version())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))