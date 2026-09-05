#!/usr/bin/env python3
import sys, subprocess, tempfile, shutil, pathlib, os, zipfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "server"))
from rebuild_arm64 import sign, ZIPALIGN

REPO = pathlib.Path(os.environ.get("KGC_ROOT") or pathlib.Path(__file__).resolve().parents[2])
# Which extracted XAPK to build from. Every patch in this file is either an offset into
# the INJECTED libil2cpp (so it does not care which APK carries it) or a NEO-loader
# offset - and the v171.1.00 packer is byte-identical to v171.0.01's (4 bytes differ in
# 3.3 MB of code, all 12 patch sites at the same offsets), so one script covers both.
# v172.0.00's packer (libbeniolle.so) is the same binary again: all 8 NEO_SIG_SITES
# byte-identical and the bail-out pattern hits the same 4 offsets, only the filename
# rotated. v172.0.01's packer (libpouricol.so) is byte-identical to v172.0.00's at all
# 8 NEO_SIG_SITES too, and its bail-out pattern hits the same relative spacing
# (+0/+0xa8/+0xc0/+0x148). The per-version il2cpp tables below pick the right
# offsets for each build.
#   python3 server/builders/build_private.py
#   KGC_APK_SRC=xapk_extracted_v1721 python3 server/builders/build_private.py
#   KGC_APK_SRC=xapk_extracted_v1720 python3 server/builders/build_private.py
#   KGC_APK_SRC=xapk_extracted_v1711 python3 server/builders/build_private.py
SRC = os.environ.get("KGC_APK_SRC", "xapk_extracted_v17201")
XAPK = REPO / "apk" / SRC
if not XAPK.is_dir():
    raise SystemExit(f"no such APK source: {XAPK}")
WORK = REPO / (".rebuild_" + SRC.replace("xapk_extracted_", ""))
# Which recovered libil2cpp to inject, selected by the APK source directory.
#
# NATIVE (default for v171.1.00 / v172.0.00 / v172.0.01 sources): the lib unpacked
# from THIS build's own packer by server/patchers/unpack_neo.py, so it pairs with the
# metadata the APK already ships and no metadata swap is needed.
#
# The v171.0.00 lib is the fallback for older sources. It needs the swap: v171.0.01
# inserted "/auth/xcdSeed?version=" at stringLiteral index 1545 of 25730, shifting the
# index of every literal above it, and libil2cpp has those indices baked into its code
# - so the v171.0.00 lib resolves 94% of its literals to the wrong entry against any
# newer metadata. Every other section of the two files is identical.
_NATIVE = REPO / "il2cpp" / "v172.1.00" / "libil2cpp_v1721_ssl.so"
if SRC == "xapk_extracted_v1721" and _NATIVE.exists() and not os.environ.get("KGC_FORCE_V17100"):
    VER = "172.1.00"
    IL2CPP_DEC = _NATIVE
    METADATA_DEC = None                 # the shipped metadata already matches
else:
    _NATIVE = REPO / "il2cpp" / "v172.0.01" / "libil2cpp_v17201_ssl.so"
    if SRC == "xapk_extracted_v17201" and _NATIVE.exists() and not os.environ.get("KGC_FORCE_V17100"):
        VER = "172.0.01"
        IL2CPP_DEC = _NATIVE
        METADATA_DEC = None                 # the shipped metadata already matches
    else:
        _NATIVE = REPO / "il2cpp" / "v172.0.00" / "libil2cpp_v172_ssl.so"
        if SRC == "xapk_extracted_v1720" and _NATIVE.exists() and not os.environ.get("KGC_FORCE_V17100"):
            VER = "172.0.00"
            IL2CPP_DEC = _NATIVE
            METADATA_DEC = None                 # the shipped metadata already matches
        else:
            _NATIVE = REPO / "il2cpp" / "v171.1.00" / "libil2cpp_v17110_ssl.so"
            if SRC == "xapk_extracted_v1711" and _NATIVE.exists() and not os.environ.get("KGC_FORCE_V17100"):
                VER = "171.1.00"
                IL2CPP_DEC = _NATIVE
                METADATA_DEC = None                 # the shipped metadata already matches
            else:
                VER = "171.0.00"
                IL2CPP_DEC = REPO / "il2cpp" / "v171.0.00" / "libil2cpp_v171_ssl.so"
                METADATA_DEC = REPO / "il2cpp" / "v171.0.00" / "global-metadata.dat"
# Every il2cpp offset below is per-lib, so this picks which table to use.
VER_IS_NATIVE = VER in ("171.1.00", "172.0.00", "172.0.01", "172.1.00")
# Host to rebind the 5 backend hostnames to (private server). Default 127.0.0.1
# reaches the local server via `adb reverse tcp:443 tcp:8443`. Override with
# SHARE_HOST=<ip-or-domain> for a remote/shared build.
SHARE_HOST = os.environ.get("SHARE_HOST", "127.0.0.1")
# Browser URL host for the Google-login bridge. Defaults to SHARE_HOST, but a
# public build should pass the real domain (kingbugcastle.id.vn) so the browser
# gets a valid Cloudflare cert - the game API can still point at the origin IP.
GLOGIN_HOST = os.environ.get("GLOGIN_HOST") or SHARE_HOST
# Poll host/port for the native poller. Local builds talk straight to the dev server
# on :8080; public builds use the origin IP on :80, where Caddy forwards to the
# loopback-only game service without Cloudflare's HTTPS redirect.
GLOGIN_POLL_HOST = os.environ.get("GLOGIN_POLL_HOST") or SHARE_HOST
GLOGIN_POLL_PORT = os.environ.get("GLOGIN_POLL_PORT", "8080")
if not GLOGIN_POLL_PORT.isdecimal() or not 0 < int(GLOGIN_POLL_PORT) < 65536:
    raise SystemExit("GLOGIN_POLL_PORT must be a TCP port between 1 and 65535")
# Scheme for the browser URL: "http" for local (no TLS cert needed), "https" for public.
GLOGIN_SCHEME = os.environ.get("GLOGIN_SCHEME", "https" if SHARE_HOST != "127.0.0.1" else "http")

# Private-server identity: rename so it installs side-by-side with the real app.
OLD_PKG = "com.awesomepiece.castle"
NEW_PKG = "com.nowl.castle"
NEW_LABEL = "King Bug Castle"
PATCHERS = REPO / "server" / "patchers"

ORIG_APKS = {
    "base": XAPK / "com.awesomepiece.castle.apk",
    "config": XAPK / "config.arm64_v8a.apk",
    "base_assets": XAPK / "base_assets.apk",
}

# GameManager.CheckFirebase() @ dump.cs Offset 0x303C6C0 (file offset = RVA-0x4000,
# confirmed via ELF .text VMA-fileoff = 0x4000). It kicks off FirebaseApp
# CheckAndFixDependenciesAsync; on redroid (no Google Play Services) Firebase Cloud
# Messaging can't init -> "modules failed to initialize: messaging (missing dependency)"
# -> cascades to a NullReferenceException in Scene_Login.OnResourceLoadCompleted that
# hangs the game on "Loading resources...". Stub the void method to `ret` (no-op) so the
# game skips Firebase entirely - it only drives push notifications, unused on a private
# server. Makes the build run on ANY emulator regardless of Play Services.
# file offset = RVA - 0x4000; per-version, re-derived from that version's dump.cs.
CHECKFIREBASE_OFF = {"171.0.00": 0x303C6C0,
                      "171.1.00": 0x3041594 - 0x4000,
                      "172.0.00": 0x304241C,
                      "172.0.01": 0x30439B8,
                      "172.1.00": 0x3081350 - 0x4000}[VER]
