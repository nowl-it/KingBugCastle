#!/bin/sh
# Bring up the *pristine, Play-signed* King God Castle client on redroid (x86_64 + ndk_translation)
# and log it in to the OFFICIAL server as a guest.
#
# Nothing here touches the APK.  Five system-side pieces, see docs/dev-notes.md §81:
#   1. libndk_translation.so: LOAD#1 p_flags R->RW (XIGNCODE's SetUserInfo memset, §80)
#   2. bind the arm64 linker over /system/bin/linker64 *inside zygote64's mount ns*
#      (without this XIGNCODE's bytehook init fails -> packer System.exit(1))
#   3. ad/attribution domains -> 0.0.0.0 in /system/etc/hosts (removes ad-SDK traffic;
#      the ad stack is the loudest native code in the process and the prime suspect
#      for the 1-3 min SIGSEGVs - it is NOT proven to be the cause)
#   4. kgcdev patch: GameManager.CheckFirebase -> ret in the unpacked libil2cpp (RAM only),
#      because Firebase.Messaging cannot init without Play Services and the exception
#      escapes GameManager.Init(), killing the whole login chain
#   5. watchdog.sh: the client still dies on its own every 1-3 min (reproduces with no
#      patches at all), so it gets relaunched; the guest account lives server-side
#
# usage: scripts/stock-redroid/up.sh [package]
#   env: ADB=adb  NDK=~/Android/Sdk/ndk/27.2.12479018  DEV=/data/local/tmp
set -e
PKG=${1:-com.awesomepiece.castle}
ACT=${KGC_ACTIVITY:-co.ab180.airbridge.unity.AirbridgeActivity}
ADB=${ADB:-adb}
NDK=${NDK:-$HOME/Android/Sdk/ndk/27.2.12479018}
DEV=/data/local/tmp
HERE=$(cd "$(dirname "$0")" && pwd)
CC=$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/x86_64-linux-android31-clang

# CheckFirebase: dump.cs Offset 0x3145340 + 0x4000 (RVA), prologue of v174.0.00
CB_RVA=3149340
CB_EXPECT=fe0f1bf8fa6701a9f85f02a9f65703a9

say() { printf '\n== %s\n' "$*"; }

adb wait-for-device

say "1/5 translator byte patch (LOAD#1 R->RW)"
flag=$($ADB shell 'od -An -tx1 -j 124 -N1 /system/lib64/libndk_translation.so' | tr -d ' \r')
if [ "$flag" = "06" ]; then
  echo "   already patched"
else
  tmp=$(mktemp -d)
  $ADB pull /system/lib64/libndk_translation.so "$tmp/lib.so" >/dev/null
  printf '\006' | dd of="$tmp/lib.so" bs=1 seek=124 conv=notrunc 2>/dev/null
  $ADB shell 'mount -o rw,remount / 2>/dev/null || true'
  $ADB push "$tmp/lib.so" "$DEV/libndk_translation_rw.so" >/dev/null
  $ADB shell "cp $DEV/libndk_translation_rw.so /system/lib64/libndk_translation.so"
  rm -rf "$tmp"
  echo "   patched, restarting framework (zygote preloads the bridge)"
  $ADB shell stop || true
  sleep 2
  i=0; until $ADB shell start || [ $i -ge 10 ]; do i=$((i+1)); sleep 2; done
  $ADB wait-for-device
  sleep 10
fi

say "2/5 hosts: sink ad/attribution domains"
if $ADB shell 'grep -q kgc-adblock /system/etc/hosts' 2>/dev/null; then
  echo "   already applied"
else
  $ADB shell 'mount -o rw,remount / 2>/dev/null || true'
  $ADB push "$HERE/hosts-adblock" "$DEV/hosts-adblock" >/dev/null
  # keep the device's own localhost lines, append ours once
  $ADB shell "grep -v '^0.0.0.0' /system/etc/hosts > $DEV/hosts.new; cat $DEV/hosts-adblock >> $DEV/hosts.new; cp $DEV/hosts.new /system/etc/hosts"
  echo "   $(grep -c '^0.0.0.0' "$HERE/hosts-adblock") domains sunk"
