#!/usr/bin/env bash
# KGC CDN update checker - cron daily 0h
# 2 lớp: (1) official getPatchFolder API = pointer game đang trỏ; (2) HEAD-probe trên
# GCS chạy LUÔN = "list" thay thế, phát hiện folder MỚI UPLOAD trước lúc flip pointer.
# Notify nếu có bản mới.
# Layer 3 (signal thuần): official dev services gateway — env/branch roadmap.
# Enhanced: shows all dates, file counts, XML diff summary, local state comparison.

set -euo pipefail

CDN_BASE="https://kgc-cdn-1.awesomepiece.com"
STATE_FILE="$HOME/.local/share/kgc_cdn_last_date"
NTFY_TOPIC="https://ntfy.sh/nowl/test"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DISCORD_NOTIFY="$PROJECT_DIR/server/discord_notify.sh"

notify_discord() {
    [ -x "$DISCORD_NOTIFY" ] && "$DISCORD_NOTIFY" "$1" || true
}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

mkdir -p "$(dirname "$STATE_FILE")"

# ─── Official backend pointer (pre-auth, verified 2026-10-05) ────
# POST /auth/getPatchFolder của prod không cần token (spec: AccessToken required=false);
# body + header `time` mã hoá AES-128-ECB hex theo đúng recipe client (disasm Web.Post
# d__17 + GetServerTimestamp, xem docs/dev-notes.md §31). Prod trả "LIVE/<date>",
# dev env trả "" → chỉ prod dùng được. Không phụ thuộc ListBucket nên vượt luôn
# ceiling 45 ngày của HEAD-probe. Fail → in gì cũng không (caller fallback cũ chạy tiếp).
#
# POINTER BỊ VERSION-GATE (chứng minh 2026-10-08, sweep lại 2026-10-20): cùng 1
# endpoint, version 173.1.00 → LIVE/2026_09_22 (pin bản cũ), 174.0.x →
# LIVE/2026_10_06_xGrY0WbLgR, ≥174.1.00 (kể cả 999.0.00) → newest
# (LIVE/2026_10_20_bhhtbJKhrR — tìm ra update 10-20 trước store bằng cách này).
# → probe cả version client thật lẫn "999.0.00" (luôn = newest), lấy max.
official_patch_folder() {
    KGC_CLIENT_VERSION="$client_ver" python3 - <<'PY' 2>/dev/null || true
import json, os, subprocess
from Crypto.Cipher import AES
KEY = b"a6072ad6b9c959ff"
def enc_hex(s):
    raw = s.encode()
    if len(raw) % 16:
        raw += b"\x00" * (16 - len(raw) % 16)
    return AES.new(KEY, AES.MODE_ECB).encrypt(raw).hex()
def ask(ver):
    body = enc_hex(json.dumps(
        {"platform": "Android", "version": ver, "isDev": False},
        separators=(",", ":")))
    out = subprocess.run(
        ["curl", "-sf", "-m", "15", "-X", "POST",
         "-H", "version: " + ver,
         "-H", "platform: Android",
         "-H", "time: " + enc_hex("beforeLogin"),
         "-H", "Content-Type: application/json",
         "--data-binary", body,
         "https://kgc-k8s-1.awesomepiece.com/auth/getPatchFolder"],
        capture_output=True).stdout
    if not out:
        return ""
    pt = AES.new(KEY, AES.MODE_ECB).decrypt(out).rstrip(b"\x00 ")
    return json.loads(pt).get("patchFolder", "")
folders = [f for f in (ask(os.environ.get("KGC_CLIENT_VERSION") or "174.0.00"),
                       ask("999.0.00")) if f]
print(max(folders) if folders else "")
PY
}

# ─── Fetch CDN S3 listing ────────────────────────────────────────
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║            KGC CDN Update Checker            ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""

# Nguồn folder — ListBucket deny vĩnh viễn ở IAM (owner gỡ storage.objects.list của
# allUsers ~04/10/2026, GET/HEAD object vẫn 200; không có credential GCS → không mở lại
# được) → thay list bằng 2 lớp:
#   1. getPatchFolder API — pointer game ĐANG trỏ (pre-auth, recipe xem dev-notes §31);
#   2. HEAD-probe +1..+45 ngày — "list" thay thế: folder upload lên CDN nhưng CHƯA flip
#      pointer (API chưa biết) vẫn thấy được → đây là sớm nhất khi list chết.
#     (giới hạn: chỉ folder tên ngày thuần YYYY_MM_DD trên nhánh LIVE, cửa sổ +45 ngày.
#      Từ bản 2026_10_06_xGrY0WbLgR folder có suffix ngẫu nhiên → KHÔNG đoán được nữa
#      → layer 2 hết tác dụng với tên mới; nguồn chính là layer 1 với version đúng.)
all_dates=""
DATES_FILE="$HOME/.local/share/kgc_cdn_dates"