RET = bytes.fromhex('c0035fd6')  # arm64 `ret`

# OBSOLETE, opt-in only (KGC_ASSETBYPASS=1). The "infinite UniTask recursion" this was
# built to dodge was NOT a real client bug - it came from a corrupt libil2cpp_v171_ssl.so
# whose stray `b 0x3503ba8` had overwritten `mov w8,#-2` in
# Scene_Login.<CheckUseAssetBundle>d__79.MoveNext. With a clean _ssl.so (plain lib + only
# the 3 SSL RET_TRUE patches) the async runs fine. Keeping the bypass on is HARMFUL: it
# skips usePatch/getPatchFolder, so the CDN `xml` bundle (Strings + fonts) never downloads
# and the whole UI renders garbled.
CHECKUSEASSET_OFF = {"171.1.00": 0x34f9588 - 0x4000,
                      "172.0.00": 0x3501DD0 - 0x4000,
                      "172.0.01": 0x3503404 - 0x4000,
                      "172.1.00": 0x353CB6C - 0x4000}[VER]
# mov w1,#1 (0x52000021) ; b LoadAfterAssetBundle. Displacement per version:
# v171.1.00 target RVA 0x34f9618 = site +0x8C (0x14000023),
# v172.0.00 target RVA 0x3501E60 = site +0x90 (0x14000024),
# v172.0.01 target RVA 0x3503494 = site +0x90 (0x14000024),
# v172.1.00 target RVA 0x353CBFC = site +0x90 (0x14000024).
CHECKUSEASSET_PATCH = bytes.fromhex('2100005223000014' if VER == "171.1.00" else '2100005224000014')
    

# PvPPanel.<Init>d__77.MoveNext -> early return false. Same NRE stub v170 applies
# (rebuild_arm64.py "pvp-init"): the lobby PvP panel NREs on the semiSeason path even
# with a correct /pvp/info response, and the NRE blocks the whole lobby render.
# RVA 0x325658c (script.json ScriptMethod), file offset = RVA - 0x4000.
RET_FALSE = bytes.fromhex('e0031f2ac0035fd6')     # mov x0,#0 ; ret (also "return null")
RET_TRUE = bytes.fromhex('20008052c0035fd6')      # mov w0,#1 ; ret

