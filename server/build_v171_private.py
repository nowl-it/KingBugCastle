#!/usr/bin/env python3
import sys, subprocess, tempfile, shutil, pathlib, os, zipfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from rebuild_arm64 import sign, ZIPALIGN

REPO = pathlib.Path(__file__).resolve().parents[1]
XAPK = REPO / "apk" / "xapk_extracted_v171"
WORK = REPO / ".rebuild_v171"
IL2CPP_DEC = REPO / "il2cpp" / "v171.0.00" / "libil2cpp_v171_ssl.so"
# Host to rebind the 5 backend hostnames to (private server). Default 127.0.0.1
# reaches the local server via `adb reverse tcp:443 tcp:8443`. Override with
# SHARE_HOST=<ip-or-domain> for a remote/shared build.
SHARE_HOST = os.environ.get("SHARE_HOST", "127.0.0.1")

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
CHECKFIREBASE_OFF = 0x303C6C0
RET = bytes.fromhex('c0035fd6')  # arm64 `ret`

# OBSOLETE, opt-in only (KGC_ASSETBYPASS=1). The "infinite UniTask recursion" this was
# built to dodge was NOT a real client bug - it came from a corrupt libil2cpp_v171_ssl.so
# whose stray `b 0x3503ba8` had overwritten `mov w8,#-2` in
# Scene_Login.<CheckUseAssetBundle>d__79.MoveNext. With a clean _ssl.so (plain lib + only
# the 3 SSL RET_TRUE patches) the async runs fine. Keeping the bypass on is HARMFUL: it
# skips usePatch/getPatchFolder, so the CDN `xml` bundle (Strings + fonts) never downloads
# and the whole UI renders garbled.
CHECKUSEASSET_OFF = 0x34f9588 - 0x4000
# mov w1,#1 (0x52000021) ; b LoadAfterAssetBundle @0x34f9618 (0x14000023)
CHECKUSEASSET_PATCH = bytes.fromhex('2100005223000014')

# PvPPanel.<Init>d__77.MoveNext -> early return false. Same NRE stub v170 applies
# (rebuild_arm64.py "pvp-init"): the lobby PvP panel NREs on the semiSeason path even
# with a correct /pvp/info response, and the NRE blocks the whole lobby render.
# RVA 0x325658c (script.json ScriptMethod), file offset = RVA - 0x4000.
RET_FALSE = bytes.fromhex('e0031f2ac0035fd6')     # mov x0,#0 ; ret (also "return null")
RET_TRUE = bytes.fromhex('20008052c0035fd6')      # mov w0,#1 ; ret

# Lobby-NRE stubs, ported from the proven v170 set in rebuild_arm64.py (same
# purpose + same prologue bytes, only the offsets moved). RVAs from
# il2cpp/v171.0.00/script.json ScriptMethod; file offset = RVA - 0x4000.
# v170's WorldPanel.IsKGMarbleAvailable has no v171 counterpart - dropped.
# (rva, label, expected prologue, replacement)
NRE_STUBS = [
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

def patch_aledatic_and_inject_il2cpp(apk_path):
    print(f"[*] Patching libaledatic.so and injecting libil2cpp.so into {apk_path.name}...")
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
        cur = bytes(il2_data[off:off+8])
        if cur == new:
            continue
        if cur != bytes.fromhex(orig_hex):
            raise SystemExit(f"{label}: unexpected bytes at 0x{off:x}: {cur.hex()}")
        il2_data[off:off+8] = new
        print(f"  [+] stubbed {label} @ 0x{off:x} -> {new.hex()}")
    il2_data = bytes(il2_data)
    with zipfile.ZipFile(apk_path, "r") as zin:
        with zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                
                new_item = zipfile.ZipInfo(item.filename, item.date_time)
                new_item.compress_type = item.compress_type
                
                if item.filename == "lib/arm64-v8a/libaledatic.so":
                    data_bytearray = bytearray(data)
                    offsets = [0x3d2b8, 0x3d2c0, 0x3d2c8, 0x3d2f8, 0x3d484, 0x3d4c8, 0x3d4e4, 0x3d4f4]
                    for offset in offsets:
                        if data_bytearray[offset+3] == 0x37:
                            data_bytearray[offset:offset+4] = b'\x1f\x20\x03\xd5'
                            count += 1
                        elif data_bytearray[offset+3] == 0xb4:
                            data_bytearray[offset:offset+4] = b'\x1f\x20\x03\xd5'
                            count += 1
                    dlopen_offsets = [0xe5728, 0xe57d0, 0xe57e8, 0xe5870]
                    for offset in dlopen_offsets:
                        if data_bytearray[offset+3] == 0x14:
                            data_bytearray[offset:offset+4] = b'\x1f\x20\x03\xd5'
                            count += 1
                    zout.writestr(new_item, bytes(data_bytearray))
                else:
                    zout.writestr(new_item, data)
            
            # Inject il2cpp.so
            il2_item = zipfile.ZipInfo("lib/arm64-v8a/libil2cpp.so")
            il2_item.compress_type = zipfile.ZIP_STORED
            zout.writestr(il2_item, il2_data)
            
    shutil.move(tmp, apk_path)
    print(f"  [+] patched {count} signature checks in libaledatic.so")

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
    subprocess.run(["apktool", "d", "-s", "-f", str(base_apk), "-o", str(dec)], check=True, stdout=subprocess.DEVNULL)

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

    print(f"\n[+] Rebinding backend hosts -> {SHARE_HOST} (private server)...")
    subprocess.run([sys.executable, str(REPO / "server" / "patchers" / "patch_hosts.py"),
                    str(outputs["base_assets"]), SHARE_HOST], check=True)

    print("[+] Converting backend URLs https -> http (UnityTls rejects self-signed cert)...")
    subprocess.run([sys.executable, str(REPO / "server" / "patchers" / "patch_metadata_http.py"),
                    str(outputs["base_assets"])], check=True)

    print(f"[+] Rebinding leftover field-default host URLs -> {SHARE_HOST} (castle-infra/cdn copies patch_hosts misses)...")
    subprocess.run([sys.executable, str(REPO / "server" / "patchers" / "patch_leftover_hosts.py"),
                    str(outputs["base_assets"]), SHARE_HOST], check=True)

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
    out = REPO / "KingBugCastle_v171.xapk"
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