# Version cho pointer — version-gate: 173.1.00 bị pin folder cũ, 174.0.00 → bản mới.
# Nguồn: xapk mới nhất trong apk/ (override bằng KGC_CLIENT_VERSION).
client_ver="${KGC_CLIENT_VERSION:-$(ls -1 "$PROJECT_DIR/apk"/com.awesomepiece.castle@*.xapk 2>/dev/null | sed 's/.*@//; s/\.xapk$//; s/-arm64$//' | sort -V | tail -1 || true)}"
client_ver="${client_ver:-174.0.00}"   # fallback khi apk/ rỗng — bump tay khi có bản mới

api_folder=$(official_patch_folder || true)
api_date=""
if [[ -n "$api_folder" ]]; then
    api_date="${api_folder##*/}"   # "LIVE/2026_10_06_xGrY0WbLgR" -> "2026_10_06_xGrY0WbLgR"
    [[ "$api_date" =~ ^[0-9]{4}_[0-9]{2}_[0-9]{2}(_[A-Za-z0-9]+)*$ ]] || api_date=""
fi

if [[ -n "$api_date" ]]; then
    all_dates=$(printf '%s\n%s\n' "$(cat "$DATES_FILE" 2>/dev/null || true)" "$api_date" \
        | grep -E '^[0-9]{4}_[0-9]{2}_[0-9]{2}(_[A-Za-z0-9]+)*$' | sort -u || true)
    printf '%s\n' "$all_dates" > "$DATES_FILE"
    echo -e "${DIM}[api] Official patchFolder: ${api_folder}${NC}"
fi

# HEAD-probe chạy LUÔN (không phải chỉ khi API fail) — đây là nguồn "folder mới trên
# CDN" duy nhất còn lại. Seed = last-known (đã gồm pointer nếu API chạy trước).
seed=$(cat "$STATE_FILE" 2>/dev/null || true)
seed=${seed:-$(tail -1 "$DATES_FILE" 2>/dev/null || true)}
if [[ -n "$seed" ]]; then
    # Folder mới có suffix ngẫu nhiên (2026_10_06_xGrY0WbLgR) — date -d chỉ nhận
    # phần ngày, thiếu bước strip này sẽ abort vì set -e.
    seed_day="${seed:0:10}"
    echo -e "${YELLOW}[!] HEAD-probe list-thay-thế: dò +1..+45 ngày từ ${seed_day}${NC}"
    seed_epoch=$(date -d "$(echo "$seed_day" | tr '_' '-')" +%s)
    found=""
    for i in $(seq 1 45); do
        cand=$(date -d "@$((seed_epoch + i * 86400))" +%Y_%m_%d)
        code=$(curl -s -o /dev/null -w '%{http_code}' -I --max-time 15 \
            "${CDN_BASE}/patch/LIVE/${cand}/ANDROID/xml" || echo 000)
        if [[ "$code" == "200" ]]; then
            found+="${cand}"$'\n'
        fi
    done
    { [[ -f "$DATES_FILE" ]] && cat "$DATES_FILE"
      echo "$seed"
      printf '%s' "$found"; } \
        | grep -E '^[0-9]{4}_[0-9]{2}_[0-9]{2}(_[A-Za-z0-9]+)*$' | sort -u > "${DATES_FILE}.tmp" || true
    mv -f "${DATES_FILE}.tmp" "$DATES_FILE" 2>/dev/null || true
    all_dates=$(cat "$DATES_FILE" 2>/dev/null || true)
fi

if [[ -z "$all_dates" ]]; then
    echo -e "${RED}[✗] No patch dates found (api fail + head-probe fail)${NC}" >&2
    curl -sf -H "Title: 🏰 KGC CDN watcher lỗi" \
        -d "Không lấy được patch folder mới (getPatchFolder API fail + head-probe fail)." \
        "$NTFY_TOPIC" &>/dev/null || true
    exit 1
fi

latest=$(echo "$all_dates" | tail -1)
total_count=$(echo "$all_dates" | wc -l)

