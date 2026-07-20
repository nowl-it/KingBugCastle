#!/usr/bin/env bash
# KGC private server deploy script
# Usage: ./deploy.sh [APK_DIR]
# APK_DIR defaults to ~/Code/kgc/apk/
# Expects in APK_DIR:
#   base.apk
#   split_base_assets.apk  (contains global-metadata.dat)
#   split_config.apk       (contains libil2cpp.so - must be stored/uncompressed)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APK_DIR="${1:-"$HOME/Code/kgc/apk"}"
WORK_DIR="$HOME/Code/kgc/.deploy"
KEYSTORE="$HOME/.android/debug.keystore"
KS_PASS="android"

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GRN}[+]${NC} $*"; }
warn() { echo -e "${YLW}[!]${NC} $*"; }
die()  { echo -e "${RED}[✗]${NC} $*" >&2; exit 1; }

# ---- Check deps ----
for cmd in python3 apksigner adb apktool; do
    command -v "$cmd" &>/dev/null || die "Missing: $cmd"
done

# ---- Work dir ----
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR"

# ---- Extract XAPK if needed ----
XAPK="$(find "$APK_DIR" -maxdepth 1 -name "*.xapk" | sort -V | tail -1)"
if [ -n "$XAPK" ]; then
    EXTRACT_DIR="$WORK_DIR/xapk_extracted"
    mkdir -p "$EXTRACT_DIR"
    log "Extracting XAPK: $(basename "$XAPK") ..."
    unzip -o -q "$XAPK" "*.apk" -d "$EXTRACT_DIR"
    log "Extracted files:"
    find "$EXTRACT_DIR" -name "*.apk" | sed 's/^/    /'
    APK_DIR="$EXTRACT_DIR"
fi

# ---- Find APKs ----
# base: either base.apk or com.*.apk (XAPK names it after package)
BASE_APK="$(find "$APK_DIR" -maxdepth 2 -name "base.apk" ! -name "*patch*" ! -name "*sign*" | head -1)"
[ -z "$BASE_APK" ] && BASE_APK="$(find "$APK_DIR" -maxdepth 2 -name "com.*.apk" ! -name "*patch*" ! -name "*sign*" | head -1)"
ASSETS_APK="$(find "$APK_DIR" -maxdepth 2 -name "*assets*.apk" ! -name "*patch*" ! -name "*sign*" | head -1)"
CONFIG_APK="$(find "$APK_DIR" -maxdepth 2 -name "*config*armeabi*.apk" ! -name "*patch*" ! -name "*sign*" | head -1)"
[ -z "$CONFIG_APK" ] && CONFIG_APK="$(find "$APK_DIR" -maxdepth 2 -name "*config*.apk" ! -name "*patch*" ! -name "*sign*" | head -1)"

[ -f "$BASE_APK" ]   || die "base APK not found in $APK_DIR"
[ -f "$ASSETS_APK" ] || die "split_base_assets APK not found in $APK_DIR"
[ -f "$CONFIG_APK" ] || die "split_config APK not found in $APK_DIR"

log "base:   $BASE_APK"
log "assets: $ASSETS_APK"
log "config: $CONFIG_APK"

# ---- Patch split_config (libil2cpp.so - SSL + CDN bypass) ----
log "Patching split_config (libil2cpp.so binary patches)..."
cp "$CONFIG_APK" "$WORK_DIR/split_config_patched.apk"
python3 "$SCRIPT_DIR/patchers/patch_apk_inplace.py" "$WORK_DIR/split_config_patched.apk"

# ---- Replace libxigncode.so with no-op stub (disable XIGNCODE3 anti-tamper) ----
# Without this the patched client runs ~70s then XIGNCODE sabotages a random thread
# and crashes. The stub implements all ZCWAVE_* JNI methods as no-ops (return 0 / "").
# Done at build time -> client runs standalone, no runtime tooling needed.
STUB="$SCRIPT_DIR/xigncode_stub/libxigncode.so"
if [ -f "$STUB" ]; then
    log "Replacing libxigncode.so with no-op stub (disable XIGNCODE3)..."
    STAGE="$WORK_DIR/xstub/lib/armeabi-v7a"
    mkdir -p "$STAGE"
    cp "$STUB" "$STAGE/libxigncode.so"
    ( cd "$WORK_DIR/xstub" && zip -q -0 -X "$WORK_DIR/split_config_patched.apk" lib/armeabi-v7a/libxigncode.so )
    # native libs must stay stored + page-aligned (extractNativeLibs=false) -> zipalign
    ZIPALIGN="$(ls /opt/android-sdk/build-tools/*/zipalign 2>/dev/null | sort -V | tail -1)"
    [ -z "$ZIPALIGN" ] && ZIPALIGN="$(command -v zipalign)"
    [ -n "$ZIPALIGN" ] || die "zipalign not found (needed after libxigncode swap)"
    "$ZIPALIGN" -p -f 4 "$WORK_DIR/split_config_patched.apk" "$WORK_DIR/split_config_aligned.apk"
    mv "$WORK_DIR/split_config_aligned.apk" "$WORK_DIR/split_config_patched.apk"
