#!/system/bin/sh
# Keep the *pristine* KGC client running: relaunch it whenever the process dies.
#
# Why this exists: the stock client is not stable on redroid (x86_64 host + ndk_translation).
# Independent of anything we patch, it dies with an unattributed SIGSEGV roughly every 1-3
# minutes (reproduces with the in-RAM patches disabled too - see docs/dev-notes.md §81).  The
# guest account lives on the official server, so a relaunch just logs back in; nothing is lost.
#
# usage: watchdog.sh [package] [activity]     (run it with setsid so it outlives adb)
#   stop:  pkill -f watchdog.sh
#   env:   KGC_WATCHDOG_GAP (seconds to wait after a relaunch, default 8)
PKG=${1:-com.awesomepiece.castle}
ACT=${2:-co.ab180.airbridge.unity.AirbridgeActivity}
LOG=/data/local/tmp/watchdog.log
GAP=${KGC_WATCHDOG_GAP:-8}

echo "$(date '+%F %T') watchdog start (pid $$)" >> "$LOG"
while true; do
  if ! pidof "$PKG" >/dev/null 2>&1; then
    echo "$(date '+%F %T') relaunch" >> "$LOG"
    am start -n "$PKG/$ACT" >/dev/null 2>&1
    sleep "$GAP"
  else
    sleep 5
  fi
done