# ─── CDN Patch History ───────────────────────────────────────────
echo -e "${CYAN}── CDN Patch History ──${NC}"
echo -e "${DIM}Total patches on CDN: ${NC}${BOLD}${total_count}${NC}"
echo ""

# Show last 10 dates with markers
echo "$all_dates" | tail -10 | while read -r d; do
    marker=""
    if [[ "$d" == "$latest" ]]; then
        marker=" ${GREEN}◀ latest${NC}"
    fi
    # Convert underscore date to readable format (bỏ suffix ngẫu nhiên, chỉ hiện ngày)
    readable=$(echo "${d:0:10}" | sed 's/_/-/g')
    echo -e "  ${DIM}•${NC} ${readable}${marker}"
done

if [[ "$total_count" -gt 10 ]]; then
    hidden=$((total_count - 10))
    echo -e "  ${DIM}  ... and ${hidden} older patches${NC}"
fi
echo ""

# ─── Local State Comparison ──────────────────────────────────────
echo -e "${CYAN}── Local State ──${NC}"

last=""
if [[ -f "$STATE_FILE" ]]; then
    last=$(cat "$STATE_FILE")
fi

echo -e "  Last checked date:  ${BOLD}${last:-"(none)"}${NC}"
echo -e "  CDN latest date:    ${BOLD}${latest}${NC}"

# Check local snapshots (xml_history/ — IOS/ chưa từng tồn tại trong repo này)
local_dates=""
if [[ -d "$PROJECT_DIR/xml_history" ]]; then
    # Accept cả tên snapshot có suffix (vd 2026_10_06_xGrY0WbLgR) nếu mình extract theo tên folder gốc
    local_dates=$(ls -1 "$PROJECT_DIR/xml_history" 2>/dev/null | grep -E '^[0-9]{4}_[0-9]{2}_[0-9]{2}(_[A-Za-z0-9]+)*$' | sort || true)
fi
local_latest=""
if [[ -n "$local_dates" ]]; then
    local_latest=$(echo "$local_dates" | tail -1)
    local_count=$(echo "$local_dates" | wc -l)
    echo -e "  Local snapshots: ${BOLD}${local_count}${NC} (latest: ${local_latest})"
else
    echo -e "  Local snapshots: ${DIM}(none)${NC}"
fi

# Check the server's advertised patchFolder (lives in response_config.json, not server.py).
# Every lookup here must be non-fatal: `set -e` turns a no-match grep into a silent abort
# that skips the etag/republish section below - that bug hid a republish once already.
server_patch=""
cfg="$PROJECT_DIR/server/data/response_config.json"
if [[ -f "$cfg" ]]; then
    server_patch=$(grep -oP '"patchFolder"\s*:\s*"\K[^"]+' "$cfg" || true)
    echo -e "  Server patchFolder: ${BOLD}${server_patch:-"(not set)"}${NC}"
fi

echo ""

# ─── Official dev services (branch roadmap) ─────────────────────
# Host LỌT TÀI LIỆU (reports/kgc-dev-infra-recon.md §1, docs/dev-notes.md:187): gateway
# admin castle-infra-server chỉ allowlist đúng 1 path —
#   GET /api/cloud-run/services?location=asia-northeast3
# và trả serverList[] = map env dev → clientBranch (1008_update/main, 1021_update/unit_10820…).
# Env MỚI / branch đổi = tín hiệu update roadmap SỚM hơn CDN 1-2 ngày (§13.2, §16).
# 404 toàn host từ sau bản 10-08 (Cloud Run service bị gỡ — 404 y hệt host bịa = không
# còn backend, không phải đổi path), nhưng client v174 vẫn hardcode URL này → họ mở lại
# là watcher bắt ngay. Fail → skip im, không phá luồng CDN phía dưới.
# (Đã thay section "Client APK version" — apkeep/store check redundant vì version-gate
# của layer 1 đã lấy client_ver từ apk/.)
echo -e "${CYAN}── Official dev services (roadmap) ──${NC}"
SERVICES_URL="https://castle-infra-server-65408603887.asia-northeast3.run.app/api/cloud-run/services?location=asia-northeast3"
SVC_FILE="$HOME/.local/share/kgc_dev_services"
svc_json=$(curl -sf -m 15 "$SERVICES_URL" || true)
svc_sig=""
if [[ -n "$svc_json" ]]; then
    svc_sig=$(printf '%s' "$svc_json" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)