else
    warn "xigncode stub not found at $STUB - skipping (client will crash ~70s from XIGNCODE)"
fi

# ---- Patch split_base_assets (global-metadata.dat - https→http) ----
log "Patching split_base_assets (https→http)..."
cp "$ASSETS_APK" "$WORK_DIR/split_base_assets_patched.apk"
python3 "$SCRIPT_DIR/patchers/patch_metadata_http.py" "$WORK_DIR/split_base_assets_patched.apk"

# ---- Inject full localization into local PreStrings TextAssets (offline UI strings) ----
# The CDN-served full string set is 404'd by us, so without this the UI shows raw loc keys.
# Overwrite each PreStrings_<locale> with the full Strings_<locale>.xml so Localizer has all keys.
XML_DIR="${KGC_XML_DIR:-$(cd "$(dirname "$0")" && pwd)/xml_live}"
if [ -d "$XML_DIR" ]; then
    log "Injecting full localization strings (PreStrings <- $XML_DIR)..."
    python3 "$SCRIPT_DIR/patchers/patch_prestrings.py" "$WORK_DIR/split_base_assets_patched.apk" "$XML_DIR" || warn "PreStrings inject failed (UI will show raw keys)"
else
    warn "XML dir $XML_DIR not found - skipping localization inject (UI will show raw keys)"
fi

# ---- Copy base + rename display label -> "King Bug Castle" ----
cp "$BASE_APK" "$WORK_DIR/base_patched.apk"
log "Renaming app label -> King Bug Castle..."
python3 "$SCRIPT_DIR/patchers/patch_rename.py" "$WORK_DIR/base_patched.apk" || warn "rename failed (label stays 'King God Castle')"

# ---- Sign all ----
log "Signing APKs..."
for f in split_config split_base_assets base; do
    apksigner sign \
        --ks "$KEYSTORE" --ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS" \
        --out "$WORK_DIR/${f}_signed.apk" \
        "$WORK_DIR/${f}_patched.apk"
    log "  signed: $WORK_DIR/${f}_signed.apk"
done

# ---- ADB install ----
DEVICE="$(adb devices | awk 'NR>1 && /device$/ {print $1; exit}')"
if [ -z "$DEVICE" ]; then
    warn "No ADB device found - skipping install"
    warn "Run manually: adb install-multiple -r $WORK_DIR/base_signed.apk $WORK_DIR/split_base_assets_signed.apk $WORK_DIR/split_config_signed.apk"
    exit 0
fi

log "Device: $DEVICE"
log "Installing..."
adb -s "$DEVICE" install-multiple -r --no-incremental \
    "$WORK_DIR/base_signed.apk" \
    "$WORK_DIR/split_base_assets_signed.apk" \
    "$WORK_DIR/split_config_signed.apk"
log "Install done"

# ---- Start server (background) ----
if lsof -i :8080 &>/dev/null 2>&1; then
    warn "Port 8080 already in use - server may already be running"
else
    log "Starting private server on :8080..."
    cd "$SCRIPT_DIR"
    nohup uvicorn server:app --host 0.0.0.0 --port 8080 > "$HOME/Code/kgc/.deploy/server.log" 2>&1 &
    SERVER_PID=$!
    sleep 1
    if kill -0 "$SERVER_PID" 2>/dev/null; then
        log "Server PID $SERVER_PID  (logs: $HOME/Code/kgc/.deploy/server.log)"
    else
        warn "Server failed to start - check $HOME/Code/kgc/.deploy/server.log"
    fi
fi

echo ""
log "Done. Launch KGC on device and watch logs:"
echo "    tail -f $HOME/Code/kgc/.deploy/server.log"
echo "    adb -s $DEVICE logcat | grep -i 'castle\|patch\|asset\|login'"