# Lobby-NRE stubs, ported from the proven v170 set in rebuild_arm64.py (same purpose
# + same prologue bytes, only the offsets moved). Every RVA below was re-derived from
# ITS OWN version's dump.cs by exact class + signature match, and each is checked
# against the prologue at build time - a version bump moves all of them, and reusing
# the other set silently patches unrelated code.
#
# All 10 prologues are byte-identical across v171.0.00 and v171.1.00, which is the
# cross-check that the re-derivation landed on the same methods.
#
# v170's WorldPanel.IsKGMarbleAvailable has no v171 counterpart - dropped.
# (rva, label, expected prologue, replacement)
_NRE_STUBS_V17100 = [
    (0x325658c, "pvp-init",      'ff8303d1fd7b08a9', RET_FALSE),  # PvPPanel.<Init>d__77.MoveNext
    (0x3251208, "pvp-reward",    'fe0f1bf8fa6701a9', RET_FALSE),  # PvPPanel.GetReceivableWinRewardCount
    (0x32c1ea8, "shop-growth",   'fe0f1af8fc6f01a9', RET_FALSE),  # PackageItem.InitCustomGrowthPackage
    (0x32c3f78, "shop-season",   'ff4301d1fe6701a9', RET_FALSE),  # PackageItem.InitSeasonPassPackage
    (0x3055f58, "year-event",    'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsYearEventAvailable
    (0x3058038, "card-event",    'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsEventCardCollectingAvailable
    (0x3057f30, "season-event",  'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsSpecialSeasonalEventOpened
    (0x303d528, "babel-data",    'fe0f1df8f65701a9', RET_FALSE),  # GameManager.GetBabelData -> null
    (0x34a7b2c, "content-alert", 'fe0f1bf8fa6701a9', RET_FALSE),  # WorldPanel.ReloadNewContentAlert
    (0x3062df0, "accessory",     'fe0f1ff8088c40f9', RET_TRUE),   # GameManager.IsAccessoryUnlocked
]
_NRE_STUBS_V17110 = [
    (0x32574B8, "pvp-init",      'ff8303d1fd7b08a9', RET_FALSE),  # PvPPanel.<Init>d__77.MoveNext
    (0x3252134, "pvp-reward",    'fe0f1bf8fa6701a9', RET_FALSE),  # PvPPanel.GetReceivableWinRewardCount
    (0x32C2DD4, "shop-growth",   'fe0f1af8fc6f01a9', RET_FALSE),  # PackageItem.InitCustomGrowthPackage
    (0x32C4EA4, "shop-season",   'ff4301d1fe6701a9', RET_FALSE),  # PackageItem.InitSeasonPassPackage
    (0x3056E2C, "year-event",    'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsYearEventAvailable
    (0x3058F0C, "card-event",    'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsEventCardCollectingAvailable
    (0x3058E04, "season-event",  'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsSpecialSeasonalEventOpened
    (0x303E3FC, "babel-data",    'fe0f1df8f65701a9', RET_FALSE),  # GameManager.GetBabelData -> null
    (0x34A8B04, "content-alert", 'fe0f1bf8fa6701a9', RET_FALSE),  # WorldPanel.ReloadNewContentAlert
    (0x3063CC4, "accessory",     'fe0f1ff8088c40f9', RET_TRUE),   # GameManager.IsAccessoryUnlocked
]
_NRE_STUBS_V17200 = [
    (0x325E0CC, "pvp-init",      'ff8303d1fd7b08a9', RET_FALSE),  # PvPPanel.<Init>d__77.MoveNext
    (0x3258D48, "pvp-reward",    'fe0f1bf8fa6701a9', RET_FALSE),  # PvPPanel.GetReceivableWinRewardCount
    (0x32C9A04, "shop-growth",   'fe0f1af8fc6f01a9', RET_FALSE),  # PackageItem.InitCustomGrowthPackage
    (0x32CBAD4, "shop-season",   'ff4301d1fe6701a9', RET_FALSE),  # PackageItem.InitSeasonPassPackage
    (0x305BCB4, "year-event",    'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsYearEventAvailable
    (0x305DD94, "card-event",    'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsEventCardCollectingAvailable
    (0x305DC8C, "season-event",  'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsSpecialSeasonalEventOpened
    (0x3043284, "babel-data",    'fe0f1df8f65701a9', RET_FALSE),  # GameManager.GetBabelData -> null
    (0x34B0374, "content-alert", 'fe0f1bf8fa6701a9', RET_FALSE),  # WorldPanel.ReloadNewContentAlert
    (0x3068B4C, "accessory",     'fe0f1ff8088c40f9', RET_TRUE),   # GameManager.IsAccessoryUnlocked
]
_NRE_STUBS_V17201 = [
    (0x325F700, "pvp-init",      'ff8303d1fd7b08a9', RET_FALSE),  # PvPPanel.<Init>d__77.MoveNext
    (0x325A37C, "pvp-reward",    'fe0f1bf8fa6701a9', RET_FALSE),  # PvPPanel.GetReceivableWinRewardCount
    (0x32CB038, "shop-growth",   'fe0f1af8fc6f01a9', RET_FALSE),  # PackageItem.InitCustomGrowthPackage
    (0x32CD108, "shop-season",   'ff4301d1fe6701a9', RET_FALSE),  # PackageItem.InitSeasonPassPackage
    (0x305D2E8, "year-event",    'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsYearEventAvailable
    (0x305F3C8, "card-event",    'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsEventCardCollectingAvailable
    (0x305F2C0, "season-event",  'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsSpecialSeasonalEventOpened
    (0x3044820, "babel-data",    'fe0f1df8f65701a9', RET_FALSE),  # GameManager.GetBabelData -> null
    (0x34B19A8, "content-alert", 'fe0f1bf8fa6701a9', RET_FALSE),  # WorldPanel.ReloadNewContentAlert
    (0x306A180, "accessory",     'fe0f1ff8088c40f9', RET_TRUE),   # GameManager.IsAccessoryUnlocked
    (0x2CBF2C4, "ranking-endpt", 'fe0f1ef8f44f01a9', bytes.fromhex('48da01f0086545f9080140f9085d40f9000540f9c0035fd6')), # Web.GetRankingServerEndPoint -> Web._endPoint
]
_NRE_STUBS_V17210 = [
    (0x32984F4, "pvp-init",      'ff8303d1fd7b08a9', RET_FALSE),  # PvPPanel.<Init>d__77.MoveNext
    (0x32930C0, "pvp-reward",    'fe0f1bf8fa6701a9', RET_FALSE),  # PvPPanel.GetReceivableWinRewardCount
    (0x3304414, "shop-growth",   'fe0f1af8fc6f01a9', RET_FALSE),  # PackageItem.InitCustomGrowthPackage
    (0x33064E4, "shop-season",   'ff4301d1fe6701a9', RET_FALSE),  # PackageItem.InitSeasonPassPackage
    (0x3096C80, "year-event",    'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsYearEventAvailable
    (0x3098D60, "card-event",    'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsEventCardCollectingAvailable
    (0x3098C58, "season-event",  'fe0f1ef8f44f01a9', RET_FALSE),  # GameManager.IsSpecialSeasonalEventOpened
    (0x307E1B8, "babel-data",    'fe0f1df8f65701a9', RET_FALSE),  # GameManager.GetBabelData -> null
    (0x34EAD68, "content-alert", 'fe0f1bf8fa6701a9', RET_FALSE),  # WorldPanel.ReloadNewContentAlert
    (0x30A3C14, "accessory",     'fe0f1ff8088c40f9', RET_TRUE),   # GameManager.IsAccessoryUnlocked
    (0x2CF6C78, "ranking-endpt", 'fe0f1ef8f44f01a9', bytes.fromhex('68dc01f0085544f9080140f9085d40f9000540f9c0035fd6')), # Web.GetRankingServerEndPoint -> Web._endPoint
]
NRE_STUBS = {"171.0.00": _NRE_STUBS_V17100,
             "171.1.00": _NRE_STUBS_V17110,
             "172.0.00": _NRE_STUBS_V17200,
             "172.0.01": _NRE_STUBS_V17201,
             "172.1.00": _NRE_STUBS_V17210}[VER]

# Scene_Base.RegisterHackDetectionCallback @ RVA 0x34DB060 (file 0x34D7060).
# Stub it to ret (no-op) so the managed callback that shows "File integrity check
# failed" (XigncodeValidationFailed) is never registered. The chain is:
#   Scene_Base.Awake ~> tail-call RegisterHackDetectionCallback
#     ~> AppSignManager.SetDetectionCallback(Action<int,string>) 
#       ~> AppSign.System.SetDetectionCallback(HackDetectedCallback)
#         ~> AndroidJavaProxy: setHackDetectedListener on Java AppSignClientSystem
# The Java side of AppSignClientSystem detects that the real native libxigncode
# is replaced with our stub and fires onHackDetected -> C# callback -> popup.
# Patching this at the very start prevents the listener from ever being set up.
REGISTER_HACK_DETECT_OFF = {"171.0.00": 0x34D7060,
                             "171.1.00": 0x34DC038 - 0x4000,
                             "172.0.00": 0x34E38A8 - 0x4000,
                             "172.0.01": 0x34E4EDC - 0x4000,
                             "172.1.00": 0x351D9F0 - 0x4000}[VER]
REGISTER_HACK_DETECT_ORIG = 'fe57bea9'  # stp x30, x21, [sp, #-0x20]!
REGISTER_HACK_DETECT_NEW  = 'c0035fd6'  # ret

# NOP the canUseFirebase gate in FUN_03810e4c.  When CheckFirebase() is stubbed
# to ret (line 275), canUseFirebase stays false forever.  This cbz silently
# drops every ranking HTTP dispatch.  NOP it so the dispatch always fires.
# Ghidra VMA 0x3810ee8 → RVA 0x3710ee8 → file off = RVA − 0x4000 = 0x370cee8.
CANUSEFIREBASE_OFF = {"172.0.01": 0x370cee8,
                       "172.1.00": 0x37470A4}[VER]
CANUSEFIREBASE_ORIG = 'c8010034'  # cbz w8, +0x38
CANUSEFIREBASE_NEW  = '1f2003d5'  # nop

# Stub FirebaseAnalytics.LogEvent → ret.  v172.0.01 embeds LogEvent() inside
# Awesomepiece.Web.Get[T] - every single HTTP request triggers it.  On redroid
# (no Play Services) the FirebaseAnalyticsInternal static cctor throws
# TypeInitializationException, which kills the HTTP callback mid-flight.
# Symptom: game fetches usePatch, the response handler crashes, getPatchFolder
# never fires → stuck on "Loading resources…" forever.  Both overloads are
# static void, so `ret` is safe.
# Offsets: dump.cs Offset field (= file offset directly).
FIREBASE_LOGEVENT_STUBS = {"172.0.01": [
    # FirebaseAnalytics.LogEvent(string, Parameter[])
    (0x3776158, 'fe0f1df8f65701a9'),
    # FirebaseAnalytics.LogEvent(string, IEnumerable<Parameter>)
    (0x37761BC, 'fe67bca9f85f01a9'),
], "172.1.00": [
    # FirebaseAnalytics.LogEvent(string, Parameter[])
    (0x37B0314, 'fe0f1df8f65701a9'),
    # FirebaseAnalytics.LogEvent(string, IEnumerable<Parameter>)
    (0x37B0378, 'fe67bca9f85f01a9'),
]}.get(VER, [])

# Addressables passes AssetBundleRequestOptions.Crc into Unity's native bundle
# loader. Custom skin bundles no longer match the catalog's build-time CRC, but
# editing m_ExtraDataString shifts its separately indexed binary entries. Keep
# the catalog pristine and make the getter return 0 (Unity's documented
# "disable CRC validation" value) at runtime instead.
# dump.cs: RVA 0x5FC9F10, file offset 0x5FC5F10.
ASSETBUNDLE_CRC_GETTER = {"172.0.01": (
    0x5FC5F10,
    '001840b9c0035fd6',  # ldr w0,[x0,#0x18]; ret
    'e0031f2ac0035fd6',  # mov w0,wzr; ret
), "172.1.00": (
    0x607D358,
    '001840b9c0035fd6',  # ldr w0,[x0,#0x18]; ret
    'e0031f2ac0035fd6',  # mov w0,wzr; ret
)}.get(VER)
ASSETBUNDLE_CRC_READS = {"172.0.01": [
    # AssetBundleResource.LoadLocalBundle: crc argument w1.
    (0x5FC8484, '011940b9', 'e1031f2a'),
    # AssetBundleResource.CreateWebRequest: local-file and cached paths.
    (0x5FC639C, '011940b9', 'e1031f2a'),
    (0x5FC648C, '021940b9', 'e2031f2a'),
], "172.1.00": [
    # AssetBundleResource.LoadLocalBundle: crc argument w1.
    (0x607F8CC, '011940b9', 'e1031f2a'),
    # AssetBundleResource.CreateWebRequest: local-file and cached paths.
    (0x607D7E4, '011940b9', 'e1031f2a'),
    (0x607D8D4, '021940b9', 'e2031f2a'),
]}.get(VER, [])

# --- XIGNCODE NEO loader (the packer .so in the config split) ---------------
# Its on-disk filename rotates every build (v171.0.00 libaledatic.so, v171.0.01
# librolineng.so), so match the SONAME instead - that one is stable.
NEO_SONAME = b"libappsign4a.so"
NOP = bytes.fromhex('1f2003d5')
# Integrity-check bail-outs inside the loader: `bl <check>` ; `tbnz w0,#31,<fail>`
# (the last is `cbz x0,<fail>`). NOP the branch so a failed check falls through.
# These are v171.0.01 file offsets. They were NOT derivable by shifting the
# v171.0.00 ones: libaledatic maps file==VMA while librolineng maps VMA==file-0x4000,
# and the function grew, so the tail moved by a different delta than the head.
# Each is verified against its expected encoding below - a rebuilt packer raises
# instead of silently patching nothing (the old code skipped mismatches quietly,
# which is how half of these rotted unnoticed).
NEO_SIG_SITES = [
    (0x437b0, '80feff37'), (0x437b8, '40feff37'), (0x437c0, '00feff37'),
    (0x437f0, '80fcff37'), (0x43c28, 'c0daff37'), (0x43c6c, 'e035f837'),
    (0x43c88, 'e034f837'), (0x43c98, '803400b4'),
]
# Payload-parser error returns: `mov w8,#-1 ; str w8,[sp,#0x94] ; b <exit>`.
# NOP the `b` so the error is ignored. Located by pattern rather than offset -
# the 8-byte prefix occurs exactly 4x in both v171.0.00 and v171.0.01, at the
# same relative spacing (+0, +0xa8, +0xc0, +0x148), so this survives a rotation.
NEO_BAILOUT_PREFIX = bytes.fromhex('08008012e89700b9')


def patch_neo_loader(data):
    """NOP the NEO loader's integrity checks + payload-parser error returns."""
    buf = bytearray(data)
    n = 0
    for off, orig_hex in NEO_SIG_SITES:
        cur = bytes(buf[off:off + 4])
        if cur == NOP:
            continue
        if cur != bytes.fromhex(orig_hex):
            raise SystemExit(f"NEO sig check @ 0x{off:x}: expected {orig_hex}, found {cur.hex()} "
                             f"- packer was rebuilt, re-derive NEO_SIG_SITES")
        buf[off:off + 4] = NOP
        n += 1
    hits, p = [], 0
    while True:
        p = buf.find(NEO_BAILOUT_PREFIX, p)
        if p < 0:
            break
        hits.append(p + 8)
        p += 1
    if len(hits) != 4:
        raise SystemExit(f"NEO bail-out pattern matched {len(hits)} sites, expected 4")
    for off in hits:
        if bytes(buf[off:off + 4]) == NOP:
            continue
        if buf[off + 3] != 0x14:
            raise SystemExit(f"NEO bail-out @ 0x{off:x}: not a `b` ({bytes(buf[off:off+4]).hex()})")
        buf[off:off + 4] = NOP
        n += 1
    return bytes(buf), n


# Scene_Lobby.Init @ RVA 0x34E53B4: under ndk_translation ALL TypeInfo klass
# self-pointers fail to fix up (not just GameManager_TypeInfo). Every
# `ldr x0, [xR]` where xR holds a TypeInfo GOT entry reads the broken file
# offset instead of the klass pointer. Fix: replace each klass dereference
# `ldr x0, [xR]` → `mov x0, xR`. AUTO-DETECTED via disassembly scan below.

def patch_aledatic_and_inject_il2cpp(apk_path):
    print(f"[*] Patching librolineng.so and injecting libil2cpp.so into {apk_path.name}...")
    tmp = pathlib.Path(tempfile.mktemp(suffix=".apk"))
    count = 0
    il2_data = bytearray(IL2CPP_DEC.read_bytes())
    if il2_data[CHECKFIREBASE_OFF:CHECKFIREBASE_OFF+4] != RET:
        il2_data[CHECKFIREBASE_OFF:CHECKFIREBASE_OFF+4] = RET
        print(f"  [+] stubbed GameManager.CheckFirebase @ 0x{CHECKFIREBASE_OFF:x} (ret)")
    if os.environ.get("KGC_ASSETBYPASS"):
        il2_data[CHECKUSEASSET_OFF:CHECKUSEASSET_OFF+8] = CHECKUSEASSET_PATCH
        print(f"  [!] CheckUseAssetBundle bypass ENABLED @ 0x{CHECKUSEASSET_OFF:x} - breaks Strings/UI, debug only")
    for rva, label, orig_hex, new in NRE_STUBS:
        off = rva - 0x4000
        cur = bytes(il2_data[off:off+len(new)])
        if cur == new:
            continue
        if bytes(il2_data[off:off+len(orig_hex)//2]) != bytes.fromhex(orig_hex):
            raise SystemExit(f"{label}: unexpected bytes at 0x{off:x}: {bytes(il2_data[off:off+8]).hex()}")
        il2_data[off:off+len(new)] = new
        print(f"  [+] stubbed {label} @ 0x{off:x} -> {new.hex()}")
    # DIAGNOSTIC: KGC_LOBBY_DIAG=1 NOPs every explicit null-check in
    # Scene_Lobby.Init that branches to the throw block (0x34e63f8), so the
    # first null OBJECT falls through to its deref and SIGSEGVs with a locatable
    # first null OBJECT falls through to its deref and SIGSEGVs with a locatable
    # fault PC (a clean managed NRE is location-stripped). Skips the ldr/hack
    # patches for a clean baseline. Read the tombstone, then turn it off.
    LOBBY_DIAG = bool(os.environ.get("KGC_LOBBY_DIAG"))
    if LOBBY_DIAG:
        NOP = bytes.fromhex('1f2003d5')
        CBZ_THROW = [0x34e5604,0x34e56cc,0x34e5768,0x34e5770,0x34e57d0,0x34e57e8,
            0x34e5868,0x34e58b8,0x34e5908,0x34e5910,0x34e5960,0x34e5968,0x34e5970,
            0x34e59c4,0x34e59cc,0x34e59d4,0x34e5a18,0x34e5a64,0x34e5a88,0x34e5b30,
            0x34e5b38,0x34e5b98,0x34e5ba0,0x34e5c34,0x34e5c64,0x34e5c70,0x34e5c9c,
            0x34e5d10,0x34e5d3c,0x34e5dc0,0x34e5dc8,0x34e5e1c,0x34e5eb0,0x34e5f30,
            0x34e5f38,0x34e5f8c,0x34e6020,0x34e6088,0x34e60f4,0x34e60fc,0x34e6194,
            0x34e61f8,0x34e6298,0x34e629c,0x34e62d0,0x34e632c,0x34e6338,0x34e637c,
            0x34e6388,0x34e63e4]
        n = 0
        for rva in CBZ_THROW:
            off = rva - 0x4000
            if bytes(il2_data[off+3:off+4])[0] & 0x7e != 0x34:  # not cbz/cbnz
                print(f"  [!] DIAG cbz @ 0x{rva:x}: unexpected {bytes(il2_data[off:off+4]).hex()}, skip")
                continue
            il2_data[off:off+4] = NOP; n += 1
        print(f"  [DIAG] NOPed {n} null-checks in Scene_Lobby.Init (expect a tombstone SIGSEGV)")
    # Patch ALL klass dereferences in Scene_Lobby.Init.
    # Under ndk_translation every TypeInfo klass self-pointer is broken.
    # 65 total: 18 from original analysis (x23 only) + 47 from comprehensive scan.
    # Each replaces `ldr x0, [xR]` with `mov x0, xR`.
    import struct
    LDR_PATCHES = [
        # Original 18 (x23 only, continuation first pass):
        (0x34E55B8, 'e00317aa'), (0x34E55E8, 'e00317aa'), (0x34E55F8, 'e00317aa'),
        (0x34E5870, 'e00317aa'), (0x34E589C, 'e00317aa'), (0x34E58AC, 'e00317aa'),
        (0x34E58EC, 'e00317aa'), (0x34E58FC, 'e00317aa'), (0x34E5944, 'e00317aa'),
        (0x34E5954, 'e00317aa'), (0x34E59A8, 'e00317aa'), (0x34E59B8, 'e00317aa'),
        (0x34E5AE8, 'e00317aa'), (0x34E5B14, 'e00317aa'), (0x34E5B24, 'e00317aa'),
        (0x34E5B50, 'e00317aa'), (0x34E5B7C, 'e00317aa'), (0x34E5B8C, 'e00317aa'),
        # Comprehensive scan (x20, x21, x22, x23, x25):
        (0x34E563C, 'e00316aa'), (0x34E564C, 'e00316aa'), (0x34E5660, 'e00315aa'),
        (0x34E56B4, 'e00315aa'), (0x34E56E4, 'e00315aa'), (0x34E57A8, 'e00319aa'),
        (0x34E5AAC, 'e00319aa'), (0x34E5BC4, 'e00317aa'), (0x34E5BD4, 'e00317aa'),
        (0x34E5BF0, 'e00317aa'), (0x34E5C48, 'e00314aa'), (0x34E5C58, 'e00314aa'),
        (0x34E5C80, 'e00314aa'), (0x34E5C90, 'e00314aa'), (0x34E5CAC, 'e00317aa'),
        (0x34E5CD8, 'e00317aa'), (0x34E5CE8, 'e00317aa'), (0x34E5D4C, 'e00319aa'),
        (0x34E5D78, 'e00317aa'), (0x34E5DA4, 'e00317aa'), (0x34E5DB4, 'e00317aa'),
        (0x34E5E00, 'e00317aa'), (0x34E5E10, 'e00317aa'), (0x34E5E40, 'e00317aa'),
        (0x34E5E50, 'e00317aa'), (0x34E5E6C, 'e00317aa'), (0x34E5EBC, 'e00319aa'),
        (0x34E5EE8, 'e00317aa'), (0x34E5F14, 'e00317aa'), (0x34E5F24, 'e00317aa'),
        (0x34E5F70, 'e00317aa'), (0x34E5F80, 'e00317aa'), (0x34E5FB0, 'e00317aa'),
        (0x34E5FC0, 'e00317aa'), (0x34E5FDC, 'e00317aa'), (0x34E602C, 'e00317aa'),
        (0x34E6058, 'e00317aa'), (0x34E6068, 'e00317aa'), (0x34E60AC, 'e00317aa'),
        (0x34E60D8, 'e00317aa'), (0x34E60E8, 'e00317aa'), (0x34E6124, 'e00317aa'),
        (0x34E6134, 'e00317aa'), (0x34E6150, 'e00317aa'), (0x34E61B0, 'e00319aa'),
        (0x34E62F4, 'e00319aa'), (0x34E6344, 'e00319aa'),
    ]
    
    # (Removed stacktrace-bypass patch because we now hook it via stub.cpp)
    
    # LDR_PATCHES: fix broken TypeInfo klass self-pointer dereferences under
    # ndk_translation.  The native stub (HookedLobbyInit) ensures GameManager._singleton
    # is non-null by forcing .cctor, but that alone is INSUFFICIENT: every TypeInfo's
    # klass self-pointer fixup (`0x2001ba1f` -> self-pointer) never runs under
    # ndk_translation, so `ldr x0,[TypeInfo]` reads a bogus file-time value instead of
    # the klass pointer -> SIGSEGV reported as NRE at Scene_Lobby.Init [0x00000].
    # Both fixes are needed: cctor hook (singleton) + ldr->mov (klass dereferences).
    # Set KGC_SKIP_LDR=1 to disable these for A/B testing.
    patched_count = 0
    # OFF. These corrupt the klass dereference instead of fixing it, and they are
    # what blanks the lobby. In Scene_Lobby.Init:
    #     ldr x0, [x23]          x23 = GameManager's Il2CppClass** GOT slot
    #     ldr x8, [x0, #0xb8]    klass->static_fields
    #     ldr x0, [x8]           static field 0 = GameManager._singleton
    #     cbz x0, <throw NRE>
    #     bl  GameManager.Init
    # Rewriting the first load to `mov x0, x23` leaves x0 pointing at the GOT SLOT,
    # so static_fields is read from slot+0xb8 (garbage) and _singleton comes back
    # null - which is the NRE. Proven by tombstone with the null-checks NOPed:
    #   Scene_Lobby.Awake -> Scene_Lobby.Init+0x270 -> GameManager.Init+0x98,
    #   SIGSEGV on `ldrb w8,[x19,#0x1b0]` with x19==0, at the same moment the stub's
    #   own GameManager.Get() returned a valid singleton. The klass self-pointers are
    #   fine; nothing needed fixing here.
    # KGC_APPLY_LDR=1 re-enables them for an A/B.
    _apply_ldr = bool(os.environ.get("KGC_APPLY_LDR"))
    for rva, new_hex in (LDR_PATCHES if _apply_ldr else []):
        off = rva - 0x4000
        cur = bytes(il2_data[off:off+4])
        new = bytes.fromhex(new_hex)
        if cur == new:
            continue
        if cur[3] & 0xFC != 0xF8:  # not ldr (64-bit load)
            print(f"  [!] ldr_patch @ RVA 0x{rva:x}: unexpected orig {cur.hex()}, skipping")
            continue
        il2_data[off:off+4] = new
        patched_count += 1
        print(f"  [+] ldr->mov @ RVA 0x{rva:x} (file 0x{off:x}) {cur.hex()}->{new_hex}")
    if patched_count:
        print(f"  [+] patched {patched_count} klass dereferences in Scene_Lobby.Init")
    # RegisterHackDetectionCallback -> ret (stub out the AppSign hack callback)
    cur = bytes(il2_data[REGISTER_HACK_DETECT_OFF:REGISTER_HACK_DETECT_OFF+4])
    if cur != bytes.fromhex(REGISTER_HACK_DETECT_NEW):
        if cur != bytes.fromhex(REGISTER_HACK_DETECT_ORIG):
            raise SystemExit(f"RegisterHackDetectionCallback @ 0x{REGISTER_HACK_DETECT_OFF:x}: unexpected bytes {cur.hex()}")
        il2_data[REGISTER_HACK_DETECT_OFF:REGISTER_HACK_DETECT_OFF+4] = bytes.fromhex(REGISTER_HACK_DETECT_NEW)
        print(f"  [+] stubbed RegisterHackDetectionCallback @ 0x{REGISTER_HACK_DETECT_OFF:x} (ret)")
    # NOP canUseFirebase gate in FUN_03810e4c (ranking dispatch)
    cur = bytes(il2_data[CANUSEFIREBASE_OFF:CANUSEFIREBASE_OFF+4])
    if cur != bytes.fromhex(CANUSEFIREBASE_NEW):
        if cur != bytes.fromhex(CANUSEFIREBASE_ORIG):
            raise SystemExit(f"canUseFirebase gate @ 0x{CANUSEFIREBASE_OFF:x}: unexpected bytes {cur.hex()}")
        il2_data[CANUSEFIREBASE_OFF:CANUSEFIREBASE_OFF+4] = bytes.fromhex(CANUSEFIREBASE_NEW)
        print(f"  [+] NOPed canUseFirebase gate @ 0x{CANUSEFIREBASE_OFF:x} (ranking dispatch)")
    # Stub FirebaseAnalytics.LogEvent overloads → ret (prevents
    # TypeInitializationException from killing Web.Get HTTP callbacks)
    for off, orig_hex in FIREBASE_LOGEVENT_STUBS:
        cur = bytes(il2_data[off:off+4])
        if cur == RET:
            continue
        if cur != bytes.fromhex(orig_hex[:8]):
            raise SystemExit(f"FirebaseAnalytics.LogEvent @ 0x{off:x}: unexpected bytes {cur.hex()}")
        il2_data[off:off+4] = RET
        print(f"  [+] stubbed FirebaseAnalytics.LogEvent @ 0x{off:x} (ret)")

    if ASSETBUNDLE_CRC_GETTER:
        off, orig_hex, new_hex = ASSETBUNDLE_CRC_GETTER
        cur = bytes(il2_data[off:off+8])
        if cur != bytes.fromhex(new_hex):
            if cur != bytes.fromhex(orig_hex):
                raise SystemExit(f"AssetBundleRequestOptions.get_Crc @ 0x{off:x}: unexpected bytes {cur.hex()}")
            il2_data[off:off+8] = bytes.fromhex(new_hex)
            print(f"  [+] stubbed AssetBundleRequestOptions.get_Crc @ 0x{off:x} -> 0")
    for off, orig_hex, new_hex in ASSETBUNDLE_CRC_READS:
        cur = bytes(il2_data[off:off+4])
        if cur == bytes.fromhex(new_hex):
            continue
        if cur != bytes.fromhex(orig_hex):
            raise SystemExit(f"AssetBundle CRC read @ 0x{off:x}: unexpected bytes {cur.hex()}")
        il2_data[off:off+4] = bytes.fromhex(new_hex)
        print(f"  [+] zeroed AssetBundle CRC argument @ 0x{off:x}")

    # ShopItem.Init empty list crash bypass
    # ShopItem.Init(int id) reads the shop list without a count check and NREs on an
    # empty one. The fix reads Count off [x20,#0x18] and branches to the method's own
    # bail-out. Both the site and the branch displacement are per-version - the v17110
    # site was matched by instruction shape (adrp;ldr;mov x22,x0;mov x0,x20;mov w1,wzr;
    # ldr x2,[x8];bl;cbz x0), which is identical in both builds.
    # v172.0.00/01: the method was rewritten (Init(int id) -> GetInventoryItems() ->
    # List.get_Item). Upstream added a NULL check (cbz x20) before get_Item but still
    # no Count==0 check, so an empty-but-non-null list still throws
    # ArgumentOutOfRangeException - same crash, verified live on v172.0.01
    # (ShopPanel.ReloadMoney -> ShopItem.Init -> List.get_Item(0)).
    # NOTE: upstream's cbz bail target (0x32E0BEC) is a THROW helper, not the method
    # epilogue - jumping there raises NullReferenceException. Our patch redirects both
    # bails to the real epilogue 0x32E0BD0 (ldp x20,x19,[sp,#0x60];...ret).
    if VER == "172.1.00":
        SHOP_INIT_OFF = 0x3315BE8
        SHOP_INIT_ORIG = bytes.fromhex('941300b468ac01b008b140f9f60300aae00314aae1031f2a020140f938063494')
        SHOP_INIT_NEW = bytes.fromhex('b41200b4881a40b968120034f60300aae00314aae1031f2a1f2003d538063494')
    elif VER == "172.0.01":
        SHOP_INIT_OFF = 0x32E097C - 0x4000
        SHOP_INIT_ORIG = bytes.fromhex('941300b428aa01f0088d41f9f60300aae00314aae1031f2a020140f919a03394')
        SHOP_INIT_NEW = bytes.fromhex('b41200b4881a40b968120034f60300aae00314aae1031f2a1f2003d519a03394')
    elif VER == "172.0.00":
        SHOP_INIT_OFF = 0x32db348
        SHOP_INIT_ORIG = bytes.fromhex('941300b428aa01d0086545f9f60300aae00314aae1031f2a020140f92bb03394')
        SHOP_INIT_NEW = bytes.fromhex('b41200b4881a40b968120034f60300aae00314aae1031f2a1f2003d52bb03394')
    elif VER == "171.1.00":
        SHOP_INIT_OFF = 0x32D8718 - 0x4000
        SHOP_INIT_ORIG = bytes.fromhex('941300b408aa01f0087541f9f60300aae00314aae1031f2a020140f966983394')
        SHOP_INIT_NEW = bytes.fromhex('b41200b4881a40b968120034f60300aae00314aae1031f2a1f2003d566983394')
    else:
        SHOP_INIT_OFF = 0x32D77EC - 0x4000
        SHOP_INIT_ORIG = bytes.fromhex('941300b408aa01f0080540f9f60300aae00314aae1031f2a020140f961973394')
        SHOP_INIT_NEW = bytes.fromhex('b41200b4881a40b968120034f60300aae00314aae1031f2a1f2003d561973394')
    cur = bytes(il2_data[SHOP_INIT_OFF:SHOP_INIT_OFF+32])
    if cur == SHOP_INIT_ORIG:
        il2_data[SHOP_INIT_OFF:SHOP_INIT_OFF+32] = SHOP_INIT_NEW
        print(f"  [+] patched ShopItem.Init empty list / null list crash")
    elif cur == SHOP_INIT_NEW:
        pass
    else:
        raise SystemExit(f"ShopItem.Init @ 0x{SHOP_INIT_OFF:x}: unexpected bytes {cur.hex()}")

    il2_data = bytes(il2_data)
    with zipfile.ZipFile(apk_path, "r") as zin:
        with zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.infolist():
                if item.filename == "lib/arm64-v8a/libil2cpp.so":
                    continue
                data = zin.read(item.filename)
                
                new_item = zipfile.ZipInfo(item.filename, item.date_time)
                new_item.compress_type = item.compress_type
                
                if item.filename.endswith(".so") and NEO_SONAME in data[:0x10000]:
                    data, n = patch_neo_loader(data)
                    count += n
                    print(f"  [+] NEO loader = {item.filename.rsplit('/', 1)[-1]}")
                zout.writestr(new_item, data)
            
            # Inject il2cpp.so. This is NOT optional, though the packer carrying its
            # own copy of the payload makes it look like it might be: libunity.so
            # dlopen()s "libil2cpp.so" by name, and the packer only ever writes that
            # file out along the boot path whose integrity checks we NOP above. Tested
            # 2026-07-30 by building without it - the app dies in ~300 ms with
            # "JNI FatalError: Unable to load library: .../libil2cpp.so
            # [dlopen failed: library "libil2cpp.so" not found]" -> SIGABRT.
            il2_item = zipfile.ZipInfo("lib/arm64-v8a/libil2cpp.so")
            il2_item.compress_type = zipfile.ZIP_STORED
            zout.writestr(il2_item, il2_data)
            
    shutil.move(tmp, apk_path)
    print(f"  [+] NOPed {count}/12 checks in the NEO loader")

def replace_xigncode(apk_path):
    print(f"[*] Replacing libxigncode.so with stub in {apk_path.name}...")
    # Same canonical stub rebuild_arm64.py uses. There used to be a second copy at
    # jni/libxigncode.so that only this build read, and the two silently drifted a day
    # apart - one arm64 stub, one path. stub.cpp branches on v170/v171 at runtime.
    stub_data = (REPO / "server" / "xigncode_stub" / "arm64" / "libxigncode.so").read_bytes()
    tmp = pathlib.Path(tempfile.mktemp(suffix=".apk"))
    with zipfile.ZipFile(apk_path, "r") as zin:
        with zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.infolist():
                if item.filename == "lib/arm64-v8a/libxigncode.so":
                    orig_size = len(zin.read(item.filename))
                    stub_padded = bytearray(stub_data)
                    
                    # Patch the KGC_GLOGIN_HOST and KGC_GLOGIN_POLL_HOST buffers
                    # Both are 64-byte buffers in stub.cpp, starting with "127.0.0.1\0"
                    # and followed by null/space padding. First occurrence = browser host,
                    # second = poll host (may differ when Cloudflare is in front).
                    old_host_pattern = b"127.0.0.1\0"
                    
                    # Patch g_kgc_glogin_host (browser URL host)
                    new_browser = GLOGIN_HOST.encode() + b"\0"
                    if len(new_browser) > 64:
                        print(f"WARNING: GLOGIN_HOST {GLOGIN_HOST} is too long for glogin patch!")
                        new_browser = new_browser[:63] + b"\0"
                    new_browser = new_browser.ljust(64, b"\0")
                    
                    idx = stub_padded.find(old_host_pattern)
                    if idx != -1:
                        stub_padded[idx:idx+64] = new_browser
                        print(f"[*] Patched libxigncode.so KGC_GLOGIN_HOST -> {GLOGIN_HOST}")
                    else:
                        print(f"[!] Warning: Could not find KGC_GLOGIN_HOST buffer in libxigncode.so!")
                    
                    # Patch g_kgc_glogin_poll_host (native poller host = IP, bypasses Cloudflare)
                    new_poll = GLOGIN_POLL_HOST.encode() + b"\0"
                    if len(new_poll) > 64:
                        print(f"WARNING: GLOGIN_POLL_HOST {GLOGIN_POLL_HOST} is too long!")
                        new_poll = new_poll[:63] + b"\0"
                    new_poll = new_poll.ljust(64, b"\0")
                    
                    idx2 = stub_padded.find(old_host_pattern)
                    if idx2 != -1:
                        stub_padded[idx2:idx2+64] = new_poll
                        print(f"[*] Patched libxigncode.so KGC_GLOGIN_POLL_HOST -> {GLOGIN_POLL_HOST}")
                    else:
                        print(f"[!] Warning: Could not find KGC_GLOGIN_POLL_HOST buffer!")

                    # The poll port is independent of the browser URL.  Public
                    # clients use the origin IP on Caddy's :80, while a local
                    # adb-reverse build retains the development server's :8080.
                    new_port = GLOGIN_POLL_PORT.encode() + b"\0"
                    if len(new_port) > 16:
                        raise SystemExit("GLOGIN_POLL_PORT does not fit native poll buffer")
                    # `8080` also occurs in unrelated native data, so never find it
                    # globally.  stub.cpp keeps the port directly after the first
                    # (browser) 64-byte host buffer.
                    if idx == -1:
                        print("[!] Warning: Could not locate KGC_GLOGIN_POLL_PORT without browser host buffer!")
                    else:
                        port_start = idx + 64
                        old_port = bytes(stub_padded[port_start:port_start+16]).split(b"\0", 1)[0]
                        if old_port == b"8080":
                            stub_padded[port_start:port_start+16] = new_port.ljust(16, b"\0")
                            print(f"[*] Patched libxigncode.so KGC_GLOGIN_POLL_PORT -> {GLOGIN_POLL_PORT}")
                        else:
                            print(f"[!] Warning: Unexpected KGC_GLOGIN_POLL_PORT buffer: {old_port!r}")
                    
                    # Patch g_kgc_glogin_scheme ("http" for local, "https" for public)
                    old_scheme = b"http\0   "
                    new_scheme = GLOGIN_SCHEME.encode() + b"\0"
                    new_scheme = new_scheme.ljust(9, b"\0")
                    idx3 = stub_padded.find(old_scheme)
                    if idx3 != -1:
                        stub_padded[idx3:idx3+9] = new_scheme
                        print(f"[*] Patched libxigncode.so KGC_GLOGIN_SCHEME -> {GLOGIN_SCHEME}")
                    else:
                        print(f"[!] Warning: Could not find KGC_GLOGIN_SCHEME buffer!")
                        
                    stub_padded.extend(b'\0' * (orig_size - len(stub_padded)))
                    new_item = zipfile.ZipInfo(item.filename, item.date_time)
                    new_item.compress_type = item.compress_type
                    zout.writestr(new_item, bytes(stub_padded))
                else:
                    new_item = zipfile.ZipInfo(item.filename, item.date_time)
                    new_item.compress_type = item.compress_type
                    zout.writestr(new_item, zin.read(item.filename))
    shutil.move(tmp, apk_path)

def main():
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)
    
    outputs = {name: WORK / src.name for name, src in ORIG_APKS.items()}
    for name, dst in outputs.items():
        shutil.copy2(ORIG_APKS[name], dst)

    base_apk = outputs["base"]

    print("[+] Renaming label -> King Bug Castle...")
    subprocess.run([sys.executable, str(PATCHERS / "patch_rename.py"),
                    str(base_apk), NEW_LABEL], check=True)

    print(f"[+] Renaming package id -> {NEW_PKG} (base, apktool - also disables Firebase/GMS services)...")
    subprocess.run([sys.executable, str(PATCHERS / "patch_package_id.py"),
                    str(base_apk), OLD_PKG, NEW_PKG], check=True)

    print(f"[+] Renaming package id -> {NEW_PKG} (config/base_assets, light)...")
    for name in ("config", "base_assets"):
        subprocess.run([sys.executable, str(PATCHERS / "patch_package_id_light.py"),
                        str(outputs[name]), OLD_PKG, NEW_PKG], check=True)

    print("[+] Injecting Firebase Analytics deactivation meta-data...")
    dec = WORK / "dec_base"
    subprocess.run(["apktool", "d", "-f", str(base_apk), "-o", str(dec)], check=True, stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable, str(PATCHERS / "patch_genesis.py"), str(dec)], check=True)

    manifest = dec / "AndroidManifest.xml"
    txt = manifest.read_text(encoding="utf-8")
    # Re-enable FirebaseInitProvider (patch_package_id.py disabled it). A disabled
    # provider means no default FirebaseApp, which makes the game's Firebase.Messaging
    # init throw "modules failed to initialize: messaging (missing dependency)" - fatal
    # in v171's Scene_Login load path (NRE cascade -> stuck on "Loading resources").
    # GMS measurement/analytics services stay disabled + analytics deactivated below
    # (they trigger the GSF crash on redroid); only the Firebase core provider is restored.
    txt = txt.replace(
        '<provider android:authorities="com.nowl.castle.firebaseinitprovider" android:directBootAware="true" android:exported="false" android:initOrder="100" android:name="com.google.firebase.provider.FirebaseInitProvider" android:enabled="false"/>',
        '<provider android:authorities="com.nowl.castle.firebaseinitprovider" android:directBootAware="true" android:exported="false" android:initOrder="100" android:name="com.google.firebase.provider.FirebaseInitProvider"/>')
    # Fully deactivate Firebase Analytics: the measurement SDK otherwise queries
    # the GSF gservices provider (com.google.android.gsf, absent on redroid) and
    # crash-loops with SecurityException. Disabling the services isn't enough -
    # app code still inits FirebaseAnalytics; this meta-data stops collection dead.
    meta = ('<meta-data android:name="firebase_analytics_collection_deactivated" android:value="true"/>'
            '<meta-data android:name="google_analytics_adid_collection_enabled" android:value="false"/>')
    if meta not in txt:
        txt = txt.replace("</application>", meta + "</application>", 1)
    # UnityTls (UnityWebRequest) validates against the app's own baked CA bundle,
    # so it rejects our self-signed cert (Curl error 60 / UnityTls error 7). We serve
    # the API over plain HTTP instead (metadata https->http below); allow cleartext.
    if "usesCleartextTraffic" not in txt:
        txt = txt.replace("<application ", '<application android:usesCleartextTraffic="true" ', 1)
    # Deep-link scheme for the Google web-login return (google_login.py -> browser
    # navigates kingbugcastle://auth?id=...). Without this the launcher activity
    # never receives the link. The native Google-button->OpenURL hook + the
    # deep-link->login bridge in jni/stub.cpp are the other half; see
    # docs/multi-account-login.md "Google login via web".
    from patchers import patch_deeplink
    # Deep-link scheme is ALWAYS "kingbugcastle" — it is the custom URI the browser
    # redirects to after OAuth (kingbugcastle://auth). GLOGIN_SCHEME controls the
    # browser URL (https://...), which is a different thing entirely.
    txt = patch_deeplink.add_scheme(txt, "kingbugcastle")
    manifest.write_text(txt, encoding="utf-8")
    
    out = WORK / "rebuilt_base.apk"
    subprocess.run(["apktool", "b", str(dec), "-o", str(out)], check=True, stdout=subprocess.DEVNULL)
    shutil.copy(out, base_apk)

    print("[+] Forcing extractNativeLibs=true...")
    subprocess.run([sys.executable, str(REPO / "server" / "patchers" / "patch_extract_native.py"), str(base_apk)], check=True)

    patch_aledatic_and_inject_il2cpp(outputs["config"])
    # Stub now registers BOTH XigncodeClientSystem and AppSignClientSystem natives
    # (v171 hits AppSign on Guest Login), so no NoClassDefFoundError. Real xigncode
    # SIGSEGVs under ndk_translation, so the stub is required on redroid anyway.
    replace_xigncode(outputs["config"])

    # Load libxigncode.so at app start (JNI_OnLoad of the libmain wrapper) instead of
    # waiting for XIGNCODE's own login-time init. Without this the stub - and its
    # il2cpp hooks - only come up AFTER the login screen renders, so the Google-login
    # button hook is not installed when the button is first pressed. The wrapper
    # dlopens libxigncode (RTLD_GLOBAL) then forwards JNI_OnLoad to libmain_real.so.
    print("[+] Installing libmain wrapper (early-load libxigncode for the login hooks)...")
    subprocess.run([sys.executable, str(REPO / "server" / "patchers" / "patch_replace_libmain.py"),
                    str(outputs["config"])], check=True)

    # MUST run before patch_hosts / patch_metadata_http - those edit whatever
    # metadata is in the APK, and we want them editing the one we ship.
    if METADATA_DEC is None:
        print("[+] Metadata swap not needed - the injected libil2cpp is this build's own")
    else:
        print("[+] Swapping global-metadata.dat -> v171.0.00 (pairs with the injected libil2cpp.so)...")
        subprocess.run([sys.executable, str(PATCHERS / "patch_metadata_swap.py"),
                        str(outputs["base_assets"]), str(METADATA_DEC)], check=True)

    print(f"\n[+] Rebinding backend hosts -> {SHARE_HOST} (private server)...")
    subprocess.run([sys.executable, str(REPO / "server" / "patchers" / "patch_hosts.py"),
                    str(outputs["base_assets"]), SHARE_HOST], check=True)

    print("[+] Converting backend URLs https -> http (UnityTls rejects self-signed cert)...")
    subprocess.run([sys.executable, str(REPO / "server" / "patchers" / "patch_metadata_http.py"),
                    str(outputs["base_assets"])], check=True)

    print(f"[+] Rebinding leftover field-default host URLs -> {SHARE_HOST} (castle-infra/cdn copies patch_hosts misses)...")
    subprocess.run([sys.executable, str(REPO / "server" / "patchers" / "patch_leftover_hosts.py"),
                    str(outputs["base_assets"]), SHARE_HOST], check=True)

    # Normalize split package IDs once more after every bundle/metadata rewrite.
    # The asset split is repeatedly rewritten in-place above; keeping this as
    # the final pre-signing pass guarantees Android sees the same package name
    # in all three APKs (otherwise install-multiple fails atomically with
    # INSTALL_FAILED_INVALID_APK).
    print(f"[+] Final split package-id normalization -> {NEW_PKG}...")
    for name in ("config", "base_assets"):
        subprocess.run(
            [
                sys.executable,
                str(PATCHERS / "patch_package_id_light.py"),
                str(outputs[name]),
                OLD_PKG,
                NEW_PKG,
            ],
            check=True,
        )

    print("\n=== Signing ===")
    for name, apk in outputs.items():
        aligned = apk.with_name(apk.stem + "_aligned" + apk.suffix)
        subprocess.run([ZIPALIGN, "-p", "-f", "4", str(apk), str(aligned)], check=True, capture_output=True)
        shutil.move(str(aligned), str(apk))
        sign(apk)

    if "--share" in sys.argv:
        build_xapk(outputs)
        return

    print("\n=== Uninstalling (previous King Bug Castle only - real app untouched) ===")
    subprocess.run(["adb", "-s", "localhost:5555", "uninstall", NEW_PKG], capture_output=True)

    print("\n=== Installing to Device ===")
    cmd = ["adb", "-s", "localhost:5555", "install-multiple", "--no-incremental",
           str(outputs["base"]), str(outputs["config"]), str(outputs["base_assets"])]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode == 0:
        print("SUCCESS")
    else:
        print("FAILED", r.stderr)


def build_xapk(outputs):
    """Package the 3 signed APKs + manifest into a shareable .xapk (no install)."""
    import json
    if SHARE_HOST in ("127.0.0.1", "localhost"):
        print(f"\n[!] SHARE_HOST={SHARE_HOST} only works with adb reverse (local device).")
        print("    Remote players cannot reach it. Re-run with SHARE_HOST=<public-ip-or-domain>.")
    out = REPO / f"KingBugCastle_{VER}.xapk"
    src = json.loads((XAPK / "manifest.json").read_text())
    src["package_name"] = NEW_PKG
    src["name"] = NEW_LABEL
    src.pop("locales_name", None)
    src["split_apks"] = [{"file": outputs[n].name, "id": ("base" if n == "base" else outputs[n].stem)}
                         for n in ("base", "config", "base_assets")]
    src["total_size"] = sum(outputs[n].stat().st_size for n in outputs)
    src["_server_host"] = SHARE_HOST
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        z.writestr("manifest.json", json.dumps(src, ensure_ascii=False, indent=1))
        icon = XAPK / "icon.png"
        if icon.exists():
            z.writestr("icon.png", icon.read_bytes())
        for n in ("base", "config", "base_assets"):
            apk = outputs[n]
            with apk.open("rb") as fsrc, z.open(zipfile.ZipInfo(apk.name), "w") as fdst:
                shutil.copyfileobj(fsrc, fdst, length=8 * 1024 * 1024)
    print(f"\n=== Shareable XAPK: {out} ({out.stat().st_size/1e6:.0f} MB), host baked: {SHARE_HOST} ===")


if __name__ == '__main__':
    main()