rows = []
for s in d.get("serverList") or []:
    ci = s.get("cachedInfo") or {}
    rows.append("%s | %s | %s" % (s.get("name", ""), ci.get("clientBranch", ""), ci.get("changeServerTime", "")))
print("\n".join(sorted(rows)))' 2>/dev/null || true)
fi
if [[ -n "$svc_sig" ]]; then
    svc_last=$(cat "$SVC_FILE" 2>/dev/null || true)
    printf '%s\n' "$svc_sig" > "$SVC_FILE"
    printf '%s\n' "$svc_sig" | sed 's/^/  • /'
    if [[ -n "$svc_last" && "$svc_last" != "$svc_sig" ]]; then
        echo -e "${GREEN}${BOLD}[★] DEV SERVICES CHANGED — env/branch dev đổi (roadmap tín hiệu)${NC}"
        diff <(printf '%s\n' "$svc_last") <(printf '%s\n' "$svc_sig") | sed 's/^/  /' || true
        curl -sf -H "Title: 🏰 KGC dev services đổi" -H "Tags: game,kgc,dev" \
            -d "$svc_sig" "$NTFY_TOPIC" &>/dev/null || true
        notify_discord "$(printf '🌿 **KGC dev services changed**\n```%s```' "$svc_sig")"
    fi
else
    echo -e "${DIM}  (gateway 404/timeout — service bị gỡ từ ~10-10, sẽ tự hồi nếu họ mở lại)${NC}"
fi
echo ""

# ─── default dev API: swagger path-diff (branch roadmap) ─────────
# Gateway liệt kê service đã chết, nhưng project hash thì vẫn đúng → tên service mới
# vẫn dò được; `default` (branch mới nhất) còn sống và MỞ /v2/api-docs (AES-ECB key
# legacy cnf1tl65djs2wp3g). Path mới = feature đã merge, sớm hơn cả CDN.
# reports/kgc-dev-infra-recon.md §23, docs/dev-notes.md §70.
# Tải 334KB mỗi lần chạy (không có content-length/Range; ciphertext ECB deterministic nên
# md5 body là fingerprint ổn định). Giải mã + diff path CHỈ khi md5 đổi.
echo -e "${CYAN}── default dev API (swagger delta) ──${NC}"
DEF_HOST="https://default-x4bivlxmuq-du.a.run.app"
DEF_FILE="$HOME/.local/share/kgc_dev_swagger_md5"
DEF_SPEC="$PROJECT_DIR/reports/kgc_dev_swagger_default_decrypted.json"
def_md5=""
if curl -sf -m 30 "$DEF_HOST/v2/api-docs" -o /tmp/kgc_def_v2.bin 2>/dev/null; then
    def_md5=$(md5sum /tmp/kgc_def_v2.bin | cut -d' ' -f1)
fi
if [[ -n "$def_md5" ]]; then
    def_last=$(cat "$DEF_FILE" 2>/dev/null || echo "")
    if [[ -z "$def_last" ]]; then
        printf '%s\n' "$def_md5" > "$DEF_FILE"
        echo -e "  default swagger md5: ${BOLD}${def_md5:0:12}${NC} (baseline ghi lần đầu)"
    elif [[ "$def_md5" != "$def_last" ]]; then
        # Nội dung đổi → giải mã + diff path. Lỗi bất kỳ thì KHÔNG ghi state.
        if def_out=$(python3 - "$DEF_SPEC" <<'PY' 2>/dev/null
import json, sys
from Crypto.Cipher import AES
raw = open('/tmp/kgc_def_v2.bin','rb').read()
try:
    spec = json.loads(AES.new(b'cnf1tl65djs2wp3g', AES.MODE_ECB).decrypt(raw).rstrip(b'\x00 '))
except Exception:
    sys.exit(1)
paths = sorted(spec.get('paths', {}))
old = []
try:
    old = sorted(json.load(open(sys.argv[1])).get('paths', {}))
except Exception:
    pass
json.dump(spec, open(sys.argv[1], 'w'))
added, removed = [p for p in paths if p not in old], [p for p in old if p not in paths]
print("spec %d paths (%+d/-%d)" % (len(paths), len(added), len(removed)))
if old:
    for p in added[:12]:
        print("  + " + p)
    for p in removed[:12]:
        print("  - " + p)
PY
           ); then
            printf '%s\n' "$def_md5" > "$DEF_FILE"
            echo -e "  ${GREEN}${BOLD}[★] SWAGGER ĐỔI${NC} — $def_out"
            printf '%s\n' "$def_out" | sed 's/^/  /'
            curl -sf -H "Title: 🏰 KGC dev swagger đổi" -H "Tags: game,kgc,dev" \
                -d "$def_out" "$NTFY_TOPIC" &>/dev/null || true
            notify_discord "$(printf '🌿 **KGC dev swagger changed**\n```%s```' "$def_out")"
        else
            echo -e "  ${DIM}default swagger md5 đổi (${def_last:0:12}→${def_md5:0:12}) nhưng không giải mã được — bỏ qua${NC}"
        fi
    else
        echo -e "  default swagger: ${def_md5:0:12} ${DIM}(không đổi)${NC}"
    fi