fi

say "3/5 static helper"
if [ -x "$CC" ]; then
  $CC -O2 -static -o /tmp/kgcdev "$HERE/kgcdev.c"
else
  echo "   NDK not found, reusing $DEV/kgcdev"
  [ -f /tmp/kgcdev ] || $ADB pull "$DEV/kgcdev" /tmp/kgcdev >/dev/null
fi
$ADB push /tmp/kgcdev "$DEV/kgcdev" >/dev/null
$ADB shell "chmod 755 $DEV/kgcdev"

say "4/5 arm64 linker inside zygote's mount namespace"
Z=$($ADB shell pidof zygote64 | tr -d '\r')
[ -n "$Z" ] || { echo "   zygote64 not running"; exit 1; }
# idempotent enough: a second bind just stacks the same file
$ADB shell "$DEV/kgcdev nsbind $Z"

say "5/6 CheckFirebase patch daemon + launch"
$ADB shell "pkill -x kgcdev || true; pkill -x kgcpatch || true; rm -f $DEV/kgcdev.log"
$ADB shell "am force-stop $PKG"
if [ "${KGC_CLEAR_CACHE:-0}" = "1" ]; then
  echo "   clearing UnityCache (a force-stop mid-download corrupts it -> permanent 'Loading resources…')"
  $ADB shell "rm -rf /sdcard/Android/data/$PKG/files/UnityCache"
fi
$ADB shell "setsid nohup $DEV/kgcdev patch $PKG $CB_RVA $CB_EXPECT > $DEV/kgcdev.log 2>&1 </dev/null &"
$ADB logcat -c
$ADB shell "am start -n $PKG/$ACT" >/dev/null
$ADB shell "cat $DEV/kgcdev.log"
echo
echo "watching launch (40 s)…"
sleep 40
$ADB shell "cat $DEV/kgcdev.log"
echo
$ADB logcat -d | grep -E 'bytehook init' | tail -1
$ADB shell "pidof $PKG" | tr -d '\r' | sed 's/^/app pid: /'

say "6/6 watchdog (relaunch on crash; the stock client is not stable under ndk_translation)"
if [ "${KGC_WATCHDOG:-1}" = "0" ]; then
  echo "   disabled (KGC_WATCHDOG=0)"
else
  $ADB push "$HERE/watchdog.sh" "$DEV/watchdog.sh" >/dev/null
  $ADB shell "chmod 755 $DEV/watchdog.sh; pkill -f watchdog.sh; setsid nohup $DEV/watchdog.sh $PKG $ACT >/dev/null 2>&1 </dev/null &"
  sleep 2
  $ADB shell "pgrep -f watchdog.sh >/dev/null && echo '   running (log: $DEV/watchdog.log)' || echo '   FAILED to start'"
fi
cat <<'EOF'

Expected:
  - "bytehook init(...), return: 0, real-init: yes"   (piece 2 works)
  - "PATCH wr=4 (ok) after=c0035fd6..."               (piece 4 works)
  - app still alive a minute later.  First run: accept the terms, the game then
    auto-creates a GUEST account on the official server (PlayerPrefs key
    Guest_<id>, lobby shows a server-assigned name).
  - the client crashes on its own every 1-3 min (environment, not our patches);
    the watchdog relaunches it and kgcdev re-patches the new pid.

Reminders:
  - Throwaway guest account only. Piece 4 lives in RAM and does modify the running
    client; XIGNCODE has memory checks in principle. Never point this at a real account.
  - After any zygote/container restart, re-run this script (piece 2 is per-namespace).
  - Crash dumps (crash_dump) cannot exec in the patched namespace, so no tombstones!
  - Stop the watchdog: adb shell pkill -f watchdog.sh
  - Stuck on "Loading resources..." (never reaches 31/31)?  The patch cache is corrupt,
    almost always because the client was killed with am force-stop mid-download.  Fix:
      adb shell rm -rf /sdcard/Android/data/com.awesomepiece.castle/files/UnityCache
    then relaunch (or run this script with KGC_CLEAR_CACHE=1).
EOF
