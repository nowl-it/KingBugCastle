#!/usr/bin/env bash
# Capture session accesstoken from the user's own running KGC game (frida-gadget)
# then fetch Strife Battlefield (Colosseum) ranking. Run via:  ! bash scripts/capture_and_fetch_strife.sh
set -e
DEV=localhost:5556
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK=/data/local/tmp/kgc_hooks.js

cat > /tmp/kgc_capture.js <<'JS'
(function(){
 function log(m){try{var a=new NativeFunction(Module.getExportByName(null,"__android_log_write"),"int",["int","pointer","pointer"]);a(4,Memory.allocUtf8String("KGCTOK"),Memory.allocUtf8String(m));}catch(e){console.log("[KGCTOK] "+m);}}
 function hook(){var n=0;["SSL_write","BIO_write"].forEach(function(name){var ad=Module.findExportByName(null,name);if(!ad){Process.enumerateModules().some(function(m){var e=Module.findExportByName(m.name,name);if(e){ad=e;return true;}return false;});}if(!ad)return;try{Interceptor.attach(ad,{onEnter:function(a){try{var l=a[2].toInt32();if(l<=0||l>65536)return;var d=a[1].readUtf8String(l);if(d&&d.toLowerCase().indexOf("accesstoken")!==-1){d.split("\r\n").forEach(function(x){if(x.toLowerCase().indexOf("accesstoken")!==-1)log("HDR "+x);});}}catch(e){}}});n++;}catch(e){}});log("hooked "+n);}
 var t=0,iv=setInterval(function(){t++;if(Module.findExportByName(null,"SSL_write")||t>60){clearInterval(iv);hook();}},200);
})();
JS

echo "[*] backup + deploy capture hook"
adb -s $DEV shell "cp $HOOK ${HOOK}.orig 2>/dev/null; echo ok" >/dev/null
adb -s $DEV push /tmp/kgc_capture.js $HOOK >/dev/null
adb -s $DEV logcat -c

echo "[*] restart game"
adb -s $DEV shell am force-stop com.awesomepiece.castle
sleep 1
waydroid app launch com.awesomepiece.castle >/dev/null 2>&1 || true

echo "[*] waiting for accesstoken in traffic (up to 90s)..."
TOKEN=""
for i in $(seq 1 18); do
  sleep 5
  LINE=$(adb -s $DEV logcat -d -s KGCTOK 2>/dev/null | grep -i "HDR.*accesstoken" | tail -1 || true)
  if [ -n "$LINE" ]; then
    TOKEN=$(echo "$LINE" | sed -E 's/.*[Aa]ccesstoken:[[:space:]]*//' | tr -d '\r' | awk '{print $1}')
    [ -n "$TOKEN" ] && break
  fi
  echo "    ... $((i*5))s"
done

echo "[*] restore original hook"
adb -s $DEV shell "cp ${HOOK}.orig $HOOK 2>/dev/null && rm ${HOOK}.orig; echo ok" >/dev/null

if [ -z "$TOKEN" ]; then
  echo "[!] no token seen. Game may need to reach a login/online screen. Re-run after game fully loads."
  exit 1
fi
echo "[+] token captured (${#TOKEN} chars): ${TOKEN:0:8}...${TOKEN: -4}"

echo "[*] fetching Strife (Colosseum) ranking..."
cd "$ROOT"
source api/.venv/bin/activate 2>/dev/null || source .venv/bin/activate 2>/dev/null || true
KGC_TOKEN="$TOKEN" python3 api/ranking/fetch_strife.py "${1:-1}"