else
    echo -e "${DIM}  (default unreachable — bỏ qua)${NC}"
fi
echo ""

# ─── Bundle fingerprint + snapshot freshness ────────────────────
# The devs republish the SAME patch folder in place (2026-07-20, và 2026-10-08
# ×2: e6344288 → 3aca7018 → 4df4282c). Tên folder không đổi → so tên vô hại.
# GCS trả md5 object làm ETag → 1 HEAD biết bundle có đổi không.
#
# BUG đã sửa 2026-10-17: bản cũ ghi đè "etag đã thấy" NGAY MỖI LẦN CHẠY →
# republish chỉ báo MỘT LẦN rồi im lặng; snapshot local vẫn cũ mà script nói
# "No update" (đúng triệu chứng user gặp). Trạng thái mới = snapshot đã verify
# khớp CDN CHƯA (VERIFIED_FILE, so theo NỘI DUNG: download + extract + diff) →
# lệch thì in cảnh báo MỖI lần chạy đến khi snapshot được fetch lại;
# push notification chỉ 1 lần/etag (dedup qua ETAG_FILE), không spam.
ETAG_FILE="$HOME/.local/share/kgc_cdn_last_xml_etag"          # etag đã push (dedup)
VERIFIED_FILE="$HOME/.local/share/kgc_cdn_snapshot_verified"  # folder|etag snapshot khớp
bundle_url="${CDN_BASE}/patch/LIVE/${latest}/ANDROID/xml"
etag=$(curl -sfI "$bundle_url" 2>/dev/null | grep -i '^etag:' | tr -d '"\r' | awk '{print $2}' || true)
notified_etag=""
[[ -f "$ETAG_FILE" ]] && notified_etag=$(cat "$ETAG_FILE")
verified=""
[[ -f "$VERIFIED_FILE" ]] && verified=$(cat "$VERIFIED_FILE")
snap_dir="$PROJECT_DIR/xml_history/${latest}"

echo -e "  CDN xml bundle etag: ${BOLD}${etag:-"(unavailable)"}${NC}"
echo -e "  Snapshot verified:   ${BOLD}${verified:-"(never)"}${NC}"
echo ""

# push_notify_once <title> <body>: push tối đa 1 lần cho mỗi etag (body dùng
# printf %b để interpret \n). Echo kết quả thay vì nuốt im lặng như bản cũ.
# ETAG_FILE chỉ ghi KHI ntfy push thành công → push fail sẽ retry lần chạy sau
# (bug cũ: ghi state vô điều kiện → notification fail = mất vĩnh viễn).
push_notify_once() {
    local title="$1" body="$2"
    if [[ -z "$etag" || "$etag" == "$notified_etag" ]]; then
        echo -e "    ${DIM}(etag đã push rồi — bỏ qua, không spam)${NC}"
        return 0
    fi
    if command -v notify-send &>/dev/null && [[ -n "${DISPLAY:-}" ]]; then
        notify-send -u critical -a "KGC Watcher" "$title" \
            "$(printf '%b' "$body" | sed -n 1p)" &
    fi
    if curl -sf -H "Title: $title" -H "Tags: game,kgc,update" -H "Priority: high" \
        -d "$(printf '%b' "$body")" "$NTFY_TOPIC" &>/dev/null; then
        echo -e "    ${GREEN}[✓] ntfy pushed${NC}"
        echo "$etag" > "$ETAG_FILE"
        notified_etag="$etag"
    else
        echo -e "    ${YELLOW}[!] ntfy push FAILED (mạng?) — giữ state, sẽ thử lại lần chạy sau${NC}"
    fi
    notify_discord "$title — $(printf '%b' "$body" | sed -n 1p | cut -c1-200)"
}

# ─── Snapshot freshness (verify theo NỘI DUNG) ──────────────────
# Chỉ download khi chưa verify khớp (bootstrap lần đầu / patch mới / republish):
# extract bundle ra tmp rồi diff -rq với snapshot local. Khớp → ghi verified;
# lệch → cảnh báo + diff chi tiết, lặp lại MỖI lần chạy đến khi fetch lại.
# verify_state: ok = khớp | stale = lệch | unknown = không verify được.
stale_report=""
verify_state="unknown"
if [[ ! -d "$snap_dir" ]]; then
    echo -e "  ${YELLOW}[!] Chưa có snapshot local cho ${latest}${NC}"
elif [[ -n "$etag" && "$verified" == "${latest}|${etag}" ]]; then
    verify_state="ok"
    echo -e "  ${GREEN}[✓] Snapshot local khớp CDN bundle${NC} ${DIM}(đã verify theo nội dung)${NC}"
else
    echo -e "  ${DIM}→ Chưa verify / etag đổi: download bundle + diff nội dung với snapshot...${NC}"
    _tmp=$(mktemp -d /tmp/kgc_cdn_verify.XXXXXX)
    if ! curl -sf -m 180 -o "$_tmp/bundle" "$bundle_url"; then
        echo -e "  ${YELLOW}[!] Không tải được bundle để verify (mạng?) — bỏ qua lần này${NC}"
    elif ! python3 "$PROJECT_DIR/scripts/extract_xml.py" "$_tmp/bundle" "$_tmp/x" >/dev/null; then
        echo -e "  ${YELLOW}[!] Extract bundle thất bại — bỏ qua lần này${NC}"
    elif diff -rq "$snap_dir" "$_tmp/x" >/dev/null 2>&1; then
        verify_state="ok"
        echo -e "  ${GREEN}[✓] Snapshot local khớp CDN bundle${NC} ${DIM}(verify theo nội dung)${NC}"
        if [[ "$verified" != "${latest}|${etag}" ]]; then
            echo -e "  ${GREEN}[✓] Snapshot đã khớp lại — republish cũ đã được fetch${NC}"
        fi
        echo "${latest}|${etag}" > "$VERIFIED_FILE"
    else
        verify_state="stale"
        stale_report=$(python3 "$PROJECT_DIR/scripts/cdn_diff_report.py" "$snap_dir" "$_tmp/x" || true)
        echo -e "  ${RED}${BOLD}[★] SNAPSHOT LỆCH CDN: bundle bị ghi đè tại chỗ, local là bản cũ!${NC}"
        echo -e "    ${DIM}verified: ${verified:-"(never)"}  →  CDN hiện tại: ${latest}|${etag}${NC}"
        echo ""
        printf '%s\n' "$stale_report" | sed 's/^/    /'
    fi
    rm -rf "$_tmp"
fi

# ─── Update Detection ───────────────────────────────────────────
if [[ "$latest" == "$last" ]]; then
    if [[ "$verify_state" == "stale" ]]; then
        # Content-mismatch: bundle ghi đè tại chỗ, snapshot local vẫn bản cũ.
        # In MỖI lần chạy (khác cũ: one-shot) đến khi fetch lại.
        # Push chỉ 1 lần/etag — dedup trong push_notify_once.
        echo ""
        echo -e "${CYAN}── Action Items ──${NC}"
        echo -e "  ${YELLOW}▸${NC} Fetch the new pristine snapshot:"
        echo -e "    ${DIM}./kgc-cli config fetch -o /tmp/kgc_xml && ./kgc-cli config extract -o xml_history/${latest} /tmp/kgc_xml/xml_bundle_*${NC}"
        echo -e "  ${YELLOW}▸${NC} Re-base local edits onto it, then rebuild the served bundle:"
        echo -e "    ${DIM}python3 server/builders/rebase_xml_live.py xml_history/${latest} && python3 server/builders/rebuild_xml_bundle.py${NC}"
        push_notify_once "♻️ KGC republish ${latest}" \
            "Bundle ghi đè tại chỗ — snapshot local LỆCH CDN.\n\n$(printf '%s' "$stale_report" | sed -n '1,15p')"
        exit 0
    fi

    if [[ "$verify_state" == "ok" ]]; then
        # Nội dung khớp CDN. Etag lạ chưa ghi nhận (vd: user tự fetch snapshot
        # trước khi script chạy) → đánh dấu handled, không push (không có gì cũ).
        if [[ -n "$etag" && "$etag" != "$notified_etag" ]]; then
            echo "$etag" > "$ETAG_FILE"
            notified_etag="$etag"
        fi
    elif [[ -n "$etag" && "$etag" != "$notified_etag" ]]; then
        # Verify unknown (thiếu snapshot dir / mạng lỗi): push 1 lần theo etag.
        push_notify_once "♻️ KGC republish ${latest}" \
            "Etag đổi ${notified_etag:-"(none)"} → ${etag}, folder giữ nguyên — không verify được nội dung snapshot."
        exit 0
    fi

    echo -e "${GREEN}[✓] No update. CDN is at: ${latest}${NC}"
    echo ""

    # Collect staleness warnings
    stale_warnings=()
    # `<` string so với `!=`: snapshot republish (vd 2026_09_24) NEWER hơn folder
    # CDN (2026_09_22) không phải "behind" — tránh warning sai mỗi ngày.
    if [[ -n "$local_latest" && "$local_latest" < "$latest" ]]; then
        echo -e "${YELLOW}[!] Local snapshot (${local_latest}) is behind CDN (${latest})${NC}"
        echo -e "    Run: ${DIM}./kgc-cli config fetch -o /tmp/kgc_xml && ./kgc-cli config extract -o xml_history/${latest} /tmp/kgc_xml/xml_bundle_*${NC}"
        stale_warnings+=("⚠ Snapshot outdated: ${local_latest} → ${latest}")
    fi
    if [[ -n "$server_patch" && "$server_patch" != "$latest" ]]; then
        echo -e "${YELLOW}[!] Server patchFolder (${server_patch}) is behind CDN (${latest})${NC}"
        echo -e "    Update patchFolder in server/data/response_config.json"
        stale_warnings+=("⚠ Server patchFolder outdated: ${server_patch} → ${latest}")
    fi

    # Send local desktop notification if there are staleness warnings
    if [[ ${#stale_warnings[@]} -gt 0 ]]; then
        # Guard DISPLAY: under cron không có session bus → notify-send spawn
        # dbus-launch fail, spam lỗi vào /tmp/kgc_cdn.log (đã thấy 10-08).
        if command -v notify-send &>/dev/null && [[ -n "${DISPLAY:-}" ]]; then
            notify-send -u normal -a "KGC Watcher" \
                "KGC: Local data outdated" \
                "$(printf '%s\n' "${stale_warnings[@]}")" &
        fi
    fi
    exit 0
fi

# ─── New Patch Detected ─────────────────────────────────────────
echo -e "${GREEN}${BOLD}[★] NEW PATCH DETECTED: ${last:-"(first run)"} → ${latest}${NC}"
echo "$latest" > "$STATE_FILE"
echo ""

# Calculate days since last patch
if [[ -n "$last" ]]; then
    last_epoch=$(date -d "$(echo "${last:0:10}" | tr '_' '-')" +%s 2>/dev/null || echo "0")
    latest_epoch=$(date -d "$(echo "${latest:0:10}" | tr '_' '-')" +%s 2>/dev/null || echo "0")
    if [[ "$last_epoch" -gt 0 && "$latest_epoch" -gt 0 ]]; then
        days_diff=$(( (latest_epoch - last_epoch) / 86400 ))
        echo -e "  Days since last patch: ${BOLD}${days_diff}${NC}"
    fi
fi

# (Section "New Patch Contents (probe)" đã xoá 2026-10-05: path
# xml/ExportedProject/... = 404 — `xml` là object file, không phải prefix;
# section này chưa bao giờ đếm được gì, và ListBucket giờ cũng bị deny.)

# ─── Staleness Warnings ─────────────────────────────────────────
echo ""
echo -e "${CYAN}── Action Items ──${NC}"

needs_action=false

if [[ -n "$local_latest" && "$local_latest" < "$latest" ]]; then
    echo -e "  ${YELLOW}▸${NC} Fetch new XML snapshot (kgc-cli download = APKPure XAPK, sai ở đây):"
    echo -e "    ${DIM}./kgc-cli config fetch -o /tmp/kgc_xml && ./kgc-cli config extract -o xml_history/${latest} /tmp/kgc_xml/xml_bundle_*${NC}"
    needs_action=true
fi

if [[ -n "$server_patch" && "$server_patch" != "$latest" ]]; then
    echo -e "  ${YELLOW}▸${NC} Update patchFolder in server/data/response_config.json:"
    echo -e "    ${DIM}sed -i 's/\"patchFolder\": \"${server_patch}\"/\"patchFolder\": \"${latest}\"/' server/data/response_config.json${NC}"
    needs_action=true
fi

echo -e "  ${YELLOW}▸${NC} Compare with previous patch:"
if [[ -n "$last" ]]; then
    echo -e "    ${DIM}./kgc-cli compare ${last} ${latest}${NC}"
else
    echo -e "    ${DIM}./kgc-cli compare <old_date> ${latest}${NC}"
fi
needs_action=true

if ! $needs_action; then
    echo -e "  ${GREEN}Everything up to date.${NC}"
fi

# ─── Notifications ───────────────────────────────────────────────
echo ""

title="🏰 Cập nhật CDN King God Castle"
latest_fmt=$(echo "${latest:0:10}" | sed 's/_/-/g')

# Build rich ntfy body for community
ntfy_body="Phát hiện bản cập nhật mới trên CDN!\n\n"
ntfy_body+="📅 Phiên bản mới: ${latest_fmt} (${latest})\n"

if [[ -n "$last" ]]; then
    last_fmt=$(echo "${last:0:10}" | sed 's/_/-/g')
    ntfy_body+="⏮️ Phiên bản trước: ${last_fmt} (${last})\n"
    # Days since last
    last_epoch=$(date -d "$(echo "${last:0:10}" | tr '_' '-')" +%s 2>/dev/null || echo "0")
    latest_epoch=$(date -d "$(echo "${latest:0:10}" | tr '_' '-')" +%s 2>/dev/null || echo "0")
    if [[ "$last_epoch" -gt 0 && "$latest_epoch" -gt 0 ]]; then
        d=$(( (latest_epoch - last_epoch) / 86400 ))
        ntfy_body+="⏱️ Khoảng cách: ${d} ngày\n"
    fi
fi

# Bảo Cụ mới/đổi (tên + hero gợi ý + skill) — chỉ chèn khi thật có thay đổi,
# để push trả lời luôn "bảo cụ tên gì, cho ai, skill sao" thay vì chỉ file diff.
if [[ -n "$last" && -d "$PROJECT_DIR/xml_history/$last" && -d "$snap_dir" ]]; then
    tp=$(python3 "$PROJECT_DIR/scripts/treasure_peek.py" "$snap_dir" \
         --new-vs "$PROJECT_DIR/xml_history/$last" --ntfy 2>/dev/null | head -c 900)
    [[ -n "$tp" ]] && ntfy_body+="\n🪙 ${tp}\n"
fi

# (Counts từ probe ExportedProject đã xoá cùng section trên — path 404, chưa
# bao giờ có số liệu; giữ ntfy body gọn.)

# Desktop notification (non-blocking)
desktop_msg="New patch: ${latest}"
if [[ -n "$last" ]]; then
    desktop_msg="${last} → ${latest}"
fi
if command -v notify-send &>/dev/null && [[ -n "${DISPLAY:-}" ]]; then
    notify-send -u critical -a "KGC Watcher" "🏰 KGC CDN Update" "$desktop_msg" &
fi

# ntfy.sh push
if curl -sf \
    -H "Title: $title" \
    -H "Tags: game,kgc,update,new" \
    -H "Priority: urgent" \
    -H "Actions: view, Mở CDN, ${CDN_BASE}/patch/LIVE/${latest}/, clear=true" \
    -d "$(echo -e "$ntfy_body")" \
    "$NTFY_TOPIC" &>/dev/null; then
    echo -e "${GREEN}[✓] Notifications sent (ntfy + desktop).${NC}"
    # success-only: chỉ ghi etag khi push OK → nếu fail, lần chạy sau cùng-folder
    # branch sẽ retry push (tránh mất notification như bug cũ).
    if [[ -n "$etag" ]]; then
        echo "$etag" > "$ETAG_FILE"
        notified_etag="$etag"
    fi
else
    echo -e "${DIM}[ntfy] Push notification failed (network?) — giữ state, sẽ thử lại${NC}"
fi

previous_fmt="(first check)"
if [[ -n "$last" ]]; then
    previous_fmt=$(echo "${last:0:10}" | sed 's/_/-/g')
fi
notify_discord "$(printf '🏰 **KGC CDN update detected**\n**New patch:** `%s`\n**Previous patch:** `%s`' "$latest_fmt" "$previous_fmt")"
