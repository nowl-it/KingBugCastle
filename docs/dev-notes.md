# Dev Notes - Personal Reverse-Engineering Knowledge Base

> Maintained by opencode for opencode. **Task workflow (user-mandated 2026-08-18):**
> 1. Before any task: check this file first (then AGENTS.md, KNOWLEDGE.md, docs/).
> 2. Already covered → follow it. Not covered → do the work, then update this file.
> 3. Docs wrong → investigate first; only update this file once certain.
>
> Companion files: `KNOWLEDGE.md` = chronological session diary (append at bottom);
> `AGENTS.md` = binary-patch inventory + internals; `docs/` = operator playbooks.

---

## 0. Tooling & conventions (read before anything)

- **Binaries**: `apk/xapk_extracted_*/` (APKs), `il2cpp/<ver>/libil2cpp_*.so` (decrypted),
  `il2cpp/<ver>/script.json` (`ScriptMethod[].Address` = **RVA**, decimal), dumps at
  `/tmp/opencode/kgc_*dump*/out/dump.cs` (may not survive reboots - regenerate with
  Il2CppDumper if missing).
- **RVA vs file offset (ARM64)**: file offset = `RVA - 0x4000`. The 3 SSL patch rows in
  AGENTS.md are **raw file offsets** - everything else is RVA. Never mix.
- **dump.cs `Offset:`** field = `RVA - 0x4000` = raw file offset - matches `patch_apk()`
  conventions 1:1. Method name resolution = grep dump.cs for the class, read the method's
  `RVA: 0x...` line.
- **Tombstone `pc` values are RVAs** - resolve via `script.json`, never dump.cs offsets.
- **Disassembly**: capstone off the raw `.so` at file offset (`so[addr-0x4000:]`).
- **Find callers of a method**: raw-scan for `BL` targeting its RVA: `(w>>26)==0x25`,
  sign-extend `imm26`, `target = site + imm*4`. (How `Scene_Lobby.Update` was found from
  `POST /auth/login` in two hops.)
- **Frida is BLOCKED on redroid** (ndk_translation - `Process.enumerateModules()` never shows
  libil2cpp). Static Ghidra/capstone + logcat/screenshots only. Don't re-attempt.
- **Static-cctor guard pattern** (ignore while reading logic): `ldr w8,[x,#0xe0]; cbnz w8,skip;
  bl #0x2ad08a8` - runtime helper cluster: `0x2ad0774` (ensure static ctor), `0x2ad08a8`,
  `0x2ad09bc`, `0x2ad09c4`, `0x2ad09cc`. The `[x,#0x310]` bools are per-method cctor guards too.
- **Division magics**: unsigned `/5` = `umull x,w,0xCCCCCCCD; lsr #0x22`; signed `/10` =
  `smull x,w,0x66666667; lsr #0x3f; asr #0x21; add` (same magic, shift 33 vs 34 - check the
  shift to tell /10 from /5).
- **`List<T>.Find` in compiled code**: display class allocated via a `bl` helper, captures
  stored at `[disp,#0x10]/[disp,#0x14]`, then `Find(list, disp, null)` - the predicate thunk
  near `0x308xxxx` (v172) reads `[x1,#0x10]`/`[x1,#0x14]` (this.captures) vs `[x0,#0x18...]`.
  `Find` = `0x43cfcb8` (v172.0.01) / `0x43c49ec` (v171.0.00).
- **`List<T>` layout**: `_items` @+0x8, `_size` (`Count`) @+0xc, `_version` @+0x10 (relative to
  the List object pointer - dereference the containing field first).
- **Deck-length invariant**: server deck must be exactly 6 elements
  (`DECK_SLOTS`) - see AGENTS.md "Deck-length invariant".
- **String literals**: `script.json` `ScriptString[].Address` = literal VMAs; methods carry no
  literal refs - find the using method by decompiling, not string search.
- **Offsets move between versions** (v170.0.03 → v171 → v172: every prologue byte-identical,
  offsets shifted). Re-derive per version; never reuse across libs.

### iOS stock-client router capture (RPi4/OpenWrt, verified 2026-09-19)

- RPi4 runs OpenWrt 25.12.5, whose package manager is `apk` (not `opkg`). Topology:
  `eth0` = DHCP WAN on the home network (`192.168.1.0/24`); `br-lan`/5 GHz AP =
  `192.168.2.1/24`; clients receive DHCP/NAT behind the RPi. Do not bridge `eth0` into
  `br-lan`: that leaves the RPi itself without a default route and lets the upstream router
  issue client leases directly.
- Installed packages: `tcpdump`, `curl`, `jq`, `coreutils-base64`, `coreutils-nohup`, and
  `openssh-sftp-server`. SSH alias `rpi4` on the analysis workstation uses a dedicated key.
  No credentials are stored in this repository.
- iPhone has a static DHCP lease at `192.168.2.239` for its per-SSID private MAC. Capture uses
  `ether host <MAC>` on `br-lan` so it includes both IPv4 and IPv6. Commands installed on the
  RPi: `kgc-clients`, `kgc-start [IP-or-MAC]`, `kgc-status`, `kgc-stop`.
- PCAPs live under `/tmp/kgc-capture` (RAM), not the ~87 MB OpenWrt overlay. `tcpdump` rotates
  ten 25 MB files (250 MB maximum). They intentionally disappear on reboot. Copy them with
  `scp rpi4:/tmp/kgc-capture/iphone_mac.pcap0 ...`; SFTP support is installed, so modern `scp`
  needs no legacy `-O` flag.
- Verified force-close/reopen official-client capture: 3,056 packets / 2.1 MB / zero drops.
  Official endpoints observed: `kgc-k8s-1.awesomepiece.com` → `34.144.251.178` (main API),
  `kgc-cdn-1.awesomepiece.com` → `34.116.0.13`, and
  `kgc-ranking-1.awesomepiece.com` → `34.117.208.203`. DNS and TLS/QUIC metadata are visible;
  HTTPS application request/response bodies remain encrypted on a stock non-jailbroken iOS
  client. The two plaintext HTTP requests seen at `13.113.122.221/x2/xls.cgi` were unrelated
  telemetry, not KGC API data.

### iOS MITM attempt: game is SSL-pinned, bodies unreachable (tested 2026-09-19)

To read request/response BODIES you need HTTPS interception. Tried the standard iOS setup:
mitmproxy 12.2.3 in regular-proxy mode on the PC (`mitmdump --listen-host 0.0.0.0
--listen-port 8080 -w flows.mitm`), iPhone Wi-Fi proxy → PC:8080, mitmproxy CA installed as
an iOS profile with Full Trust enabled (Settings → General → VPN & Device Management →
install profile, then General → About → Certificate Trust Settings → Full Trust).

Results (mitmdump log, `kgc-k8s-1.awesomepiece.com` on `34.144.251.178`):

```
[client connect] ... [server connect kgc-k8s-1.awesomepiece.com:443 (34.144.251.178:443)]
[85ms later] Client TLS handshake failed. The client disconnected during the handshake.
```

- The game DOES honor the iOS system proxy: mitmproxy saw `client connect` + a real
  `server connect` to the KGC host. Only the TLS handshake was rejected by the client.
- The OS/Safari/ads/Apple flows all MITM-decrypt fine (proxy + CA pipeline is correct), so
  the rejection is the game's own certificate validation, not our setup.
- Conclusion: **the iOS KGC client pins/self-validates its TLS certs (same
  PinnedCertHandler / UnityTlsProvider.ValidateCertificate family the Android build needed
  binary patches for) and ignores the OS trust store. On a stock, non-jailbroken iPhone the
  API bodies are unreadable from the wire - DNS/SNI/IP/conversation metadata only.** The game
  hangs at the awesomepiece logo while the proxy intercepts, because its `usePatch`/login
  (`POST /auth/...` on kgc-k8s-1) can't complete. Turn the proxy Off on the iPhone to restore
  normal gameplay (the installed CA profile is inert without the proxy).
- Setup notes: don't rely on `apk add py3-pip` (OpenWrt 25.12 names it `python3-pip`; Python
  3.13.9 has no `ensurepip`). mitmproxy ≥ 12 needs the Rust `mitmproxy-rs` wheel, which has
  no aarch64-musl build - installing mitmproxy on the RPi4 fails; run it on the PC instead.
  DNAT-to-another-host does NOT work for transparent mode (proxy loses SO_ORIGINAL_DST), so
  if a transparent MITM is ever needed it must run on the RPi4 itself (REDIRECT + local
  listener) - which currently can't host mitmproxy (see above).

- **Full pinning map (test B, 2026-09-19, same session):** with mitmproxy running regular
  proxy mode + the iPhone's system proxy pointed at it, the host-by-host result is:

  | KGC host | Transport | Result |
  |---|---|---|
  | `kgc-k8s-1.awesomepiece.com` (API: /auth, /pvp/*) | TCP:443 TLS | **pinned** - client rejects our CA, handshake dead in ~85 ms |
  | `kgc-cdn-1.awesomepiece.com` (patch/CDN assets) | TCP:443 TLS | **pinned** - same rejection (3 retries, all failed) |
  | `kgc-ranking-1.awesomepiece.com` (leaderboard) | QUIC/HTTP3 natively; **TCP:443 when a system proxy is set** | **pinned** - with the proxy on, the game falls back to TCP CONNECT and rejects the CA exactly like the other two (confirmed 2026-09-19, mitm_d run: 3 tries at `21:40:10`, all `Client TLS handshake failed`) |

  Native (no-proxy) operation uses QUIC, which mitmproxy cannot MITM; with a system proxy
  configured the client downgrades to TCP, which proves pinning there too. **All three
  awesomepiece hosts are unreachable for body inspection on a stock iOS client.** Route
  enumeration workspace: `kgc-ranking-1` → `34.117.208.203`, all QUIC Initial/Handshake
  packets in the pcap are to this IP. `--ignore-hosts "kgc-k8s-1\.awesomepiece\.com|kgc-cdn-1\.awesomepiece\.com"`
  lets the game boot normally while everything else is still MITM'd (SDK/ads/analytics flows
  decrypt fine and are visible in the log) - a useful isolation trick if a future question is
  ever "which non-game host does the client cleanly talk to". The game is v173.0.00
  (`an=173.0.0.iphone.com.awesomepiece.castle` in the AdMob request).

### v173.0.00 private-client port (verified 2026-09-13)

- Stock inputs: `apk/xapk_extracted_v1730/`; recovered game code:
  `il2cpp/v173.0.00/libil2cpp_v173.so`; matching metadata and dump live beside it.
- `build_private.py` defaults to v173 and selects `_NRE_STUBS_V17300`. The rotating NEO loader is
  `libbisedich.so`; its eight guarded branch sites are file offsets `0x43914`, `0x4391c`,
  `0x43924`, `0x43954`, `0x43ae0`, `0x43b24`, `0x43b40`, `0x43b50`; the four parser-return sites
  are still found by the guarded `08008012 e89700b9` pattern. All 12/12 matched during a real build.
- v173 SSL raw file offsets are `0x2D24844`, `0x5A02FA8`, `0x5A016B8`.
  `python3 server/patchers/make_ssl_so.py 173.0.00 --check` verifies the generated SSL-only copy.
- Full local share build completed as `KingBugCastle_173.0.00.xapk` (1,209 MB). Archive test passed;
  all three APKs verify with the same v2/v3 debug certificate; base and both split manifests report
  `com.nowl.castle`; base reports version `173.0.00` and label `King Bug Castle`.
- Build verification: 95 server tests pass, local mods are idempotent, and route coverage is
  `355/355`. A clean redroid install registered a guest, completed the tutorial battle, fetched the
  full lobby chain with HTTP 200, logged `HookedLobbyAwake EXIT`, and rendered the lobby correctly.
- The first runtime attempt failed in `ResourceManager.LoadMultiThread` after downloading `xml`.
  Cause: `refresh_master_data.py` rebuilt the new XML files into the previous v172 AssetBundle;
  replacement cannot add new TextAsset objects, so all four v173 Pick-and-Pass tables were absent
  (141 non-empty assets vs 145 after the fix). The refresh now copies the newly fetched official
  bundle over `real_cdn/xml` before replaying `xml_live`; the rebuilt v173 bundle replaces all 147
  TextAssets and preserves the new object table. Always restart both uvicorn processes and clear the
  app's UnityCache after rebuilding because CDN bytes are cached at server import and on-device.
- Apktool's Java process ignores `TMPDIR`. On a nearly full `/tmp` tmpfs, `aapt2 link` misleadingly
  fails with `failed to write AndroidManifest.xml to archive: Invalid entry name`. Set both
  `TMPDIR=<workspace>/.tmp` and `JAVA_TOOL_OPTIONS=-Djava.io.tmpdir=<workspace>/.tmp`; the same stock
  resources then rebuild successfully. This is a local disk-space failure, not malformed v173 data.

### v173.1.00 private-client port (verified 2026-09-24, build runtime-OK)

- Stock inputs: `apk/xapk_extracted_v1731/` (from `com.awesomepiece.castle@173.1.00-arm64.xapk`,
  versionCode 1133, arm64 split only). Recovered game code: `il2cpp/v173.1.00/libil2cpp_v1731.so`;
  matching metadata + dump + script.json live beside it. All offsets below were re-derived from this
  build's own script.json by exact `ScriptMethod[].Name` match (namespace included, e.g.
  `Awesomepiece.Web$$GetRankingServerEndPoint`) and verify against the v173.0.00 table 11/11.
- `build_private.py` defaults to `xapk_extracted_v1731`, selects `_NRE_STUBS_V17310`, and uses the
  same NEO table as v173.0.00: the v173.1.00 packer `liberallisi.so` (SONAME `libappsign4a.so`) is
  byte-identical to v173.0.00's `libbisedich.so` at all 8 guarded branch sites + the 4 parser-error
  sites (`08008012 e89700b9` x4). Build NOPed 12/12 during a real run.
- v173 SSL raw file offsets: `0x2D33B44` (PinnedCertHandler), `0x5A1E9C4` (UnityTlsProvider),
  `0x5A1D0D4` (MobileTlsContext). Regenerated via `make_ssl_so.py 173.1.00`; `--check` clean
  (3 patches + anchor + zero stray bytes).
- NRE stubs (RVA; file = RVA - 0x4000): pvp-init `0x32E4EA0`, pvp-reward `0x32DFAD0`,
  shop-growth `0x3352448`, shop-season `0x3354584`, year-event `0x30E0B30`, card-event `0x30E2DC4`,
  season-event `0x30E2CBC`, babel-data `0x30C7BAC`, content-alert `0x35392BC`, accessory
  `0x30EDEB4` (RET_TRUE), ranking-endpt `0x2D37F58`. Specials: firebase-check file `0x30C6D50`,
  RegisterHackDetection file `0x3568CA8`, canUseFirebase gate file `0x3798E14` (fingerprint
  `080140f9880200b408e14839c8010034`, tail-call dispatch → `0x37EB890`), LogEvent file
  `0x37EB890` + `0x37EB8F4`, CRC getter file `0x60CA5BC` (orig `001840b9c0035fd6` = the real
  `get_Crc`), CRC reads `0x60CCB30`/`0x60CAA48`/`0x60CAB38`, ShopItem.Init file `0x3363E24`
  (ORIG `941300b468ac01f0080945f9f60300aae00314aae1031f2a020140f9e1ca3394`; both cbz
  displacements +0x254/+0x24C match v173.0.00, final `bl` → `e1ca3394` = #0x40569C4).
- Share build completed as `KingBugCastle_173.1.00.xapk` (1,209 MB), host baked 127.0.0.1 for
  adb-reverse local play. Server working tree (T1/T2 commits `9457c65` + `3d0e913`) sets
  `VERSION=173.1.00` + `serverVersion=173.1.00` so gated Gacha/Shop content goes live.
- **"Failed to connect" & "Loading resources" hang - AES Zero Padding & CheckFirebase Typo (2026-09-25):**
  - **AES Zero Padding**: The v173.1.00 client's `Utility$$AESDecryptWithServer` now explicitly configures `PaddingMode.Zeros` (`mov w1, #3` into `SymmetricAlgorithm.set_Padding`). The server previously used Space padding, which `PaddingMode.Zeros` does NOT strip. This caused Newtonsoft JSON to throw `JsonReaderException` on the trailing spaces, resulting in "Failed to connect" errors (e.g. after `/auth/getPatchFolder`). Fixed by updating `server/crypto.py` to pad AES payloads with `\x00`.
  - **CheckFirebase Typo**: `build_private.py` had a typo for `CHECKFIREBASE_OFF` (`0x30C8D50` instead of `0x30C6D50`). This caused the patch to miss `GameManager.CheckFirebase`, leading to a fatal GMS init crash on Redroid when downloading resources. Fixed the offset so `CheckFirebase` is properly stubbed to `ret`.
- **"Loading resources" hang - `GetDevServers` AES mismatch (2026-09-25):**
  `Scene_Login.Awake` calls `RestAPI.GetDevServers()` which hits
  `http://127.0.0.1/api/cloud-run/services?location=asia-northeast3` (endpoint rewritten from
  `INFRA_SERVER_URL = https://castle-infra-server-65408603887.asia-northeast3.run.app` by
  `patch_hosts` + `patch_metadata_http` + `patch_leftover_hosts`). The coroutine
  (`<GetDevServers>d__437.MoveNext`, RVA `0x2D04250`) calls `Web.Get<T>` overload **d__15**
  (RVA `0x50AA460`, signature `Get<T>(endPoint, uri, List<(string,string)> customHeaders,
  bool useSystemSerializeFunc)`) which reads raw `DownloadHandler.data` → UTF8 decode →
  `JsonConvert.DeserializeObject`. This overload does **NOT** call `DecryptResponseBody`. But
  the generic `respond()` path in `server.py` AES-encrypts every response. The client receives
  AES ciphertext, UTF8-decodes it (producing `U+FFFD` for invalid byte sequences), and throws
  `JsonReaderException: Unexpected character ... position 0`. Fix: serve `/api/cloud-run/services`
  and `/api/cloud-run/default-ranking` as direct `JSONResponse` routes registered before the
  `ROUTE_MODELS` loop. The `ServerListResponse` model (`base: null`, not a `ResponseModel`)
  carries only `serverList: ServerData[]` (`{name, url, cachedInfo}`). Also note:
  `GetDefaultInfraRankingServer` (`<d__438>`, RVA `0x2D03CF4`) uses the same infra endpoint
  with URI `/api/cloud-run/default-ranking?location=asia-northeast3&useReplica={0}` and the
  same non-AES `Web.Get` overload. Both routes need the plain-JSON treatment.

---

## 1. Invasion rewards - COMPLETE decode (2026-08-18)

User client is **v171.1.00** (no dump exists; v171.0.00 dump + v172.0.01 dump/binary are the
proxies - panel absent in v171.0.00, added by v171.1.00; GameManager API identical).

### Client contract

- `InvasionRewardDatasResponseModel{RewardData rewardDatas}`;
  `RewardData{int index@0x10, int pass@0x14, long rewardState@0x18}`.
  Rewards themselves come from CDN `InvasionRewards.xml` (flat IDs, `divmod(rid,100)`,
  200 rows: themes 1-20, 51-70 × 5 difficulties) - the response carries **only claim state**.
- **`ThemeIdToPassIndex(theme)`** (v172 `0x33ECF4C`, v171.0.00 `0x33E3460`):
  `theme<=50 → 2*((theme-1)//10)`; `theme>50 → 1+2*((theme-51)//10)`.
  10 themes share one index: 1-10→0, 11-20→2, 51-60→1, 61-70→3.
- **Panel pass per theme** (`GetStartEndThemesByPassIndex`, v172 `0x33ECDF4`):
  pass 0=[1,5], 2=[6,10], 4=[11,15], 6=[16,20], 1=[51,55], 3=[56,60], 5=[61,65], 7=[66,70].
  Formula: `t<=50 → 2*((t-1)//5)`; `t>50 → 1+2*((t-51)//5)`. `ThemePerPass = 5`;
  `GetPassCount` = `ceil(r0/5)+ceil((r1-50)/5)` → 6 tabs with 11/61 records.
- **`GetInvasionRewardData(theme, pass)`** probe (v171.0.00 `0x304ED40`): finds the FIRST entry
  with `entry.index == ThemeIdToPassIndex(theme) && entry.pass == pass`.
- **`InvasionRewardReceived(theme, difficulty, pass)`** (v171.0.00 `0x304EC74`, v172 `0x3055F6C`):
  probe entry, then bit `(difficulty-1) + 5*((theme-1)%10)` of `entry.rewardState` (bit test via
  `RewardData` method `0x3716560` v172). **Bit layout is 5 bits per theme inside the entry.**
- **`HandleInvasionRewardReceived(theme, pass, rewardState)`** (v172 `0x305612C`): probe, then
  `entry.rewardState = rewardState` (wholesale overwrite - sibling themes transiently wrong until
  re-fetch; that's the real game's behavior too).
- **`GetInvasionRewardDatasByPassIndex(pass)`** (v171.0.00 `0x304EE50`): entries with
  `entry.pass == pass` (b__0 v172 `0x308A978`).
- **`HasInvasionPass(passIndex, pass)`** (v171.0.00 `0x304EB98`, v172 `0x3055E90`):
  `Find(entry.index == passIndex && entry.pass == pass)` (b__0 v172 `0x308A8F0`).
- **`GetReceivableRewardCount(passIndex)`** (v172 `0x33EDB40`; the panel tab badge):
  - 25 rows: `theme = base + r/5`, `difficulty = r%5`, `base = (odd?51:0) + 5*(pass//2)`
    (v172.0.01 base is 0-based → theme 0 for pass 0 - its own quirk; v171.1.00 counts 1-based).
  - gate: skip row unless `GetInvasionClearedDifficulty(theme) > difficulty`
    (`0x30568B8` v172 = `records.First(t.theme==theme).difficulty` via Find, null → 0).
  - then: `entry.pass == 0` → count (pass-0 shortcut) **or** `HasInvasionPass(P, entry.pass)`
    → count - the count needs an entry `{index: P, pass: P}` for every pass P ≥ 2!
  - count only if NOT `InvasionRewardReceived(theme, difficulty, entry.pass)` (bit clear).
  - **Symptom of wrong shape**: all entries deserialize `{0,0,0}` → only pass 0 counts
    (25 on Part 1, 0 everywhere else) - exactly the user's report.

### Server response (the fix, shipped 7b84fc5, `server/routes/challenge_routes.py`)

`GET /invasion/reward` (no `theme` in body) returns 16 entries, normal-first, markers last:
1. **8 group entries** `{index: TI(t), pass: P(t), rewardState}` - one per (TI, pass) group,
   mask = OR over the group's 5 themes of `st_mask[t] << (5*((t-1)%10))`.
2. **2 pass-1 entries** `{index: 0|2, pass: 1}` for themes 1-20 (pass-reward display/claim).
3. **6 markers** `{index: p, pass: p, rewardState: 0}` for p = 2..7 - make
   `HasInvasionPass` true. Passes 0 and 1 need none (shortcut / own group entry).
   Do NOT add {0,0}/{1,1} markers - they'd shadow the real entries (same probe key).

Claim POST (`theme` present): `{rewardListData, rewardState: st_mask[theme] << (5*((theme-1)%10))}` -
the offset matters, the client bit-tests at `(d-1)+5*((theme-1)%10)`.

Server helpers: `_invasion_pass_index`, `_invasion_pass_of`, `_invasion_entry_mask`.
State key: `st["invasionRewardState"][str(theme)]` = per-theme 5-bit mask (bit `d-1`), set by
`_invasion_claim` regardless of `pass` (normal + pass claims share one bit - deliberate
simplification). Tests: `server/tests/test_invasion_reward.py` (run with `python3
tests/test_invasion_reward.py` - the `check_*` functions are not pytest-collected).

---

## 2. Weekly ranking / eliteRankingScore (2026-08-14/18)

- Score submission = `eliteRankingScore` (long, field offset 0xC8) inside `POST /game/complete` -
  **no separate score POST**. `RestAPI.AddRanking` only fires from a debug button
  (`SettingsPanel.<OnClickTestRanking>`). The ranking-stage battle ("Measure Combat Power")
  computes `GetRankingScore` (v171 `0x2d70230`) → stored → complete request carries it.
- `r_game_complete` stores best in `st["eliteRankingScore"]`; `r_ranking` prefers it, falls back
  to `bestClearedTheme*100+bestClearedStage`. Test: `check_elite_score_flows_through_game_complete`.
- No `ranking*` string literals in v171/v172 `.so` - API paths are static fields; **the TLS log
  (`/tmp/kgc_pub_tls.log`) is the source of truth for what the client calls**.
- `GetRankingServerEndPoint()` patched (v172.0.01 file `0x2CBB2C4`) to return `Web._endPoint`
  (127.0.0.1) instead of the cloud-run URL.
- Leaderboard roster safety in `roster.py`: `deck_units` (6, pad with
  `[10000,10010,10020,10030,10040,10050]`), `rank_row` (never-null names), `playerRank` always
  populated for the caller. Empty fallback model → `RankingPanel` NRE - routes must return
  populated rows.

### Original-server seasonal boards (verified 2026-08-24)

- Production ranking host: `https://kgc-ranking-1.awesomepiece.com` (not the main
  `kgc-k8s-1` API, which returns 404 for `/ranking/*`). Direct unauthenticated requests with
  header `version: 172.0.01` reach its auth layer and return `401 WrongTokenError`; stale
  `169.1.05` returns `403 NotLatestVersion`. The same applies to `172.0.00`.
- Current season must be read with the same account session: `GET /pvp/info` for Arena and
  `GET /colosseum` for Strife. Use their `season` field respectively in:
  `GET /ranking/pvp-ranking?season=<n>&useCache=true` and
  `GET /ranking/colosseum-ranking?season=<n>&useCache=true`.
- Auth is the client header `accesstoken`, not `Authorization: Bearer`; preserve a current
  client `version` header. `api/ranking/fetch_seasonal.py` reads both season values and fetches
  both boards with `KGC_TOKEN=<accesstoken>`; set `KGC_VERSION` only when using a different APK.
- Infra discovery `GET https://castle-infra-server-65408603887.asia-northeast3.run.app/api/cloud-run/default-ranking?location=asia-northeast3&useReplica=false`
  currently returns a `qa-ranking-default` Cloud Run URL. It produced HTTP 500 for direct board
  reads in this check, so do not substitute it for the verified production ranking host.

### Guest token automation vs XIGNCODE gate (verified live 2026-08-24)

Probed against production `kgc-k8s-1` (main API has no version WAF - old `170.1.00` /
`169.1.05` headers are still accepted there, unlike the ranking host):

- `POST /auth/register` `{type:4, id:"", userName, castleName, kingPostfix:1, castlePostfix:1,
  version:172001}` works unauthenticated and returns the account's `loginId`
  (server-assigned, shape `Guest_` + 10 uppercase alnum). **Arbitrary names are rejected**
  (`code:400 WrongKingName`, e.g. "Guest1234"); random 8-char uppercase+digits passes.
  The v170-era "register returns accessToken" behavior is **gone** - v172 always answers
  `accessToken: null`, regardless of client version headers.
- Every token-issuing endpoint requires a valid XIGNCODE cookie and answers
  `401 WrongTokenError` without one: `/auth/auth?id=<loginId>&version=…&cookie=` (alias
  `/auth` → `code:410 Fail` for these ids), `/auth/xcd?cookie=`, `/auth/login`. Fake cookies
  fail identically. `/auth/xcdSeed?version=` works unauthenticated and returns the seed for
  the native SDK. Conclusion: tokens cannot be minted outside the genuine client.
- Working pipeline: harvest a token from a real session with the passive addon
  `api/auth/token_harvester.py` (`mitmdump -s api/auth/token_harvester.py`, tap Guest login
  once in the stock client → writes repo-root `captured_token.txt` + `captured_guest.json`)
  → `api/ranking/fetch_seasonal.py` auto-loads it. `api/auth/guest_login.py` scripts
  register / id-reuse / seed fetch but stops at the XIGNCODE gate by design. Two probe
  accounts (`Guest_D27R24JK8S`, `Guest_2HWUF68893`) remain registered on official from these
  tests - there is no delete endpoint without auth.

## 3. Daily reset (2026-07-31)

`tomorrow` must be **derived** (`next_reset_iso()` - next UTC midnight, `+7d` for `nextWeek`),
never stored: `Scene_Lobby.Update` (RVA `0x34EA5F0`+) re-runs the whole login chain at 1 Hz when
`now >= tomorrow_` (`PlayerDataResponseModel.tomorrow` @ 0xD0). A past value = constant
re-login loop, 17 req/s, NO exceptions. Test: `server/tests/test_daily_reset.py`.
Fixed-period loops with no exception = client timer, not retry.

## 3a. Discord CDN monitor (2026-08-24)

- `scripts/check_cdn_update.sh` owns update detection; it invokes
  `server/discord_notify.sh` only for a new CDN folder, an in-place XML republish, or a newly
  observed store APK version. No-change and local-staleness results must stay quiet.
- The notifier posts with the existing Discord bot to channel `1541439188686213221`. Its bearer
  token is a single line in ignored `server/secrets/discord_bot_token` (or `DISCORD_BOT_TOKEN`),
  never a tracked config value.
- `systemd/kgc-cdn-monitor.service` runs `scripts/run_cdn_watcher.sh` as a user service. The
  wrapper posts one online message on start, checks immediately, then sleeps 1800 seconds.
- **2026-08-25 format fix:** Bash does not turn `\n` inside ordinary double quotes into line
  breaks. Build the Discord content with `printf`, so it contains real newlines; normalize both
  folder dates from `YYYY_MM_DD` to `YYYY-MM-DD` before sending.
- CDN `2026_08_25` was refreshed with `refresh_master_data.py`: 22 local files were rebased,
  all five `local_mods` replayed without warnings, and `response_config.json` now advertises
  that patch folder. The rebuilt XML hash is `ef2d0d9c2c26a5a1cb8a3bfc5d001266_4031397`.
- Pristine `2026_08_13 → 2026_08_25` delta is six files: new v173.1-gated Mystic treasure
  `30043` (Vitacorde, for unit `10060`), its buffs/visual skill, a guard-duration metadata fix
  for accessory synergy `10082`, `Unit10390AI` assigned to Rie (`10390`), and KR-only upcoming
  Pick-and-Pick mode text. Pristine `30043` has `MinVersion=173100`; local_mods lowers it to
  `172001` for the deployed v172.0.01 client.
- `FetchComplete` is a deliberate private-server loading-text override: "Ready to bug! Starting
  the fix now!" and 12 locale equivalents. The `2026_08_25` refresh reset it to the official
  text; `_apply_fetch_complete` in `server/local_mods` restores all 13 versions idempotently.
- **2026-09-08 CDN snapshot:** pristine bundle md5 `d06f765ad4c726d545c96d57f152310c`
  (4,689,193 bytes), extracted to ignored `xml_history/2026_09_08`. The previous official base is
  `2026_08_25`; local `patchFolder=2026_09_05` came from the v172.1.00 client build and is not an
  official CDN folder. Semantic pristine diff `08_25 -> 09_08`: 40 files (36 modified + 4 new).
  Main content is Season 73 Harvest Moon Festival: pass 73, map/login skins, advisors 40070/40080,
  skins 1059003 (Dandelyn) and 1074001 (Suha), event shop/packages, Rift season 73, Arena/Strife
  season 73 data, and permanent dimension gacha 8500 (pool 10780/10790/10800). The new Pick and
  Pass mode adds theme 1003, stages 103000-103005, 117 draft definitions, 78 unit options, four
  item options, nine devil offers, and four new XML tables. Other fixes include Arena opponent
  reroll limits/prices, Colosseum trigger 160131 `80050 -> 80030`, D.Ophelia chroma effect mappings,
  rift-gauge ad charging, and corrected Vitacorde description parameters. Most new playable/store
  rows require client `173000` or `173100`; do not assume v172.1.00 can consume them merely by
  lowering XML gates because Pick and Pass introduces new client-side models. A trial replay of all
  `local_mods` completed with 30 writes and zero warnings; the served bundle was not changed.
- Official v173.0.00 notice `3d51c2e0-6f0e-81ac-a15e-f5a1fc736f88` confirms the Season 73
  schedule, Pick and Pass, both new skins, package contents, Arena reroll schedule, gacha rates,
  and Swift/North Rift effects. Its Rift paragraph says "Season 74 Seasonal Effects", but the
  surrounding section and `DimensionRiftSeasonDatas.xml` ID 73 show this is a notice typo. Full
  Vietnamese comparison: `docs/master-data-2026-09-08.html`.
- **2026-09-10 in-place republish of CDN folder `2026_09_08`:** bundle md5/etag changed from
  `d06f765ad4c726d545c96d57f152310c` to `194b61a19e71f67c77f802fd02e21741`
  (4,684,494 bytes). Only the 13 `Strings_*.xml` files changed; all gameplay/master-data tables
  are byte-identical after line-ending normalization. Devs removed 19 leaked placeholder keys for
  the unreleased `Cor Orbis` treasure (`50002` / buffs `350002x`) from every locale, corrected
  package names `1690..1692`, and added `1693` for the Sep 10-23 treasure pickup (Meirna `30014`
  and Tome of Tides `30024`). AR instead drops the stale package keys and adds its three missing
  Pick-and-Pass devil reward strings; JA/ZH add rich-text spacing to those same rewards and make a
  formatting-only `SkinShop` change. Trial replay of all `local_mods` completed with 30 writes and
  zero warnings. The served bundle was not changed during this investigation.
- **2026-09-22 CDN folder `2026_09_22`** (new slot; `response_config.json` was switched to
  advertise it):
  - Pristine snapshot extracted to ignored `xml_history/2026_09_22` (147 files). Diff vs the
    `2026_09_08` snapshot = **4 master-data files + the 13 Strings_*.xml**, everything else
    byte-identical (no new/removed files).
  - The older `2026_09_10` republish (Cor Orbis `50002` key purge, package `1690..1692` renames,
    package `1693`) is already folded into the served bundle, so what is genuinely NEW in `09_22`
    was isolated by checking which rows/keys the served `xml_live` already had:
    - **ShopItems `200`/`202`/`210` → `<IsUnavailable>true</IsUnavailable>`** - the cash storefront
      for heroes/skins (direct hero buy, buy-hero-when-skin-owned, unit-skin buy). `Unit`+`Skin`
      rows only; the PassUnit row `201` stays available.
    - **Gacha `9000` (WelcomeGacha, new-player summon) → `<IsUnavailable>true`**.
    - **Skills `102650..102653` nerf (~-14.3% all 4 tiers)**: 청아 (unit 10260) ultimate
      "2식 청룡참" (2nd-form Azure Dragon Slash) Damage/MAtkPer 350→300, 420→360, 490→420, 560→480.
      The unit row is unchanged - only the tiered skill numbers moved.
    - **Advisors `40070`/`40080`** (Season 73 Harvest-Moon rabbit advisors): `SpriteOffsetY -8 → 0`.
    - **Strings**: orphan key `RedValve ` (trailing space) renamed `RedValve`; 11 unused keys
      dropped (`ArtifactOptionProbUrl`, `AtkPerByRange(+_Piece)`, `MoveStopTimeDesc(+_Piece)`,
      `RiftWeaponBuffDesc_160`, `SeasonalEvent(+CeilFormat+NumberFormat)`, `SimplifyAISaveData`,
      `AccessorySynergyDesc_10091`); 3 placeholder `ItemDesc_10030/31/32` = "+5/+10/+20 Silver"
      (no `InventoryItems` row references them yet); KR-only `UnitGachaPickupCountFormat` added.
      34 EN values differ but are all trailing-space/newline padding noise (Localizer line-break
      padding) - no gameplay text edits.
    - Net read: a balance/cleanup hotfix (hero-ultimate nerf + cash storefront shutdown), no new
      content, no season/Strife data changes. `ColosseumRankScoreTable/Tiers` identical to `09_08`,
      so the Strife score math below is unaffected by this update.
- **2026-09-23 in-place republish of CDN folder `2026_09_22`:** bundle etag changed from
  `7d08aeb133fb7bff9008055ff6c8c106` to `5a6d7db2aeb8d932684548b53761741b`.
  Diff vs initial `2026_09_22` snapshot:
  - **TreasureBuffDatas.xml**: Vitacorde (treasure `30043`, for Alberon `10060`) buffed:
    - BuffData `3300431`: `DefDenNoLevel` MAtkPer `10 → 20` (protection scaling doubled: `0.1% → 0.2%` MAtk per Guard).
    - BuffData `3300435`: `DefDenNoLevel` MAtkPer `20 → 40` (overcome increment `0.1% → 0.2%`, cumulative `0.2% → 0.4%`).
  - **Strings_*.xml (all 13 locales)**:
    - `Potential_10260_2`: Chung Ah potential 2 final damage nerfed `+40% → +20%` (matches her ultimate skill nerf).
    - Restored the 11 keys dropped in initial `09_22` (`ArtifactOptionProbUrl`, `AtkPerByRange`, `MoveStopTimeDesc`, etc.).
    - Removed stale placeholder keys `ItemDesc_10030..32` (+5/+10/+20 Silver).
    - Added new keys across all locales: `BlessedTreasure` ("Blessed Legacy" / "축복받은 유산"), `PlayReward_Semi1`/`PlayReward_Semi2` ("First/Second Half Reward"), `PlayRewardPlayCountFormat` ("({0}/{1}) Plays"), `UnitGachaPickupCountFormat`.
    - Rich-text padding cleanup (`<size=2> </size>`) across Asian locales (JA, ZH_CH, ZH_TW).
- **2026-10-06 CDN folder `2026_10_06_xGrY0WbLgR` (v174.0.00) - treasure audit 2026-10-08:**
  pristine extracted to `xml_history/2026_10_06_xGrY0WbLgR` (150 files); served
  `response_config.json` still advertises `2026_09_22` (refresh not yet run).
  **No new treasure.** `Treasures.xml` + `TreasureBuffDatas.xml` are byte-identical to
  `2026_09_24b` (still 62 rows: `30000..30043`, `50000`, `50001`; no `330044x` buffs), and the
  set of `Treasure*_[id]` keys across all 13 `Strings_*.xml` is unchanged (434 -> 434, zero
  added/removed; no `TreasureName_30044` anywhere). No `<Reward Type="Treasure">` cites an id
  above `30043`. Treasure-adjacent deltas: new GachaPools `230057`/`231057` = **double pickup of
  existing `30002` (Sacramentum) + `30009` (Rain of Fire)** (`IncompatibleWithPermanentPool`
  false); `InventoryItemDesc_SelectableTreasureBox` added to item/box `5603` (box contents
  unchanged: 30002/30007/30015/30017/30022/30030); `BlessedTreasure` string dropped; ShopItems
  `590/591/592` moved into the new `ShopItems_deprecated.xml`; `EarlyAccessModeInfos` early-access
  test loadouts cleared (incl. test treasure `30017`); 14 new `RewardBoxInventoryData` rows
  (47->61), none treasure-typed. New files overall: `ShopItems_deprecated.xml`,
  `SingleArenaSettings.xml`, `Videos.xml`.
  **Unity (v174 export `unity/kgc-rebuild`)**: treasure art ids cover `30000..30044` +
  `50000/50001`, still no `50002` art. `30044` has the full 18-file UI set but **deliberate `!`
  placeholder pixels** (illust mean RGB 6/255; icon = black hexagon + white exclamation, verified
  by crop), no `Fx_Treasure_30044`, no buffs/text - it is the next regular slot, already
  registered since v172.1.00 (see the Cor Orbis section), not new in v174.

### Reference-derived Frieren idle sheet (2026-08-24)

- `server/assets/frieren/frieren/idle_2x2/` contains a standalone four-frame (`2x2`) pixel-art
  idle loop derived from `Illustration_1040.png`. It is an auxiliary generated asset, not the
  production `Unit_10570_03` atlas or a replacement for `rebuild_frieren_sprites.py`.
- Strict processing passed: no source/output edge contact, empty or clamped frames; body-scale CV
  `0.0103` and anchor-Y std-dev `0.0332` (limits `0.08` / `0.05`).

### Pixelorama Frieren single-sprite refinement (2026-08-25)

- Source: `server/assets/frieren/frieren/Frieren KGC Sprite.pxo` is a Pixelorama `60x76` one-frame,
  one-layer draft based on `Illustration_1040.png`. The `.pxo` stores raw RGBA at
  `image_data/frames/1/layer_1` (`60*76*4` bytes) plus an 8x `preview.png`.
- `server/assets/frieren/frieren/refine_frieren_sprite.py` is deliberately conservative after the
  first over-processed attempt looked muddy: it preserves every source color/pixel cluster and only
  clears edge-connected near-black background to alpha. It writes both the legacy refined filenames
  and explicit `alpha_clean` filenames, including `Frieren KGC Sprite alpha clean.pxo`. It does
  **not** replace the original `.pxo`.
- The optional `Frieren KGC Sprite color pass.pxo` is a separate, localized material pass: opaque
  dark fill clusters (not only pure black) become dark violet (clothing/collar), cold lavender
  (hair), warm brown (staff metal), warm skin shadow, or boot shadow. It raises only lavender,
  gold, and red chroma; the white robe, skin, eyes, original canvas size, and hard alpha remain
  intact. The only pure-black pixels left are the eye/eyelash cluster. It is a revision candidate,
  never a replacement for the original draft.
- For subsequent user-directed edits, start directly from `Frieren KGC Sprite.pxo`, not an alpha or
  colour pass. Do not infer staff-head mechanics from the low-resolution draft: two automated
  attempts at ruby braces were rejected and deleted. Require a user-marked three-bar overlay or
  explicit pixel endpoints before altering that assembly.

## 4. Auth & sessions (2026-08-18)

- `_uid_for_login`: id-less logins refused in multiplayer (never fall back to the active save -
  that minted dev-0001 sessions every ~5-20 min). Single-player fallback only.
- `GET /auth?id=...` (native Google sign-in) MUST mint a token (`direct_routes.py` →
  `mint_session_token`) - an empty model means a fresh client never gets `accessToken` and every
  later request hits the throwaway template save ("KingBug"). Diagnosis: zero new session rows
  at login time = the login body carried no id.
- **v172.1.00 post-logout login fixes (2026-09-06):**
  - Google browser callbacks arrive through Cloudflare while the native poller may reach origin as
    `127.0.0.1`; IP-only parking makes `/glogin/pending` poll forever. The stub now persists a
    random 128-bit device handoff key, sends it to both `/glogin?device=` and
    `/glogin/pending?device=`, and the server signs it into OAuth state before parking the result.
    Do not use a shared loopback alias: concurrent users could overwrite or consume each other's
    handoffs. Clients without a device key retain the legacy IP-bound flow.
  - Guest `AutoRegister` POSTs `/auth/register`, then GETs `/auth` with the same id. The direct
    handler requires a one-use native grant, so successful type-4 registration must call
    `_grant_native_auth`; otherwise `/auth` returns `success:false`, missing date strings make
    `Scene_Login.HandleAuthResponse` throw `ArgumentNullException`, and UI stays Authenticating.
    After logout an existing Guest can bypass register and call `/auth` directly, so the handler
    also accepts an id already bound to an `accountType=4` save. Unknown Guest ids remain denied;
    Google ids always require the signed browser/poller handoff.
  - The native hook must locate `<AutoRegister>g__AutoRegisterImpl` by stable prefix: its compiler
    suffix changed from `|134_0` to `|137_0` in v172.1.00. Exact lookup silently skipped the hook.
    Regression: `tests/test_multi_login.py::check_guest_register_grants_its_followup_native_auth`.
- Template uid is `""`; every key fallback is `st.get("uid") or "dev-0001"` - never persist a
  `""` or `guest-0001` row. Full write-up: `docs/multi-account-login.md`.
- `dev-0001` = NightOwL since 2026-08-18 (uid `p-410890b421a5`, merged; old KingBug save
  deleted, backup in `server/state/backups/players.db.bak-uidmerge-*`).
- **Guest takeover guard (2026-09-25):** a Guest register (`type:4`) whose `id` resolves to an
  EXISTING save that was created as a non-Guest (accountType != 4) is now REFUSED in
  `_uid_for_login` (returns `None` → `success:false`, no session). Root cause of the report
  "pressed create guest account → ended up in dev-0001": the v173.1.00 private client does NOT
  patch `GetGoogleUserId` to return a synthetic id (the old v171 pattern lived in
  `patch_apk_inplace.py` Patch 7 and was never ported to `build_private.py`), so the guest
  button sends the device's REAL Google Play Games id as `id` with `type:4`. The server then
  resolved `uid_for_login(id)` to that account's save and minted a session - i.e. anyone on a
  machine signed into NightOwL's Google account (`google_102274623045401309225`) got `dev-0001`
  with a fresh token. Repro (local): `r_login({'id': 'google_...225', 'type': 4})` →
  `accessToken: True, uid: dev-0001`. Live proof: accounts `google_112752210344722037317` →
  `p-4ffd36398c99` etc. were created with `accountType=4` - real guest presses carrying real
  google ids. Returning Guests (save accountType==4) still re-attach; Google login via
  type:1/`/auth` unaffected. Regression:
  `tests/test_multi_login.py::check_guest_register_cannot_take_over_a_google_save`.
  **Client-side fix (2026-09-25, done, both shipped)**: do NOT port the old
  `GetGoogleUserId → GenerateRandomName` prologue patch (`patch_apk_inplace.py` Patch 7). That
  would break guest persistence: `GenerateRandomName(8)` returns a NEW random id every call, so
  auto-register would mint a fresh save each launch instead of re-attaching the persistent
  `device_id` (`guest-<r>-<r>` in `/data/data/com.nowl.castle/guest_id.txt`) that
  `server/jni/stub.cpp`'s `HookedAutoRegisterImpl` already injects. Instead the fix lives in that
  existing hook: `AutoRegister` (RVA `0x358F3F0`) calls `GetGoogleUserId` (`0x358E388`) and
  tail-calls `<AutoRegister>g__AutoRegisterImpl|139_0` (`0x35905E0`) with the result as `id` - the
  exact function the stub detours. The old guard only replaced id when its length (Il2CppString
  `int32` at `+0x10`) was 0; a device signed into Google Play Games made `GetGoogleUserId` return
  the REAL `google_...` account id (non-empty) -> it sailed through. `HookedAutoRegisterImpl` now
  also treats an id with the UTF-16LE prefix `google_` (chars at `+0x14`) like an empty one and
  substitutes the persistent `device_id`. Returning guests (own `guest-...` id) and Google login
  (type:1/`/auth`) unchanged. Rebuild recipe: SETUP.md "Rebuilding the native .so" (NDK 27, cmake)
  -> `cp libxigncode.so server/xigncode_stub/arm64/ server/xigncode_stub/` (BOTH copies - they
  drifted once). The `.so` ships in-repo, so the next client build picks it up via
  `build_private.py` (which pads it back to the APK's original size on injection).
  **Live verification (2026-09-25, release `v173.1.00`, public server 213.35.110.245):**
  redroid pressed "create guest account" → logcat
  `HookedAutoRegisterImpl injected persistent ID: guest-2034096186-1184495937` (12:38:09) →
  public `players.db` gained `accounts ('guest-2034096186-1184495937','p-6dbedb9fc64b')`
  (accountType=4, name "Player1667", lvl 100) + `sessions` row
  `DEV.627a3bb… → p-6dbedb9fc64b` minted 12:38:13 UTC → client reached the real lobby.
  `dev-0001`/`p-410890b421a5` untouched (no new session). Ephemeral gotchas while verifying:
  (a) ICMP ping to the OCI box is blocked → use `toybox nc -w 3 <ip> 80` for device-side
  connectivity, not `ping`; (b) Android's `sh` has no `/dev/tcp` (bash-ism); (c) the baked
  `http://213.35.110.245` lives in `base_assets.apk`'s `global-metadata.dat`, NOT in
  `libil2cpp.so` string tables - grep the metadata; (d) the public HTTP uvicorn runs
  access-log-`OFF` (`INFO:…` lines only exist in `/tmp/kgc_pub_tls.log`), so an absent log entry
  proves nothing - the `players.db` `accounts`/`sessions` tables are the source of truth.
  New client-side crash found in the same test run: tapping the Arena tab throws
  `IndexOutOfRangeException` in `ArenaWinRewardUI.Reload()` (via `PvPPanel.Reload()`, 12:40:50,
  non-fatal, game continues) - a v173 code path with no existing NRE stub; see §4 arena note if
  it bothers players.
- **v173 sends the account Auth as `POST /auth`, not `GET /auth` (2026-09-25, fixed).** The
  reported bug: logout → re-login guest → "still lands on KingBug" (the template save:
  name="KingBug", castle "BugCastle", gold 290909, uid=""). Root cause chain, proven by live
  traffic + code:
  1. The v173.1.00 client issues **`POST /auth`** for `RestAPI.Auth` (zero `GET /auth` hits in
     /tmp/kgc_pub_tls.log across the whole day; stringLiteral `'/auth'` @ `0x6b140a0`).
  2. `direct_routes.py` `auth_native` was registered **GET-only**, so `POST /auth` fell into the
     generic dispatcher: `data/route_models_extra.json` maps bare `/auth` →
     `AuthResponseModel`, `respond()` had no OVERRIDE → **empty model (no `accessToken`)**.
  3. The client then runs `RestAPI.Login` = `POST /auth/login` with the token from (2) = empty →
     `_uid_for_login` returns `None` (multiplayer) → `r_login` refuses silently (no `[auth]`
     trace, no session; the refusal only lands in the per-worker in-memory `LOG_BUF`, read via
     `/admin/api/logs`) → every following request hits `load_state()`'s throwaway template save.
  4. The first-ever login worked only because a NEW account takes the **register** path
     (`POST /auth/register` → `r_login` mints a real token). Every subsequent launch/logout takes
     the **Auth** path (id stored in AwesomePrefs survives logout) → broken.
  Fix (`direct_routes.py`): `auth_native` now answers `POST /auth` (and `POST /auth/auth`) with
  the same mint as GET; `id` is read from the query string OR the JSON body (mirrors
  `server.py:597`), body read only on POST; logs
  `[host] POST /auth id=... body_keys=[...]` to admin_log (stderr → `/tmp/kgc_pub_tls.log`, always
  printed even under `KGC_QUIET=1`). Returning guests (bound `accountType=4`) mint; unknown
  ungranted ids stay refused. Regressions: `tests/test_multi_login.py::check_post_auth_mints_a_session_for_a_returning_guest`
  (legacy runner) + `tests/test_post_auth.py::test_post_auth_mints_for_a_returning_guest`
  (pytest-collected). Note: the pytest suite only collects files with `test_*`-named functions
  (98 items); the `check_*` files are standalone scripts via `if __name__ == "__main__"` and are
  NOT part of CI - a regression in one of those must be pinned in a `test_*`-style file to be
  CI-enforced.

- **Returning Google re-login needs no fresh handoff (2026-09-25, fixed).** The v173.1.00 client
  re-issues `POST /auth` with its STORED id on EVERY launch ("out game, vào lại"), because the id
  persists in AwesomePrefs across logout/restart (same statement as §4 step 4 above). But
  `auth_native` required the one-shot browser/poller grant (`NATIVE_AUTH_GRANT_TTL=60`, single-use,
  in `google_login.py`) for EVERY Google id - even one already bound to a save. The first login
  consumed the grant; re-entry had no fresh `/glogin/callback` (live proof: `grep -c
  'glogin/callback' /tmp/kgc_pub_tls.log` == **1** for the whole day vs 3 google `POST /auth`), so
  re-entry got `success:false` → the client's `ReAuth...` = "Retrying authentication..." forever,
  while the stub's `/glogin/pending` poller (1/s, background noise) waited for a handoff never
  re-armed. Fix: the grant is now required only when NO save is bound to the login id (unknown id
  → still anti-squatting); any returning account (save bound, ANY accountType) re-auths freely -
  exactly the policy already applied to returning Guests. `_uid_for_login`'s existing guard still
  stops a type:4 register from taking over a Google save. Security note: the handoff's IP-binding
  is vacuous on this deploy anyway (every request arrives as 127.0.0.1 through the loopback DNAT),
  so the grant only ever meaningfully gated brand-new ids. Regression:
  `tests/test_multi_login.py::check_returning_google_relogin_without_handoff` (legacy runner).
  Follow-up idea (not done): the POST /auth body carries a `cookie` (seen on `GET /auth/xcd?cookie=…`)
  that could serve as a stable per-device credential for a stronger re-auth gate.

### Official-token harvesting - Firebase Test Lab verdict (2026-08-24, DEAD END)

Goal was a real official `accesstoken` for the ranking API. Ran the **stock v172.0.01 client**
on Test Lab physical Pixel 8a (`model=akita,version=34`, project `kgc-harvest-43937`) with a
custom instrumentation APK that dumped `shared_prefs` every few seconds and auto-tapped dialogs:

- Stock xapk → single APK via APKEditor, then **re-sign** (zipalign + apksigner debug key) or
  Test Lab rejects with `NO_SIGNATURE`. Harness: plain JUnit4 `@Test` +
  `InstrumentationRegistry.getInstrumentation()` + UiAutomator; **no** `android.test.*`
  (removed in API 34 → `NoClassDefFoundError`). `targetPackage=com.awesomepiece.castle`
  means instrumentation runs inside the game process.
- Game installs/launches fine and writes prefs (Unity Screenmanager keys, airbridge,
  tapjoy…), but the process dies at **T+75s on every run**: clean `exit(0)` normally, or
  `FORTIFY: pthread_mutex_lock called on a destroyed mutex` when our UI-poking races the
  teardown. Right before death its threads scan `/proc/net/tcp|unix`, `/dev/configfs`,
  `/system`, and read `Settings.Global adb_enabled` (always on for Test Lab). The GPGS
  "Create a Play Games profile" dialog is NOT the cause (tapping Cancel only delays it).
- Verdict: **XIGNCODE environment-kill ~75s after launch, before any server login** - no
  `loginId`/`accesstoken` is ever written. No amount of UI automation fixes this; don't burn
  more matrices on this route.
- Re-confirmed §2 above: `/auth?id=` needs `version` in the **query string** (header alone →
  `403 최신 버전이 아닙니다 (Version)`); with query version ≥172.0.01 the check passes and an
  unknown id gives `404 존재하지 않는 계정입니다` (the old iOS guest id is gone/not visible to
  Android-platform lookups). Registering fresh guests still works but token issuance stays
  behind the XIGNCODE cookie gate.

### QEMU ARM64 emulator verdict (2026-08-24, blocked)

- Host is x86_64. The normal Android Emulator launcher refuses the API 33 Google APIs ARM64
  image with `AVD's CPU Architecture 'arm64' is not supported by the QEMU2 emulator on x86_64`.
- Calling the bundled `qemu-system-aarch64` frontend directly with `-avd-arch arm64` bypasses that
  check. Its `ranchu` machine then always appends `-soundhw virtio-snd-pci`, which fails because
  the ARM64 ranchu machine has no PCI bus, even with `-no-audio` and `hw.audioOutput=no`.
- Adding `-qemu -M virt` avoids the PCI error. The correct AVD `userdata-qemu.img` (8 GiB virtual
  size) is required; the stock `userdata.img` is only 1 MiB. With that fix Android API 33 mounts
  system/vendor/data and reaches the vendor HAL start sequence, but the bundled QEMU frontend
  segfaults around the graphics/USB HAL startup before `adbd` becomes online. `-gpu off` does not
  change the result. No APK login or token was reached; XIGNCODE was not patched.
- Do not spend more time on this direct-emulator variant unless switching to a compatible
  Cuttlefish/full-system image or a different emulator build. Redroid remains the only bootable
  ARM64 path tested here, but its stock client dies around T+75s before login.
- Follow-up: Android CI build `16102939` on `aosp-android-latest-release` provides matching
  ARM64 Cuttlefish images, but the ARM host package cannot execute on this x86_64 host. The
  x86_64 host package rejects both `qemu_cli` and `crosvm` here, and cannot run the ARM64 guest.
  The matching x86_64 Cuttlefish image is not useful for this APK: the stock ARM64 APK fails
  with `INSTALL_FAILED_NO_MATCHING_ABIS` on both Google APIs and Google Play x86_64 AVDs;
  both report `ro.dalvik.vm.native.bridge=0`. The remaining viable route is a real ARM64
  device/runner, or an emulator/runtime that explicitly supplies ARM64 translation.


### Official iOS iCloud-password prompt - investigation boundary (2026-08-29)

- Reported symptom: the unmodified official iOS client repeatedly presents an iCloud-account
  password prompt despite an already-signed-in Apple account.
- Repository evidence: there is no IPA/XCArchive, entitlement, provisioning profile, iOS device
  log, crash report, or iOS-native source here; the server has no CloudKit, StoreKit, GameKit, or
  Sign in with Apple implementation. It only records the client-supplied account type (`2`
  GameCenter, `3` AppleID) after login. Therefore no private-server response is evidenced as the
  direct source of this OS-owned prompt.
- Do not attribute the prompt to a particular Apple service without its exact text and device log.
  The discriminating evidence is the presenting framework/caller in Console/sysdiagnose, plus the
  official IPA's entitlements. Candidate owners to distinguish are Game Center authentication,
  iCloud Keychain/CloudKit, and StoreKit receipt/restore; they require different fixes.
- App Store lookup on 2026-08-30 confirms official iOS `172.1.00` (released 2026-08-26) declares
  Game Center support. `scripts/capture_ios_auth_logs.sh` captures and redacts the relevant
  device log services over USB, so the presenting Apple framework can be identified before an
  IPA patch is considered.
- **Cause confirmed from the on-device v172.1.00 capture (2026-08-30): this is StoreKit, not
  Game Center/iCloud.** At `07:51:31` `storekitd`, proxied by
  `com.awesomepiece.castle`, requests the IAP catalog and transaction/entitlement caches. At
  `07:51:32.300` it starts `TransactionHistoryRequest` with
  `AccountRequirement.forceAuthentication(useBiometrics: false)` for the KGC production client;
  `appstored` then faults that an interactive authentication was requested by a background daemon
  (it should use silent-preferred) and at `07:51:33.935` presents the Apple Account password UI.
  The client must not launch that force-auth transaction sync during boot: defer a user-initiated
  restore/purchase refresh until the shop action, and use a non-interactive entitlement/cache
  read for launch. This cannot be corrected by the game server; it requires an official iOS source
  change or a legally supplied, inspectable IPA. The log has one prompt event in this run.
- A first revision of the capture script did not redact quoted `storekitd.CacheAccount(token: ...)`
  values. The stored `.log` files are already ignored by Git, but treat that original capture as
  sensitive and do not upload it. The script now redacts quoted token, GUID, credentials and email
  values before writing new captures.

## 5. Reward vocabulary (2026-08-09/18)

- Wire types are CLIENT strings (`InventoryItem`, `Key`, `Gold`, `Cash`, `Heart`, `UnitSoul`,
  `CardSoul`, `Artifact`, `Treasure_*`, `Skin`, ...) - there is **no `"Item"`**; an unmatched
  type renders a wrong icon + nonsense count. Internal state keys translate at the wire boundary
  in `_wire_rewards()` (`_reward_list_data()`); state keys never move.
  Test: `server/tests/test_reward_vocabulary.py`.
- **`Key` = ShopItem id**, not inventory id: `<Reward Type="Key" ID="370">` → ShopItem 370,
  `<KeyItem>` names the inventory row (370→380, 70000→70005). `missions.key_item_for()`.
- Safe way to gift artifacts/treasures/accessories: send a **reward box** (Item reward), the
  player opens it. Direct Artifact/Accessory injection can trip panel invariants
  (ArtifactOptionUI crash - see AGENTS.md).
- Dashboard catalog: `GET /api/catalog` (173 items / 73 units / 318 artifacts / 60 treasures /
  108 accessories, names from `Strings_EN_US`).

## 6. Dimension gacha & cards (2026-08-09)

- Dimension heroes (e.g. D.Ophelia 10790) use `overcome` (0-5), NOT `soul`; first pull sets
  `overcome=1`, duplicates increment. Never delete the card to "reset" - set `overcome`.
- Both buy paths (`server/shop_routes.py`): `_grant_reward()` return → `pull["upgrade"]`,
  `rg["type"]="DimensionOvercome"`, and **`newUnitIds` + `cardExpResults` are mandatory** -
  without them the client's card state is stale until restart.
- `card_to_dict()` REQUIRES `unitId` in the card dict (server.py:340) - missing it crashes
  `/card/all` → all heroes show "Not Owned".
- Gacha `<KeyItem>` ≠ Shop `<KeyItem>` (8001→70000, shop 70000→70005) - prefer the gacha's.
- Dimension level resonance (fixed 2026-09-08): every owned card in an `<OriginalUnit>` family
  is serialized with the family's highest owned level. `originLevel` keeps that card's unsynced
  level and `isLevelSynced=true`; the client only considers sync applied when that flag is true
  and `level > originLevel`. Regression: `check_original_and_dimension_hero_share_the_highest_level`.
- Dimension sync upgrade response (fixed 2026-09-09): `/dimension-unit/upgrade` must return
  `DimensionUpgradeResponseModel{unit, remainEcho}`. Returning a `CardResponseModel` spends the
  remnants server-side but leaves `model.unit` null in `GameManager.HandleDimensionUpgradeResponse`,
  so the client never applies the new sync level. Regression: `check_upgrade_charges_exactly_the_listed_cost`.
- `DimensionUpgradeRequestModel.count` is the amount selected by the upgrade panel's investment
  slider, not a level count. Add it to `dimensionGauge`, consume each crossed level's cost, preserve
  partial progress, and cap spending at the amount needed for level 10. Ignoring `count` made every
  request buy exactly one full level regardless of the slider. Regression: `check_partial_and_multi_level_investment`.

## 7. Awakening / potentialTier (2026-08-01)

- `potentialTier`: 0 = not awakened, 1 = max. Seed MUST be 0 (`default_player.json` had 1 →
  every fresh hero showed "Thức tỉnh 1"). Client enables only at `level==16 && tier==0`.
- Upgrade endpoint exists and is correct: `POST /card/upgradePotentialTier` (client gates).
- Slot selection: `POST /deck/setPotential` `{presetIdx, idx, unitId, potential}`.
- ObscuredInt fields read as 20-byte pairs via thunk RVA `0x2B84070` (v171.0.00) - static
  analysis without Ghidra: capstone straight off the .so, file = RVA-0x4000.

## 8. CDN / master data (2026-07-05)

- `docs/cdn-master-data.md` - bundle rebuild, Strings gotchas (no XML comments in
  Strings_*.xml - breaks the whole locale's Localizer), Skill/Unit key-redirect trick.
- Tools: `server/builders/rebuild_xml_bundle.py`, `server/builders/refresh_master_data.py`; pristine backup
  `server/real_cdn/xml.bak` (md5 `779193a15d1377a7b8c2e6edfbe94095`).
- **Host rebinding needs two passes**: `patch_hosts.py` (stringLiteral table) +
  `patch_leftover_hosts.py` (field/parameter defaults - `castle-infra-server…run.app`,
  `kgc-cdn-1.awesomepiece.com/patch/`). Verify 0 real hosts remain after.

### 8a. Adding a distinct skin asset set (Frieren/Farael, 2026-08-20)

- Never point a new skin row at an existing skin's `<Prefab>` / `<Sprite>` names and then replace
  that Texture2D. `1057002` owns `Unit_10570_02`, `Unit_10570_02_0..18`, prefab
  `Unit_10570_02`, and `Unit_Illust_10570_02`; overwriting either texture changes the original
  Morning Star skin too.
- Frieren `1057003` uses the independent namespace `Unit_10570_03`:
  `server/cli/inject_skin.py` restores pristine `base_assets.apk`, clones the sprite Texture2D plus
  all 19 Sprite sub-assets, clones the prefab hierarchy/components plus its 10 AnimationClips and
  AnimatorController while sharing materials/VFX/MonoScripts, remaps its 20 external sprite PPtrs,
  and clones the illustration Texture2D/Sprite as `Unit_Illust_10570_03`. Every cloned Sprite gets a
  deterministic render GUID distinct from `02`; retaining `m_RenderDataKey` can make Unity resolve
  the source Sprite or render the cloned portrait empty. It also adds matching AssetBundle
  container/preload rows; cloning serialized objects without those rows does not make them loadable
  by name.
- `Unit_10570_02` is a **650x560 atlas of 19 fixed 130x140 frames** (5 columns, then four
  frames in the final row); every Sprite uses pivot `(0.5, 0.235)`. Its serialized
  `SpriteSheetData.sheets` gives the runtime order: Front = `0,1,2,3,4,18`, Side =
  `5,6,7,8,9,5`, Back = `10,11,12,13,14,10`; `15..17` are magic silhouettes. This mapping is
  authoritative - frame 18 is the front-facing prefab/thumbnail idle, not a side/run frame.
  `Unit_10570_02_reference.png` is the unmodified 650x560 Texture2D extracted from the v172
  `base_assets.apk` sprites bundle; it is a **geometry-only** input and never a character-design
  reference. `server/cli/rebuild_frieren_sprites.py` rebuilds a direct 5x4 Frieren design board:
  cells 0..18 map one-to-one to runtime frames and cell 19 remains transparent. It fits each
  generated pose into the original frame envelope at integer coordinates with NEAREST only, locks
  the final atlas to a shared 20-colour no-dither palette, and normalizes frames 15..17 to a
  white/cyan magic silhouette. The design board (`Frieren_source_design.png`) must be created from
  Frieren-only design reference; never reuse the `02` character's face, hair, costume, palette, or
  staff. Reproducible inputs/outputs live under `server/assets/frieren/`:
  `Frieren_source_design.png`, `Unit_10570_02_reference.png`, `Unit_10570_03.png`, and
  `Unit_10570_03_comparison.png`.
- `inject_skin.py` consumes those repository assets directly (no `/tmp/farael_assets` dependency).
  Run the atlas rebuild first, inspect `Unit_10570_03_comparison.png`, then run the injector. The
  original `Unit_10570_02` hash check is the guard against ever modifying Morning Star again.
- AssetBundle container rows are still insufficient: Addressables resolves the XML names through
  `assets/aa/catalog.json`. A missing catalog key produces exactly this symptom: the skin XML row and
  name render, but the thumbnail/pixel prefab are blank and the large portrait falls back to the
  unit's default illustration. The injector therefore clones five compact locations from `02`:
  `Unit_10570_03` (Texture2D + Sprite), `Character_Unit_10570_03` (GameObject), and
  `Unit_Illust_10570_03` (Texture2D + Sprite). The first illusts-bundle clone passed offline checks
  but rendered blank at runtime. The target portrait is now stored in the sprites bundle and its
  catalog locations clone the proven sprite-bundle dependency; provider/resource type remain.
  It appends 3 internal IDs, 3 ASCII keys/buckets, and 5 seven-int entry records without changing
  any existing key/index.
- The private v172.0.01 build disables bundle CRC at runtime:
  `AssetBundleRequestOptions.get_Crc` file `0x5FC5F10` returns zero, and direct CRC argument reads at
  `0x5FC8484`, `0x5FC639C`, `0x5FC648C` are replaced with `mov wN,wzr`. Editing catalog ExtraData is
  unnecessary and error-prone; changing the key/bucket/entry tables is required and independent of
  CRC bypass.
- Verification: injector reloads all three bundles, proves the `02` texture/portrait hashes are
  unchanged, checks `Unit_10570_03_18` points at the cloned texture with a distinct render GUID,
  and proves every cloned frame renders through `Sprite.image` as a 130x140 full rectangle. This
  last check is essential: `Sprite.m_Rect` alone does not control rendering. Source `02` stores a
  silhouette-specific `m_RD.textureRect`, `textureRectOffset`, `uvTransform`, tight polygon
  `m_VertexData`, and `m_IndexBuffer`; retaining them crops a wider Frieren pose and Unity then
  magnifies that crop. `_set_full_rect_sprite` replaces all 19 target render records with a
  four-vertex quad covering the declared cell while preserving pivot `(0.5, 0.235)` and PPU 1.
  The illustration Sprite has the same trap: cloning `Unit_Illust_10570_02`'s 908x912 tight mesh
  over Frieren's 1024x1024 portrait cuts the face/body into holes even though the Texture2D and
  catalog key are correct. The injector now applies the full-rectangle quad to
  `Unit_Illust_10570_03` too and verifies `Sprite.image == (1024,1024)` plus its cloned texture PPtr.
  The XML row explicitly sets `<IllustSprite>Unit_Illust_10570_03</IllustSprite>`; this matches the
  client's inferred default but removes inheritance/format ambiguity during diagnosis.
  Frame semantics still matter after the geometry is fixed: `Unit_10570_03_18` is both the prefab's
  default Sprite and the `<Sprite>` used by the skin thumbnail. A running pose in cell 18 therefore
  makes both UI surfaces look wrong even when every PPtr/UV is valid. The production atlas maps
  frame 18 to the board's calm **front-facing** standing pose with a complete vertical staff. `--frame18`
  remains available only as an explicit optional override; the obsolete side-facing v2 override
  is no longer the default. Runtime confirmation of the new sprites-bundle portrait placement is
  still pending user inspection; do not mark it solved solely from UnityPy verification.
  The verifier also confirms both prefabs coexist with disjoint 10-clip/controller dependencies,
  and checks all five new catalog locations resolve to the three new asset paths. Rebuild
  `server/real_cdn/xml`
  afterward so skin `1057003` points at `Unit_10570_03` / `Unit_10570_03_18`.

### 8b. Unit_10570 animation clip semantics (2026-08-20)

The 19 atlas cells are selected by `SpriteSheetData.SetSheet` + `SetSpriteIndex`; they are
not played as one linear 0→18 animation. In the v172.0.01 `characters_assets_all` bundle,
`AnimatorController Unit_10570` has ten clips: `Idle_10570`, `Run_10570`,
`Attack_{Front,Side,Back}_10570`, `Shoot_{Front,Side,Back}_10570`, `Skill_10570`, and
`End_10570`. The directional sheet arrays are:

```
Front:  index 0,1,2,3,4,5 -> atlas frames 0,1,2,3,4,18
Side:   index 0,1,2,3,4,5 -> atlas frames 5,6,7,8,9,5
Back:   index 0,1,2,3,4,5 -> atlas frames 10,11,12,13,14,10
```

Clip event timelines (60 Hz clips, seconds):

| clip | events / visual role |
|---|---|
| `Idle_10570` | `SetSpriteIndex(5)` at 0.0 → Front idle frame 18 (prefab/thumbnail pose) |
| `Run_10570` | `SetSpriteIndex(0)` → directional frame 0/5/10; locomotion base |
| `Attack_Front` | frame 1 at 0.0 (wind-up), `ShootSkill` + frame 2 at 0.333 s (release), end 0.667 s |
| `Attack_Side` | same timing using Side frames 6→7 |
| `Attack_Back` | same timing using Back frames 11→12 |
| `Skill` | frame 3 at 0.0 (cast/wind-up), `ShootSkill` + frame 4 at 0.333 s (active cast), `SkillEnd` at 2.667 s |
| `Shoot_Front/Side/Back` | one-shot projectile pose: directional index 4 → frame 4/9/14 |
| `End` | index 0 at 0.0, `SkillEnd` at 0.333 s; returns from skill/action |

The facing sheet is selected by the unit's direction blend/state (`Dir_Blend`); clips reuse the
same index meanings across Front/Side/Back. Therefore frame 0 specifically means the first
directional locomotion/base pose (front-facing when the active sheet is Front), not the idle pose
and not a generic thumbnail. Frame 1 is front attack wind-up, frame 2 the front attack release,
frame 3 skill wind-up, and frame 4 the front shoot/active pose. Frame 18 must remain the calm
front idle because the prefab default Sprite and skin thumbnail point to it. A reskin must preserve
these action roles and staff/hand anchors per frame.

## 9. Content-unlock gates (2026-07-11)

- Accessory/treasure/rift-weapon unlock keys off **invasion cleared difficulty**
  (`ResourceChallengeSeason.Constants`: Treasure=1, **Accessory=6**, RiftWeapon=11, Max=25;
  invasion II-1 = diff 6). `[Corruption]` tag is a red herring.
- `data/response_config.json` `invasionUnlockedDifficulty` = 6 (≥11 unlocks rift-weapon too).
- `r_player()` emits per-theme records with `"difficulty": unlocked` - it previously used the
  loop var `d` (1..unlocked) so `.First().difficulty` returned 1 and 6/11 stayed locked
  (masked by treasure=1 working). The `d`-loop still pads list length for
  `ProfilePanel.ReloadChallenge`.
- Accessories: `load_corruption_accessories()` builds the 4 real Invasion II-1 rewards from
  `FixedAccessoryPresets.xml` IDs 2000-2003 (valid stat keys - `mainStat="ATK"` was garbage).
- **Difficulty progression (2026-09-06):** a winning `/game/complete` stores the cleared
  difficulty and unlocks the next one through 15. The old `min(diff + 1, 5)` confused the five
  first-clear reward rows with the playable difficulty ladder, so winning difficulty 11 left 12
  locked. Regression: `check_winning_unlocks_the_next_difficulty`.

### 9a. Accessory change-sub-stat - duplicate-tier decode (2026-08-18, d843ed5)

**Client models (v172.0.01)**: `AccessoryChangeSubStatRequestModel{accessoryId, targetSubStat,
itemId}` - `targetSubStat` is the **OLD** stat (confirm panel `_targetSubStatName` =
`beforeStatNames[targetIndex]`). Response `AccessoryResultResponseModel{accessories,
deletedAccessories, playerGold, playerCash, inventories, addedExpItems}` - exactly what
`_make_result_response` sends; the client's `AccessoryModel.data.subStats` = `List<{key,value}>`
objects (NOT strings - the parallel `subStats: List<string>`/`subStatScores: List<float>` are a
second, deduped view).

**Client apply path**: `<OnClickConfirm>d__17.MoveNext` (RVA 0x334FF70) → success → `GameManager`
@ RVA 0x305B060: for each response accessory, find by id in the owned list then
**`CopyFrom` (RVA 0x2CCCAC0 = shallow field copy, no merge)** - list entries are never replaced,
only field-copied; not-found → append; then remove `deletedAccessories`, apply gold/cash.

**Root cause of "chosen stat applied + extra lower-tier stats"**: `FixedAccessoryPresets.xml`
tier lines are additive duplicates of the same key (e.g. 6× `BaseDefDen 4.0` + 1× `2.0`), and
`make_fixed_accessory` kept every line as its own `data.subStats` entry (only the parallel lists
were deduped). The client renders `data.subStats`, so seeded accessories showed 7-8 stat lines;
the change handler replaced only the FIRST copy, leaving the rest as "extras" (and handing the
full summed score to the new stat while the leftover copies kept their own - inflated pool).

**Fix (server-side only)**: `make_fixed_accessory` (both copies: `routes/accessory.py` +
`routes/rewardbox.py`) builds `data.subStats` from the deduped `scores` dict (one entry per key,
value = score × unit); `ensure_accessory_state` merges duplicates in existing saves (heal -
38/38 live players fixed at deploy); `r_accessory_change_sub_stat` removes ALL `target_stat`
entries and inserts one `new_stat` entry with the summed score at the first removed index.
Regression: `test_accessory_merge_duplicate_substats` in `server/tests/test_accessory.py`.
Verified live: dev-0001 acc 62 `[AtkPer 26.0, BaseDef 80.0]` after manual remnant cleanup
(the old handler had given AtkPer the full 26 pool while leaving BaseDefDen 22 behind).

### 9b. Legacy (treasure) upgrading (2026-09-06)

- `TreasureRequestModel` transcendence materials are the combination of
  `materialTreasureIds: List<int>` and `materialItemCount` (item 3200). Their total must satisfy
  the rarity's `TreasureOvercomeCost.NeedMaterial`; do not always charge the full cost in ingots.
- Validate both sources before mutating state, never allow `targetId` to consume itself, and return
  consumed instance IDs in `TreasureResultResponseModel.deletedTreasures` so the client removes
  them immediately. Regression: `check_treasure_overcome_accepts_duplicate_legacy`.

## 10. Post/mail system (2026-07-11)

- Inbox = "Post": direct handlers `GET /post`, `POST /post/receive`, `POST /admin/sendmail`
  (registered before the ROUTE_MODELS loop - generated models lack `posts`).
- `title`/`text` are localization KEYS (fallback `Post_Title_Default`); `@raw:` prefix bypasses
  the Localizer via the native `PostListItem.Set` hook (strip at write, re-add at read -
  `_process_posts`).
- `RewardResponseData.type` = client vocabulary (see §5). Test:
  `server/tests/test_rename_and_mail.py`.

## 11. il2cpp hook techniques (stub.cpp)

- **methodPointer swap**: only Unity-engine-invoked methods (Update/Awake/...). Invisible to
  C#→C# calls.
- **inline detour** (16-byte absolute jump + trampoline): ALL callers incl. direct compiled
  calls. Guard aborts on PC-relative prologue instructions.
- Debug checklist: wrong dlopen handle (`libil2cpp.so is loaded (poll took 0s)` = bug; 1s+
  = right), `r-xp` never matches under ndk_translation (use `dl_iterate_phdr` + `dlpi_addr`),
  `#if 0` left behind.
- Each hook logs exactly one line; a silent failure means the hook wasn't installed.

## 12. Open questions / to verify

- `[GAME/COMPLETE] body=` debug print in `r_game_complete` - confirm from a real battle, then
  remove.
- v172.0.01 `GetReceivableRewardCount` uses a 0-based theme base (theme 0 for pass 0, gate
  fails → 20 not 25) - its own quirk; not our bug, not fixable server-side. Verify against a
  real v172 client if one ever appears.
- One-time `WorldPanel.Reload()` NRE at IL offset 0x00000 - non-blocking, unpinned.
- `deck-reload`/`deck-reload2` v170 patches still disabled (root-cause investigation 2026-07-02,
  never re-enabled - re-derive v171+ offsets if ever needed).

## 13. Strife Battlefield (Colosseum PvP)

### Strategy/ColosseumAbility catalog (verified 2026-09-15)
- Full catalog: `docs/strife-compendium.html`. The served v173 season-73 data contains **141 tier
  rows grouped into 67 strategy roots**. ID last digit is the zero-based tier (`0/1/2` = tier
  `1/2/3`); some roots intentionally start at tier 2 or 3.
- `ColosseumAbilitySelectPanel.ABILITY_PICK_COUNT=3`; `PickRandomAbilities` uses `Weight`, tier,
  current categories/composition, abandoned choices and season themes. Settings provide 5 rerolls,
  max strategy level 7, and EXP thresholds `0,40,70,120,200,300,420`.
- Season 73 themes are `1,6,7,8,9,10,11,12,13,14,15`, so theme strategies 2-5 are excluded.
  Region/role strategy offer gates (`AppearWhenRegionUnit3`, `AppearWhenRoleLevel5`) are distinct
  from their in-battle activation conditions.
- v173 `PickRandomAbilities` exclusion rules: uncategorized abilities compare `_inheritFrom`
  (the root; e.g. `50031/50032 -> 50030`) against both `ColosseumData.abilities` and
  `abilityQueue`, so selecting one tier blocks every tier of that root. Categorized abilities are
  blocked on any shared category: `BuildingLevel` (3 roots), `InvadeShop` (6 shop roots plus theme
  roots 80000/80040/80090), `HighestLevel` (4), `UnitRegionOrRole` (11), and `InvadeChapter`
  (all 15 themes). A rerolled exact ID is excluded only on the normal pass; retry ignores
  `abandonedAbilities`. Hard gates remain: slot count `<7` (10050), stage `<7` (10100),
  `Disabled` (60010), 3 matching-region heroes (70000-70040), or one matching-role hero level
  5+ (70050-70100).
- For mechanics, trust `WorldTriggers -> ColosseumEventTriggers -> ColosseumBuffDatas`, not
  `DescComment`: multiple comments are stale. Confirmed examples: Silver Chest T1=40 (not 30),
  Plunder=25 (not 20), Focus on Defense=14 Silver (not 16), Winter Armor=+150% HP (not 200),
  Hero's Vigor=+60% stats (not 70), Guardian God's Excellence=+25% HP/max 7 stacks, and Devil's
  Blood runtime attack-speed buff=30% while its UI params say 40%.
### Season display
- `ColosseumSettings.xml`: `CurrentSeasonTheme` = "1,2,6,7,8,10,11,12,13,14,15" matches
  `SeasonTheme Season="72"`. `SeasonThemes` has Season="71" and Season="72".
- Client logic in `HandleSemiSeasonChanged` → `LeagueContentRankBox.Set<Tier>`: the format
  string (`ColosseumBetaSeason` vs `ColosseumSeasonFormat`) is chosen by comparing
  `season` (field offset 0x2C in `PlayerColosseumInfoResponseModel`) against **0x25 = 37**.
  `csel` at RVA 0x3252e18: if season > 37 → uses `ColosseumSeasonFormat` ("Strife Battlefield
  Season {0}"), else → `ColosseumBetaSeason` ("Strife Battlefield Beta Season").
- **Two-step season source (critical)**: the format string selection does NOT read from the
  colosseum response model. Assembly chain: `Il2CppClass → static_fields → _singleton →
  pvpData (offset 0x220) → season (offset 0x2C)`. `GameManager.pvpData` is populated by
  `/pvp/info` (Arena endpoint), NOT `/colosseum`. So both endpoints must return season > 37.
- **Fix (commit 14dc59b)**: `response_config.json` colosseum season `1` → `72`. Outer panel
  gate card showed "Season 72" but inner panel still showed "Beta Season".
- **Fix (commit b4cf13a)**: `response_config.json` pvpInfo season `1` → `72` (and
  pvpInfoDirect `1` → `72`). Inner panel reads `GameManager.pvpData.season`, which comes
  from `/pvp/info`. Old value 1 was <=37, still triggering ColosseumBetaSeason.
- `LeagueContentRankBox.Set<Tier>` signature (RVA 0x3b247d0, file offset 0x3b207d0):
  `Set<Tier>(string seasonFormat, int season, int curSemiSeason, List<LeagueContentScoreData>
  scoreDatas, DateTime seasonUntilAt, DateTime thisSemiSeasonStartAt, DateTime
  nextSemiSeasonStartAt, Func<int, int, Tier> getResTierFunc)`. Does
  `Localizer.Get(seasonFormat)` then `string.Format(result, season)` → `_seasonText.text`.

#### Dimension Rift season-number source (the "Season 71" mystery, decoded 2026-09-25)
- The rift season-info popup ("Season N Dimensional Rift Seasonal Effects") gets its **N** from
  `GameManager.passModel.passSeason`, NOT from `/rogueLike/season-info` (the response model
  `RogueLikeSeasonInfoResponseModel` has **no** `season` field - verified in dump.cs).
- Assembly chain (from `DimensionRiftSeasonInfoPanel.Reload` RVA `0x34C6070`, v173.1.00):
  `GameManager._singleton → [x8, #0x2d0] = passModel (SeasonPassResponseModel) → [x8, #0x38] =
  passSeason`. `SeasonPassResponseModel.passSeason` @ 0x38 (dump.cs line ~232386). So the panel
  title = the **Season Pass** number the server advertises.
- `GameListBox.ReloadDimensionRiftSeasonRemainTime` (RVA `0x3442164`) draws the lobby rift
  button's "Season N / ends in" from the same `RogueLikeDataSet` (theme 2100) date fields.
- The **effects** (advantage region/role, boss) DO come from `/rogueLike/season-info`, which
  picks a `DimensionRiftSeasonDatas.xml` row by season number in `r_rogue_season_info`
  (fallback = max row). Keeping the effect row ≠ `passSeason` shows a mismatched title/effects.
- **Gotcha (found 2026-09-25, after the 73 bump)**: `r_rogue_season_info` originally read
  `RCFG["pvpInfo"]["season"]` (top-level) - but the top-level pvpInfo dict has NO `season` key
  (only `fixed`, `seasonDayOffsets`, `nextSeasonDayOffsets`), so `.get("season", 72)` always
  returned the hardcoded **72**. Result: title "Season 73" + effects row 72 (South/Shadow) -
  same mismatch as the old 71-vs-72 bug. `/pvp/info` (POST, `_pvp_state` → `fixed`) and the GET
  direct route (`pvpInfoDirect.season`) both read the right place, which is why only the rift
  effects lagged. Fixed to read `pvpInfo.fixed.season` first, top-level as fallback, then 72.
  Regression: `test_dimension_rift_season_info_serves_current_season_effects` in
  `server/tests/test_rift_season.py` (asserts the served row equals the config season + master
  data row for every field).
- **Fix (2026-09-25, commit to be pushed)**: `response_config.json` bumped to Season 73
  (Harvest Moon Festival, the newest - SeasonPasses.xml rows go `3..73`):
  - `pass.fixed.passSeason`: 71 → 73 (rift title + pass panel; ID 73 has full reward table)
  - `pvpInfo.fixed.season` and `pvpInfoDirect.season`: 72 → 73 (rift effects → S73 row:
    adv `Swift` / penalty `North`; Arena label + `GameManager.pvpData.season`)
  - `colosseum.fixed.season`: 72 → 73 (Strife label)
  - Arena/Strife labels are plain `string.Format(seasonFormat, season)` - no master-data lookup
    by season number, so 73 can't NRE. `ChallengeSeasons.xml` max=72 is the Hall-of-Challenge
    table, unrelated.

### Pre-season popup fix
- `_isColosseumPreSeason()` (RVA 0x324fba4): calls `GetSeasonStartAt(colosseumData, 0)` →
  `nextSeasonStartAtDates[max(0, 0-1)]` = `nextSeasonStartAtDates[0]` (clamped). Then checks:
  `nextSeasonStartAtDates[0] > UtcNow` → if TRUE, returns true (pre-season), popup shown.
- `_isSemiSeasonBreakTime()` (RVA 0x324fcf0): calls `GetCurrentSeasonUntilAt()` →
  `seasonUntilAtDates[semiSeason-1]`. Then checks: `seasonUntilAt <= UtcNow` → break time.
- `CheckColosseumEnabled` (RVA 0x32513b4) calls both; if either returns true, shows popup
  and returns false (game start blocked). The popup format is `SeasonEndTimeFormat` with a
  countdown timer using `nextSeasonStartAtDates[0]` (stored at ColosseumPanel field 0xD8).
- **Root cause**: `nextSeasonDayOffsets[0]` was `+16` (future). With semiSeason=2, this meant
  semi-season 1's start date was in the future → pre-season = true → popup.
- **Fix (commit 8753945)**: `nextSeasonDayOffsets[0]` changed to negative values so
  `nextSeasonStartAtDates[0]` is in the past:
  - colosseum (semiSeason=2): `[-30,-15,15]` - semi 1 started 30d ago, semi 2 started 15d ago
  - pvpInfo (semiSeason=1): `[-15,16,31]` - semi 1 started 15d ago
  - `seasonDayOffsets` adjusted: colosseum `[-15,15]` (semi 1 ended 15d ago, semi 2 ends in 15d)
- **Index mapping**:
  - `GetCurrentSeasonUntilAt()` → `seasonUntilAtDates[semiSeason-1]` (end of current semi)
  - `GetNextSeasonStartAt()` → `nextSeasonStartAtDates[semiSeason]` (next global season)
  - `GetSeasonStartAt(semiSeason)` → `nextSeasonStartAtDates[semiSeason-1]` (start of semi)

### Battle flow
- `OnClickStartColosseum` (RVA 0x3250fb8) → checks level gate, opens confirm dialog →
  `GameManager.StartColosseumMatchmaking` (RVA 0x3071578).
- `StartColosseumMatchmaking` → `RestAPI.RequestColosseumMatchmaking` → `POST /colosseum/match`
  → `ColosseumMatchResponseModel{gameId, serverAddress}`.
- Empty `serverAddress` = client falls through to local bot stage (single-player colosseum).
- Battle runs locally → `POST /colosseum/complete-round-data` on completion
  → `r_colosseum_complete_round` handles score update.
- `POST /colosseum/round-data` = round-in-progress snapshot (ack only, no persistence needed).

### Scoring (server-side, `routes/colosseum.py` + `routes/pvp.py`)
- The server owns the running total; the client owns the battle. A finished round hits
  `/colosseum/complete-round-data` → `r_colosseum_complete_round` (pvp.py:194) → `_pvp_record`
  (pvp.py:52) → `colosseum.apply_result(before, win)` (colosseum.py:111).
- **Delta** comes from `ColosseumRankScoreTable.xml` (`score_delta`, colosseum.py:97): pick the row
  with the highest `ReqScore <= current`, take `WinScore` if win else `LoseScore` (loss deltas are
  negative). Example rows: 0→+300/−70, 1000→+126/−80, 2000→+80/−64, 2450→+73/−62; win at 1000 = 1126.
- **Floor clamp**: `apply_result = max(bottom_tier.reqScore, score + delta)` - a loss cannot push the
  score below the bottom tier's floor (0). Verified: `python3 routes/colosseum.py` self-check.
- **Tier** = `tier_for(score, rank)` from `ColosseumRankTiers.xml` (27 tiers, 0..2400): score-decisive
  below the shared-score tiers; at 2200 the `갓/갓+(31~100/11~30위)` pair and at 2400 the
  `킹갓(6~10/2~5/1위)` trio are split ONLY by the leaderboard rank bracket spelled in their
  `NameComment` (`_rank_bracket`, required for rank>=1; rank 0 = unranked = lowest of the shared tier).
- **Tier rewards**: `r_colosseum_tier_rewards` (`/colosseum/get-reward`) pays every tier ≤ current
  via `tier_rewards_up_to`; each tier pays once (claimed set in `st["colosseumClaimed"]`).
- **Win/loss bookkeeping**: `colosseumWin/Lose` counters, `colosseumTier`, `colosseumLogs` (50 cap,
  ids from a monotonic `colosseumLogSeq`), scores seeded from `response_config.json` `colosseum.fixed`
  (score 1000, season 72, semiSeason 2, theme 3000 = Strife). The 4-player statistics histogram
  `countsByRank` = `[wins, losses, 0, 0]`.
- **Arena shares the machinery** with prefix `pvp`, `ArenaSettings.xml` win-count reward steps
  (`arena_rewards_for`, cumulative counts), and the same `ColosseumRank*` tables for delta/tier.
- Both score tables are unchanged between CDN `2026_09_08` and `2026_09_22` - the update did not
  touch Strife scoring.

### Key RestAPI endpoints (all from script.json)
| Method | Endpoint | Response model |
|---|---|---|
| `RequestColosseumMatchmaking` | `/colosseum/match` | `ColosseumMatchResponseModel` |
| `PingColosseumMatchingResult` | `/colosseum/match/ping` | polling for match result |
| `CancelColosseumMatching` | `/colosseum/match/cancel` | ack |
| `FetchPlayerColosseum` | `/colosseum` | `PlayerColosseumInfoResponseModel` |
| `FetchColosseumPlayersData` | `/colosseum/fetch-players-data` | opponent list |
| `FetchColosseumAddressByGameID` | `/colosseum/server-address` | game server addr |
| `SaveColosseumRoundData` | `/colosseum/round-data` | ack |
| `SaveCompleteColosseumRoundData` | `/colosseum/complete-round-data` | score update |
| `ColosseumGetReward` | `/colosseum/get-reward` | tier rewards |
| `ColosseumReceiveAllRewards` | `/colosseum/all-tier-rewards` | bulk claim |
| `GetColosseumRanking` | ranking path | leaderboard |
| `GetColosseumLeagueRanking` | ranking path | league board |
| `GetColosseumHallOfFame` | ranking path | hall of fame |
| `TestColosseumSinglePlay` | `/colosseum/test-single-play` | same as /match |
| `TestColosseumFreeMatching` | `/colosseum/test-free-match` | same as /match |
| `CreateColosseumCustomMatch` | `/colosseum/create-custom-match` | custom lobby |
| `JoinColosseumCustomMatch` | `/colosseum/join-custom-match` | custom join |
| `ColosseumReenterTried` | `/colosseum/reenter-tried` | ack |
| `ColosseumReenterSucceed` | `/colosseum/reenter-succeed` | ack |
| `CheckColosseumReenterEndGame` | `/colosseum/check-end` | ack |
| `ColosseumRecordMinimumRank` | `/colosseum/record-minimum-rank` | ack |
| `GetColosseumOpenMissionReward` | `/colosseum/open-mission-reward` | reward list |

### Key model offsets (v172.0.01)
- `PlayerColosseumInfoResponseModel.season` = field offset 0x2C
- `PlayerColosseumInfoResponseModel.semiSeason` = field offset 0x54
- `ColosseumPanel._leagueContentRankBox` = offset 0x28
- `ColosseumPanel._matchStartButton` = offset 0x50
- `ColosseumPanel._colosseumEnabled` check via `CheckColosseumEnabled` (RVA 0x32513b4)

### All routes registered
All 33 colosseum routes are in `routes/pvp.py` → `handlers()`. The `r_colosseum_match` returns
empty `serverAddress` to trigger local bot battle. `r_colosseum_complete_round` handles score
delta + tier update. `r_colosseum_round_data` is a no-op ack (client replays own rounds).

### Friendly Battle (custom match) - implemented 2026-08-19
The Friendly Battle ("Trận Giao Hữu") lets players create a private room, share a 6-char code,
and play a colosseum match that **does not affect tier, score, or missions**.

**Client flow:**
1. Host taps "Create Friendly Battle" → `POST /colosseum/create-custom-match` (no args)
   → server returns `{lobbyId: "A3WGBF", endPoint: ""}`. Client copies the code.
2. Guest taps "Join Friendly Battle" → enters the code → `POST /colosseum/join-custom-match`
   with `{matchId: "A3WGBF"}` → server validates, returns `{lobbyId, endPoint}`.
3. Both players call `POST /colosseum/fetch-players-data` with `{isCustomMatch: true}`
   → server returns actual lobby members (not random opponents).
4. Host starts the match → `POST /colosseum/match` → `{gameId, serverAddress: ""}`.
   Empty serverAddress = local bot play (same as regular colosseum).
5. After battle: `POST /colosseum/complete-round-data` - same handler as regular, but
   friendly matches are NOT supposed to affect score. (Currently they still do because the
   client sends the same `win` flag - a `gameType` field would be needed to differentiate.)

**Server implementation:**
- Lobby state stored in SQLite `lobbies` table (migration v5 in `playerdb.py`):
  `code TEXT PK, host_uid TEXT, members TEXT (JSON array), created_at REAL`.
- `lobby_create/code`, `lobby_get/code`, `lobby_join/code/uid`, `lobby_leave/code/uid`,
  `lobby_leave_by_uid/uid`, `lobby_members/code`, `lobby_get_by_uid/uid`.
- Host leaving → lobby deleted. Non-host leaving → member removed, lobby stays.
- Max 4 members per lobby.
- Lobby code: 6-char uppercase alphanumeric, no ambiguous chars (0/O, 1/I/L).
- `_gen_lobby_code()` retries up to 100 times to avoid collisions.
- `_colosseum_custom_players(st)` loads each member's state and returns their
  `ColosseumPlayerData` (deck, buildings, etc.).

**New routes added:**
| Route | Handler | Purpose |
|---|---|---|
| `/colosseum/create-custom-match` | `r_colosseum_create_custom_match` | Generate lobby code |
| `/colosseum/join-custom-match` | `r_colosseum_join_custom_match` | Validate code, join lobby |
| `/colosseum/leave-custom-match` | `r_colosseum_leave_custom_match` | Leave lobby |
| `/colosseum/custom-match-start` | `r_colosseum_custom_match_start` | Start match, return gameId |
| `/colosseum/check-end` | `r_colosseum_check_end` | Reenter: return score delta |
| `/colosseum/reenter-tried` | `r_colosseum_reenter_tried` | Reenter: ack |
| `/colosseum/reenter-succeed` | `r_colosseum_reenter_succeed` | Reenter: ack |

**Key client strings (from Strings_EN_US.xml):**
- `ColosseumCustomMatch` = "Friendly Battle" / "Trận Giao Hữu"
- `ColosseumCustomMatchCreate` = "Create Friendly Battle"
- `ColosseumCustomMatchJoin` = "Join Friendly Battle"
- `InputColosseumCustomMatchCode` = "Enter Participation Code"
- `ColosseumCustomMatchDesc` = "Friendly Battles do not affect your tier, score, and missions."
- `ColosseumCustomMatchRoomFull` = "This room is full!"
- `ColosseumCustomInvalidMatchCode` = "Invalid code."
- `ColosseumCustomMatchHostExited` = "This room has been terminated."
- `ColosseumCustomMatchEmptyItem` = "Empty Slot"
- `ColosseumCustomMatchAddBot` = "Create {0} Bot"

**TODO:** A proper score-skip for friendly matches would require the client to send a
`gameType` or `isCustomMatch` flag in the `complete-round-data` body, which it currently does
not do. For now, friendly matches count toward score like regular matches.

## 14. Frieren Aseprite frame-0 review draft (2026-08-20)

- The prior `server/assets/frieren/Frieren_frame_00.aseprite` / `Frieren_frame_00.png` paths are
  stale (verified absent). The current review-only artifact is the v4 pose-matched redraw
  `server/assets/frieren/drafts/00_frieren_frame_0_v4.aseprite`, with native PNG, 1x/4x/8x
  previews, source-vs-Frieren comparison, constraint JSON, and build entry point at
  `pixel-art/frieren-frame-00/build_frieren_v4.py`.
- Frame 0 is a one-cell 130×140 transparent RGBA redraw. The original sprite is used as the
  pose/layout reference (head, hands, feet, staff diagonal); the illustration and a dedicated
  render supply Frieren identity. The result is palette-locked, nearest-neighbour reduced to the
  68×75 cell, and hard-alpha cleaned. Bbox `(46,38)-(108,109)` is close to source
  `(45,38)-(108,108)`; the illustration itself is not cropped into a sheet.
- This is pending user visual approval only; it does not replace `Unit_10570_03.png` or enter the
  injector/build path. Do not infer or draw frames 1-18 without explicit approval.

## 15. Codex pixel-art skill stack (2026-08-20)

- Codex skills live at `/home/nowl/.codex/skills`. `generate2dsprite` is a symlink to the checked
  Agent Sprite Forge source at `/home/nowl/tools/agent-sprite-forge`; its isolated `.venv` has
  Pillow and numpy. `pixel-art-studio` is a Codex-adapted copy with deterministic Pillow tools,
  Aseprite-compatible JSON export, Codex-specific iterative three-pass instructions, and no
  remaining hard-coded `.claude`/`/Users` installation paths. `pixel-sprite-reskin` enforces a
  source-sheet geometry/pose lock for skins.
- Aseprite CLI (`/usr/bin/aseprite`, v1.3.18.2-dev) and the `aseprite` MCP server are already
  configured in `/home/nowl/.codex/config.toml`; do not replace that configuration. Use
  `/home/nowl/sprite-skill-test/` for a minimal validated 32×32 transparent test asset.

## 16. Generated Frieren production reskin (2026-08-20)

- The complete production review export is now
  `server/assets/frieren/generated/frieren_sprite_sheet_650x560.png`; individual native frames
  are under `generated/frames/00.png` through `18.png`. It is a 5×4 650×560 RGBA atlas with
  130×140 cells and an intentionally transparent cell 19.
- `generated/build_frieren_sprite.py` is the reproducible build: it uses
  `Unit_10570_02_reference.png` strictly for each cell's bbox/baseline/placement and the
  independent Frieren design board strictly for character identity. It hardens every output edge
  to binary alpha and a shared 22-colour Frieren material palette; frame 15-17 use the isolated
  cyan/white silhouette palette. The large source board is retained as
  `generated/frieren_design_master.png`, with 19 high-resolution editable pose crops in
  `generated/design_frames/`; only those crops are reduced once, with NEAREST, for the game atlas.
  Do not replace this with a whole-atlas resize.
- `generated/validate_sprite.py` verifies atlas/frame dimensions and mode, binary alpha, an empty
  final cell, and byte-exact integer grid placement. The last run passed. `geometry_constraints.json`
  records the measured source envelopes and was checked against every output frame.
- Editable outputs are `generated/frieren_sprite_sheet.aseprite` (atlas) and
  `generated/frieren_animation.aseprite` (19 130×140 timeline frames). Its contiguous semantic
  tags are Front_Base 0-4, Left_Base 5-9, Back_Base 10-14, Magic 15-17, Idle 18; the non-contiguous
  runtime loops are recorded in `generated/animation_mapping.json`.
- Accessory correction pass: the staff head now uses the reference's gold ring + red gemstone
  treatment consistently across full/side/back/idle poses, preserving the original shaft angle,
  ribbon anchor, and source geometry envelopes. Rebuild and Aseprite exports were regenerated and
  visually checked after this pass.

## 17. Client UI → web UI fidelity baseline (2026-08-24)

- Do not recreate KGC screens from a screenshot with CSS. Trace the matching-version IL2CPP
  controller first, export the original Unity `Sprite` assets, then capture the actual client
  render as the initial visual baseline. Full playbook: `docs/web-ui-reconstruction.md`.
- Verified Hero Detail is `CardInfoPanel` (v172.0.01 `Show` RVA `0x31829FC`), not the
  in-battle `UnitInfoPanel`. It owns tabs Hero/Growth/Profile/Skin (`0..3`) and actions
  `OnClickToggleDotIllust`, `OnClickUnitStatistics`, `OnClickSkillButton`, `OnClickTab(int)`.
- Prototype: `server/hero-detail-prototype/`. The Farael fixture was captured from the running
  v172.0.01 client; hero art `Unit_Illust_10570` and source UI sprites (frame/tab/item/skill/
  treasure) were exported from v172.0.01 bundles. It is intentionally a visual baseline with
  mapped accessible hotspots, not a claim that the screen's state is already web-native.

## 18. Player Portal Phase 1 (2026-08-27)

- Public portal is `GET /` (with `/player` retained as a compatibility route), served from its own
  `playerportal_server:app` process on internal `:8082` (default public hostname
  `https://player.kingbugcastle.id.vn`), from
  `server/webui-next/out/player.html`; static Next assets are mounted at `/_next`. Game API stays
  `kingbugcastle.id.vn → :8080`; admin stays `admin.kingbugcastle.id.vn → :8081`. Build with
  `cd server/webui-next && ./node_modules/.bin/next build --webpack`. The host needs
  `experimental.cpus=1`: default worker fan-out can exhaust its process limit.
- **Identity invariant:** portal never creates a game account/save. Existing `accounts.login_id →
  uid` is authoritative. `google_<sub>` can obtain portal cookie `kgc_player` only after that
  mapping exists; Guest access can be issued only for an existing `Guest_*` mapping by the admin
  dashboard. Guest credential password rotation revokes portal sessions; database stores SHA-256
  token hashes, not browser tokens.
- `google_login.make_state(target)` signs `game|portal`. Target `game` preserves native poller
  handoff and only `server:app` registers `/glogin/callback`. Target `portal` is accepted only by
  `playerportal_server:app` at `/portal/api/auth/google/callback`, then redirects to `/`
  after issuing only the portal cookie. `playerportal_server:app` calls `playerdb.init()` at startup:
  this matters because it can run without the game API, and portal session tables first appear in
  migration v6. Set `PLAYER_PORTAL_PUBLIC_URL` to that hostname and register
  both its callback and the game callback in Google OAuth. Do not route portal sign-in through
  `/glogin/pending` or change the APK stub.
- `SiteShell` portal branch must test `pathname === "/player" ||
  pathname.startsWith("/player/")`. A bare `startsWith("/player")` also matches admin
  `/players`, omits `PlayerProvider`, and makes `/players` prerender fail with
  `usePlayerSelection must be used within PlayerProvider`.
- Phase 2 uses **Google Ad Manager Rewarded Ads for Web**. `ticket_wallets`,
  `ticket_provider_sessions`, `ticket_provider_events` and `ticket_log` were added in migration
  v7. `POST /portal/api/ticket/video/start` creates an opaque `gam` session after local caps;
  the Next portal loads GPT and only shows the video after `rewardedSlotReady`. Its browser-side
  `rewardedSlotGranted` event calls `POST /portal/api/ticket/video/complete`, which consumes that
  session id as its idempotent event id. Cooldown is 5 minutes, wallet cap 10, daily UTC cap 20.
  This is intentionally weaker than a provider server callback: it is accepted for video-only UX,
  so keep ticket value/caps conservative. Config: `GAM_REWARDED_AD_UNIT_PATH` is an absolute GAM
  ad-unit path such as `/123456789/kgc_player_rewarded`.
- Phase 3 self-grant lives in `playerdb.ticket_redeem_grant()`, not in a route:
  it holds `write_lock` and changes the ticket wallet, audit log, player save and derived
  projections in one DB transaction. The portal only exposes the small fixed catalog in
  `playerportal._GRANT_CATALOG` (Gold 50,000; Heart 10; Item 100×20; Item 150×10). It does
  not expose Cash, heroes, treasures, artifacts or accessories. Mail text is stored without
  `@raw:`; `routes.inbox._process_posts()` adds that prefix only on the game wire. Focused proof:
  `python3 server/tests/test_grant_self.py` verifies mail/ticket atomicity, concurrent spending,
  and that a stale login mapping cannot consume a ticket.

### Public portal deployment (2026-08-28)

- Public state is a distinct SQLite file on OCI (`/home/ubuntu/kgc/server/state/players.db`), not
  the workspace DB. The Player Dashboard must run on the OCI host to share its game account,
  ticket and mailbox transactions. It is enabled as `kgc-playerportal.service`, bound only to
  `127.0.0.1:8082`; its first start migrated the live database from schema v5 to v8 after the
  normal automatic backup.
- Caddy owns public `80/443` and proxies `kingbugcastle.id.vn → :8443`,
  `admin.kingbugcastle.id.vn → :8081`, and `player.kingbugcastle.id.vn → :8082`. Its tracked
  sources are `systemd/caddy.service` and `systemd/kgc-public.Caddyfile`; it runs unprivileged
  with only `CAP_NET_BIND_SERVICE` and reads a root-owned copy of the existing self-signed origin
  key. Cloudflared is instead a Docker container (`cloudflare/cloudflared`, bridge networking,
  restart `always`), whose remotely managed Zero Trust ingress currently owns the public hostnames.
  The portal must remain loopback-only: do **not** point its tunnel service at
  `http://213.35.110.245:8082`, because Docker cannot reach that listener. Route it via Caddy
  (`https://213.35.110.245:443` with origin TLS verification disabled for the self-signed
  certificate) while retaining the `player.kingbugcastle.id.vn` Host header. The external hostname
  must also have the Cloudflare Tunnel CNAME/DNS route; a tunnel ingress rule alone does not publish
  DNS. Origin Caddy health returned HTTP 200 for the player host header.

### Player Portal Phase 4-5 (2026-08-28)

- Requests: `grant_requests` (v8) records the resolved game uid at submit time. Submit debits one
  ticket and writes `ticket_log(request)` in the same transaction; approval mails the admin-selected
  reward, denial refunds exactly one ticket and mails the reason. `resolve_grant_request()` owns its
  flock, so dashboard's generic write middleware must skip `/api/requests/*` to avoid a nested
  `flock` deadlock. UI: portal request panel + admin `/requests`. Proof:
  `test_requests.py` and `test_requests_api.py`.
- Donations: v9 adds `donations`, including `credited_at`, `credited_by` and `credited_tickets`.
  A portal note is only an acknowledgement - it cannot credit tickets. `admin_credit_tickets()` is
  the sole credit path, logs `admin_topup`, and atomically marks a donation credited so retries fail.
  The player form is available both on the dashboard and `/player/donate`; admin UI is `/donations`.
  `PLAYER_DONATE_INSTRUCTIONS` comes from optional `/etc/kgc/playerportal.env`, deliberately blank
  until an operator supplies payment instructions. Proof: `server/tests/test_donate.py`.

## 19. Project audit - release blockers (2026-08-28)

- **Route coverage now defaults to v172.0.01** and accepts
  `KGC_IL2CPP_SCRIPT_JSON` for an extracted artifact elsewhere. The verified v172.0.01 artifact is
  at `il2cpp/v172.0.01/script.json` locally (SHA-256
  `27349c11aafdae1632719de6d017d0409456be927dfff7044075892204a33445`); it is intentionally
  untracked because it is generated from the proprietary client. It contains 261333 methods and
  25742 strings; the v172.0.01 anchors `GetRankingServerEndPoint` (`0x2CBF2C4`),
  `RegisterHackDetectionCallback` (`0x34E4EDC`), and `CheckFirebase` (`0x30479B8`) match. Keep
  this exact artifact alongside the deployed server, or set `KGC_IL2CPP_SCRIPT_JSON` to its
  absolute location. Do not substitute the known-stale generated route list.
- **OAuth state secret hard-code removed.** Public/portal scripts and the portal systemd unit now
  require `GLOGIN_STATE_SECRET` from deployment configuration; preflight fails if real Google OAuth
  is enabled without it. The old tracked value must be treated as leaked and rotated on the host.
- **Direct request readers share the streaming cap.** `security.read_capped_body()` is used by the
  generic dispatcher, direct accessory/post routes and admin mail; an oversized chunked request
  receives 413 before it is buffered. Proof: `server/tests/test_body_limit.py`.
- **Sensitive debug logs removed from served routes.** Dashboard no longer prints request headers;
  game/auth/shop/rift/artifact routes no longer write whole request bodies or cookie fragments.
  `r_card_use_candy` must not create `scroll_debug.txt`: that untracked runtime file dirties the
  production checkout and makes the guarded deploy hook refuse every later rollout.
- **Public deployment configuration is externalized.** `serve_public.sh` and `deploy_hook.sh` load
  `/etc/kgc/server.env` (override `KGC_ENV_FILE`) before preflight; on a personal machine with no
  `/etc/kgc`, they fall back to ignored, mode-600 `server/secrets/server.env`. Stand-alone
  `preflight.py` reads the same simple `NAME=value` configuration without executing it as shell
  code. This makes the OAuth state key, v172 `script.json` location, and proxy/loopback pairing
  survive non-interactive deploys. `deploy_hook.sh` now refuses a dirty checkout and
  dependency-install failure instead of stashing, swallowing errors, and potentially reloading an
  inconsistent tree.
- **Public OAuth origin respects deployment configuration.** `serve_public.sh` now treats
  `https://kingbugcastle.id.vn` as its fallback only; an operator-provided `GLOGIN_PUBLIC_URL` from
  `/etc/kgc/server.env` is no longer overwritten after that file is loaded. Proof:
  `server/tests/test_deploy_config.py`.
- **Public XAPKs can now use either the Cloudflare hostname or the origin IP.** The CI workflow
  accepts `glogin_poll_port` (public default `80`), and `build_private.py` patches that value into
  the native raw poller; local builds keep their `:8080` default. `kgc-public.Caddyfile` proxies
  both `kingbugcastle.id.vn` and `213.35.110.245` to the loopback TLS game service. The direct-IP
  routes strip client-supplied Cloudflare/forwarded-IP headers and replace `X-Forwarded-For` with
  Caddy's peer address; the domain route accepts only Cloudflared's private Docker bridge before
  preserving `CF-Connecting-IP`. This retains the source-address invariant of the Google native
  handoff while allowing either baked `share_host`. Regression proof:
  `test_public_caddy_serves_the_game_through_domain_and_origin_ip_safely` and
  `test_native_poll_port_is_patched_relative_to_the_browser_host_buffer`. The Caddy binary is not
  installed in this workspace, so validate and reload `/etc/caddy/Caddyfile` on the origin before
  releasing the XAPK.
- **Preflight refuses the dev Google-login bypass.** `GLOGIN_DEV=1` can create an authenticated
  session without real OAuth and is valid only for a local development command. It is now a FAIL,
  not a WARN, so `serve_public.sh` cannot expose it accidentally. Proof:
  `test_preflight_refuses_the_google_dev_login_bypass`.
- **GAM rewarded-video completion is browser-asserted, not provider-verified.** The portal now
  rejects both browser start/complete calls with 503 even if an ad-unit path is configured; tickets
  stay protected until a provider-verifiable server callback calls the existing accounting helper.
- **Standalone portal gets the same public request boundary.** `CappedBodyMiddleware` limits bytes
  at the ASGI receive layer before FastAPI can buffer a chunked `body: dict`; checking only
  `Content-Length` or guarding route readers leaves that bypass. `security.register_portal()`
  installs this cap and the shared per-IP rate limiter for `playerportal_server:app`, without taking
  the game-save lock (portal ticket/grant transactions retain their own DB lock). Proof:
  `server/tests/test_portal_body_limit.py`. It buffers no more than the cap and replays with
  Starlette's own `_CachedRequest` receive bridge, preserving nested middleware's response-disconnect
  lifecycle rather than fabricating a disconnect itself.
- **Dashboard uses the public boundary too.** `dashboard.py` owns its own cross-process transaction
  lock, but its `body: dict` administration endpoints were otherwise outside the game middleware.
  It now installs `security.register_public()` in the enforced order: body cap → rate limit → admin
  guard → Dashboard write lock. This prevents oversized or unauthorized writes from occupying the
  lock while retaining Dashboard's atomic edits.
- **Dashboard mutations have a server-side CSRF check.** When a browser sends `Origin`, it must
  match the dashboard host (using `X-Forwarded-Proto` only under trusted-proxy mode); a foreign
  origin receives 403 before the admin/session logic. Origin-less local operator calls remain
  supported. Proof: `server/tests/test_dashboard_origin.py`.
- **Dashboard admin cookies are HTTPS-only when the browser is HTTPS.** Local direct HTTP remains
  available for development, while a trusted public proxy's `X-Forwarded-Proto: https` now sets the
  `Secure` cookie attribute. This prevents the authenticated cookie from being sent over a later
  cleartext request to the same dashboard host. Proof: `test_dashboard_cookie_is_secure_only_for_the_browser_facing_https_scheme`.
- **Dashboard static fallback stays inside its export root.** Route paths are resolved before every
  `FileResponse` and must remain under `webui-next/out`; a `..` traversal can no longer read Python
  source, secrets, or arbitrary sibling files from the dashboard origin. Proof:
  `test_dashboard_static_fallback_cannot_escape_the_export_root`.
- **Manual portal launch matches systemd.** `serve_playerportal.sh` now loads
  `/etc/kgc/playerportal.env` (override `KGC_ENV_FILE`), binds `127.0.0.1` by default, and rejects
  `KGC_TRUST_PROXY=1` on a non-loopback bind. This prevents its old `0.0.0.0` default from exposing
  a service intended to live behind Caddy/Tunnel. `bash -n` and the invalid trust/bind combination
  were checked.
- **The development stack is a cross-platform Python TUI and loopback-only by default.**
  `server/run.py` supervises game HTTP/TLS, admin, and Next.js on Linux/macOS with POSIX sessions
  and on Windows with native process groups plus `CTRL_BREAK_EVENT`/`taskkill` fallback. It finds
  both `.venv/bin` and `.venv/Scripts`, stores logs in the platform temp directory, and gets curses
  from the conditional `windows-curses` dependency on Windows. Enter/a/x/r control processes,
  `d` wires ADB, and `q` stops the owned groups. All services bind to `127.0.0.1`; LAN testing remains
  an explicit `KGC_DEV_BIND_HOST=0.0.0.0` opt-in. Proof:
  `test_development_launcher_binds_loopback_unless_lan_access_is_explicit` and
  `test_development_launcher_stops_the_process_group_it_started`, plus the simulated Windows
  process-group/configuration checks in `server/tests/test_deploy_config.py`.
- **Google pending handoff is address-bound.** The old fallback consumed the newest pending entry
  for *any* source address (and, in local split-brain mode, fetched an entry from a different
  server). Because the result is a Google account id accepted by `/auth`, that was an account
  takeover path. `_get_and_clear_pending()` now reads only its hashed source-address slot and
  `_client_ip()` delegates to `security.client_ip()`, so forwarded headers are trusted only under
  the existing loopback-bound proxy invariant. Runtime `.glogin_pending_*` handoff files are ignored
  by git. Proof: `server/tests/test_google_pending_security.py`.
- **Google pending handoff is atomically published and claimed.** The OAuth callback now writes a
  temporary same-directory file and atomically replaces the address-bound slot. Pollers atomically
  move that slot into a unique claim file before reading it, so they cannot see an empty partial write
  or return the same account id twice during an overlapping native-poller transition. Proof:
  `test_pending_google_account_is_published_and_consumed_once`.
- **Native `/auth` cannot mint a session for an arbitrary Google ID.** The endpoint previously
  treated query parameter `id=google_<sub>` as proof of Google authentication, which permitted a
  caller who knew an ID to obtain that account's bearer token. Retrieving `/glogin/pending` now issues
  a 60-second, one-time, address-and-account-bound native-auth grant; `/auth` consumes that grant
  before it can mint a session. The grant is atomically claimed and rejects different IDs, addresses,
  replays, and expiry. Proof: `test_native_google_auth_grant_is_address_bound_fresh_and_single_use`;
  the full native-route test now proves a direct request is denied before the poller handoff.
- **Runtime maintenance is UTC-aware and lifecycle-owned.** `common.now_iso()` and
  `next_reset_iso()` now use `datetime.timezone.utc`, preserving the client wire format while
  avoiding deprecated naive UTC APIs on supported Python versions. The backup worker is owned by
  FastAPI's lifespan context and is cancelled on shutdown rather than escaping as an orphan task.
  A direct lifespan check confirms exactly one worker starts and none remains afterward.
- **Save reads repair malformed card/deck shape before handlers see it.** A raw-save edit with a
  non-numeric card key, non-dict card/deck, or malformed deck slot previously raised inside
  `playerdb.load()` and made the entire account unloadable. The persistence layer now drops invalid
  cards/entries, normalizes card identity/level, and returns exactly six valid-or-empty deck slots
  plus six non-negative potential slots. Proof: `test_load_repairs_malformed_cards_and_decks_before_routes_use_them`.
- **Account lookups reject non-string credential values.** `/auth/login` may carry its prior token
  in decoded JSON; a dict/list was previously passed to SQLite as a bind parameter and raised
  instead of simply being treated as an unknown token. `uid_for_token()` and `uid_for_login()` now
  enforce their string contract at the shared persistence boundary. Proof:
  `test_identity_lookups_reject_non_string_values_before_sqlite_binding`.
- **External login IDs are bounded database keys.** Identity is now a non-empty string of at most
  256 characters before it can reach the `accounts` index. Auth treats malformed IDs as absent while
  preserving a valid token-refresh path; `bind_login()` rejects them at the persistence boundary so a
  future caller cannot retain an arbitrary request blob. Proof:
  `test_login_identity_is_a_bounded_string_before_persistence` and
  `test_auth_rejects_a_malformed_new_identity_but_allows_session_refresh`.
- **`accountId` is immutable through generic/raw admin saves.** It is the player's unique targetId
  for rankings and profile lookups; a malformed value used to make a leaderboard's integer conversion
  fail, and a pasted duplicate broke identity. `backfill_account_ids()` now treats unparsable IDs as
  missing, while both generic and raw admin writes preserve the row's existing uid/accountId. Proof:
  `test_backfill_repairs_malformed_account_ids_as_missing_identity` and
  `test_dashboard_raw_save_preserves_the_player_account_identity`.
- **Dashboard macro `legacy_max` parses artifact XML correctly.** It referenced `ET.parse()` without
  importing ElementTree, so the macro always failed before granting relics/treasures. The XML parser
  is now imported at the module boundary; a direct macro test executes the branch and verifies maxed
  artifacts plus level-30/overcome-10 treasures.
- **The WebUI standard is pnpm 11.3.0.** `package.json`, development launcher, portal guidance and
  operator docs invoke `pnpm run ...`; existing installed binaries still validate TypeScript and
  ESLint in the restricted environment. pnpm 11 defaults `verifyDepsBeforeRun` to `install`, so the
  launcher passes `--config.verify-deps-before-run=false`; otherwise starting Next.js tries to
  migrate/install the legacy npm-only graph and fails on ignored build scripts. Do not manufacture
  `pnpm-lock.yaml`; migrate it deliberately on a networked development host.
- **Static WebUI export has no production Next proxy.** The `/api/*` rewrite is declared only for
  `next dev`; dashboard and portal serve the exported files themselves in production, so a rewrite
  declaration there is both inert and makes Next warn. `outputFileTracingRoot` is pinned to the
  repository root so an unrelated parent-directory pnpm lockfile cannot expand tracing. A full
  webpack export now builds all 16 static pages without warnings.
- **Runtime dependencies have one authoritative file.** Root `requirements.txt` is the tested
  server runtime contract; `server/requirements.txt` includes it for compatibility and adds
  UnityPy for asset/build flows plus cryptography for setup's cross-platform TLS certificate
  fallback. CI installs the runtime contract plus pytest (not the unused
  `httpx2` package), and CI/deploy path filters include root dependency changes so a dependency
  update cannot silently skip validation or rollout. Workflow YAML parses and the current focused
  test selection passes.
- **Verification drift:** CI currently collects 69 pytest tests; many route-contract checks are standalone
  `check_*` functions and are absent from CI. The WebUI TypeScript and ESLint gates now pass cleanly:
  raw endpoint payloads are narrowed into page-level response types, polling/state synchronization is
  documented at the exact effects that own it, and static image usage uses `next/image` unoptimized
  for the export. Use `pnpm` for future frontend operations; the current tree still has only the
  npm lockfile, and an attempted pnpm import cannot complete in the restricted environment because
  the registry is unavailable. Perform that lockfile migration deliberately on a networked host.
  `pytest.ini` pins pytest-asyncio's pending default to a function-scoped loop. On this Python 3.14
  environment, both Starlette `TestClient` and `httpx.ASGITransport` block before returning from a
  synchronous FastAPI endpoint (reproduces with an empty app); this is a framework/runtime harness
  defect, not evidence of a server deadlock. Use focused async-transport tests here or a compatible
  runtime/real Uvicorn listener for the legacy synchronous-route tests.
  There is also a large dirty worktree (225 entries on audit), including tracked generated frontend
  output; establish an owner/clean-build policy before merging unrelated work.
- **APK bundle extraction never invokes a shell.** The editing and art-export CLIs share
  `server/cli/bundle_extract.py`, which validates the APK path and invokes `unzip` with literal
  argument-list semantics. A pathname containing shell metacharacters is therefore data, not code;
  missing APKs fail before extraction. Proof: `server/tests/test_bundle_extract.py`.

### Blacksmith and legacy Dominion recovery (2026-08-30)

- `/artifact/crafting`, `/artifact/merge`, and `/artifact/polish` must mutate the saved
  `ArtifactModel` rows; returning the correct response model with empty `results` only makes the
  Blacksmith UI appear to succeed. Crafting charges 25/50/100 dust for Normal/King/God, merging
  consumes three matching relics into the next tier within the XML `Root` family, and polishing
  consumes Artifact ids 901/902/903 using their `AddPolishPoint` before increasing one option level.
  `ensure_artifact_state()` seeds those three client-renderable polishing stones at 99,999 while
  keeping incompatible synthesis stones excluded. Proof: `python3 server/tests/test_artifact_blacksmith.py`.
- Tutorial #40 needs a server-side snapshot containing Chamber `10001` at `posIndex=1` and Inn
  `10101` at `posIndex=0`; it hides and reveals those rows locally. `_terr()` repairs an empty
  persisted plot to that snapshot. Proof: `python3 server/tests/test_territory.py`.

### Official v172.0.01 XAPK → AssetRipper Unity project (2026-08-30)

- The official source is `apk/com.awesomepiece.castle@172.0.01.xapk` (package
  `com.awesomepiece.castle`, SHA-256
  `c34c717620216121b11f031c5783c99afdc279c2c496810595f69d01f33a42ac`). Do not use the
  root `KingBugCastle_172.0.01.xapk`: its manifest identifies it as the private
  `com.nowl.castle` build.
- AssetRipper 1.3.3 needs an Android directory containing the official
  `assets/bin/Data` tree, matching `global-metadata.dat`, and a decoded
  `lib/arm64-v8a/libil2cpp.so`. For this release, take `base_assets.apk` and
  `config.arm64_v8a.apk` from the official XAPK, extract `assets/bin/Data/*` and
  `libunity.so`, then place the version-matched recovered
  `il2cpp/v172.0.01/libil2cpp_v17201_ssl.so` at that libil2cpp path. The three
  SSL return patches do not affect AssetRipper's static IL2CPP type recovery.
- The process opens more than the shell default 1024 descriptors. Run it with a
  process-local `ulimit -n 16384`:
  `AssetRipper.GUI.Free --cli --input <game-dir> --output <output-dir> --mode unity --script-content-level Level1`.
  With the installed binary at
  `/home/nowl/.local/share/rg-toolkit/tools/AssetRipper/AssetRipper.GUI.Free`, the
  initial output was `unity/king-god-castle-v172.0.01/ExportedProject/` (ignored
  as generated data): 694 MB, Unity `2022.3.62f3`, 26,650 asset files, 2,285 C#
  stubs, six scenes, 65 prefabs, and 30 shaders. It was incomplete: the prepared
  input omitted the Addressables bundles holding the hero content. Do not reuse it.
- Do not open this Level1-script export as a runnable/editable game project.
  On Unity `2022.3.62f3`, its generated stubs have three ambiguous
  `YieldAwaitable` references (`StoryModeBasePanel.cs:125,243` and
  `ChangeBGMVolumeNodeData.cs:67`), then the editor itself SIGSEGVs during
  `MonoScriptInfoScraper::ScanForSourceGeneratedMonoScriptInfo` on its initial
  assembly reload. The reliable viewer-oriented export is AssetRipper with
  `--disable-script-import` (or stubs preserved outside `Assets/` as text);
  keep Level1 stubs only for static inspection, not Unity compilation.
- For the already-exported `v172.0.01` viewer, move `Assets/Scripts` (and its
  `.meta`) to `AuxiliaryFiles/GeneratedScriptStubs`, and `Assets/Plugins` (and
  its `.meta`) to `AuxiliaryFiles/GeneratedGameAssemblies`, then delete only
  that project's `Library/`. The second move matters: AssetRipper copied 97
  game-runtime DLLs, including `Assembly-CSharp.dll` and `UnityEngine.*`; after
  scripts are removed Unity still SIGSEGVs at `MonoManager::ReloadAssembly` if
  it loads them as Editor plugins. Two clean batch launches completed with exit
  code 0 after both moves. AudioClip import emits FSBTool errors because the
  extracted files are not valid desktop WAV/OGG payloads; retain them as viewer
  data because the warnings are non-fatal.
- **Correct hero export (2026-08-30, shader fix 2026-08-31):** extract the original `base_assets.apk`'s
  `assets/aa/Android` bundles directly; the prior convenience copy under
  `apk/xapk_extracted_v17201/bundles/` contained a zero-byte
  `sprites_assets_all_*.bundle` and must not be trusted. A full 81-bundle input
  currently triggers AssetRipper 1.3.3's internal `atlas is not the same as
  mappedAtlas` exception. The working viewer input is the six original bundles
  `characters`, `prefabs`, `sprites`, `illusts`, `shaders`, and
  `*_unitybuiltinshaders_*`; it exports 79,801
  assets to `unity/king-god-castle-v172.0.01/ExportedProject-heroes/ExportedProject/`.
  The first four-bundle export was not visually valid: 414 of 458 materials,
  including the `Sprites-Default` material used by hero prefabs, referenced
  AssetRipper's fake `0000000deadbeef15deadf00d0000000` shader GUID and rendered
  white/magenta in Unity. Re-exporting all six resolves built-in material refs to
  `0000000000000000f000000000000000` and leaves zero material references to the
  fake GUID. Use `--disable-script-import`; Unity 2022.3.62f3 batch-imported the
  corrected project with exit 0.
  Hero assets retain their original hierarchy, especially `Assets/00_Unit/`:
  verification found 1,316 prefabs, 1,352 `Unit_*.png` textures, and 279
  illustrations. It has no imported C# stubs or DLL plugins.

### Official v173.1.00 XAPK → AssetRipper Unity project, FULL 81-bundle export (2026-09-24)

The `atlas is not the same as mappedAtlas` failure on a full input is a known
AssetRipper bug (issue #740, Skul) — **not** a reason to drop the 64
`spriteatlases_assets_atlas_*` bundles. The fix (PR #2318, still unmerged at
2.0.0) is 2 source files; Recipe:

- **Source + patch.** Clone AssetRipper at commit `1ac666f4` (= v2.0.0) to
  `/home/nowl/AssetRipper-2318/` and apply PR #2318 by hand:
  `Source/AssetRipper.Processing/Textures/SpriteInformationObject.cs` (drop the
  `throw` when the same sprite is mapped by two different atlas instances) and
  `SpriteProcessor.cs` (prefer the direct atlas mapping). Build with
  `-p:PublishAot=false` (JIT; no clang/AOT needed) → `out-free/AssetRipper.GUI.Free`.
- **The built binary has NO `--cli`.** Public source `Arguments.cs` only parses
  Port/Log/LogPath/LocalWebFiles/Headless — the `CliRunner` exists only in the
  rg-toolkit binary build, do not pass it `--cli`. Write a wrapper instead:
  `/tmp/opencode/arcli` (`Program.cs` calls `GameFileLoader.LoadAndProcess` +
  `ExportUnityProject` with `Headless=true`, `ScriptContentLevel.Level0`; run via
  `dotnet bin/Release/net10.0/arcli.dll <input> <output>`). `dotnet 10.0.112` available.
- **Input = full 81 bundles** from `base_assets.apk`: the 17 content bundles
  (`characters`, `prefabs`, `sprites`, `illusts`, `shaders`, `*_unitybuiltinshaders_*`,
  `storymodedata_assets_all`, …) **plus all 64** `spriteatlases_assets_atlas_*`
  (accessoryicon…unitrelateduis, ui_*), plus `assets/bin/Data`. Staging:
  `/tmp/opencode/kgc_v1731_input/`. Run under `ulimit -n 16384`; export to
  `/home` (NOT `/tmp` — tmpfs is 7.7G and runs dry mid-export, EXIT=134).
- **Output** (gitignored): `unity/king-god-castle-v173.1.00-ExportedProject/
  ExportedProject/Assets`. Logs: `/tmp/opencode/ar_v1731_fixed.log` (success,
  EXIT=0) vs `ar_v1731_full.log` (pre-patch atlas crash). Export adds one layer:
  root output contains `ExportedProject/Assets` + `AuxiliaryFiles`.
- **Verification (post-patch, all 81 bundles):**
  - 168 `sactx-*` atlas textures exported as PNG (e.g. `Texture2D/sactx-0-2048x2048-
    Uncompressed-UI_Icons-8aee2437.png` = the UI_Icons atlas). Pre-patch/atlasless
    export had zero. All 50 distinct `m_AtlasTags` found in sprites have a
    matching sactx texture — no atlas pixel data missing.
  - **56,294 / 58,034 sprites (97%)** have valid `m_RD.texture` (atlas-packed
    sprites now bind to their atlas texture; `InventoryItem_3302.asset` →
    `m_RD.texture {guid: 2e1d1b1d…}` = the UI_Icons sactx PNG, previously `fileID: 0`).
  - The remaining 1,740 with `m_RD.texture: {fileID: 0}` all carry a non-empty
    `m_RenderDataKey` + `m_AtlasTags` — they are atlas-packed sprites whose
    texture lives in the SpriteAtlas `RenderDataMap`, not in the sprite. Their
    pixel data IS in the exported sactx PNG. AssetRipper clears `m_SpriteAtlas`
    (`SpriteProcessor`) after processing and only back-fills `m_RD.texture` when
    it re-derives the packed-sprite texture, which fails for sprites serialized
    *inside* an atlas bundle (e.g. `Sprite/HPBar_Rework_04.asset`, atlas
    `UnitRelatedUIs`). This is a Unity-serialization artifact, not data loss;
    a textures-`fileID: 0` count must regex the `m_RD:` block only (`m_AtlasRD:
    texture: 0` is normal — raw grep counts 32,637 false positives).
  - Counts vs the atlasless export: Textures 6,125 → 6,192 PNG; AudioClips 1,608
    and AnimationClips 4,372 / Prefabs 6,068 unchanged. `Sprite/<name>_0.asset`
    files are name-collision variants (same-master sprite from a second bundle)
    and often hold the recoverable texture twin.

- `/home` and the KGC worktree share `/dev/nvme0n1p3`; freeing `/tmp` or `/var`
  does not increase the space reported to Unity for this project. Prioritize
  user cache and ignored, reproducible KGC build directories. In this worktree,
  `.rebuild_v17201` and `.rebuild_local` are disposable output; keep `unity/`,
  `apk/`, `il2cpp/`, and the worktree data unless a task explicitly supersedes
  them.
- The high-impact user cache is `/home/nowl/.cache` (not source data). System
  package cache and journal cleanup require local sudo: `paccache -r -k 2`
  retains two package versions per package, and `journalctl --vacuum-size=500M`
  retains a 500 MB journal. Never use broad deletion against Android SDK,
  emulator data, Downloads, or locally installed model directories without an
  explicit replacement/retention decision.
- **Unity Hub exception:** it requires the writable directory
  `~/.cache/unityhub/tmp` during an Android NDK module post-install rename. If
  `.cache` has been cleared, recreate it with `mkdir -p ~/.cache/unityhub/tmp`
  before retrying; otherwise Hub reports "Android NDK Install failed" with
  `ENOENT` from `mkdtemp`, even after checksum validation and extraction passed.
### Official v174.0.00 XAPK → AssetRipper Unity project (2026-10-08)

Same pipeline as v173.1.00 above; only the deltas are listed. Source:
`./kgc-cli download -v 174.0.00 -o apk/` → `apk/com.awesomepiece.castle@174.0.00.xapk`
(1.08 GB; XAPK holds `base_assets.apk` 950 MB + `config.arm64_v8a.apk` 153 MB).

- **Packer is `libxpoulled.so`** (115 MB, `SONAME = libappsign4a.so`) - filename
  rotates again, never match on it. `patchers/unpack_neo.py` needed no change
  (still TARA v4): `unpack_neo.py libxpoulled.so libil2cpp_v17400.so` → 115,323,624 bytes.
- **The `arcli` wrapper now lives at `tools/arcli/`** - it had been in
  `/tmp/opencode/arcli` and was wiped, so this cycle it had to be rewritten from
  scratch (`tools/` is gitignored, so it survives on disk, not in git). It is 20
  lines over the patched AssetRipper clone; build `dotnet build -c Release`, run
  under `ulimit -n 16384`, usage `arcli <input> <output> [level]` (level matters -
  see the rebuild-project section below). The `dump.cs` set-diff used below is
  `tools/dump_diff.py`.
- **Il2CppDumper aborts before writing anything when stdin/stdout is redirected**
  ("Press any key to exit..." → `InvalidOperationException` → core, EXIT=134, and
  *no* `dump.cs` on disk even though every stage printed `Done!`). Wrap it in a
  pty: `script -qec "dotnet Il2CppDumper.dll <lib> <metadata> <outdir>" /dev/null`.
  Output for this build: `il2cpp/v174.0.00/` (`dump.cs` 44 MB, `script.json` 122 MB,
  `il2cpp.h` 122 MB, `stringliteral.json`, `DummyDll/`).
- **Input staging** unchanged: `assets/bin/Data/*` (1,625 files, 0.47 GB) + all
  `assets/aa/Android/*.bundle` (81) + `lib/arm64-v8a/libunity.so` + decoded
  `libil2cpp.so` → `/tmp/opencode/kgc_v174_input/` (1.1 GB). Temp apks and the
  staging dir are disposable; the XAPK in `apk/` is the canonical source.
- **Output**: `unity/king-god-castle-v174.0.00-ExportedProject/ExportedProject/`
  - 187,360 files, 2.6 GB, EXIT=0. 6 scenes, 6087 prefabs, 5,166 PNG,
    33,210 `Sprite/*.asset`, 152 `sactx-*` atlas textures, 1,611 audio files.
    Sprite texture binding is healthy: **32,118 / 33,210 (97%)** have a non-zero
    `m_RD.texture`; the 1,092 `fileID: 0` are the known in-atlas serialization
    artifact (their pixels are in the sactx PNGs).
  - `Assets/Scripts` (4,707 Level0 dummy stubs, comment-only bodies) was moved to
    `AuxiliaryFiles/GeneratedScriptStubs/` straight away, as with v172/v173 -
    they are useless for reading code (use `dump.cs`) and would break an editor
    assembly reload. No `Assets/Plugins` is produced at Level0.
- **Disk**: `/home` was at 100% (2.6 GB export fits with ~1.9 GB left). `uv cache
  clean` freed only 35 MB despite `du` showing 6.5 GB (hardlinked/sparse), so the
  real reclaimable space is elsewhere - check `du -sh /home/nowl/*` before assuming
  a cache will save you. **The single biggest recurring leak is
  `~/.local/share/rg-toolkit/tools/AssetRipper/temp/`** - the rg-toolkit GUI build
  leaves per-run work dirs there (13 GB after the v173 exports, plus old export
  logs in the same folder); it is pure cache, delete it after every export. Also
  recoverable without touching any real data: `~/.local/share/Trash`, `Code/kgc/
  .rebuild_*`, and `~/.cache/*`. A disk cleanup on 2026-10-08 took `/home` from
  1.7 GB to 78 GB free; `redroid-data` (the Android 12 test volume) and the docker
  images were deliberately kept.

**What v174.0.00 adds** (diff vs v173.1.00: `tools/dump_diff.py` on both `dump.cs`, and
a set diff of both `stringliteral.json`): +64 classes / 0 removed, +215 / -19 string
literals.

1. **Single Arena - a whole new mode.** 20 new `SingleArena*` classes (panels,
   deck-choice/match/log/ranking/reward UI) plus `ResourceSingleArenaSetting`,
   7 `SingleArena*ResponseModel`/`RequestModel`, and 10 new endpoints:
   `/single-arena/{info,matching,matching-reroll,fetch-log-history,mission-reward,
   rank-reward,rank-all-rewards,reward-info}` and `/ranking/single-arena-ranking`.
   New master-data file `SingleArenaSettings.xml`; deck/match constants
   (`Constants.SINGLE_ARENA = 210`, `MATCH_*`, `DECK_TYPE_*`), daily counters
   (`DailyAttackCount`, `DailyMatchRerollFreeCount`, …), AP/lose-point fields.
   Nothing routes these yet in `server/server.py` → unknown paths fall back to the
   empty `ResponseModel`.
2. **Video playback subsystem** (`VideoPlayer`, `VideoUrl`, `VideoCache`,
   `VideoIntroLoopPlayer`, `VideoOverlayPlayer`, `SeasonEventPanel`): lobby /
   season-event background videos, downloaded from
   `https://storage.googleapis.com/kgcastle_patch/` (new external host!) with a
   local cache (`[Video] Cache hit/download started` log strings) and a new
   master-data file `Videos.xml`.
3. **6th anniversary**: `Lobby_6th`, `SixthYearDailyAttendanceEvent*` (incl. a
   premium track), `SurpriseAttendanceEventID`, `ForceEventLobbyBGM` /
   `SavedEventLobbyBGM`; `Constants.DEFAULT_LOBBY_BGM = "Advisor_40070"` was
   removed (that literal and `MoonEventIllustAvailable_20260908` dropped out too -
   the Moon event is over).
4. Smaller: `CombatPowerCalculator.CalculateCombatPower` gained an
   `int[] territoryStatBuffPers` argument (territory stat buffs now count toward
   combat power - ranking scores shift), `GiveSoulIfAlreadyHasUnit`,
   `IncarnationOvercome`, `TerritoryHuntingDifficulty_1..3`, `PassSkinUntilSeason`,
   `RankTier`/`RankTiers`, `HasSeasonEventPanel`, and an internal QA host moving
   `10.0.1.31:7070` → `10.0.1.41:7070`.

### Official v174.1.00 XAPK → AssetRipper Unity project (2026-10-22)

Same pipeline as v174.0.00; deltas only. Source: `./kgc-cli download -v 174.1.00 -o apk/`
→ `apk/com.awesomepiece.castle@174.1.00.xapk` (1.04 GB; `base_assets.apk` 957 MB +
`config.arm64_v8a.apk` 154 MB).

- **Packer is `libbaningan.so`** (116 MB, `SONAME = libappsign4a.so`). `patchers/unpack_neo.py`
  needed no change (still TARA v4) → decoded `libil2cpp.so` 115,695,304 B.
- Export took **2m10s** (dotnet JIT warm, Level0) to
  `unity/king-god-castle-v174.1.00-ExportedProject/ExportedProject/` - 198,104 files / 2.9 GB,
  EXIT=0. 81 bundles, all re-hashed but the bundle *set* is identical to v174.0.00. 168 `sactx-*`
  atlas PNGs, 6,097 prefabs, 6,268 `Assets/Texture2D/*.png`, 4,384 anim, 2,007 controllers.
  `Assets/Scripts` (4,713 Level0 stubs) moved to `AuxiliaryFiles/GeneratedScriptStubs/` as usual
  (no `Assets/Plugins` at Level0).
- Cheaper asset delta used instead of a second full export: dump `type<TAB>name` for every object
  in each bundle set with UnityPy and set-diff. v174.0.00 vs v174.1.00 = **+165 / −11** unique
  objects (Sprite +60, GameObject +45, Texture2D +30, Material +10, AnimationClip +9, MonoScript +6,
  Mesh +2, AnimatorController +2, MonoBehaviour +1). 15 s per version, answers "what art is new".
- **New hero 10820 `Yhoundeh`** ("Hansi", East/Swift/Arrow, first **Incarnation**
  (`<IsIncarnationUnit>true`) unit): 28 sprite frames 110x140 from a 440x980 sheet, illust 1024²,
  `Unit_10820.prefab` + controller, 9 clips (`Attack/Skill × Front/Side/Back`, `Skill_Ultimate`),
  9 FX prefabs and 9 `MT_10820*` materials. Match same-id master data in
  `xml_history/2026_10_20_bhhtbJKhrR` (units, `Skill_10820*`, `Overcome_10820_0..4`).
- New UI: `IncarnationSkillInfoSlot/IncarnationSkillDetailSlot` scripts + `IncarnationSkills`
  (Passive/Ultimate tabs) - the **Incarnation** progression UI; `GachaShopPanelBG_Pickup_SpecialUnit`;
  `Prefabs/Video/VideoOverlayPlayer` (+`ThemeIntroVideoOverlayPlayer`, `AcquireVideoOverlayPlayer`,
  `BgVideo`) - the v174 `Videos.xml` runtime; `DimensionUnitOvercomeTicketPanel` →
  **`UnitOvercomeTicketPanel`** (ticket UI generalized past dimension units).
- Content art: treasure **30045** (illust 760², card illust, icon 54x60, skill icon 30x30),
  map-skin shop sprite **`MapSkinSprite_40200`** (skin itself existed), season theme
  `Themes_Background/Title_1000_S74`, `SeasonEvent_Banner_07` + `SeasonEvent_TitleImage1`,
  **`Title_6Th_Event`** (6th anniversary), `Title_Hansi`, `Synergy_17`, `PotentialIcon_43`,
  `Avatar_082`/`Portrait_082`, and skin FX `Fx_1040000_07` (skin 1040000 = unit 10400).
  Treasure 30045 / map skin 40200 are **not yet in the CDN master data** (client ships ahead of
  `xml` bundle) - expect them in the next CDN refresh.
- Private build (`server/builders/build_private.py`) has **no 174 table**: `VER` tops out at
  173.1.00, so v174.1.00 is asset-inspection only until the NEO/`NRE_STUBS` rows are re-derived
  from its own `dump.cs`.

### Unity rebuild project (S0, 2026-10-08)

Plan + denominator + stage table: **`plans/unity-rebuild.md`**. Rebuild project:
`unity/kgc-rebuild/ExportedProject/` (project root; gitignored, reproducible from
`tools/arcli`). Master-data reader + gate: `Assets/Game/MasterData.cs` +
`Assets/Game/Editor/MasterDataSmokeTest.cs` (run with
`-batchmode -quit -executeMethod Kgc.Editor.MasterDataSmokeTest.Run`, throws →
Unity exits non-zero; reads `server/xml_live` by walking up from `Assets/`, env
`KGC_MASTER_DATA` overrides).

- **`tools/arcli` now takes a level argument**: `arcli <input> <output> [level]`.
  The v174 *viewer* export used **Level0** (no scripts loaded) - at that level the
  10,679 `MonoBehaviour` assets serialize **only `m_Script` + `m_Name`**, all game
  field names/values are missing. **Level1** ("methods are stubbed") is the right
  level for the rebuild: same art, but `.asset` files carry real per-instance fields
  (`_keys`, `_styles`, sprite refs) and the stubs have the real class shape
  (`Scene_Lobby : Scene_Base`, nested compiler-generated classes, fields - just empty
  method bodies). Level2/3 differ only in processing layers that the public build
  does not ship (`RecoveryProcessingLayers` is null → Level3 ≡ Level2).
- Level1 output differs from Level0 in two more ways: `Assets/Scripts` is 2,336 files
  (nested classes folded, 19 MB) not 4,707 dummies, and **`Assets/Plugins/` is
  produced** (real game DLLs: `ACTk.Runtime`, `AirbridgeSDK`, `appsign4acs`, …) -
  keep those. `Assets/Scripts` must still be moved out of `Assets/` before the first
  editor open (same assembly-reload SIGSEGV trap as v172/v173): →
  `AuxiliaryFiles/GeneratedScriptStubs/`.
- `ProjectSettings/ProjectVersion.txt` = **2022.3.62f3**, exactly the installed
  editor, so batchmode opens it with no upgrade pass.
- **The 94 stub DLLs in `Assets/Plugins` crash Unity** - build succeeds, then
  `Begin MonoManager ReloadAssembly` → `MonoScriptInfoScraper::
  GetAssemblyScrapedMonoScripts` → SIGSEGV (exit 139), no `error CS` anywhere, so
  it looks like the old Scripts trap but isn't. Bisect (set-based, one Unity
  batchmode run per set, ~15 s/run with a warm `Library/`):
  `/tmp/opencode/bisect_plugins.py` → **exactly one culprit,
  `Unity.MemoryProfiler.dll`** (a Unity *package* DLL AssetRipper dumped into
  Plugins, not game code). Keep the other 93: they are signature-only reconstructions
  (no real DLL exists anywhere in the APK), but their `.meta` guids are what prefab
  `m_Script` references point at - swap real assemblies in later, keeping the metas.
  The culprit stays in `AuxiliaryFiles/Plugins/`.
- **S0 gate result**: `-batchmode -quit -executeMethod Kgc.Editor.
  MasterDataSmokeTest.Run` → exit 0, 0 compile errors, `Units 1043 / Skills 2342 /
  InventoryItems 173 / Strings_EN_US 15923 rows`.

### Unity rebuild — stub DLL swap, full stub compile, scene audit (2026-10-08)

Continues the S0 section above. Everything here is about making the exported project
*actually render and compile* rather than merely open.

1. **The 93 `Assets/Plugins` DLLs are signature-only reconstructions - and uGUI's stub is a
   silent killer.** `tools/ilsize <dll>` (histogram of IL body sizes) shows median body 1-2 B
   = `ret` / `ldnull;throw`; `tools/ilsize --dump "UI.Text::set_text" <dll>` prints the IL:
   `Text.set_text` → `ret` (setting text silently does nothing), `Image.OnPopulateMesh` →
   `ret` (**no mesh is generated → every uGUI element renders invisible, with no exception**).
   So a scene full of Images looks "fine" (0 missing scripts, no errors) and still shows
   nothing. Do not trust a clean log as proof of rendering.
2. **Recipe: swap in a real `UnityEngine.UI.dll`, keeping the prefab guids.**
   - Scratch project `unity/_pkgbuild/` whose manifest pins `com.unity.ugui` to the version in
     `Editor/Data/Resources/PackageManager/BuiltInPackages/com.unity.ugui/package.json`
     (1.0.0 for 2022.3.62f3), batchmode `-quit` once →
     `Library/ScriptAssemblies/UnityEngine.UI.dll` (250,880 B vs the 131,072 B stub).
   - `cp` it over `Assets/Plugins/UnityEngine.UI.dll` **without touching `.dll.meta`**.
     Safe because script refs into an assembly key on the *assembly* guid + a fileID derived
     from namespace+class name, so content can change freely as long as type names don't.
     Project must NOT also have `com.unity.ugui` in its own manifest (conflict:
     "Multiple precompiled assemblies with the same name").
   - After swap: `set_text` 74 B of real IL, `OnPopulateMesh` 118 B, 44 % of bodies >20 B,
     project still `UNITY_EXIT=0`.
3. **Which stub DLLs the assets actually depend on** (counted `m_Script` refs across 82,025
   asset files): `UnityEngine.UI` **40,539** / `UIEffect` **32,605** / `Coffee.UIParticle`
   **924** / `PolyNav` 90 / `Unity.RenderPipelines.Core` 26 + `Universal` 5 /
   `FancyCarouselView` 5 / `LeTai.TranslucentImage` 3 / `AirbridgeSDK` 3 / `Tapjoy` 2 /
   `ACTk`·`UIEffect_Demo`·`DOTween`·`OfferWallEdge`·`Sirenix.Serialization.Config` 1 each.
   **TextMeshPro = 0 refs**: the game uses legacy uGUI `Text`, not TMP - don't install TMP.
   A stubbed UIEffect is survivable (`BaseMeshEffect.ModifyMesh` = `ret` = effect ignored,
   element still renders); swap it when UI fidelity starts to matter.
4. **All 1,793 stub classes compile inside the project** (copy
   `AuxiliaryFiles/GeneratedScriptStubs/Scripts/` back to `Assets/Scripts/`). They are
   ILSpy-shaped and syntactically valid (void → `{ }`, non-void → `return null/false`,
   state machines preserved as nested types). One fix needed: **3 files take
   `using YieldAwaitable = Cysharp.Threading.Tasks.YieldAwaitable;`** after the Cysharp using
   (`StoryModeBasePanel.cs`, `Data/StoryMode/EventChain/Node/ChangeBGMVolumeNodeData.cs`,
   `VideoOverlayPlayer.cs`) or CS0104 collides with
   `System.Runtime.CompilerServices.YieldAwaitable` from the BCL - the v172 trap, now solved
   with an alias instead of moving files out of `Assets/`.
5. **`Assets/Game/Editor/SceneAudit.Run`** (env `KGC_AUDIT_SCENE=Scene_Logo,...`,
   `KGC_AUDIT_STRICT=1` to throw): counts missing scripts, Images with sprites, empty Texts,
   and LocalizedText keys resolved against `Strings_EN_US.xml`.
   - `Scene_Logo`: missing **1** - GameObject `AndroidManager` has `m_Script: {fileID: 0}`;
     `AndroidManager` appears nowhere in `dump.cs`/`DummyDll`/`stringliteral.json`, so the
     class genuinely is not in the metadata → known export defect, not ours to fix.
   - `Scene_Loading`: missing 0, 1/1 loc key.
   - `Scene_Login`: **missing 0, 139 Images (114 with a sprite), 80 Texts (8 empty = filled
     by code at runtime), 31/31 localizer keys resolve.**
6. **Screenshots work headless**: the machine is Arch (not Debian - `dpkg` is empty), Xvfb and
   Mesa `swrast_dri.so` are installed, `DISPLAY=:1` is an Xwayland session with NVIDIA 4060 +
   Intel iGPU. `xvfb-run -a -s "-screen 0 1280x2048x24" Unity -batchmode -quit -force-glcore
   -executeMethod Kgc.Editor.CaptureScene.Run` creates an OpenGL 4.6 device.
   `CaptureScene` re-parents every Canvas to `ScreenSpaceCamera` (**Overlay canvases are not
   drawn by `Camera.Render()`**, so they must be forced), renders into a RenderTexture, writes
   `KGC_CAPTURE_DIR/shot_<scene>.png`; env `KGC_CAPTURE_W/H` default 1080x1920.
7. **Scope of the login flow**: 29 classes / **577 methods** (Scene_Login 80, Scene_Loading 113,
   AudioController 155, SignInWithApple 32, SimpleAssetDB 31, Popup 30, DeepLinkManager 27,
   Scene_Loading 113, the rest trivial). `Localizer` is a singleton over `_stringMap` /
   `_krStringMap` fed by `ParseTextAsset(locale, TextAsset)`, with
   `AddPending(ILocalizedComponent)` → `HandleLocalizerInitialized()`; `LocalizedText` carries
   serialized `key` + `format: '{0}'` and writes `Text.text`.

### Unity rebuild — S1: Localizer + Scene_Login boot trong Play mode (2026-10-08)

S1 done = play capture có button login + text EN. Code ghi đè method body trong
`Assets/Scripts/Assembly-CSharp/` (giữ `.meta`), không thêm class mới.

1. **`Localizer`** (đã ghi đè stub): singleton `Instance` + `Locales` init trong static ctor;
   `Initialize()` idempotent đọc `Strings_<locale>.xml` qua `Kgc.MasterData`
   (`Root ?? FindRoot()` → `Load` → `Doc("Strings_"+locale)`; root `<Strings>`, row
   `<String Key="…">text</String>`, 15923 rows EN). Default locale: env `KGC_LOCALE` →
   `Application.systemLanguage==Vietnamese` → VI → EN_US. `AddPending` **self-heal**: chưa
   init → `Initialize()` rồi `HandleLocalizerInitialized()` ngay (file local đọc đồng bộ,
   không cần queue; `_onLoaded` giữ shape API). `Localize(key)` miss → `null` →
   `LocalizedText` giữ text serialized trong scene. `ChangeLocale` reload map nhưng
   **không refresh component đã apply** (ceiling - LocalePanel inactive, sửa nếu S2+ cần).
2. **`ReloadLoginPanel(show)` disasm** (RVA `0x3642250`) - semantic verify từng lệnh:
   show=true → `loginPanel.SetActive(true)`; `Utility.SetActive(loginButtonGroup, true)`;
   `Utility.SetActive(testLoginIdInput, true)` (unconditional - không phải bug); nhánh
   admin/US-replica (static ObscuredBool gate) bỏ qua; `DOTween.Kill(logo)` +
   `DOFade(logo→0, 0.5)`; `loginButtonGroup.alpha=0` + tail-call `DOFade(→1, 0.5)`.
   show=false → inverse, **không** đụng `loginPanel`, + audio call SE `0x13` (bỏ qua).
   `Utility.SetActive(Component,bool)` (`0x2C84C00`/`0x2C8F034`) = null-check →
   `gameObject.SetActive`. **DOTween là stub (no-op) → phải set end-state trực tiếp**
   (`logo.alpha=0`, `loginButtonGroup.alpha=1`); bám nguyên disasm (`alpha=0` + gọi DOFade
   stub) là button group kẹt ở alpha 0 = invisible, không lỗi nào báo.
3. **`Scene_Login` flow**: `Awake` = `Instance = this; base.Awake()` (`Scene_Base.Awake` =
   `Localizer.Instance.Initialize()` - mọi scene derive Scene_Base nên một chỗ là đủ;
   `LocalizedText.OnEnable` self-heal nên thứ tự Awake/OnEnable không quan trọng);
   `Start` = `ApplyLoginSceneIllustData(); SocialInit(); ReadyToAuth();` - **bỏ
   `CheckUseAssetBundle` chain** (rebuild không có CDN/Addressables; riêng warning
   `KGC_ASSETBYPASS` trong AGENTS chỉ áp cho client trỏ CDN thật). `SocialInit` =
   google+guest ON, apple/gameCenter/appleGuest OFF, bỏ social-SDK init. `ReadyToAuth` =
   tail-call `ReloadLoginPanel(true)`, `showComment` không dùng (đúng disasm).
4. **Play-mode capture** (`KGC_CAPTURE_PLAY=1`, **không** `-quit`):
   `CaptureScene.Run` set `SessionState["KGC.PlayCapture"]` + `EditorApplication.isPlaying`,
   `[InitializeOnLoad] PlayCaptureDriver` hook `EditorApplication.update` - static ctor chạy
   lại sau domain reload (SessionState sống sót, static `_ticks` reset = đếm từ lúc vào play).
   Tick: wall-clock 120s → Exit(1); đang play + 60 tick + `Time.frameCount≥10` → log 10
   `LocalizedText` active đầu (`key => text`) → `RenderShot` → `EditorApplication.Exit`.
   ```
   KGC_CAPTURE_PLAY=1 timeout 300 xvfb-run -a -s "-screen 0 1280x2048x24" \
     Unity -batchmode -force-glcore -projectPath <proj> \
     -executeMethod Kgc.Editor.CaptureScene.Run -logFile <log>
   ```
   Edit-mode capture (không env) giữ nguyên hành vi cũ.
5. **Gates (cùng 2026-10-08)**: compile `MasterDataSmokeTest.Run` → `UNITY_EXIT=0`,
   0 `error CS`; `SceneAudit` `KGC_AUDIT_SCENE=Scene_Login KGC_AUDIT_STRICT=1` →
   missing 0, locKeys 31/31 (giống trước S1); play log →
   `[LOCALIZE] initialized=True locale=EN_US`, `GuestLogin => Guest Login`,
   `LoginByGoogle => Sign in with Google Play`; ảnh `/tmp/opencode/shot_Scene_Login.png`
   1.09 MB có illustration + 2 button (edit-mode trước S1 = illustration không text).
   Trong play chỉ **2 LocalizedText active** - key còn lại nằm trong register/terms panel
   (inactive, mở theo yêu cầu) - đúng kỳ vọng, không phải lỗi resolve.
6. **Boot flow `Scene_Logo → Scene_Login`** (cùng 2026-10-08, complete S1):
   - `Scene_Logo` (driver = `Update`, không phải Start): `Awake` = base + `SetAlpha(logo,0)`
     + `GameManager.LoadSetting` + DOTween sequence fade (`OnComplete → _canMoveToLoginScene`);
     `Start` (async void) = `DontDestroyOnLoad` + `SimpleAssetDB.Initialize()`; `Update` =
     countdown `_loginSceneIllustDataFetchStartTimer` 3→0 → `FetchLoginSceneIllustData`
     (async `RestAPI.LoginSceneIllustData()` + `UniTask.Delay(5000)` → flag
     `_loginSceneIllustDataFetched`) → gate 2: SimpleAssetDB ready →
     `_loginSceneLoadHandler = LoadSceneAsync(<static string>, Single); allowSceneActivation=false`
     → gate 3: `_canMoveToLoginScene` → `allowSceneActivation=true`.
   - **Rebuild bypass**: DOTween + REST đều là stub → `Start()` set thẳng
     `_loginSceneIllustDataFetched` + `_canMoveToLoginScene = true`; `Update` giữ
     async-load + activation mechanism, đích hardcode `"Scene_Login"`; bỏ SimpleAssetDB gate.
   - **Đích RE method (recipe tái sử dụng)**: text `"Scene_Login"` KHÔNG tồn tại trong
     `.so` (literal giữ trong metadata, quét adrp+add = 0 hit) → resolve qua **static slot
     readers**: slot `0x695f000+0x3a0` (arg `LoadSceneAsync` của Logo) chỉ được LDR, không
     STR, bởi `SettingsPanel.OnClickLogout/OnClickAccountTransferConfirm`,
     `Web.HandleErrorCode`, `LinkAccountPanel`, `NicknameChangePopup`,
     `Scene_Lobby/Territory.Awake` = toàn bộ ngữ cảnh "về login" → value = `"Scene_Login"`.
   - **`Scene_Loading` KHÔNG thuộc boot**: `Scene_Loading.Start` = sync
     `LoadScene(<arg>)` với arg = graph 3 nấc `[[0x6969000+0x2d8]→field0]→+0xb8→[0]`
     (instance của `GameManager`, slot chỉ readers: `GameManager.LoadScene` state machine
     + `Scene_Game.StartSingleArenaBattleAfterDeckRecord`) - boot chưa set → NRE nếu đi
     qua; `Scene_Loading` là trung gian transition `GameManager.LoadScene(target)` →
     làm ở S2. `Scene_Loading.cs` giữ nguyên stub.
   - **Capture fix**: `PlayCaptureDriver.Tick` chụp theo `SceneManager.GetActiveScene().name`
     (env `KGC_CAPTURE_SCENE` chỉ để mở scene ban đầu; play flow đã load sang scene khác →
     filter canvas theo tên cũ sẽ ra ảnh đen).
   - **Gate**: `KGC_CAPTURE_PLAY=1 KGC_CAPTURE_SCENE=Scene_Logo …` → exit 0, log
     `Opening scene 'Assets/Scene_Logo.unity'` → `Loaded scene 'Assets/Scene_Login.unity'`
     → `[LOCALIZE] GuestLogin => Guest Login` → `[CAPTURE Scene_Login] canvases=2
     1091209 bytes` → screenshot login đầy đủ (illustration + 2 button EN).

### Unity rebuild — S1.5: swap DLL thật UIEffect + Coffee.UIParticle (2026-10-08)

2/93 stub DLL có asset ref thật (`UIEffect.dll` 32.605 ref, `Coffee.UIParticle.dll` 924
ref) → build source upstream **đúng version** thành DLL, thay vào `Assets/Plugins/` giữ
nguyên file name + `.meta` guid (script ref = guid + fileID hash(namespace.class) → cùng
type name = cùng fileID → ref không vỡ).

1. **Công thức xác định version CHÍNH XÁC từ stub** (không đoán bằng type match): stub
   giữ `<PrivateImplementationDetails>` + `UnitySourceGeneratedAssemblyMonoScriptTypes_v1`
   — 2 field byte[] blob của chúng = payload source-gen `MonoScriptData`
   (`FilePathsData` + `TypesData`). Dump từ PE: `ikdasm <stub>.dll` lấy field RVA
   (`at I_2050`), bóc section table → file offset → bytes → `strings`:
   - **UIEffect**: path `\Library\PackageCache\com.coffee.ui-effect@b43e40508b\...` =
     git SHA → `git rev-list --all | grep ^b43e40508b` trong mob-sakai/UIEffect =
     **tag `4.0.0-preview.9`**. FilePathsData liệt kê 18/22 file (4 file enum-only bị
     source-gen loại; `Enums/EffectArea.cs` còn vì chứa class static
     `EffectAreaExtensions`). ⚠️ `4.0.0-preview.10` type/field/method cũng khớp 28/28
     (stub strip hết body → không phân biệt được) → **phải chốt bằng SHA trong path,
     không phải type diff**.
   - **UIParticle**: path `\Assets\UIParticleEffect\Scripts\*.cs` (8 file, import loose,
     không version) → tìm bằng history repo mob-sakai/ParticleEffectForUGUI (repo cũ tên
     `UIParticle`, đã đổi tên): `git log -S 'namespace Coffee.UIParticleExtensions'` →
     namespace bị migrate ở `8c1bef4` (ship từ 4.10.0), `b76bf5a` xóa chính 3 type có
     trong stub (BakingCamera/CombineInstanceEx/MeshHelper) → `git describe --tags
     b76bf5a^` = **3.3.12** = upper bound; không commit runtime nào giữa 3.3.12 →
     b76bf5a; type diff 15/15 + 8 file list khớp → **chốt 3.3.12**.
2. **Build**: `tools/unity/build_plugin.sh <name> <src_root> <out.dll>` — csc (Roslyn
   trong dotnet SDK) với `-nostdlib+` trỏ đúng profile Unity dùng
   (`MonoBleedingEdge/lib/mono/unityjit-linux` = mscorlib/System/System.Core +
   `Facades/netstandard.dll`; engine modules 2022.3 ref `netstandard` facade — xác nhận
   bằng `monodis --assemblyref Library/ScriptAssemblies/Assembly-CSharp.dll` = refs
   `mscorlib`), ref toàn bộ `Managed/UnityEngine/UnityEngine*.dll` +
   `Assets/Plugins/UnityEngine.UI.dll`, define = chuỗi `UNITY_*_OR_NEWER` đến 2022.3 +
   `UNITY_ANDROID`, **không** `UNITY_EDITOR`, `-langversion:9`,
   `AssemblyVersion=0.0.0.0` (= stub), chỉ `Scripts/` trừ `Editor/`.
3. **Verify** (`tools/unity/diff_dll.py`, parse ikdasm): diff typedef + field name +
   method name từng type — trước build: type 28/28 + 15/15 khớp stub; sau build: **0
   field, 0 method diff**. Diff duy nhất còn lại = `MonoScriptData` + PID blob (artifact
   source-gen của Unity — plugin DLL không cần, Unity đọc type plugin qua reflection;
   fileID tính từ guid + namespace.class).
4. Game code chỉ dùng `Coffee.UIEffects` (19 file: UIEffect×13, BaseMeshEffect×11,
   UIShadow×6, UIGradient×2, UIShiny×1), không file nào gọi API UIParticle → mảng ref
   UIParticle là component trong scene/prefab, không phụ thuộc API.
5. **Gates** (cùng bộ S1, chạy lại sau khi thay DLL): compile `MasterDataSmokeTest` →
   exit 0 / 0 `error CS`; `SceneAudit` Scene_Login strict → `missingScripts=0`;
   boot capture `KGC_CAPTURE_PLAY=1 KGC_CAPTURE_SCENE=Scene_Logo` → exit 0, screenshot
   login 1.71 MB đầy đủ, không exception mới. `Script error: OnParticleUpdateJobScheduled`
   (×3) **pre-existing** — có trong cả log S1 trước swap, engine message "will be
   ignored", benign. Stub cũ backup: `/tmp/opencode/stubs_backup/` (mất thì tái tạo từ
   AssetRipper export). `Unity.MemoryProfiler.dll` (culprit SIGSEGV) vẫn không đụng.

### Dominion tutorial #40 native flow (2026-08-31)

Tutorial #40 must remain unfinished, but Dominion must already return Chamber `10001` at
`posIndex=1` (visual site 8) and Inn `10101` at `posIndex=0` (visual site 3). The client simulates
construction without calling `/territory/build`: `PrepareTutorial40` snapshots the territory list,
then predicate `b__68_0` removes roots `10000` and `10100` from the live client list. Step 5 calls
`Scene_Territory.GetBuildableArea(1)`; callback `b__68_6` restores the snapshot minus Inn, revealing
Chamber. Step 7 calls `GetBuildableArea(0)`; the later callback restores both rows, revealing Inn.
`b__68_8` calls `TerritoryBuildingListPanel.GetBuildingCell(10100)`, so an empty server snapshot
leaves Inn locked and throws `NullReferenceException` before any HTTP build request. The old seeded
layout had the right rows but reversed positions (`Chamber@0`, `Inn@1`), making each reveal jump to
the other tutorial site. Normal builds still require `refreshRet.buildingRet`; that response shape
is unrelated to the tutorial's local reveal flow. Regression: `server/tests/test_territory.py`.

### Blacksmith create / merge / polish contract (v172.0.01, 2026-08-31)

- `ArtifactCraftTab.<Craft>d__13.MoveNext` RVA `0x30B85FC` uses two craft slots. The request's
  `targetId` identifies a `ResourceArtifact.Type.Piece`; two matching pieces create the normal
  artifact named by the piece's inherited `<Root>`. With one slot empty, `useDust=true`: consume
  one piece plus `CraftDustCost[GetFromTypeRank(piece.fromType)]` (`25/50/100`). Piece rows must be
  present in `/artifact/inventory`'s `artifacts`; the old default inventory contained only the 184
  `Type=Artifact` rows, so the Craft tab had no selectable materials.
- `ArtifactMergeTab.ReloadActionButtonInteractable` RVA `0x30BA4D8` requires both merge slots.
  Consume two matching relics and create their next master-data tier. `GetMergeGoldCost`
  RVA `0x30BA2B8` resolves the output (`next`) resource first, then charges that tier's
  `MergeCost` row (King `400/600/800`, God `1000/1500/2000`, KingGod `4000/6000/8000`).
- `ResourceArtifact.GetFromTypeRank` RVA `0x340E2A8` table for enum values 0..9 is
  `[0,1,2,2,2,0,-1,-1,2,2]`: ShopCommon/Special=0, ShopRare=1,
  ShopSpecial/HardMode/Arena/Event/Raid=2; the two RogueLike families are invalid (`-1`).
- Polishing material request IDs are **resource IDs**, not artifact instance IDs:
  `MaterialArtifactItem.From` RVA `0x338EA10` copies `ArtifactModel.artifactId` into inherited
  `UpgradeMaterial.id` and the instance id into separate `uniqueId`. Stones 901/902/903 add
  10/50/100 points. `ArtifactPolishPointByRank` is transposed relative to the old server code:
  rows `One..Five` are the current option rank and columns are `FromType` rank. Moving an option
  position uses `/artifact/polish/replace-option-slot-idx`, costs
  `ArtifactPolishPointToReplace` (`200/400/800`), and must update both
  `data.options[i].targets` and `options.targets[i].idx`.
- Server implementation: `routes/artifact_routes.py`; durable focused regression:
  `python3 server/tests/test_artifact_blacksmith.py`.

### Guaranteed Forge contract (v172.0.01, 2026-08-31)

- `ArtifactRerollTab.<SmartRerollImpl>d__68.MoveNext` RVA `0x31018A0` sends
  `ArtifactRequestModel{targetId=<instance id>, index=<target position 1..6>,
  stat=<AtkPer|MAtkPer|AtkSpeedPer|HpPer>}` to `/artifact/smart-reroll`. A successful
  response must contain the updated artifact in `results[0]`; an empty result is a visible no-op.
  Generated fields identify `+0x110` as `_smartRerollTypeIndex` and `+0x114` as
  `_smartRerollTargetIndex`; `OnClickSmartRerollTarget` RVA `0x30C917C` stores the selected
  zero-based formation position there, and the request sends it plus one.
- `GetSmartRerollCost` RVA `0x30C9CB0` indexes `ResourceArtifact.fromType`: ShopCommon 1,
  ShopSpecial/HardMode/Arena 4, Event 0, Raid 2 Blacksmith's Tokens (inventory item 800).
  ShopRare, Special, and both RogueLike families return the client's invalid/max sentinel.
- Every active option row becomes the selected stat at level 6/value 24 and targets only the
  requested position. This matches `ReloadSmartRerollOptionUI` RVA `0x30C8A5C`, whose four-row
  preview loop builds each option with the selected type and `targetIndex + 1`. Update both
  `data.options` and parallel `options.{types,lvs,targets}`, then persist and deduct item 800. Regression:
  `server/tests/test_artifact_blacksmith.py`.

### Treasure 50002 / Cor Orbis (2026-09-02)

- `Strings_VI.xml` defines `TreasureName_50002` as `Cor Orbis`, with temporary subname and
  concept text about borrowing, storing, and releasing Mana from nearby plants and animals.
  It also defines skill/buff localization keys `3500020..3500025` and packages `1690..1692`.
- The current `xml_live/Treasures.xml` has no `<Treasure ID="50002">` row, and
  `TreasureBuffDatas.xml` has no `3500020..3500025` rows. Therefore owner, rarity, role,
  recommended unit, numeric values, and runtime implementation cannot be determined from the
  current master data.
- `StoryStages.xml` equips `50002` on story unit `10010210` (Story Mel) in stages
  `410101053` and `410101054`; this is only a scripted NPC loadout, not proof of Treasure
  ownership. Do not confuse it with `Items.xml` item `50002` (Mel's Injury).
- **Text restored 2026-09-26** (`local_mods` mod 8): 20 keys replayed into
  `Strings_EN_US`/`Strings_VI` after every refresh - `TreasureName/SubName/Desc`,
  `TreasureSkillName`, `BuffDataName/Desc_3500021..25`, `TreasureSkillDesc_3500020..23`,
  `SpecialShop_TreasurePickUp50002`. All values are the operator-supplied leak block
  byte-exact (verified: 20/20 EN keys match; VI matches the official VI snapshot) - the
  subname/desc keep the shipped placeholder wording ("Temporary Subname" / the
  "Planned concept: a stone? artifact? ..." note), nothing is rewritten in-game style.
  `_apply_cororbis` therefore **overwrites** a differing value instead of only inserting.
  `SpecialPackage_1690..1692` are NOT written (operator dropped them: they are live keys
  renamed by the 2026-09-10 republish, restored to `Legacy Pickup Summoning Stone Package
  1/2` / `Meirna Package`); `AdsSummonRestrictionAlert` already equals the supplied text.
- **Rows added 2026-09-26** (`local_mods` mod 9): `<Treasure ID="50002">` + `BuffData
  3500020..3500025`, so the text actually renders. Two things about them are deliberate
  guesses, both flagged in the code:
  - **The buff numbers are TEST VALUES** - the official `350002x` table never leaked. What is
    *not* a guess: every `DescParams`/`TotalDescParams` carries exactly as many `<Const>` as the
    leaked string has `{N}` placeholders, in index order (verified: `3/6/7/8` skill params for
    rows `020..023`, `0/3/1/1/1/3` buff params for `020..025`).
  - **Two desc/effect gaps**: "until using a skill 3 times" is implemented as a permanent
    `BattleStart` buff (no generic 3-cast counter exists), and `BuffDataDesc_3500023`'s
    splash-on-enhanced-skill became a mana refund on skill cast (there is no
    `Treasure50002Action` and no skill `9500020`). Effects follow the `30038` shape:
    add one `<BuffOptions>` per level, then override in place for the II tiers
    (`option counts = 2,3,4,5,5,5`).
  - Art: no override tags - the row uses the header's own defaults
    (`TreasureIcon_50002` / `TreasureIllust_50002` / `TreasureCardIllust_50002` /
    `TreasureSkillIcon_50002`), which resolve to the client's placeholder (operator
    request: never borrow another treasure's art). `MinVersion` is `170000` so the row
    passes `CONTENT_GATE` on any deployed client.
  - Ownership is **not** automatic: `player_routes` only seeds `st["treasures"]` when the key
    is absent. Grant with `POST /admin/api/treasures/give-all` (or the `Treasure` reward type
    in `POST /admin/sendmail` for a non-destructive single grant).
- **30044 is NOT Cor Orbis** (checked 2026-09-26): `30044` is the next regular-treasure slot
  (would be buff series `330044x`, none exists in any snapshot) with placeholder black art only,
  registered in Addressables since v172.1.00. Cor Orbis is `50002` (limited series, `350002x`).
  The `30044` IDs elsewhere are unrelated namespaces: `GachaPool 230044` and `ShopItem 30044`
  ("왕의 소환서", EventShop S15).

## 20. Player Dashboard branding and locale (2026-09-03)

- **Admin login 500 behind Cloudflare (fixed 2026-09-06):** public HTTPS terminates before the
  dashboard, which receives HTTP. `_same_origin` compared schemes and rejected the browser's valid
  `https://...` Origin; raising `HTTPException` from `BaseHTTPMiddleware` then escaped as 500.
  Origin protection now compares the browser Origin's validated HTTP(S) host to `Host`, and
  middleware converts real origin failures to 403.
  Keep the `0.0.0.0:8081` bind: the Cloudflare Tunnel reaches the host address, not loopback.
  Regression: `server/tests/test_dashboard_origin.py`.

- The public Player Dashboard now supports Vietnamese and English through
  `webui-next/src/components/portal-i18n.tsx`. It defaults from the browser language, persists the
  explicit choice under `localStorage["kgc-player-locale"]`, synchronizes same-tab/cross-tab
  changes with `useSyncExternalStore`, and updates the document `lang`. `SiteShell` installs this
  provider only for the portal, so the administrator dashboard is unchanged.
- `PortalMasthead` is shared by `/player` and `/player/donate`. It is intentionally wordmark-only;
  the old `K / BC` mark and its attempted SVG replacement were removed at the user's request. The
  masthead owns the accessible `VI / EN` switch, and mobile moves its actions below the title.
- Portal copy, common API errors, fixed reward names/notes, request statuses and date formatting all
  follow the selected locale. Operator-authored `PLAYER_DONATE_INSTRUCTIONS` remains literal by
  design because it is deployment content, not application copy. Object-shaped FastAPI errors such
  as `{detail: {code: "insufficient_tickets"}}` are normalized by `player-api.ts` before lookup.
- Verification: `./node_modules/.bin/eslint .` passes; `./node_modules/.bin/next build --webpack`
  exports all 16 pages with TypeScript clean. Chromium headless checks at 1440x1000 and 390x844
  confirmed the login view and locale control render without horizontal overflow.

## 21. Rewarded-ad provider gate (2026-09-03)

- Keep `/portal/api/ticket/video/start` and `/complete` disabled. Google explicitly documents that
  Server-Side Verification is app-only and unavailable for GPT rewarded ads on web; its
  `rewardedSlotGranted` event therefore remains an untrusted browser assertion.
- AppLixir is the only direct web rewarded-video candidate verified against current vendor docs.
  Its v6.1 web callback carries signed `gameApiKey`, `gameId`, `userId`, and unique `tid`; production
  mode is `MD5 and TID`, so it can map an opaque portal session and deduplicate retries before
  calling the existing ticket-accounting helper. Do not trust or sign decisions from `customData`.
- AppLixir is not approved for this project yet. Its current public requirements conflict:
  the main site says 100,000 monthly impressions, while the publisher FAQ requires 5,000 daily ad
  impressions or active users; the signup form nevertheless accepts an `Under 100K` range. It also
  requires a publicly reviewable, original, non-infringing property, exact-domain registration,
  HTTPS, and `ads.txt`. Obtain written pre-approval for the actual portal, traffic, Vietnam-heavy
  audience, and content/IP situation before writing integration code or exposing either endpoint.
- Monetag's signed rewarded postback is documented only for Telegram Mini Apps, not an ordinary web
  portal. AdswedMedia and the surveyed BitLabs/CPX/Lootably/AdGate-style products are offerwalls
  (installs, surveys, registrations, tasks), not the requested one-click rewarded-video UX. Other
  gaming monetization vendors did not publish enough web S2S verification detail to satisfy the
  trust boundary. The smallest next step is AppLixir pre-qualification; if declined, retain
  donations/manual ticket credit rather than weakening the callback invariant.

## 22. Dimension Rift difficulty progression (v172.1.00, 2026-09-05)

- Theme 2100 has challenge levels `-5..16` in `RogueLikeSettings.xml`; level 16 is seasonal.
  `GameCompleteRequestModel` sends `rogueLikeChallengeLevel` @ `0x164` and the run's computed
  `rogueLikeBaseScore` @ `0x168`. There is no request field named `rogueLikeScore`.
- `DimensionRiftStartPanel.get__canChallenge` @ RVA `0x347A5C8` enables the challenge button when
  status `DimensionRiftPlayCount > 4` or `DimensionRiftMaxClearedChallenge >= 0` (defaults 0 and
  -1 respectively). `RogueLikeChallengePanel.Show` @ `0x347DED4` activates levels only through
  `maxCleared + 1`.
- `RogueLikeGameOverPanel.Show` @ `0x3660770` increments play count after every run. On a win it
  writes the selected challenge only when it exceeds the saved max. Its max lookup unusually uses
  default 0, while the selection panel uses -1; therefore the server must explicitly send max=-1
  for a fresh account or clearing level 0 cannot unlock level 1 locally.
- `GameResponseModel` has `rogueLikeScore` @ `0xCC` but no `updatedKeyValues`. The client updates
  its local key dictionary itself; the server mirrors both status keys into the save so `/player`
  restores them after relogin. Existing saves initialize play count from `rogueLikePlayedCount`.
- Server fix: `r_dimension_rift_complete` reads the two real request fields, clamps challenge to
  `-5..16`, requires the five-run gate and sequential `max+1` clear, keeps the best score for the
  leaderboard, and returns the current run score to the game-over panel. Assign the response score
  after `gameComplete.fixed`: that config contains `rogueLikeScore: 0` and otherwise overwrites it.
  Regression: `test_dimension_rift_difficulty_progresses_sequentially` in
  `server/tests/test_ranking.py`.

### Operator: unlock "full rift phase" for an account (2026-09-25)

"Full rift phase" = Dimension Rift (theme 2100) challenge levels `-5..16` all selectable, incl.
Phase 16 (Seasonal Challenge Mode). No API exists to set it - patch the save in place, the same
way `/player` serves it:

1. Keys live in the save's `keyValues` list (`{key, value}` strings), served verbatim by `/player`:
   - `DimensionRiftPlayCount` = `"5"` (must be `> 4`; `DimensionRiftStartPanel.get__canChallenge`
     @ `0x347A5C8` unlocks the button with `PlayCount > 4` OR `MaxClearedChallenge >= 0`).
   - `DimensionRiftMaxClearedChallenge` = `"16"` (`RogueLikeChallengePanel.Show` @ `0x347DED4`
     activates levels through `maxCleared + 1`, capped at the max 16).
2. Mirror into plain keys so server-side fallbacks/ranking stay consistent: `st["rogueLikeChallenge"]`
   = 16, `st["rogueLikePlayedCount"]` = 5. (`r_roguelike_ranking` shows `rogueLikeChallenge`;
   `r_dimension_rift_complete` reads the keyValues via `_key_value` with `rogueLikeChallenge` fallback.)
3. Phase 16 also needs a live season: `/rogueLike/season-info` already returns `seasonEnabled:
   True` with active date bounds (`now_iso(-10)`..`now_iso(30)`), so no season work is needed.
4. Write with the server's own writer (`playerdb.load` → mutate → `playerdb.save`, never raw SQL
   so derived rows stay consistent), after a `sqlite3` `src.backup()` snapshot.
5. Verify end-to-end: `curl -H 'accesstoken: <tok>' http://127.0.0.1:8080/player` answers
   `encryptedwithhex: true` (AES) - decrypt with `server.crypto.aes_decrypt` and check the two
   `keyValues` entries. Applied to public `dev-0001` (KingBug, lvl 100) 2026-09-25.

## 23. API audit completion fixes (2026-09-06)

- Run the contract tools from the repository root: `python3 server/cli/api_audit.py` and the
  direct `server/tests/test_{route_coverage,api_contract,all_routes_respond,malformed_bodies}.py`
  scripts. Their primary checks use `check_*`, so pytest collection alone does not execute them.
- Account transfer lookup must enumerate `playerdb.all_players()`; the removed `all_uids()` API
  made every redeem fail. Transfer credentials are eight hex characters, expire after one day,
  and are deleted on first use.
- `ChangeProfileIconRequestModel` sends `profileIconId`, not `icon`; only persist an owned card ID.
  `/player/ad` initializes, increments, and persists `dailyAdCount` for old saves missing the key.
- `/player/other` must populate `OtherPlayerDataResponseModel` profile and current-deck fields;
  identity text alone leaves the profile panel without hero count or portraits.
- `api_audit.py` creates a real friendly-match room before probing join. An empty room code is a
  valid business rejection, not evidence that the success response contract is broken.

## 24. Admin accessory builder UI (2026-09-06)

- `/accessories` follows the same header, `PlayerBar`, card and spacing patterns as the existing
  Items/Heroes admin pages. Do not introduce a page-specific dark hero or visual system.
- The UI states the data model explicitly: there is one persistent admin set; every save adds one
  accessory to it; Apply replaces the selected player's whole accessory inventory and never merges.
- `Build set` and `Player inventory` are separate tabs. The saved set has search and a fixed 570px
  scroll region; inventory has a 65vh scroll region with a sticky table header. Neither collection
  is allowed to make the whole page grow with its item count.
- The builder keeps the server-supplied rarity slots, stat lists, per-stat maximum and shared score
  budget as the source of truth. A budget meter and inline over-budget message prevent invalid saves.
- `include_builtin` is an operator-controlled deployment option, not hidden configuration. The
  options API returns `builtinCount` (derived as `len(SETS) * len(LOADOUT)`, currently 65), and the
  UI includes it in the deployment total. A built-in-only set is valid and must leave Apply enabled.
- Custom entries can be edited in place through `/api/admin-accessories/update` or copied into the
  builder as a new variant. Update runs the same game-rule validation as create, preserves list
  order, and rejects a fingerprint duplicate of any other entry. Apply requires confirmation with
  the exact target and deployment count.
- Production keeps runtime saves in the untracked `server/state/` directory. `deploy_hook.sh` must
  reject dirty tracked files with `git status --porcelain --untracked-files=no`; checking all
  untracked files permanently blocks deploy as soon as runtime state exists. Never delete state to
  make the checkout clean. Both `.glogin_pending_*` and `.glogin_auth_*` are ephemeral runtime
  markers and belong in `.gitignore`.
- The deployable dashboard is the tracked static export under `server/webui-next/out/`; run both
  `pnpm run lint` and `pnpm run build` after editing the source page. Do not retain the generated
  `pnpm-lock.yaml`; this repository's committed lockfile is `package-lock.json`.

## 25. Dimension Rift incomplete-save black screen (v172.1.00, 2026-09-06)

- The pre-incident backup for `p-2787e1889bcd` contained a real theme-2100 save (`saveData` 16,684
  bytes, card snapshot 141,693 bytes, `state="0"`, response `saveVersion=2`). The JSON itself parsed,
  but the floor-1 run was incomplete: `cards=[]`, `fieldUnits=[]`, and `resStages=[]` while enemy/AI
  state was already present. Active theme-2100 saves from other players have non-empty cards and
  stages, including at floor 1. Passing this partial object into scene restore produced the reported
  black screen; the client subsequently deleted the run.
- `GameManager.<LoadRogueLikeFromServerImpl>d__731.MoveNext` @ RVA `0x30D822C` checks response
  `state == "DELETE"` before calling `JsonUtility.FromJson` for the snapshot and save blob
  (`0x30D94A8` / `0x30D94D8`). This is the client's safe invalid-save path.
- `r_rogue_load` now applies a narrow theme-2100 check: malformed JSON or a save with neither cards
  nor stage history returns an empty blob with `state="DELETE"`. Other themes and valid Dimension
  Rift blobs remain opaque and unchanged. Regression: `check_an_incomplete_dimension_rift_run_is_discarded`
  in `server/tests/test_roguelike_shop.py`.
- Do not infer corruption from `rogueLikeGameIndex` when debugging theme 2100. Client
  `GameManager.GetRogueLikeGameIndex` @ RVA `0x30B3F3C` reads `dimensionRiftGameIndex` for 2100 and
  `rogueLikeGameIndex` for 2000.

### iOS Token Extraction (AwesomePrefs)
Unity's PlayerPrefs on iOS are stored in `Library/Preferences/com.awesomepiece.castle.plist`. The game uses `AwesomePrefs` which encrypts keys and values using TripleDES ECB (PKCS7 padding). The TripleDES key is `MD5("APPROJECTL2")` (static across devices).
The prefix for plain keys is `T:_79ee6c63096ae9b47a7567aadb779e05`.
To extract credentials, parse the plist and decrypt all keys/values using this TripleDES key. Look for `accessToken`.
See `tools/extract_ios_token.py` for the implementation.

---

## 26. "Sniper Spot" tile buff - Dwarven Scope artifact (2026-09-24, leaker cross-check)

Leaker's item description: *"Placed Heroes gain Mighty Block +400; first và mọi Normal damage hit
thứ 5 +25% damage"*. Master data cross-check (2026-09-22 CDN rebase, `server/xml_live/`):

### What it actually is
Artifact family **14020-14024 "Dwarven Scope"** (KR 드워프 조준경):

| Artifact | Tier | TileBuffItem | Range check |
|---|---|---|---|
| 14020 | Piece (shard) | - | - |
| 14021 | Normal | 21030 | `TileBuffItems X=1 Y=1` + `X=5 Y=1` |
| 14022 | King | 21031 (Inherit 21030) | same two tiles |
| 14023 | God | 21032 (Inherit 21030) | same |
| 14024 | KingGod | 21033 (Inherit 21030) | same |

`<ArtifactDesc_14020>`: "A scope that embodies Dwarven technology...". The two tiles at (1,1)/(5,1)
are the "sniper spots" from the desc key `MoveStopTimeDesc`
(`Strings_*.xml`): *"Designate two tiles on the Battlefield as sniper spots. Placed Heroes gain
Mighty Block +{1}. Until they leave the sniper spot for the first time, the first and every 5th
Normal damage hit deals +{0}% damage."*

### Item 21030 buff options (all `BattleStart`, `Targets Self` = the placed hero)
1. `ShowTileEffect Prefab="Fx_Artifact_14020"` - tile visual only.
2. `AddMoveStopTime` FixedValue 10/15/20/25 (per tier) - hero is pinned to the spot (that's the
   "Until they leave... for the first time" condition).
3. `AddStat StatType="Range"` FixedValue 3 - +3 Range (the "sniper" reach).
4. `AdjustNormalDamage Count="5" First="true"` + `AddDamagePer` FixedValue 100/200/300/400 - the
   **first** normal hit AND **every 5th** normal hit deal +{0}% damage.
5. Same condition + `ShowEffect Damaged="true"` - hit visual.
6. `AddSuperShield` FixedValue 1/2/3/4 - grants N **Mighty Blocks** (EN localizes SuperShield as
   "Mighty Block", see `BuildingEffect_SuperShield` = "Mighty Block {Value} time(s)").

DescParams on the item bind `./ItemBuffOptions[2]/Values/FixedValue`, `[4]`, `[6]` (XPath 1-based =
AddMoveStopTime / AddDamagePer / AddSuperShield) so the tooltip renders the stop time, the per-5th-hit
damage % and the Mighty Block count from JSON-deserialized options.

### Per-tier values (Items.xml 21030-21033)

| Tier | Item | AddMoveStopTime | AddDamagePer (5th hit) | AddSuperShield (Mighty Block) | CoolTime (recall) |
|---|---|---|---|---|---|
| Normal | 21030 | 10 | 100 | 1 | 10 |
| King | 21031 | 15 | 200 | 2 | 15 |
| God | 21032 | 20 | 300 | 3 | 20 |
| KingGod | 21033 | 25 | 400 | 4 | 25 |

Buff recall (four trailing `ItemBuffOptions`, `RemoveTileEffect` + `Dispose` on `DuringBattle`
(cooltime) and `AfterMove`) removes the tile buff if the hero leaves the spot - matching "Until
they leave the sniper spot for the first time".

### Verdict vs leaker
- **Structure matches**: two sniper-spot tiles, Mighty Block grant, first + every-5th-hit damage
  amp - exactly `MoveStopTimeDesc`.
- **Numbers do NOT match**: no tier grants "Mighty Block +400" (max is +4 at KingGod) and no tier
  uses +25% (damage amp is 100/200/300/400%). The leaker likely read a fan-translation or a
  modded/mis-scaled sheet. Ground truth is the table above.
- If a player asks "what is the sniper spot item": it is **Artifact 14020-14024 Dwarven Scope**,
  dropped/upgraded through ShopSpecial (FromType), piece 14020 → 14024 KingGod.

## 27. Coupon auto-redeem bot (2026-09-25)

Auto-redeem codes from the official Discord into every registered Player-ID, via the public
coupon site. Plan: `plans/coupon-autoredeem/` (agent-local, gitignored). Code: `server/couponbot/`.

### The official site (all verified live 2026-09-25)

`POST https://kgc-coupon.awesomepiece.com/submitCoupon`, body
`uid=<Player-ID>&code=<CODE>&lang=en_us` (`application/x-www-form-urlencoded`, no cookies, no
captcha) → **HTML only**, no JSON variant (tested `Accept: application/json`). Result = the
`<h1>` + first `<p>` of the page. Header `X-Rate-Limit-Remaining` starts at 299.

Response vocabulary (English pinned by `lang=en_us`; h1 is `Success!` / `Failed to enter coupon`):

| `<p>` text | Result enum | Meaning |
|---|---|---|
| `Rewards have been sent to your inbox. Please log in to check.` | `ok` | redeemed |
| `This Player-ID does not exist. Please check and try again.` | `no_pid` | uid wrong |
| `This coupon does not exist.` | `no_coupon` | **code** unknown (global → stop trying it on other accounts) |
| `This coupon number is invalid or has already been used.` | `used_or_invalid` | ambiguous: wrong code *or* this uid already used it |
| `This coupon has expired.` | `expired` | global |
| `The coupon cannot be entered currently. Please try again later.` | `not_available` | transient |
| `The usage limit has been reached.` | `limit_reached` | ambiguous: global cap or per-account |

The h1/body strings match the game's `KG_Coupon_*` keys in `Strings_EN_US.xml`.

**Validation order is uid first, then code.** Proven by two live probes:
`uid=TESTUID000,code=ABCDE12345` → `no_pid`; `uid=S6R83U,code=ZZZZZZZZZZ9` → `no_coupon`.
That gives a **Player-ID probe** (dashboard "add account" uses exactly this) and it means
`no_coupon`/`expired` are global facts worth short-circuiting, while `used_or_invalid` must be
treated as one-shot per pair - **each `(uid, code)` is attempted exactly once**
(`redemptions` PK, first result wins). Player-ID format seen: 6-char alphanumeric (`S6R83U`).

Unrecognised pages are saved under `server/state/coupon_raw/` (gitignored - they contain UIDs)
for calibration; the success page's exact wording is still to be captured (first real code).

### Discord: the bot token cannot read the official server

- Official server: **KingGodCastle**, guild `766554437275615242`, invite `discord.gg/5d2H4sfHcA`
  (from the Google Play listing's "Official Forum" link). Features include `NEWS`/`COMMUNITY`.
- Our only token on the box is `server/secrets/discord_bot_token` = **bot** token
  (`King Bug Castle Bot`, user id `1538471329588842556`), member only of our own guild
  **King Bug Castle** `1537853106132484146`. It is *not* a user token - a selfbot plan needs a
  user token and the user declined to supply one after the finding.
- Live checks with that token against the official guild: `GET /guilds/…` → **404 Unknown Guild**,
  `GET /guilds/…/channels` → **403 Missing Access**, `GET /channels/{id}/messages` → **403
  Missing Access** (`code 50001`). A *discoverable* guild (tried `Castle` `515820161694171141`,
  a different game) does leak its channel list via `GET /guilds/{id}/channels` while the bot is
  not a member - but message reads stay 403, so that leak is useless on its own.
- **Chosen approach (superseded twice)**: first *Follow Announcement Channel* (the official server
  has no `📢` channel - the codes are posted in `#event`, a plain text channel, so Follow cannot
  mirror them), then a user-token selfbot (the user declined to supply one). **What actually runs**:
  the operator forwards codes into **`#coupon` in our own guild** (King Bug Castle
  `1537853106132484146`, channel `1553078533486682133`), and
  `couponbot.discord_feed.fetch_new_messages` polls that channel with the existing bot token
  (`GET /channels/{id}/messages?after=<snowflake>`, cursor in `meta.discord_cursor`). Read-only,
  no user token, no ToS risk. The official notice site was checked too: the 2026-08/09 updates
  carry no coupon keyword, so it is not a source.
- Config lives in `/etc/kgc/coupon.env` (or `server/secrets/coupon.env`): `COUPON_DISCORD_CHANNEL`
  (`1553078533486682133`), `COUPON_NOTIFY_CHANNEL` (default `1541439188686213221`, the CDN channel),
  `COUPON_WEB_PORT` (8083). Missing/failed token degrades the reader to
  `discord_mode=manual` (codes can still be added by hand on the dashboard) and notifies once.

### Layout

```
server/couponbot/{config,state,codes,coupon_client,discord_feed,worker,web}.py
server/couponbot/static/{index.html,app.js}     # vanilla JS + i18n.js, no build step
server/state/coupons.db                         # accounts / codes / redemptions / runs / meta
systemd/kgc-coupon.service                      # uvicorn on 0.0.0.0:8083, PUBLIC (8082 is playerportal)
systemd/kgc-coupon-worker.{service,timer}       # 10 min cycle, RandomizedDelaySec=60
server/serve_coupon.sh                          # manual start/stop wrapper
server/tests/test_couponbot{,_worker}.py        # 27 tests, network-free
```

Cycle = pull codes → for every enabled account × open code with no `redemptions` row →
`redeem()` (2 s throttle, stops early when `X-Rate-Limit-Remaining <= 5` or `Retry-After` seen).
A `flock` on `server/state/coupon.lock` keeps the timer and the dashboard's "Chạy ngay" button
from running concurrently.

**Dashboard = public, no login** (operator decision 2026-09-25): anyone may `POST /api/accounts`
(ID probe against the official site) or `POST /api/codes`, and an anonymous `GET /api/state`
returns the **complete ID list, complete code list** and the account × code matrix. There is
deliberately **no delete/disable route** (the routes do not exist - 404), so nothing on the page
can be removed; the operator escape hatch is `state.set_account_enabled(uid, False)` from a shell
on the box (the worker then skips it). Because the page is open, the three write routes are
throttled per client IP (`web.WRITE_LIMITS`: 20 account probes / h, 20 codes / h, 5 runs / 10 min)
- every probe and redeem is spent from OUR IP against the official site, and the site's rate limit
is what an unauthenticated page would otherwise hand to a troll. All user text is HTML-escaped in
`app.js` (`label` is free text and would otherwise be stored XSS on a public page).

**Bilingual (song ngữ, 2026-09-26)**: every string lives in `static/i18n.js` as
`const KGC_I18N = {vi, en}` written as **JSON inside the const** so the test suite can parse it.
`index.html` marks its text with `data-i18n` / `data-i18n-html` / `data-i18n-ph`, `app.js` renders
dynamic text through `t(key, vars)` with `{name}` placeholders (user data is `esc()`aped before it
is substituted), and the header button toggles VI/EN - the language follows the browser on first
visit, then the choice is stored in `localStorage.coupon_lang`. API errors carry a machine
`code` (`web.py`) plus the human Vietnamese `error`; the page translates the `code`, so the English
page never shows a Vietnamese sentence. Two regressions keep it honest:
`test_every_string_the_page_uses_is_translated_in_both_languages` (every `data-i18n`/`t("...")`
key must exist in **both** dicts) and `test_every_server_error_code_is_translated_too` (scans
`web.py` for `code="..."`).

**Static assets are never cacheable - incident 2026-09-26**: the page sits behind Cloudflare
(`auto-coupon.kingbugcastle.id.vn`), which caches `.js` on its own: with no `Cache-Control` from
the origin it invents `max-age=14400`, for **both** the edge and the visitor's browser. After the
bilingual deploy the edge kept serving the previous `app.js` (login-era, `$("loginForm").onsubmit`)
for hours, so the new page threw at line 139 **before `applyLang()` could run** - reported as
"song ngữ không hoạt động", with the i18n dict itself perfectly fine. `web.py` now sends
`Cache-Control: no-store` on `/`, `/app.js` and `/i18n.js`, and stamps the HTML with a content
hash (`_asset_version()`, one version for **both** files) so an entry already sitting in any
cache is simply a different URL - no CF purge needed. i18n is served from `/i18n.js` (its own
route, like `/app.js`) rather than the `/static` mount: routes match in registration order and
that mount is registered first, so a later `/static/...` route would never be reached. Regression
tests: `test_assets_carry_no_store_and_the_page_urls_are_versioned`,
`test_asset_version_changes_when_a_static_file_changes`.

The `static.cloudflareinsights.com/beacon.min.js` integrity/CORS errors that show up in the
console are Cloudflare Web Analytics being injected at the edge and then blocked - the reported
"computed hash" is SHA-512 of an **empty body**, i.e. an ad-blocker dropped the request. Harmless
and unrelated to the page.

### Open questions
- Exact success-page wording (need one real code) and the real code format (does the extractor's
  `[A-Z0-9]{8,20}` + letter/digit rule cover it?).
- Is `usage limit has been reached` global or per-account? Treated as per-pair one-shot either way.
- ~~Whether the official `📢` channel carries codes~~ - resolved: the official server has **no**
  announcement channel (codes live in the text channel `#event`, which Follow cannot mirror), so
  codes are forwarded by hand into our own `#coupon` and polled from there.

## 28. Strife Leaderboard turned off (2026-09-26)

Two halves were disabled because the scheduled fetch kept failing (upstream
`https://kgc-k8s-1.awesomepiece.com/colosseum` returns **403 NotLatestVersion**, and GitHub mails
one failure notification per run - the cron was every 15 minutes):

1. **CI/CD**: workflow `Update Strife Leaderboard` disabled as a repo *setting*, not in git -
   `state: disabled_manually` via `gh workflow disable "Update Strife Leaderboard"`. The cron in
   `.github/workflows/update-strife-leaderboard.yml` is untouched (still `*/15`), so re-enabling is
   `gh workflow enable "Update Strife Leaderboard"` and it starts again with the same file.
2. **Web**: GitHub Pages page deleted - `docs/strife-leaderboard.html` (404 now) and its data
   `docs/strife-leaderboard-data.json`, plus both inbound links: the nav item in
   `docs/strife-compendium.html` (`#nav-leaderboard`) and the paragraph in `docs/index.html`.
   `scripts/update_strife_leaderboard.py` already guards the HTML with "if present" (only the JSON
   path is unconditional), so a re-enabled workflow would just re-commit the JSON.

**To bring it back**: `gh workflow enable "Update Strife Leaderboard"` then
`git revert <the delete commit>` (restores the page + data + both links). If the 403 persists,
pass the `version` workflow_dispatch input (the runner derives it from `api/version.py`, and the
403 means the ranking API is ahead of the bundled client).

## 29. Hand-granting a custom accessory set (2026-09-27)

Recipe used to grant `p-2787e1889bcd` a "Barbarian" set with 9999% sub-stats (also the general
shape for any future admin grant - no endpoint exists, so it goes through `playerdb` like §22):

- **Slot layout is 5 per hero, not 4**: the client pads `targetIds` to 5
  (`r_accessory_equip`'s `is_padded = len(target_ids) >= 5`) and the observed pattern per unit is
  `type 1, 2, 3, 3, 4` = Necklace, Bracelet, **Ring x2**, Earring. Only 4 `<AccessoryType>` rows
  exist in `AccessoryConstants.xml` (Ring just occupies two slots).
- **Set = the `synergy` int**, not a name: `AccessorySynergyName_5 = Barbarian` (0 Steel, 1 Fear,
  2 Sharpness, 3 Ocean, 4 Wind, 5 Barbarian, 6 Adamant, ...); `AccessorySynergyBuff` ids are
  `10000 + synergy*10`, e.g. Barbarian's 2-piece is `AccessorySynergyDesc_10050 = +% ATK`.
- **Stat keys vs display labels** (Strings_EN_US): `MAtk` = "Spell Power", `SpecialDamageMul` =
  "Special Damage" - so the accessory keys are `MAtkPer` (Spell Power %) and
  `BaseSpecialDamageMul` (Special Damage %). Both `ValuePerScore = 1.0`, so `subStatScores` = raw
  value and any huge value lands on the top grade (`AccessorySubStatScoreRange` tops out at 26.5).
- **Sub-stat pool constraints are generation-time only.** `MainStatInfo.SubStats` and
  `roll_accessory`'s sampling decide what a *rolled* item may get; nothing validates what is in
  the save. The one hard rule is `data.mainStat` must be a legal main for the type or the client
  renders an empty name (Necklace `AtkPer|MAtkPer`, Bracelet `BaseDef|BaseMDef`, Ring
  `HpPer|AttackSpeedPer|BaseDefPen|BaseDefDen`, Earring `BaseCriticalDamageMul|
  BaseMCriticalDamageMul|BaseDef|BaseMDef|BaseSpecialDamageMul`).
- **Shape**: copy sibling keys from an existing item, then set `data.subStats` (unique keys),
  parallel `subStats` + `subStatScores` (= value / `VALUE_PER_SCORE`), `synergy`, `rarity: 3`,
  `level: 20`, `unitId: 0`, `slot: 0`. Ids are per-save; the next mint is `max(id)+1`
  (`rewards._next_accessory_id`), so appending at max+1 never collides.
- **Verify with the real route**, not just a re-read: `routes.accessory.r_accessory_inventory({}, st)`
  runs `ensure_accessory_state` (which merges duplicate sub-stat keys and recomputes the parallel
  lists) - `changed` must be `False` for hand-written items. The GET `/accessory` wiring is
  `routes/direct_routes.py` (server.py's `"/accessory"` POST entry is the *equip* handler).
- Backup first via `playerdb._backup('<tag>')` (sqlite `.backup` API), write with
  `playerdb.load/save`.

Grant applied: ids 68-72, synergy 5, mains `MAtkPer / BaseDef-ish / HpPer / AttackSpeedPer /
BaseSpecialDamageMul`, both sub-stats `BaseSpecialDamageMul` 9999 + `MAtkPer` 9999.
Backup `players-20260927-152403-barb9999.db`.

## 30. Official-client patch-flow decode + il2cpp literal xref recipe (2026-10-05)

Decoded from the OFFICIAL 173.1.00 dump (`il2cpp/v173.1.00/`: `stringliteral.json`, `dump.cs`,
`libil2cpp_v1731.so`) - answers "how does the real client fetch master data" with zero
private-server code involved.

**How the official client builds CDN URLs:**

- Base `https://kgc-cdn-1.awesomepiece.com/patch/` + relative folder + `ANDROID` + `/AssetHash.txt`
  etc. Routes baked in metadata: `/auth/getPatchFolder` (`RestAPI.GetPatchFolder()` ->
  `PatchFolderResponseModel.patchFolder`), `/auth/usePatch?platform=`, `/auth/checkPatchVersion`.
- Folder fallback `LIVE/2026_09_22` has exactly ONE code reader: `Constants..cctor` @ RVA
  `0x2FC7160`. There is no standalone `LIVE` literal, so the client never prepends `LIVE/` itself -
  whatever the backend returns IS the relative path (official backend presumably returns
  `LIVE/<date>`; our `response_config.json` returns bare `2026_09_22` and `server/cdn.py` matches
  by final filename, which is why the shape difference is invisible privately. Do not "fix" one
  shape into the other blindly).
- CDN base is read by exactly 3 coroutines: `AssetBundleManager.<Load>d__30` (MoveNext RVA
  `0x37826E0`), `<LoadTargetAsset>d__27` (`0x3783A84`), `<UpdatePatchSetList>d__35` (`0x3784444`);
  `AssetBundleManager.GetPatchFolder()` RVA `0x3781E5C` returns the static field filled from the
  server response; `CurrentPlatformString()` RVA `0x3781E1C` -> `"ANDROID"`
  (`CommonDataWrapper.GetPlatform()` RVA `0x60E5138` = twin).
- 0 of 25,905 string literals are list-query params (`prefix=`/`max-keys`/`list-type`) - the client
  never lists the bucket, only concrete GETs, so the GCS list denial is invisible to it.

**il2cpp literal xref recipe (which method uses string S):**

1. The code section is named **`il2cpp`**, NOT `.text` (`readelf -SW`); `RVA = fileoff + 0x4000`
   (cross-check against `dump.cs` `Offset:`). Scanning `.text` silently returns 0 sites - that bug
   cost a whole debug round.
2. `stringliteral.json` gives `value -> address`; `.rela.dyn` (24-byte entries - parse with numpy,
   not `readelf -r` on the full file) maps `offset` (GOT slot vaddr) -> `addend` (literal address).
   Find the slot(s) for S.
3. Scan the `il2cpp` section for `ldr xT,[xN,#pageoff]` (compare `(w & 0xFFFFFC00)` against
   `0xF9400000 | (off/8 << 10)`) and `add xT,xN,#off`; walk back <=8 instructions for a same-reg
   `adrp` whose computed page == the slot's page.
4. Map site RVA -> dump.cs: the `// RVA: 0x...` line + the NEXT line = signature; but ALSO track
   the nearest preceding `class X` / `struct X.<M>d__N` declaration, otherwise every async method
   resolves to an anonymous `MoveNext()`.
5. Always sanity-check the scanner against a KNOWN site first - a 0 result from an untested
   scanner is a bug, not a finding (this is what exposed step 1).

String access in this build is exclusively GOT-slot (adrp+ldr through `.rela.dyn`);
`il2cpp_codegen_string_literal_from_index` is absent from dynsyms - skip the movz-index technique
here. Scan script from the session: `/tmp/opencode/scan_literal_refs_v2.py` (recipe above is
self-sufficient to recreate).

RESOLVED 2026-10-05: official `/auth/getPatchFolder` (prod `kgc-k8s-1.awesomepiece.com`) IS
pre-auth readable (spec `AccessToken` required=false) with the exact client recipe - verified
HTTP 200, response shape = **`LIVE/2026_09_22`** (full `LIVE/<date>`, not bare date); the dev
env returns `patchFolder: ""`. Wired into `scripts/check_cdn_update.sh` as the primary folder
source (union into all_dates, beats the 45-day HEAD-probe ceiling). Request recipe: see §31
tail. Budget note: ~10 prod requests spent on this (~290/300 left).

RESOLVED 2026-10-20: `getPatchFolder` POINTER LÀ VERSION-GATE — cùng endpoint, đổi header
`version` là đổi kết quả: `174.0.x` → `LIVE/2026_10_06_xGrY0WbLgR`, `≥174.1.00` (thử tới
`999.0.00` đều được) → `LIVE/2026_10_20_bhhtbJKhrR`. Nghĩa là: (1) probe version "quá mới"
`999.0.00` = luôn trả newest → biết data mới TRƯỚC cả khi store có client mới (APKPure vẫn
174.0.00 lúc đó); (2) KHÔNG hardcode version thật — `scripts/check_cdn_update.sh`
`official_patch_folder()` giờ probe cả client_ver lẫn `999.0.00` rồi `max()`. Tương lai
dev flip folder mới → watcher tự thấy, không cần bump version tay. Cách này find ra bản
10-20 trong khi HEAD-probe +45 ngày fail hoàn toàn (folder có suffix ngẫu nhiên).

## 31. Official-client request headers, complete list (v173.1.00, 2026-10-05)

Exhaustive: BL-scan of `UnityWebRequest.SetRequestHeader` (RVA `0x644B668`) yields exactly **32
call sites**, all decoded (`(w>>26)==0x25`, sign-extend imm26, target = siteRVA + imm; numpy scan
runs in <1s). No header can exist outside this list + the `WWW`-dict path below.

**Game API - every `RestAPI.*` call funnels through these `Web.*` MoveNexts:**

| header | value | set in | site RVA |
|---|---|---|---|
| `Content-Type` | `application/json` | `Post d__17` / `Put d__19` / `Delete d__21` | `0x538F8CC` / `0x53984FC` / `0x4FB96FC` |
| `version` | `Application.get_version()` | `Get14`, `Get15`, `Post17`, `Put19`, `Delete21` | `0x50A95D4` / `0x50AA95C` / `0x538F910` / `0x5398540` / `0x4FB9740` |
| `platform` | `Application.get_platform().Enum.ToString()` | same five | `0x50A9624` / `0x50AA9AC` / `0x538F960` / `0x5398590` / `0x4FB9790` |
| `time` | `Utility.GetServerTimestampV2()` when session-key flag set, else `GetServerTimestamp()` (`0x379B864` / `0x379B614`, both return a string, fallback `DateTime.Now`) | `Get14`, `Post17`, `Put19`, `Delete21` - **not** `Get15` | `0x50A9680` / `0x538F9BC` / `0x53985EC` / `0x4FB97EC` |
| `accessToken` | state field (`[x19,#0x38]`), emitted only if non-null (`cbz` skip) | same four | `0x50A96A4` / `0x538F9E0` / `0x5398610` / `0x4FB9810` |
| caller pairs | `List<(name,value)>` loop, one `SetRequestHeader` per element | `Get d__15` only | `0x50AAA00` (shared-generic `0x50ABAE4/0x50ABB5C/0x50ABC08`) |

`Web.Get(endPoint, uri, customHeaders)` (`0x3CE77A0`) has exactly **2 callers**:
`RestAPI.<GetDefaultInfraRankingServer>d__438` and `RestAPI.<GetDevServers>d__437`. So the normal
path (`Web.Get(uri, accessToken)` `0x3CE76EC`, 105 callers / `Post` `0x3CE7BBC`, 228) never sees
caller headers. `Web.HandleWebHeader` (`0x2D38F00`) reads response `NeedTriggerFetch` only.

**Non-Web sites (the other 8):**
- `TimeCheatingDetector.GetWebRequest` (`0x2BF69D0`): `Accept-Encoding` = `""`, only when
  AndroidSDKLevel < 18 (site `0x2BF6C04`); both callers are inside TimeCheatingDetector itself.
- `DeepLinkManager` anti-piracy POSTs - `AxisBladeCheckPost d__5` (`0x3569AD8`),
  `AxisBladeOpenEventRequest d__6` (`0x356AA64`), `IsekaiGateCheckPost d__8` (`0x356B3C8`): each
  sets `Content-Type: application/json`.
- `Unity.Services.Analytics.Internal.WebRequestHelper.CreateWebRequest` (`0x60EC580`):
  `x-client-id` = its own field `+0x10` (site `0x60EC670`) + `uploadHandler.contentType =
  application/json`; 0 BL callers (interface-dispatched from the analytics dispatcher).
- Unity internals: `UnityWebRequest.SetupPost` (`0x644C400`) copies `WWWForm.headers`;
  `WWW.ctor(url,post,headers)` (`0x644D044`) copies a caller dict - generic loops, no literals.

**Third path (not `SetRequestHeader`)**: `BugReportApi.<Submit>d__19` calls `WWW` with a dict -
`Content-Type: application/json`, `Accept`, `Method: POST`, `X-ApiKey` ->
`http://srdebugger.stompyrobot.uk/report/submit` (SRDebugger reporter). Firebase
`<AddFirebaseTokensAsync>d__27/d__28` set `Authorization` for Firebase sockets (Firebase is stubbed).

**Absent (checked, do not re-derive):** `User-Agent`, `Accept`, `Cookie`, `Authorization` in the
game layer (reverse literal pass hits only System.Net/Newtonsoft/`HttpHeaders..cctor`), `nonce`,
`sign`/`signature`, lowercase `accesstoken`, and `encryptedWithHex` - the last is **not in
`stringliteral.json` at all**. No signing scheme: `Utility.MD5` (RVA `0x378A360`) has **0 BL
callers** and its method pointer appears once (the pointer table) = dead code in this build.

Related (not a header): POST/PUT/DELETE bodies are **always** AES-encrypted - the MoveNext calls
`Utility.AESEncryptWithSessionKey` (`0x3799FFC`) or `AESEncryptWithServer` (`0x37989E0`, produces
hex via `{0:x2}`) right before `UnityWebRequest.PostWwwForm` (Post sites `0x538F878` / `0x538F894`);
the private server already handles this (`server/crypto.py::aes_decrypt`, `server.py:559`).

Scanner: `/tmp/opencode/bl_callers.py` (BL -> caller method incl. state-machine owner), built on the
§30 recipe; `dumpblk.py` for annotated block disassembly.

**Value decodes (follow-up disasm, same session):**

- `GetServerTimestamp` (V1 `0x379B614`) = `AES_hex(str(unix_ms))` after login, and
  **`AES_hex("beforeLogin")` when `GameManager.logined == false`** - NOT md5 (the older
  `docs/api-and-crypto.md` claim "MD5(unix_timestamp)" is wrong for this build; `Utility.MD5`
  is dead code). V1 = AESEncryptWithServer: AES-128-**ECB**, **Zeros** pad, lowercase `{0:x2}`
  hex, key = the static `crypto.py AES_KEY`. V2 (`0x379B864`) = AESEncryptWithSessionKey
  (AES-CBC/PKCS7, X25519 session key) but `useSessionKey = accessToken != null && HasSessionKey`
  and the handshake only exists in-game -> **V1 is the live path for every pre-auth call**.
  `time` header value goes in as-is (no prefix).
- `RestAPI.<GetPatchFolder>d__7.MoveNext` body build: `platform` = `Application.get_platform()
  .Enum.ToString()` -> **`"Android"`** (NOT `CurrentPlatformString()`/"ANDROID" - those differ:
  header+body use "Android", the CDN folder literal uses "ANDROID"), `version` =
  `Application.get_version()`, `isDev` = `Constants.DEVELOPMENT_MODE`, then `JsonUtility.ToJson`
  -> `Web.Post<T>(uri, json, accessToken=NULL, useSystemSerializeFunc=false)`; the null token
  skips the `accessToken` header and forces the V1 encryptor.
- Wire form: `AESEncryptWithServer(json)` -> lowercase hex string posted verbatim as
  `UploadHandlerRaw` content (form-encoding is a no-op on hex), `Content-Type` then overridden
  to `application/json`.

**Verified pre-auth recipe (prod 200, 2026-10-05):**

```
POST https://kgc-k8s-1.awesomepiece.com/auth/getPatchFolder
Headers: version: 173.1.00 | platform: Android | Content-Type: application/json
         time: hex_aes("beforeLogin")
Body:    hex_aes('{"platform":"Android","version":"173.1.00","isDev":false}')
hex_aes = lowercase hex of AES-128-ECB(a6072ad6b9c959ff, zero-padded utf8)
Resp:    hex_aes -> {"code":200,"msg":null,"patchFolder":"LIVE/2026_09_22","success":true}
```

Plain JSON body => 400; raw binary body => 400; empty `{}` => 400 (all rejected before the
controller). Dev env with the same recipe => 200 but `patchFolder: ""`.

**VERSION-GATE (chứng minh 2026-10-08)**: `patchFolder` phụ thuộc `version` header/body —
cùng recipe, `173.1.00` → `LIVE/2026_09_22` (bị pin), `174.0.00` → `LIVE/2026_10_06_xGrY0WbLgR`
(bản đang phát). Luôn gửi version của client mới nhất. Từ bản này folder mang **suffix ngẫu nhiên**
`YYYY_MM_DD_<10 ký tự base62>` (không đoán được → HEAD-probe vô dụng với tên mới, chỉ API biết);
`timeCreated` GCS = 2026-10-07T22:09Z (≈4h trước maintenance 08/10 11:00 KST — "upload trước
1-2 ngày" đúng theo TÊN folder 10_06, upload thật cách release <1 ngày).

## 32. Unity rebuild — S1 polish: locale runtime + ApplyLoginSceneIllustData (v174.0.00, 2026-10-09)

Scope: 2 mục S1 còn treo — (1) `ApplyLoginSceneIllustData` đúng bản gốc,
(2) đổi ngôn ngữ runtime từ LocalePanel (login). Toàn bộ RE đọc từ
`il2cpp/v174.0.00/` (`dump.cs` RVA + `script.json` + disasm/Ghidra decomp),
code ghi vào `unity/kgc-rebuild/ExportedProject/Assets/Scripts/Assembly-CSharp/`.
**4 gate pass** (xem cuối mục).

### Bảng RVA đã decode

| Method | RVA | Ghi chú |
|---|---|---|
| `Scene_Login.Awake` | `0x36424D4` | |
| `Scene_Login.ApplyLoginSceneIllustData` | `0x36435F8` | |
| `Scene_Login.OnClickLocaleButton` | `0x3647244` | `localePanel.Show(OnSelectLocale)` — Show bị inline |
| `Scene_Login.OnSelectLocale` | `0x36472D4` | |
| `Scene_Login.ReloadTermsPanel` | `0x3647358` | bị inline vào OnSelectLocale → decomp thấy 2 câu `L("LanguageName")` |
| `LocalePanel.Show` | `0x3343C30` | |
| `LocalePanel.OnSelectLocale` | `0x3343D18` | |
| `Localizer.ChangeLocale` | `0x34DBA10` | |
| `Localizer.SetCanvasRoot` | `0x34DC744` | setter 8 byte |
| `LocalizerUtility.L(str)` / `L(str,def,fromKR)` / `KR` | `0x34DCB80` / `0x34DCC18` / `0x34DCDA4` | |
| `Utility.SetActive` ×4 | `0x2C84C00` Mono / `0x2C8F008` Transform / `0x2C8F034` CanvasGroup / `0x2C8F060` Renderer | |
| `Utility.ToColor(string)` | `0x2C8CEB8` | |
| `Utility.MakeOriginSize` | `0x2C94374` | |
| `Utility.SetColorWithoutAlpha` | `0x2C98D68` | |
| `ResourceSkill.HandleLanguageChanged` | `0x2DF8DA4` | |
| `GameManager.Get` / `.ctor` / `SaveSetting` / `.cctor` | `0x3148984` / `0x3147E7C` / `0x3149B8C` / `0x3185F4C` | |

### Decode từng chỗ (đủ để port lại, không cần decomp lại)

- **`Utility.SetActive` ×4** = `@this.gameObject.SetActive(value);` — null `this`/
  null `gameObject` → NRE (IL2CPP check, không guard).
- **`Utility.ToColor(s)`**: `uint.TryParse(s, NumberStyles.HexNumber /*0x203*/,
  InvariantCulture, out v)` fail → `Color.white`; asm dùng
  `w11=0xff; bfi w11,w8,#8,#0x18` = **`(v<<8)|0xFF` khi `s.Length==6`**, `csel` theo
  `cmp len,#6`; rồi `rev w8` → component = byte cao trước. Port đúng:
  `len==6 → v=(v<<8)|0xFF`, return `((v>>24)&0xff, (v>>16)&0xff, (v>>8)&0xff, v&0xff)/255f`.
  Length 6 = `RRGGBB` (alpha=255), length 8 = `RRGGBBAA`.
- **`MakeOriginSize(image, scale=1)`**: `if (image.sprite==null) return;`
  `image.rectTransform.sizeDelta = (sprite.rect.width*scale, sprite.rect.height*scale)`
  — asm đọc `image.sprite` **3 lần** (guard + width + height), const `-1f` là default
  của nhánh chết sau guard.
- **`SetColorWithoutAlpha(image,color)`**: `var c=image.color;
  image.color=new Color(color.r,color.g,color.b,c.a);` (alpha tham số bị bỏ).
- **`ForEach`/`Find`**: loop chỉ số thuần; Find trả phần tử đầu match / `default`.
- **`ReloadTermsPanel()`**: `localeText.text=L("LanguageName")` →
  `termAgreeButton.interactable=false` → `ForEach(termAgreements, t=>t.isOn=false)`
  (setter — KHÔNG phải `SetIsOnWithoutNotify`, invoke không điều kiện) →
  `nightPushAggrement.SetActive(currentLocale==KR)` (**`GameObject.SetActive` trực tiếp**,
  không phải extension) → `nightPushAggrementToggle.isOn=false` → `loginPanel.SetActive(false)`.
  Mọi truy cập đều trực tiếp → NRE-faithful.
- **`Scene_Login.OnSelectLocale(locale)`**: `_locale=locale` (field +0x260, **câu đầu tiên**)
  → `localeText.text=L("LanguageName")` → `ReloadTermsPanel()`.
- **`LocalePanel.Show(cb)`**: `_callback=cb` → `Utility.SetActive(buttons[buttons.Length-1],
  Constants.DEVELOPMENT_MODE)` (null buttons → NRE, rỗng → IndexOutOfRange; asm bounds check
  `uint` nên cả -1 cũng IOOR) → `gameObject.SetActive(true)`. `DEVELOPMENT_MODE` = `ObscuredBool`
  → implicit `bool` (ACTk thật).
- **`LocalePanel.OnSelectLocale(idx)` đúng thứ tự**:
  `var old=_locale` → `_locale=Localizer.Locales[idx]` (uint bounds) →
  `GameManager.Get().settings.newLocale=_locale.ToString()` → `GameManager.Get().SaveSetting()`
  → `Localizer.Instance.ChangeLocale(_locale)` → `Utility.LogAdjust("t4335r",
  ("before_locale",old.ToString()??""),("after_locale",_locale.ToString()??""))` →
  `_callback?.Invoke(_locale)` → `Utility.SetActive(this,false)`. Hai `Get()` **riêng biệt**.
- **`SaveSetting()`**: `AwesomePrefs.SetString("Settings", JsonUtility.ToJson(settings), false);
  AwesomePrefs.Save();` — key `"Settings"` lấy từ cell `0x69762a0` (**xem recipe rela.dyn bên dưới**).
- **`Localizer.ChangeLocale(locale)`**: `Clear(); Initialize(locale);
  if (canvasRoot!=null){ foreach t in canvasRoot.GetComponentsInChildren<LocalizedText>(true) t.OnEnable();
  foreach i in …<LocalizedImage>(true) i.OnEnable(); }` rồi tail = **3 cờ static
  `CrossAssemblyDefinitions` (locale==JA / ZH_TW / ZH_CH) — BỎ**, class không có trong
  export và code LocalizedText không đọc → chỉ còn `ResourceSkill.HandleLanguageChanged()`.
  **Không có guard `Locale.None`** (None → `Initialize` map về DefaultLocale).
- **`ResourceSkill.HandleLanguageChanged()`**: `foreach (kv in datas)` với
  `var s=(ResourceSkill)kv.Value;` (castclass cứng, null value → cast ok rồi NRE ở field store),
  null 4 cache `_longDesc/_shortDesc/_altShortDesc/_altLongDesc`. **`datas` null → NRE**;
  root-cause fix = initializer `ResourceBase<T>.datas = new Dictionary<int,object>()`
  (ResourceBase chưa bao giờ load → không bao giờ gán), không guard từng caller.
- **`GameManager` minimal** (chỉ đủ cho locale flow; body 5.800 dòng còn lại để stub):
  `.cctor` → `_singleton=new GameManager()` (bỏ 3×`WorkTimer.GenerateSimpleKey()` + list/pool,
  có comment); `.ctor` → `settings=new Settings()` (field +0x130, bỏ phần còn lại);
  `Get()` → `return _singleton;` — **trước đây `return null` làm OnSelectLocale NRE**.
- **`AwesomePrefs` vẫn stub** (`GetString→null`, `SetString/Save` no-op) → Apply chạy
  particle-size rồi `FromJson(null)→null→return` = **đúng nhánh lần đầu của bản gốc khi key
  chưa có** (asm có `if (data==null) return;` ngay sau assign → FromJson(null) không ném, nếu
  ném thì game gốc đã crash lần boot đầu).

### `ApplyLoginSceneIllustData` (`0x36435F8`) — thứ tự chính xác

1. `int w=Screen.width, h=Screen.height` (lưu trước — asm gọi lại `get_width/height` lần 2
   cho shape.scale, giá trị như nhau → port dùng `w/h`).
2. `var shape=_screenParticle.shape; shape.scale=new Vector3(w/10f+10f, h/10f+10f, 0f);`
3. `var emission=_screenParticle.emission;
   emission.rateOverTime=new ParticleSystem.MinMaxCurve((int)Math.Round(w*h/150000f));`
4. `var main=_screenParticle.main; main.maxParticles=(int)Math.Round(w*h/30000f);`
   (`Math.Round` = banker's rounding — asm `modf` ±0.5 + even check → mặc định C# ✓;
   `(int)` cast inf → int.MinValue, unchecked ✓. **`main` local dùng lại ở bước 13**.)
5. `loginSceneIllustData = JsonUtility.FromJson<…>(AwesomePrefs.GetString(LoginScenePrefsKey,null,false));`
   → assign **trước khi** check null. Key const = `"LastLoginSceneIllustData_20260422"`.
6. `if (loginSceneIllustData==null) return;`
7. `sprite=Utility.Find(_loginIllusts, s=>s.name==data.illust); _illustImage.sprite=sprite;`
   (predicate đọc **static field** → không capture → asm cache delegate trong `<>c` +0x20;
   port dùng local `data` = display class, hành vi như nhau).
8. `_illustImage.MakeOriginSize(1f)` (asm truyền `0x3f800000` explicit).
9. `transform.localScale=Vector3.one*data.scale`
   → `rectTransform.anchoredPosition=new Vector2(data.x,data.y)` (x,y là **int**)
   → `rectTransform.rotation=Quaternion.Euler(0f,0f,data.rotation)` (asm inlined
   `*Deg2Rad` rồi `Internal_FromEulerRad`).
10. `ForEach(_effectImages, x=>x.gameObject.SetActive(!data.disableBGAndEffects))` →
    `_effectParticle.SetActive(!data.disableBGAndEffects)`.
11. nếu `disableBGAndEffects`: `_castleBG.SetActive(false); _bgBlur.spriteBlending=1f;`
    — **`spriteBlending` là FIELD của `LeTai.TranslucentImage`** (không có `get_/set_` trong
    #Strings; asm `str` thẳng +0x144). Đã xác minh có trong DLL.
12. `effectColor=ToColor(data.effectColor)` (đóng closure +0x10) →
    `bottomGradientColor=ToColor(data.bottomGradientColor)`.
13. `ForEach(_effectImages, x=>x.SetColorWithoutAlpha(effectColor))` (closure không cache) →
    `_bottomColoredImage.SetColorWithoutAlpha(bottomGradientColor)` →
    `_bottomColoredGradationImage.color1=new Color(b.rgb, color1.a)` (`a` lấy lại của image,
    `color1.a` @UIGradient+0x50, `color2.a` @+0x60) → `color2=` tương tự →
    `main.startColor=effectColor` (**dùng lại local `main` ở bước 4**).
14. `AwesomePrefs.SetString(LoginScenePrefsKey, JsonUtility.ToJson(loginSceneIllustData), false);`

`LoginSceneIllustDataResponseModel` field offsets khớp dump: `illust@0x30 x@0x38 y@0x3C
rotation@0x40 scale@0x44 effectColor@0x48 bottomGradientColor@0x50 disableBGAndEffects@0x58`.

### `SetCanvasRoot` — tìm call site bằng BL-scan (recipe tái sử dụng)

`SetCanvasRoot` là setter 8 byte, không đọc từ code đọc được. Quét `.so` lấy BL tới
RVA `0x34DC744` (`(w>>26)==0x25`, imm26 sign-extend, `target = rva + imm*4`, RVA = file+0x4000)
→ **đúng 3 caller**:
`Scene_Game.Awake` (`0x2E642A0`), `Scene_Lobby.Awake` (`0x362B50C`),
`Scene_Login.<LoadAfterAssetBundleImpl>d__84.MoveNext` (`0x365197C`) — cả 3 đều
`SetCanvasRoot(this.transform)` (disasm quanh call site: `get_transform(x19=this)` → `x0=Instance`).
Kết luận: **KHÔNG có trong `Scene_Base.Awake`** → port:
`Scene_Login.Awake` gọi `Localizer.Instance.SetCanvasRoot(transform)` (rebuild bỏ chuỗi
`LoadAfterAssetBundleImpl`); Scene_Lobby/Scene_Game **phải tự thêm lúc S2** (Awake của 2 scene
này là stub trống, không gọi `base.Awake()`).
Ghi chú: Scene_Login component **đứng trên object "Canvas" (root)**; Scene_Lobby component
đứng trên **"BaseCanvas" (root)** → refresh chỉ phủ subtree canvas đó (bản gốc cũng vậy).

### Recipe resolve string trong `.data` (cell pointer = 0 trong file)

`script.json` `ScriptString[].Address` là **số thập phân (RVA)**; `.data` cell trong Ghidra
khác script space **+0x100000**. File bytes tại cell = `00` (relocatable) → đọc **`.rela.dyn`**
(`SHT_RELA`, entsize 24): `r_offset` = VMA cell, `r_addend` = VMA string → tra `ScriptString`.
Đã dùng cho: `0x69762A0 → "Settings"` (SaveSetting key), `0x6982AE8 → "LanguageName"`,
cells LogAdjust `0x69819D0/9D8/9E0 → "before_locale" / "t4335r" / "after_locale"`.
`script.json` `ScriptString.Value` có thể rỗng → fallback đọc bytes tại addend.

### Porting gotchas gặp thật

- **CS1612** `Cannot modify the return value of 'ParticleSystem.shape'/'emission'/'main'`:
  module struct Unity 2022 trả về bản copy → bắt buộc `var main = ps.main; main.x=…;`.
  Khớp với decomp (result của `get_main` nằm **trên stack slot, dùng lại 2 lần** →
  bản gốc cũng khai local).
- `Utility.ToColor` cần `using System.Globalization;` (Utility.cs không có).
- `Locales`: `Enum.GetValues` = **14** entry (có AR@13) vs blob gốc 13 (AR loại) —
  13 button trong scene wired `OnSelectLocale` arg **0..12** → AR không tới được, vô hại.
- `Localized*` component: **Scene_Login.unity không có cái nào** (0 ref) →
  canvasRoot refresh là no-op ở login; `Scene_Lobby.unity` có hàng trăm (dưới BaseCanvas/
  PopupCanvas/OverlayCanvas — 3 **root** riêng) → quan tâm lúc S2.

### Gate (tất cả pass 2026-10-09)

| Gate | Lệnh | Kết quả |
|---|---|---|
| compile | `Unity -batchmode -nographics -quit -projectPath <proj> -executeMethod Kgc.Editor.MasterDataSmokeTest.Run` | exit 0, 0 `error CS`, `[S0] master data` 4 bảng |
| locale (mới) | `-executeMethod Kgc.Editor.LocaleSmokeTest.Run` | exit 0, `[S1] locale smoke test OK` — check ToColor (6/8-digit, parse-fail→white), ForEach/Find, `GameManager.Get()+settings+SaveSetting`, `ChangeLocale(VI/EN_US)` → `L("LanguageName")` = `Tiếng Việt`/`English`, `HandleLanguageChanged` không NRE |
| audit | `KGC_AUDIT_SCENE=Scene_Login KGC_AUDIT_STRICT=1 … -executeMethod Kgc.Editor.SceneAudit.Run` | exit 0, `missingScripts=0 locKeys=31/31` |
| play capture | `KGC_CAPTURE_PLAY=1 timeout 300 xvfb-run -a -s "-screen 0 1280x2048x24" <Unity> -batchmode -force-glcore -projectPath <proj> -executeMethod Kgc.Editor.CaptureScene.Run` | exit 0, `[PLAYCAPTURE] play capture ok`, screenshot `/tmp/opencode/shot_Scene_Login.png` render đúng, không exception |

## 33. v174 request-format audit + the AES key bug (2026-10-09)

Prompted by "lỗi không phải do token, mà do cách req/res mình đang làm". Checked the client
code, then A/B-tested prod. **Verdict: the format had 2 real bugs, neither explains the dead
tokens.**

### Client header set re-derived on v174.0.00 (same as §31, re-verified)

`Web.<Get>d__14<object>.MoveNext` (generic inst RVA **0x5120F64**) sets exactly
`version` ← `Application.get_version()`, **`platform`** ← `Application.get_platform().ToString()`,
`time` ← `GetServerTimestampV2/V1()`, `accessToken` ← state field (skipped when null).
No `x-unity-version`, no `encryptedwithhex` (still absent from `stringliteral.json`).
`Web.SetHandler` (0x2DAAAF8) only installs the certificate handler - no headers.
The 3 other `SetRequestHeader` callers in game code are `DeepLinkManager` collab POSTs
(`Content-Type: application/json` only).

**Bugs found in `api/config.py` (both fixed, test `server/tests/test_api_client_format.py`):**

1. `AES_KEY` was `b53019bb76da6b34` (the v169 value) -> prod answers **HTTP 400** to every POST
   and responses are undecryptable. Correct = `a6072ad6b9c959ff` (`server/crypto.py`).
   Verified live: same body, only the key differs -> 400 vs 200.
2. `platform` header missing; `time` was `md5(unix_seconds)` instead of
   `AES(str(unix_ms))`; `x-unity-version` + `encryptedwithhex` were invented.
   `tools/prod_probe.py` A/B on `/auth/getPatchFolder`: `time` = **md5 still returns 200**,
   so the server does not validate the `time` value - only its presence was in doubt and the
   400 turned out to be cause (3) below, not `time`.

### Extra finding: an invalid `accesstoken` header turns a pre-auth 200 into HTTP 400

`/auth/getPatchFolder` answers 200 with no token but **400** when the auto-loaded dead token
from `captured_token.txt` rides along. So a 400 there is a *token* symptom, not a body symptom.

### Token blocker unchanged - format is NOT the cause

`GET /player` with the same (dead) token, correct headers vs the old config.py shape, one
minute apart: **both `401 NotCertifiedToken`**. Header shape changes no token verdict.
Re-confirmed dead ends:
- The captured plist holds only `accessToken`, `lastLoginId`, `GuestId` - **no XIGNCODE cookie**
  (all 506 prefs keys decrypted, `tools/extract_ios_token.decrypt_3des`); cookie stays runtime-only.
- `POST /auth/login` (with token in query and/or `accesstoken` header, real `deviceUuid` =
  `UnityInstallationId` from the plist) cannot revive a purged session -> same 401.
- Every other endpoint tested without a token -> `401 WrongTokenError`.

Open question: authenticated POST bodies may be encrypted with the **session key** established by
`RestAPI.Auth`'s `BeginCryptoV2Handshake` (X25519) rather than `AESEncryptWithServer`; untestable
until a live token exists. GETs (all of find_player) have no body, so this only affects POSTs.

### Tooling (now in-repo, replaces the /tmp scanners in §30)

- `tools/lit_refs.py` - string literal -> ADRP/LDR sites -> owning method (fixes the §30 step 1
  trap: scan every exec section, the code is in `il2cpp`, not `.text`; also reads the
  `/* GenericInstMethod : */` RVAs, which is where generic MoveNexts like `Web.<Get>d__14` live).
- `tools/bl_callers.py <dump> <so> <target_rva> [--literals]` - callers of one method + their literals.
- `tools/method_lits.py <dump> <so> <rva...>` - literals of one method.
- `tools/prod_probe.py [--player]` - the format matrix above (each variant = 1 prod request).

## 34. XIGNCODE cookie call-chain (route B) + fast token capture via incremental backup (2026-10-10)

Goal was still a live official `accesstoken` for `api/find_player.py`. Two routes worked in
parallel; route A (capture) is the one expected to pay off, route B is mapped but parked.

### Route B - the `cookie` that gates `/auth/xcd` is computed by a packed native core

Full static chain, all from `apk/com.awesomepiece.castle@174.0.00.xapk`, resolved offline:

1. C# `RestAPI.GetXigncodeSeed()` @ `0x2D2F030` -> `GET /auth/xcdSeed?version=`; the coroutine
   using `/auth/xcdSeed?version=` has MoveNext @ `0x2D7F020`.
   `RestAPI.XigncodeValidCheck(cookie)` @ `0x2D2F0F8` -> `GET /auth/xcd?cookie=`
   (MoveNext @ `0x2DAA65C`). Endpoint strings are set in `RestAPI..cctor` @ `0x2D2E088`.
2. `AppSignManager.GetCookie(seed)` @ **`0x361FC5C`** (image `appsign4acs.dll`) is a 104-byte
   wrapper: `AppSign.System.get_Instance()` then tail-calls **`System.GetCookie2(seed)`**
   @ `0x2C397E0`. `AppSign.System` is an `AndroidJavaClass` wrapper, so this is JNI:
   `_clazz = new AndroidJavaClass("com.wellbia.xigncode.AppSignClientSystem")`, methods
   `"getCookie2"` / `"setUserInfo"`. `AppSignManager.SetUserInfo(info)` @ `0x361FCC4`.
3. `lib/arm64-v8a/libxigncode.so` (559 KB, in `config.arm64_v8a.apk`) is only a **JNI shim** -
   24 exports, all `Java_com_wellbia_xigncode_*`, no algorithm.
   `Java_..._AppSignClientSystem_ZCWAVE_GetCookie2` @ `0x1EB18` does:
   `GetStringUTFChars` -> `System->ZCWAVE_SendCommand(0x20, buf, 0x104, seed)` -> `NewStringUTF`.
   `GetCooke` (v1) @ `0x1E728` uses cmd **`0x1c`**; `Cleanup` @ `0x1E524` uses `0x16`.
   The `System*` is `*(u64*)0x8C0B0` (.bss, a `shared_ptr{ptr,ctrl}` pair - ptr first), and the
   command entry point is the **atomic slot `System+0x30`** (`ldar` on read, `stlr` on write at
   `0x10644`).
4. That slot is filled by `dlsym(handle, "ZCWAVE_SendCommand")` in the init function starting
   @ **`0xFF04`** (`libxigncode.so`). The symbol name is built on the stack with a **double XOR**:
   `key = 0x6e` at `[sp]`, `byte[i] = (key+i) ^ MASK[i]`, then re-XORed with `(key+i)` - the two
   passes cancel, so the plaintext is just the mask bytes. Mask =
   `5a 43 57 41 56 45 5f 53 65 6e 64 43 6f 6d 6d 61 6e 64` = **`ZCWAVE_SendCommand`** (18 chars).
   The `dlopen` handle comes from `System+8+0x924` (an in-object path), `bl 0xE5B0`.
5. The symbol is **not** in any on-disk `.so`'s `.dynsym`. `libgabriel.so` (8.6 MB) is a 0x3C-byte
   stub (SONAME `dummy_symbol`, `.text` 60 bytes) that **embeds uncompressed arm64 ELFs** at
   `0xDF620`, `0x120620`, `0x6BE620` (ELF magics also at `0`, and a bogus one at `0x6869C8`).
   Carve + `readelf`:
   | carve | SONAME | size | `ZCWAVE_SendCommand` |
   |---|---|---|---|
   | `0xDF620..0x120620` | `libraphael_barrier.so` | 266 KB | `0xD388` (104 B) |
   | `0x120620..0x6869C8` | (no dynsym - the packed core) | 5.6 MB | - |
   | `0x6BE620..0x848620` | `libsariel.so` | 1.6 MB | `0x22414` (104 B) |
6. Both are the same varargs trampoline: pack `(cmd, buf, size, seed, ...)` into a `va_list` and
   tail-call **`ZCWAVE_SendCommandVa`** (`libraphael_barrier.so` `0xD250`, 312 B).
   **PLT/GOT mapping trap**: `.rela.plt` is NOT in PLT-slot order here. Resolve by `r_offset`
   (GOT address) instead of relocation iteration index - GOT `0x43E20` -> `ZCWAVE_SendCommandVa`
   while the first relocation is `usleep`. `bl 0x87D0` = SendCommandVa, not usleep.
7. `SendCommandVa`: `w8 = cmd - 0x15; if w8 > 0xf -> default`; byte jump table at
   **`0x301A0`**, target = `0xD290 + table[w8]*4`. Table = `00 1c 10 10 10 10 3a 10 10 10 10 10
   10 10 00 00`, so cmd `0x20` (GetCookie2) and `0x1c` (GetCooke) both land on **`0xD2D0`**,
   which is *another* indirection: `handler = *(u64*)0x44040; handler(cmd, ap)`.
   That global is set at init, and the registered implementation lives in the **packed 5.6 MB
   core** (`gabriel_p2`), which has no symbol table.

**Where route B stops**: reversing cmd `0x20`'s real body requires unpacking that core (same class
of work as `server/patchers/unpack_neo.py` for libil2cpp), and the cookie may still embed a device
fingerprint set by `setUserInfo`/init, in which case a Python port would not validate. Revisit only
if route A proves impossible.

Tools added (generic, work on any stripped arm64 `.so` where `vaddr == file offset`):
`tools/xign_xref.py` (ADRP+ADD -> literal xref), `tools/xign_bl.py` (BL/B -> target),
`tools/xign_absrefs.py` (ADRP + encoded imm12 load/store -> exact absolute address; the naive
capstone page-tracking version leaks across basic blocks and produces garbage - don't reuse it).

#### Route B progress (2026-10-10, second pass): Unicorn emulator reaches the cookie handler; blocker = the packer's runtime GOT/reloc decryption

Built `.tmp/xign/emulate_cookie.py` (Unicorn, arm64). It **loads xign_core.so, applies all
relocs, and executes `ZCWAVE_SendCommandVa(0x20, buf, 0x104, seed)`** — a `--pc` trace proves the
full dispatch path runs: `0x1961c0` (export: `sub w8,w0,#0x11; cmp w8,#0x16` cmd-range check +
byte-table at `0x436A7E`) -> cmd `0x20` block `0x196398` -> `0x1d248c` (global-object dispatcher)
-> vtable[+0x70]. This is a working skeleton; only the last hop fails.

**ELF layout (verified; the headers lie for the RW region - packed):**
- 7 phdrs. `PH[0]` R-X off 0 vaddr 0 filesz `0x54a9fc`; `PH[1]` RW off `0x54bf90` vaddr `0x54ff90`
  filesz `0x206d0` memsz `0x29880`; `PH[2]` DYNAMIC off `0x562db0` (this one is **empty/stale**).
- Real `DYNAMIC` is at **file `0x563db0`** (found by scanning for a valid DT-tag run). Its values
  (SYMTAB `0xa40`, STRTAB `0x2330`, RELA `0x2f38`, JMPREL `0x37198`, INIT_ARRAY `0x54ff90`) are
  **+0x1000 off from the actual file bytes** for the R-X metadata region: real SYMTAB file `0x1a40`,
  STRTAB `0x3330`, RELA `0x3f38`, JMPREL `0x38198`. `ZCWAVE_SendCommandVa` st_value `0x1951c0` but
  the code is at file/guest **`0x1961c0`** (`0x1951c0` is mid-function string-decrypt).
- Relocs apply cleanly in "file offset == guest VA" space: 8859 RELATIVE + 20 GLOB_DAT + 257
  JUMP_SLOT (+21 other). R_AARCH64_RELATIVE addends are true VAs; PH[1] maps file `= VA-0x4000`.

**The blocker (precise):** cmd `0x20` needs the core object at bss **`0x571C98`** (reloc
`*(0x567C88)=0x571C98`; dispatcher `0x1d248c` does `ldr x8,[0x567C88]; ldr x8,[x8]; vtable=*[x8];
bl vtable[+0x70]`). With no object it returns `0xe0190304`. Bootstrapping a minimal object
(vtable `0x557540`, ctor `0x1d2574`) makes the dispatcher fire, and the cookie handler then runs
until it hits **PLT thunk `0x3a7b0` -> GOT slot `0x5686c8` -> raw `0x389b0` = `udf`** -> crash.
That GOT slot is **NOT in JMPREL** and has **no reloc**. In fact the whole `0x568000+` GOT region
(the INIT_ARRAY thunks at `0x568030+` AND the cookie handler's imports) is placeholder'd with
`0x389b0` (udf / packed-reloc sentinel). `xign_core.so` here is **byte-identical to libgabriel's
embedded container copy** (`0x120620..0x68D300`) = the **raw pre-decryption** image.

**Root cause:** XIGNCODE does not encrypt code (hence the dispatch executes) but **hides the
reloc table / lazy-binding GOT** behind a sentinel. `libraphael_barrier.so`'s init (`0x96c0`,
XOR-decrypts filenames + file I/O; the caller fwrite's the cleaned ELF to a temp file and
`dlopen`s it) produces the clean, initializable image. Our emulator runs the **raw** copy, so both
the core-object init (INIT_ARRAY thunks -> `0x389b0`) and the handler's imports fail.

**Next step to finish route B:** obtain the **decrypted xign_core.so** (emulate/extract libraphael's
unpacker, same class of work as `server/patchers/unpack_neo.py`) and load *that* in the emulator —
then init constructs the object and cmd `0x20` should emit the cookie.
**Caveat (unchanged from above):** the cookie may embed a device fingerprint from `setUserInfo`/
init, so even a correctly computed cookie might not validate server-side — test once one computes.

### Route A - capture the plist token fast (incremental MobileBackup2)

Verified fact: the plist token **is** the token the client sends, and prod recognises it
(`402 ExpiredToken` = server-issued, just expired). So the whole problem is the ~115 s full-backup
latency, not token validity. Real profile on this iPhone: the game plist lands ~150 s in, and the
device streams ~500 files/s (51 k+ files, 1.7 GB discarded) before `Manifest.db` arrives.

`tools/extract_ios_token_live.py` was one-shot and **aborted the stream the moment the plist was
read**, so `Manifest.db` was never written and pymobiledevice3 could never go incremental. Now:

- `KGC_KEEP_BACKUP` (default **1**) keeps `.tmp/kgc-live-backup/` instead of `rmtree`-ing it.
- `KGC_BACKUP_COMPLETE=1` suppresses both `raise TargetPlistCaptured` sites so the backup runs to
  the end - **required once**, so the device commits incremental state.
- `_instrumented_upload` now **keeps** `Manifest.db`/`Manifest.db-{shm,wal}`/`Manifest.plist`/
  `Status.plist`/`Info.plist` into `<BACKUP_DIR>/<udid>/`; previously everything but the game
  container was drained, so the metadata never existed locally.
- `_incremental_ready()` then makes `main()` pass `full=False`, and pymobiledevice3's own
  `_should_do_full_backup` re-forces a full run if the three required files are missing/empty.

One-off bootstrap: `KGC_BACKUP_COMPLETE=1 KGC_KEEP_BACKUP=1 python3 -u tools/extract_ios_token_live.py`
(keep the phone unlocked; a passcode prompt appears). Afterwards plain
`python3 tools/capture_and_probe.py` should capture in seconds and probe immediately.
**Risk still open**: the *device* decides full vs incremental (the `Backup` request carries no
flag), so if it never committed a snapshot the "incremental" run silently streams everything again.
The timing printed by the extractor is the verdict.

#### Route B progress (2026-10-10, third pass): relocs fixed, cookie fn reachable, blocker = JNI runtime env

`.tmp/xign/emulate_cookie.py` now loads the raw `xign_core.so`, applies **all** relocs correctly
and drives the dispatcher to the cookie handler. Corrections over the second pass above (the
`0x567C88` / vtable `0x557540` figures there were the **un-shifted** wrong addresses):

- **Metadata shift is real but `dynsym` is SPLIT by the packer.** DYNAMIC values (`SYMTAB 0xa40`,
  `STRTAB 0x3330`, `RELA 0x3f38`, `JMPREL 0x38198`) and `st_value` are **+0x1000** in file space
  (`ZCWAVE_SendCommandVa` st_value `0x1951c0` → code `0x1961c0`). `INIT_ARRAY` read at
  `0x54ff90+0x1000 = 0x550f90`. **`.dynsym` entries 3..61 live at file `0xa40`, 62..265 at `0x1a40`**
  (`0x1a40 + 266*0x18 == 0x3330 == STRTAB`); merging both ranges resolves 202 more imports and makes
  `idx 264 → ZCWAVE_SendCommandVa` self-resolve. All relocations write to `r_offset + 0x1000`, addend
  un-shifted. Result: 8859 RELATIVE + 20 GLOB_DAT + 257 JUMP_SLOT + 21 ABS64 applied.
- **Cmd table (byte table `0x436a7e`, `index = cmd-0x11`, `handler = 0x1961ec + byte*4`):** every
  handler ends `ldr x30,[sp],#0x10; b TARGET`. cmd `0x23`/`0x24` → `0x1961ec` (reads 6 va-args) →
  **`0x1d2158` = lazy-init, the ONLY writer of `*(0x571c98)`** (object cell). If the cell is already
  set it returns `0xe0191011`. cmd `0x1d`/`0x20` → `0x196398` → **`0x1d248c` dispatcher**.
- **JNI surface (`libxigncode.so`) — the real call sequence:** `SetUserInfo(info)` @ `0x1ed68` →
  tail-call `0x1930c` → **sends cmd `0x1d`** with the userInfo string. `GetCookie2(seed)` @ `0x1eb18`
  → `GetStringUTFChars` → **sends cmd `0x20`** with `x1=buf, x2=0x104, x3=seed-C-string-ptr` (the
  seed is a **string pointer**, not an integer). `Initialize` @ `0x1dd98` only JNI-converts strings
  and stores them in shim globals (does **not** send a cmd). No `.so` sends cmd `0x23`/`0x24` (the
  `movz` scan only finds return values) and there are **zero direct B/BL callers** of `0x1d2158` —
  so who creates the object in production is still unconfirmed (likely an internal core init).
- **Dispatcher `0x1d248c`:** `x8 = **(0x568c88)` (= `*(0x571c98)`; reloc `*(0x568c88)=0x571c98`);
  null → `0xe0190304`; else `vtable = *obj; br vtable[+0x70]` = **`0x2509d8`** (cookie fn).
- **Object ctor `0x22ce98`** stores `obj[0]=0x558e18` (vtable), `obj[8]=0x558f18`, `obj[16]=0x558f48`.
  A hand-built object (`--bootstrap`, vtable `0x558e18`) makes the dispatcher **reach `0x2509d8`**.
- **Syscalls:** the core issues raw `svc #0` (bionic wrappers @ `0x31a1xx`). aarch64 numbers (NOT
  x86-64): `79 newfstatat, 56 openat, 48 faccessat, 34 mkdirat, 35 unlinkat, 63 read, 57 close,
  61 getdents64, 78 readlinkat`. `UC_HOOK_INTR` handles them; a fake FS makes `/proc/self/maps`
  parse. **`UC_ARM64_REG_X8` must be imported** or the hook crashes.
- **vtable entries are control-flow-flattened** — `0x2509d8`, `0x24d830`, `0x250cf8` all begin
  mid-`std::string`/basic-block (no prologue). The obfuscator scrambles BB order, so entering at the
  vtable value with stale regs/flags follows bogus branches (observed: reads unmapped `0x57b000`).

**Blocker (precise): cmd `0x23` init cannot complete in the emulator.** The chain is
`0x1d2158` → scan `0x229908(arg1)` (result → `**(0x568d10)`) → `malloc(0x2e8)` → ctor `0x22ce98` →
init `0x22d3b8` → `0x218b90`. Three environment dependencies, each revealed by bypassing the last:
1. `0x229908` filesystem/anti-tamper scan builds paths `/data/data/<pkg>/xigncode/...` using a
   package name from **JNI `getPackageName`**; with no JNI env the name is `(null)` and the format
   strings themselves are **not plaintext** in this raw image (runtime-decrypted).
2. `0x218b90` reads `*(0x575818)->[0x5c0]`, a **JNI-populated ops-table fn ptr** (NULL here) → `blr 0`.
3. Bypassing those two (`--bypassscan/--bypassinit`) just moves the crash deeper (`0x225788` reads a
   garbage pointer `0x7f0000875404` derived from the zeroed dummy config).

**Conclusion (route B):** the emulator is architecturally correct and reaches the cookie handler, but
producing a valid cookie requires reconstructing the **XIGNCODE JNI runtime** — a fake `JNIEnv`
(`FindClass`/`GetMethodID`/`CallObjectMethod`/`GetStringUTFChars`), the ops table at `*(0x575818)`,
and the scan config at `**(0x568d10)` — plus working through control-flow-flattened code. That is a
multi-session effort with uncertain payoff (the cookie may still embed a device fingerprint). The
reusable assets are `emulate_cookie.py` (reloc/metadata/dynsym-split + syscall emulation + cmd
dispatch, all verified) and this decode. Route A (capture) remains the simpler path but needs a live
device and beats the ~115 s TTL race.

### Official AES key rotated BACK to `cnf1tl65djs2wp3g` (verified 2026-10-11)

The key documented in §33 / `api/config.py` / `server/crypto.py` / `tools/prod_probe.py`
(`a6072ad6b9c959ff`, "current prod") is **stale**: it now yields HTTP 400 on request-body
endpoints and garbage on response decrypt. The **current key is `cnf1tl65djs2wp3g`** (the old
v165-168 value — official rotated back). Empirical check on `kgc-k8s-1.awesomepiece.com`:

- `GET /auth/xcdSeed` decrypts cleanly with `cnf1tl65djs2wp3g` → `{"code":200,...,"seed":<long
  random string, changes every request>}`; `a6072ad6…`/`b53019bb…` → garbage.
- `POST /auth/getPatchFolder` enc'd with `cnf1tl65djs2wp3g` → HTTP 500 (body decrypted, failed
  on missing auth); enc'd with `a6072ad6…`/`b53019bb…` → HTTP 400 (undecryptable). So
  `cnf1tl65djs2wp3g` is the universal request+response key, not endpoint-specific.

### Cookie capture = MITM, and `token_harvester.py` now also grabs it (2026-10-11)

The plist-based `tools/extract_ios_token_live.py` captures the **token** only (TTL ~2 min —
reconfirmed: the Oct-10 captured token answers `401 NotCertifiedToken`). The durable **cookie**
exists only inside the HTTPS request URL `GET /auth/xcd?cookie=…`; it is not persisted to the
plist (searched — no cookie-shaped value). `api/auth/xigncode.xel` in the app container is
XIGNCODE's encrypted state file (magic `mLxz`, 2.88 MB), not plaintext.

`api/auth/token_harvester.py` (passive mitmproxy addon) was extended to capture the cookie
from the request query (`request()` hook → `captured_cookie.json`) and the seed from the
`/auth/xcdSeed` response (`response()` hook → `captured_seed.txt`), in addition to the token.
It overrides `config.AES_KEY = b"cnf1tl65djs2wp3g"` locally. Verified end-to-end through
`mitmdump --listen-host 0.0.0.0 -p 8888 -s api/auth/token_harvester.py` (curl needs `-k`
unless the system trusts the mitmproxy CA). **Caveat not yet tested on the stock iOS client:**
the game ships `PinnedCertHandler` (the private build patches `ValidateCertificate`→true to
accept a self-signed cert), so live-HTTPS MITM may be rejected by cert pinning — §34's route B
emulation exists precisely because the cookie can't otherwise be minted. If the iPhone capture
works, next step is to test cookie **reusability** (is the cookie a stable per-device value, or
bound to the per-request seed?).

### MITM is dead on the stock iOS client — cert pinning confirmed (2026-10-11)

Set the iPhone Wi-Fi proxy to the host (`192.168.1.55:8888`, mitmproxy CA installed + trusted).
mitmproxy log: Apple Game Center domains (`init.gc.apple.com`, `friend.gc.apple.com`) return **200**
(system-CA trust), but **`kgc-k8s-1.awesomepiece.com:443` fails the client TLS handshake** ("client
disconnected during the handshake … does not trust the proxy's certificate"). The game's own backend
is pinned (`PinnedCertHandler`), so the cookie cannot be intercepted on a stock client. Revert the
proxy after testing — with it set, the game hangs at the dev-logo screen (its first backend call is
the pinned one). Route B (compute the cookie) exists precisely because capture is blocked.

### Route B emulate: x30 clobber fixed; scan = anti-tamper + custom JNI-wrapper; cookie fn uses MD5 (2026-10-11)

Continued `.tmp/xign/emulate_cookie.py` (Unicorn arm64). Concrete findings, in the order they unblocked:

1. **Fake-syscall stack clobber (fixed).** cmd `0x23` (init) crashed at `0x21f3a0` (`ret` → x30 was
   0 → executed the ELF header at VA 0). Root cause: the fake `newfstatat` (svc 79) handler wrote a
   **256-byte** `struct stat` (`pack(8×Q)=64 + 192`), but the aarch64 **kernel** `struct stat` is
   **128 bytes**. The oversized `emu.mem_write` overflowed the caller's stack stat buffer into
   `0x21c3d0`'s saved x30 slot (`sp_final+0x2A8`). Fixed to 128 bytes with `st_mode@16` / `st_nlink@20`.
   **Debug recipe**: watch the saved-x30 slot (`stp x29,x30,[sp,#0x50]` → x30 at frame `sp_final+0x2A8`);
   a Python-side `emu.mem_write` from a syscall/stub does **not** fire `UC_HOOK_MEM_WRITE`, so instrument
   the `_w`/`memcpy`/`memset` stubs with an overlap guard — the guest-write hook alone misses it.

2. **The scan is anti-tamper and uses a custom XIGNCODE JNI-wrapper.** After the x30 fix the scan runs
   with a healthy stack but then jumps to the tamper sentinel **`0x2600000000`** (unmapped → intentional
   halt). It reaches JNI through a **wrapper ops-table at `*(0x575818)`** — *not* the raw JNINativeInterface:
   observed method offsets `+0x1d0` (a `fn(outbuf, size, str)` format/copy wrapper), `+0x478`, `+0x5c0`.
   `*(0x575818)` is NULL after INIT_ARRAY (a ctor does not populate it). The `--fakjni` mode (fill the
   table with per-slot logging stubs, `JNI_STUB_BASE+i*16`, so the code hook derives the offset from the
   stub addr) fires the calls, but zero-returns flow into object-graph building (`object[x19+0x20]` vtable
   derefs) as garbage pointers → `READ_UNMAPPED`. Running the scan to completion = reimplement this wrapper
   layer + the object graph + the anti-tamper checks. Multi-session.

3. **The cookie fn computes with MD5 (portable once the input is known).** cmd `0x20` → dispatcher
   `0x1d248c` → object vtable `[0x70]` = `0x2509d8` (control-flow flattened). It strips `'-'` (0x2d) from a
   device-ID **`std::string`** held in the object, then assembles the cookie. **MD5** init constants
   `H0-H3` (`0x67452301/0xefcdab89/0x98badcfe/0x10325476`) sit at `0x4c73c0-0x4c73cc`; no SHA-256 constants
   exist. So the checksum is standard MD5 — portable to Python **if** the exact input (seed + fingerprint
   + any secret/composition) is known. With a zeroed `--bootstrap` object it loops reading a null
   `std::string` ptr → crash.

**Net**: route B now has two concrete sub-paths, both still needing the object layout: (a) run the scan to
completion (reverse the JNI-wrapper + object graph + anti-tamper), or (b) craft an object with a **known**
fingerprint string → run the cookie fn → capture an (input, output) pair → reverse the MD5 composition
empirically → port to Python. (b) is the shorter path to a *portable* cookie but still requires finding
the fingerprint `std::string` field offset in the object. Neither is quick; the honest endgame for a real
cookie fast remains running the **real** `libxigncode.so` on redroid (real JNI env + real anti-tamper
passes natively) with an SSL-bypass build, MITM-capturing the cookie, and reversing the algorithm from
real cookie+seed pairs.

## 35. Official-token sprint: session refresh mechanism, TTL race, and why every capture failed (2026-10-10)

### The answer to "how does the game never log out if the token expires"

**`Scene_Game.UpdateImpl` -> `RestAPI.ShakeHand()` -> `GET /auth/shake-hand`**

`RestAPI.ShakeHand()` (RVA **0x2D2EE9C**) has exactly **one** caller in the whole binary:
`Scene_Game$$UpdateImpl` at call site RVA **0x2E73388**. So the game pings the keep-alive
**from its main gameplay loop**. The server slides the session window on every ping, which is
why the client never needs to re-login while playing.

Related (found while hunting the refresh, kept for completeness):

| Method | RVA | Called from |
|---|---|---|
| `Scene_Login.AutoLogin` | (caller, site 0x36442F0) | → `Login(token)` 0x364434C **and** → `ReAuth()` 0x36443F0 |
| `Scene_Login.CheckError` | 0x36463BC | site 0x36464C0 → **`ReAuth()`** (error path re-auths) |
| `CheckError` callers | — | `<Auth>d__97.MoveNext` 0x364B2B8, `<Login>d__95.MoveNext` 0x3652998 |
| `HandleAuthResponse` (writes prefs + `RestAPI.accessToken`) | 0x364452C | `<Auth>d__97` 0x364B2A8, **`<ReAuth>d__122.MoveNext` 0x36537D0** |
| `Auth(id)` | 0x364448C | Google/Apple login, AutoRegister, AccountTransfer, Register |
| `RestAPI.NextDay(token, cookie)` | 0x2D2EB60 | `Scene_Base.<FetchNextDay>d__40.MoveNext` 0x3625130 (daily reset, see §"daily-reset boundary") |

**Recipe for "who calls X" on il2cpp** (reused 3× this session): scan the `.so` for `BL` with
`(w>>26)==0x25`, sign-extend the 26-bit `imm26`, target = `site_RVA + imm*4`; file offset =
`RVA - 0x4000`; identify the enclosing function by binary-searching `script.json`'s sorted
`ScriptMethod.Address`. Do this instead of grepping — it answers in one pass.
The mirror trick (find callers of a **string literal**) does **not** work by ADRP: literals are
reached through a static field, so direct page references to `/auth/shake-hand` (0x6B97F58)
scanned to **0 hits**. Go via the method's RVA instead.

### The real blocker: capture (119 s) vs token lifetime (~100 s)

Six capture+probe runs on 2026-10-10. `tools/capture_and_probe.py` reads the game plist
**~119 s** into a MobileBackup2 stream (device streams ~9000 files at ~75 files/s before the
plist; the game's own container is near the *end* of the stream).

Verdict matrix observed:

| Verdict | Meaning | Cause here |
|---|---|---|
| `200` | live token | plist written **recently** (game had been sitting in lobby, token <81 s old) |
| `402 ExpiredToken` | **genuine**, server-issued, just expired | plist written >~100 s before the read |
| `401 NotCertifiedToken` | server does not recognise it | plist captured **before login completed** (early/mid-auth write) |

**Timing model (fits all 6 runs):** force-quit + relaunch → an *early* token lands in the plist
within seconds, but the **certified** token lands ~**90 s after relaunch**; token then lives
~100 s. Therefore:

- relaunch **before** capture starts → read at T+119 → age ~150 s → **402**
- relaunch at T+55 → certified write would be ~T+145, read at T+118 → reads the early
  uncertified token → **401**
- (untested sweet spot) relaunch **at T=0** → certified ~T+90, read T+119 → age ~29 s → should be 200

Capture and mint are therefore fundamentally racy until capture is <30 s. That is exactly why
**route B (compute the cookie locally)** is the real prize: with `ZCWAVE_SendCommand` ported to
Python, `GET /auth/xcdSeed` → cookie → `GET /auth/xcd?cookie=` mints a token on demand, in
milliseconds, no backup stream at all.

### Incremental backup still does not work (closed for now)

- Client-side `KGC_BACKUP_COMPLETE=1` run reaches ~65 k files then dies with device error
  **205 "Manifest references files not in backup"** — our instrumented upload **discards** files,
  so the device's own manifest cross-check fails. `Manifest.db` (128 MB) *is* still downloaded.
- A subsequent run *does* print `Starting INCREMENTAL stream backup` (Status.plist +
  `Manifest.plist` are on disk) but the **device still streams everything** and still takes 115 s,
  so no speedup — the device never committed a successful snapshot.
- **Stock, unfiltered `Mobilebackup2Service` backup** (store everything, ~63 GB free) is the way
  to make the device commit; it was started at 01:09 and died with
  `ConnectionTerminatedError` at 01:14 (~5 min in, only 3 MB written — never even got the passcode
  stream going properly). **Not yet retried.**
- API gotcha: `Mobilebackup2Service.__init__(lockdown)` takes **no** `backup_directory`; pass it to
  `await mb.backup(full=True, backup_directory=...)`.
- House Arrest/AFC into the game container → `InstallationLookupFailed` (no file-sharing shortcut).

### Tooling traps recorded this session

- **`tools/prod_probe.py`**: default mode is the **format matrix on `/auth/getPatchFolder`
  (3 prod requests per run)**; `--endpoint X` is *not* a flag — the flag is **`--player`**.
  Two accidental runs cost ~6 requests of the ~290 budget. Print the mode before calling it.
- Probe verdict can be read from the `plain = {"code":...}` line; `GET /player` is the cheapest
  liveness check (200 = live, 402 = expired, 401 = unknown).
- `api/find_player.py` only scans **top rankings**; even with a live token it reported
  "not found in top rankings" and skipped Strife because `/colosseum` needs the token too.
  Searching by name needs a wider sweep (or the Account ID) — **still open**.

### Honest state at handoff

No working official token yet. Everything else is mapped: request format (§33), the full cookie
call-chain (§34), the session-refresh mechanism (§35). The two remaining paths are (a) retry the
stock full backup once so captures become incremental/fast, then use the relaunch-at-T=0 window;
or (b) finish route B and mint tokens locally. A handoff prompt for a fresh agent is checked in
at `docs/handoff-official-token.md`.

## 36. Official-server auth BREAKTHROUGH: real-xigncode cookie → token → login, and the scale blocker (2026-10-11)

### The breakthrough (route: private build + real libxigncode.so on x86 redroid)
- Private build `com.nowl.castle` (shows v173.1.00; ships the **v174 real** `libxigncode.so`) runs
  on x86 redroid via ndk_translation. The real `libxigncode.so` (559296 B from
  `apk/xapk_stock_174/config.arm64_v8a.apk`) was swapped into the config APK (stub→real,
  re-signed `.debug.keystore`), installed via `install-multiple -r`.
- Auth host `kgc-k8s-1.awesomepiece.com` appended to device `/system/etc/hosts` → 127.0.0.1
  (`adb root` + `remount`). `adb reverse tcp:80 → tcp:9090` to `logproxy2.py` (fakes 200 for
  `/auth/*`, forwards `/patch` to the local server :8080).
- Capture: `am start …AirbridgeActivity` → wait for the login screen → `input tap 540 1612`
  (Guest Login; white button band y≈1563-1662 on 1080x1920) → real xigncode computes the cookie →
  client `POST /auth/xcd` (form body `cookie=…&client_id=…`, header `X-KGC-Device-UUID`) → proxy
  captures the raw body.
- Captured cookie (uuid `0fe32f28-6d7d-418f-9b3c-4b094b6f2380`):
  `926988259842277236_809719a0b875d60aba56908821a52a6d_686d6c652d30303031<+23 nulls>`.
  Component 3 = ASCII `"hmle-0001"` + null padding (32 B). Component 1 (num, 59-bit) = the
  **device-id** (the server's `loginId` = `guest-<num>-<rand>`).

### Official accepts it (end-to-end verified)
- `GET /auth/xcd?cookie=<real>` → 200 `{"accesstoken":"…","refreshtoken":"…"}` (POST form also OK;
  plain, no AES needed on this path).
- `POST /auth/login` header `accesstoken` → 200 `{"loginId":"guest-926988259842277236-445246881","loginResult":1}`.
- MD5 fakes (uuid±dash, raw bytes) do NOT match → there is a secret/salt. The num is not a uuid
  reinterpretation (tested big/little-endian, first8/last8).

### The scale blocker: the cookie is NOT freely reusable
- Re-`/auth/xcd` with the same cookie after ~minutes → **401 `WrongTokenError`** (not rate-limit;
  `x-rate-limit-remaining: 299`). Two *immediate* xcd calls (GET+POST) both minted the SAME token,
  then a few minutes later → 401 ⇒ the cookie is **time/session-windowed** (neither single-use nor
  eternal). ⇒ Scale requires minting a **fresh cookie per auth**: either (a) per-device capture
  (rotate the device uuid + re-run the fragile emulator capture) or (b) crack the algorithm to
  generate fresh cookies offline.

### Emulator capture is a lottery (why it is not reliable)
- x86 redroid runs arm64 via ndk_translation; the game **intermittently crashes** in libil2cpp
  `ResourceSkin$$Init → ResourceBase.LoadFromString → String.Format` on the background
  `ResourceManager.StartLoadingThread` (a race, ~10-18 s after login-screen `Awake`). The login
  screen renders *before* the crash, but the window is racy; ~15+ capture attempts after the first
  success all failed (crash killed the game before the tap→xcd flow completed, or the
  "Failed to log in" auto-resume state disabled the button). One clean success proves it is
  possible but not repeatable enough to scale.

### Route B (offline Unicorn oracle) — real progress this session
- `.tmp/xign/emulate_cookie.py` emulates `ZCWAVE_SendCommandVa` over `xign_core.so`. The prior
  session's "**anti-tamper 0x2600000000**" is **misdiagnosed**: it is the **JNI ops-table**
  (`*(0x575818)`) being unpopulated — init does `ldr x11,[x11,#0x1d0]; blr x11` (wrapper slot at
  +0x1d0) and branches to garbage. Not an integrity check.
- `--bootstrap` builds the core object at `*(0x571C98)` (vtable `0x558e18`) and `--noinitcmd` skips
  init ⇒ the **cookie fn `0x2509d8` is reached and runs** (dispatcher path works). It then reads
  the device-uuid from the object (dash-strip loop `ldrb w8,[x11]; cmp #0x2d` @ `0x250a0c`); with a
  zeroed object the uuid pointer is garbage ⇒ the uuid field must be set.
- Fixed: the RW-segment .bss map was too short (globals at `0x57b000`/`0x590000` unmapped); bumped
  `map_seg` memsz `0x2A880`→`0x40000`.
- `--fakjni` fills the ops-table with logging stubs ⇒ init proceeds past `0x2600000000` and calls
  the JNI wrapper (`obj+0x1d0(env,0x410,buf)` ×2, `obj+0x478` ×2 = device-info reads), then crashes
  deref-ing the stub's `0` return @ `0x22af54`. **Next**: implement the wrapper stubs to return a
  valid device-uuid (jstring), let init complete, then reproduce the ground-truth cookie
  (`0fe32f28… → 9269882598…_809719a0…`) to validate the oracle; then rotate the uuid for unlimited
  fresh cookies.

### Tooling for this session (not committed; lives in `.tmp/xign/`)
- `logproxy2.py` — HTTP-aware proxy :9090 (fake `/auth/*`, forward `/patch`→:8080, log raw bodies).
- `capture_cookie.py` / `harvest.py` / `diag_tap.py` — emulator capture + login drivers (fragile).
- `emulate_cookie.py` — the Unicorn oracle (see Route B above).
- `d.py` — capstone disasm helper (`python3 d.py <hex-file-off> [len]`, file-offset = RVA−0x4000).

### Capture root-cause (2026-10-12): ToS dialog + SIGSEGV — why the "lottery" never hits

Two findings that explain the ~45 failed capture attempts this session and reframe the emulator route:

1. **Fresh-install shows a Terms-of-Service dialog BEFORE the login buttons** (`Agreement of Terms and
   Condition`, two checkboxes + an "I have read and consent" button). After `pm clear` the game does
   NOT go straight to the login buttons — the ToS dialog pops OVER the login illustration at ~10 s.
   Old drivers tapped blindly at the Guest coords and hit the dialog. Proven accept sequence (1080x1920,
   0.4 s apart): checkbox `(257,975)` → checkbox `(257,1093)` → consent `(540,1300)`. The **login buttons
   (Sign-in-with-Google / Guest Login) only render AFTER resources finish loading** ("Loading resources…"
   at the bottom) — tapping Guest before they render does nothing. A PIL detector for the white Guest pill
   (crop `(320,1555)-(760,1665)`, >8000 px with r,g,b>220) reliably tells "buttons up" from "still loading".

2. **The killer is a native SIGSEGV, not the managed abort.** Logcat `E CRASH`: `signal 11 (SIGSEGV),
   code 1 (SEGV_MAPERR)`, thread `IL2CPP Threadpo` (the background Addressables loading worker), `#00 pc
   0x2ad0aac libil2cpp.so` (does not resolve in v173.1.00 `script.json`). It fires ~12-22 s in, i.e. while
   "Loading resources…" is still up, **before the login buttons ever render**. This is an ndk_translation
   x86-translation crash — intermittent, near-unfixable. A separate SIGABRT `terminating` (managed
   exception → abort) tombstone also exists but the segfault is the common one.

Consequence: the emulator capture is a pure **race** (main-thread button render vs worker-thread crash),
win rate ~1/15–1/30. The FIRST launch after `pm clean` is the only one that reliably reaches ToS+buttons;
later launches (partial state from a crash) hang on "Loading resources" and never show buttons — so
blindly retrying without clearing does not help. Capture CAN win (once reached buttons + ToS-dismiss) but
is not repeatable enough to depend on. One win is enough to keep a session alive (shake-hand), so a long
campaign may still land a live token, but the robust path remains **Route B (offline Unicorn oracle)**.

- `capture_full.py` — the current best driver: `pm clear` → launch → dismiss ToS → detect Guest button
  (PIL) → tap → read cookie from proxy log → mint token against official. Flaky (see above).
- `capture_btn.py` / `capture_tos.py` / `capture_fresh.py` / `rapid.py` — earlier iterations of the same
  (superseded by `capture_full.py`).
- `api/official.py` — scriptable official-API client: `--cookie` mints (xcd→login), demo-calls
  `/player`+`/player/getInventory`+`/card/all`, `--keepalive N` pings `GET /auth/shake-hand` every N s.
  `api/auth/auth.py` `shake_hand()` fixed to **GET** (POST returns 405; the game uses GET from
  `Scene_Game.UpdateImpl` to slide the session window). Live session saved to `/tmp/xsign/live_token.txt`.

## 37. Skin-mod: equip skins you don't own (v173.1.00, 2026-10-15)

Question: "bản mod skin" - a player with no skin can still use it. Two touch points, both landed:

- **Client gate**: `GameManager.HasSkin(int)` - v173.1.00 RVA `0x30EFD3C` (file `0x30EBD3C`,
  prologue `ff4301d1fe5f02a9`). Stubbed to `RET_TRUE` as the `has-skin` row in
  `_NRE_STUBS_V17310` (`server/builders/build_private.py`). All 12 `bl` callers are UI/shop
  only - `SkinInfoPanel.ReloadBottomButtons` (Equip vs Buy button), the
  `SkinInfoPanel.<ShowCatalogImpl>b__93_1` catalog predicate, `SkinInfoTab_Old.AfterSetSelectedSkin`,
  `SeasonalEventShopItem.Set`, `WorldPanel.Reload` (new-content badge), gacha/package panels.
  **No battle renderer calls it**: every skin's prefab/texture ships in the client bundle and
  lobby/battle/PvP render purely from `currentSkin`, so ownership is a UI/shop concept only.
  Re-derive the RVA per version from that version's own `dump.cs` before adding the row to
  another `_NRE_STUBS_*` table (the build raises on a prologue mismatch, never corrupts).
- **Server**: `r_card_equip_skin` (`server/routes/card_routes.py`) no longer requires the skin
  to be in `card.skins`. It validates the id exists in `Skins.xml` (`_skin_ids()`, cached parse)
  and persists `currentSkin` WITHOUT granting ownership - equipping ≠ owning is the whole point.
  `r_card_buy_skin` is unchanged and remains the real grant path (stock buy flow, gacha-style).
  Stock/unpatched clients are unaffected: they never send unowned ids, and their buy popup still
  routes to `/card/buySkin`.
- **Tests**: `server/tests/test_skin_mod.py` - equip-unowned persists, unknown id refused,
  skin 0 unequips, ownership never granted.
- **BL-scan recipe (gotcha cost me an hour)**: scan in FILE space end-to-end. For a `bl` at file
  offset `F`: `imm = sign_extend26(w & 0x3FFFFFF)`, `target_file = F + imm*4`, compare against
  `wanted_rva - 0x4000`; the caller's RVA is `F + 0x4000` (never `F - 0x4000` - mixing the two
  spaces maps every caller to the wrong enclosing method, silently).

## 38. Unity rebuild — S2 Slice A: guest login chain chạy thật + 2 DLL stub "silent" của AssetRipper (2026-10-15)

### Kết quả Slice A
- Play mode (batch + xvfb + glcore): trigger `AutoLoginAsGuest` → `POST /auth/register` →
  `POST /auth` → `POST /auth/login?id=` → `GET /player` (header `accesstoken`) →
  `auth chain OK: uid=p-fbc904313418 name=Player3640` → `LoadScene("Scene_Lobby")`, capture
  160 canvas. Gate: `KGC_CAPTURE_PLAY=1 KGC_CAPTURE_LOGIN=1 … CaptureScene.Run` exit 0
  (`/tmp/opencode/s2gate/login_play20.log`).
- Guest id persist ở PlayerPrefs key `KGC.GuestId`; **register LUÔN gọi trước Auth** —
  `/auth/register` → `r_login` (routes/player_routes.py:34) idempotent (id đã bind = login,
  chưa bind = tạo save) → tự chữa được id lưu từ lần register đầu lỗi/mất mạng.

### UniTask fork KHÔNG dùng được trong môi trường này → netcode = pure callback
- Probe 2026-10-15: (1) `async UniTask<T>` body **không chạy** khi invoke; (2) awaiter
  không resume kể cả `UniTaskCompletionSource.TrySetResult` gọi từ coroutine; (3)
  `PlayerLoopHelper` không init (`mainThreadId=0`, runners rỗng); `Init()` 0-param no-op.
- `Task`/async-await cũng không được: await continuation rơi threadpool → `Debug.Log` ném
  `UnityException: GetMethod can only be called from the main thread`; context-ful
  continuation queue không bao giờ pump trong batch editor play.
- **Contract**: `Web.Send<T>(req, accessToken, useSystemSerializeFunc, Action<T> onDone)` —
  decrypt/parse/`MakeFail` TOÀN BỘ trong `op.completed` lambda (engine guarantee: main
  thread, kể cả khi op đã done). Get/Post overload đều explicit 5-6 tham số (optional
  param phải đứng trước `onDone`). `RestAPI.Auth/Login/Register/GetPlayerInfo` →
  `void …(Action<T> onDone)`; `Scene_Login` chain nested callback (depth ~4).
- `op.completed` dispatch **theo frame**; editor tick (`EditorApplication.update`) chạy
  nhanh hơn frame → gate driver đợi theo `Time.frameCount` (900 frame post-trigger), KHÔNG
  đếm tick (play17 stall = budget 600 tick hết trước khi response kịp dispatch).
- `Debug` ambiguity: file có `using System.Diagnostics;` phải viết `UnityEngine.Debug.`
  đầy đủ.

### AssetRipper export DLL plugin = STUB (method bodies rỗng) — sai logic im lặng, không exception
Triệu chứng chung: call chạy không ném exception, trả `null`/default. Đã gặp 2 DLL:
1. **`Newtonsoft.Json.dll` 167KB** (bản thật netstandard2.0 ~705KB): MỌI
   `JsonConvert.DeserializeObject<T>(json object)` trả NULL — kể cả
   `Dictionary<string,object>`; `DefaultContractResolver.ResolveContract` trả NULL;
   `Version=13.0.0.0` giả mạo. Fix: thay nuget `Newtonsoft.Json 13.0.3 netstandard2.0`
   tại `Assets/Plugins/Newtonsoft.Json.dll`; bản stub giữ ở
   `ExportedProject/Newtonsoft.Json.dll.bak-ripped`. (Bản 167KB không phải reference
   assembly — method body stub trả default.)
2. **`ACTk.Runtime.dll` 76KB** (CodeStage anti-cheat): `ObscuredString("DEV.abc123")`
   implicit→string trả NULL → `RestAPI.accessToken` (ObscuredString) mất → `GET /player`
   KHÔNG gửi header `accesstoken` → server single-player mode fallback `playerdb.active()`
   → trả save **dev-0001 (KingBug)** thay vì player vừa login. Đây chính là cách bug
   "login xong nhưng data của KingBug" manifest — server OK hoàn toàn, curl verify tách
   bìa. Fix: xóa `ACTk.Runtime.dll` + `ACTk.Examples*.dll` (+ .meta; chỉ 3 DLL này tham
   chiếu lẫn nhau) → thay **source shim**
   `Assets/Scripts/Assembly-CSharp/CodeStageShim.cs` — namespace `CodeStage.AntiCheat.
   ObscuredTypes`, 6 type (Int/Long/Float/Double/Bool là struct, **String là class** để
   `== null` + implicit qua string hoạt động), lưu plain value, đủ implicit 2 chiều +
   so sánh + số học + `++/--` + `+` concatenate. Wire model (`Awesomepiece/Model/*`) không
   chứa field Obscured (grep verified) → JSON contract không đổi.
   - `Scene_Login.unity` chứa component `SpeedHackDetector` (MonoBehaviour từ ACTk.Runtime,
     block `--- !u!114 &1108` + entry `- component: {fileID: 1108}` trong GameObject 191
     tên "SpeedHackDetector") → **gỡ khỏi scene YAML trước khi xóa DLL** (còn lại
     `SpeedHackHandler` source — method rỗng, harmless).
- **Cảnh báo**: nhiều DLL khác trong `Assets/Plugins/` kích thước bất thường nhỏ
  (Firebase.* 3-28KB, GoogleMobileAds 6-9KB, Tapjoy/Airbridge, Unity.Burst 21KB,
  Google.Protobuf 157KB, UniTask 497KB…) — có thể cũng stub. Chưa swap vì path chưa chạy
  tới; khi activate path nào thì probe lại DLL đó theo pattern `JsonProbe`.

### Server-side quan sát (local server 8080)
- `GET /player` với token thiếu/không hợp lệ → single-player mode trả `playerdb.active()`
  (dev-0001) — KHÔNG phải lỗi parse phía client. Muốn biết server nghĩ gì về token:
  curl decrypt response (AES-ECB, key ASCII `a6072ad6b9c959ff`, zero-pad, TrimEnd NUL/space).
- `/auth` POST từ chối id chưa bind: msg "Google sign-in was not verified"
  (routes/direct_routes.py auth_native) → register-first bắt buộc với guest.

### Tool giữ lại
- `Kgc.Editor.JsonProbe.Run` (Assets/Game/Editor/JsonProbe.cs): regression probe cho lớp
  lỗi stub-DLL — parse `AuthResponseModel` + contract + ObscuredString roundtrip. Chạy:
  `Unity -batchmode -quit -executeMethod Kgc.Editor.JsonProbe.Run -logFile <log>` rồi grep
  `JSONPROBE` (mong đợi `obj = ok`, `obscured = DEV.abc123`).
- Backups ngoài Assets: `ExportedProject/Newtonsoft.Json.dll.bak-ripped`,
  `ExportedProject/ACTk*.dll`.

## 39. Unity rebuild — S2 Slice B: Scene_Lobby fetch chain chạy thật (2026-10-15)

**Gate GREEN** (`/tmp/opencode/s2gate/lobby_b2_play.log` + `shot_Scene_Lobby.png`): login →
`Lobby.Init` → 9 fetch tuần tự đều 200 → `lobby data: name=Player3640 lv=100 gold=290909
cards=73 inv=161 posts=1 buildPoint=25 territory=0 mission=OK shop=OK`, 0 exception,
black overlay nhả (ShowBlack(false) chạy). Compile + MasterDataSmokeTest + LocaleSmokeTest
đều exit 0.

### Decode Scene_Lobby (v174, decomp cache `/tmp/opencode/s2re/lobby_batch1.txt`)
- `Awake` RVA **0x362B1F0** (script.json decimal 56799728): `base.Awake` →
  `GameManager.InstantiateSimpleAssetDB(gm,false)` → `PopupManager.Clear(false)` →
  `Localizer.SetCanvasRoot` → `timeScale=1` → **check `RestAPI.accessToken` rỗng → quay
  Scene_Login** → `ShopPanel/DeckPanel/WorldPanel/ClanPanel/ArchivePanel.PreInit(false)`
  (fields ở offset +0xc0..+0xe0) → `WorkTimer.ClearAll` + `WorkTimer.Do(...)` →
  `targetFrameRate=60` → `CenterText.Show` (nếu flag static) → `CheckSavedGame` →
  `GameManager.CheckXcd` → `WorkTimer.Do(45f,...)`.
- `Start` RVA **0x362D2EC**: `WorkTimer.Do(1.25f, Init)` — delay splash rồi Init.
- `Init` RVA **0x362D7D4**: `GameManager.Init` → `InventoryFilterSaveData` ctor →
  `PlayLobbyBGM` → `Screen/Utility.GetScale` → lấp list panel (field +0x158/+0x370).
- Fetch chain gốc bắn từ **closure trong `Update`** (`Scene_Lobby.<Update>g__Fetch|257_1`,
  MoveNext RVA decimal 56832100) — KHÔNG phải từ Init. `Update` cũng chứa
  `FetchNextDay`-relogin vector (đã biết) → **Update để nguyên stub = tránh luôn bug loop**.
- `ReloadPanels` RVA 0x36323A8; `FetchPlayerInfo` MoveNext 0x363E58C gọi
  `RestAPI.GetPlayerInfo` rồi check `isSuccess`, `VoidedPurchasePanel.Show` khi `level<0`.

### Port (behavior-faithful, callback — không UniTask)
- `Scene_Lobby.Init` = kick chain **tuần tự**: player → currencies → card/all →
  getInventory → post → building → territory/fetch → mission → shop → `ReloadPanels` +
  `ShowBlack(false)`. Mỗi `Fetch*(Action onDone = null)`: `Web.Get<Model>(path,
  RestAPI.accessToken, false /*Newtonsoft*/, cb)` → `gm.HandleXxx(r)` → log `[S2]` →
  `onDone?.Invoke()` **luôn luôn** (fail 1 bước không chặn bước sau).
- `GameManager.Handle*` bodies mới (AssetRipper stub, chữ ký gốc giữ nguyên):
  `HandlePlayerDataResponse` (data từ `/player`), `HandlePlayerCurrencies`,
  `HandleCardListResponse`×2 → `UpdateOrAddCards` (tìm theo `unitId.value`) →
  `ApplyDimensionUnitData` (overcome/dimensionLevel/dimensionGauge từ `dimensionUnit`),
  `HandleInventoryResponse` (2 list song song → `inventory` dict) + `GetInventoryItemCount`,
  `HandlePostResponse`→`postModel`, `HandleBuildingResponse`→`buildingPoint`+`buildingData`,
  `HandlePlayerTerritory` (response→`PlayerTerritoryModel`, buildings convert
  `TerritoryBuildingResponseModel`→`TerritoryBuildingData`, level-sync list→dict key
  `unitId`), `HandleMissionsResponse`→`missionModel` thô, `HandleShopResponse`→`currentShop`.
  Storage đều là field/property GỐC của GameManager (`currentShop`/`missionModel`/
  `postModel`/`inventory`/`playerTerritoryModel` — không thêm field mới).
- `PlayerData.name/castleName` => đọc từ `model` (trước stub `=> null` → HUD không tên).
- `Scene_Login.HandlePlayerDataResponse` → delegate `gm.HandlePlayerDataResponse` (dùng chung).

### Endpoint ↔ model: dùng `server/generated/route_models.json` (authoritative)
Không cần đọc path từ il2cpp (path là static field, không phải string literal —
`stringliteral.json` không match). Map core: `/player`→PlayerDataResponseModel,
`/player/currencies`→PlayerCurrenciesResponseModel, `/card/all`→CardListResponseModel,
`/player/getInventory`→InventoryResponseModel, `/post` GET→PostResponseModel,
`/player/building`→BuildingResponseModel, `/territory/fetch`→PlayerTerritoryResponseModel,
`/mission`→MissionResponseModel, `/shop`→ShopResponseModel. Server chấp nhận
GET/POST/PUT tất cả route (`server.py:772`), handler state-only khi không có body.

### Gotchas đã tốn thời gian — đừng lặp lại
1. **`PreInit()` của panel KHÔNG nhận argument** trong export (`PreInit(bool)` là của bản
   gốc; AssetRipper xuất stub 0-tham số) → `CS1501` nếu port thẳng `PreInit(false)`.
2. **Field scene-wiring**: field `public` trong Scene_Base/Scene_Lobby (baseCanvas, black,
   blackBack, shopPanel..archivePanel, screenScroller, tabManager, loadingPopup, …) **có
   entry trong `Scene_Lobby.unity` YAML → tự wire**. Field `private` KHÔNG có
   `[SerializeField]` (toàn bộ `_xxxPanel` popup ở Scene_Lobby.cs:1241-1301) → KHÔNG có
   YAML entry → null runtime. Muốn nối: thêm `[SerializeField]` (public cũng được) rồi
   **scene YAML phải có entry sẵn** — nếu không có thì phải tự gán trong editor/prefab (S4).
3. **WorkTimer là stub no-op toàn bộ** (Do/ClearAll rỗng) → `Start` port gọi `Init()` thẳng
   thay vì `WorkTimer.Do(1.25f, Init)` (callback không bao giờ bắn).
4. **ShowBlack**: set alpha trực tiếp trên `black`/`blackBack` Image (không đụng DOTween —
   `DOTween.dll` 71KB chưa probe stub hay thật; nếu cần fade mượt thì probe trước, kiểu
   như Newtonsoft).
5. **Gate driver** (`CaptureScene.PlayCaptureDriver`): slice A capture SẬP khi vừa sang
   Scene_Lobby (fetch chain chưa kịp chạy) → thêm settle window: `_lobbyFrame` ghi frameCount
   lúc thấy Scene_Lobby, chờ thêm `KGC_CAPTURE_SETTLE` frames (default **420**) rồi mới
   capture; wall-clock nâng 120s→**240s**. `KGC_CAPTURE_SETTLE=0` = hành vi slice A.
6. **ObscuredInt `==` với `int`**: shim có cả implicit 2 chiều → có thể ambiguity; dùng
   `x.unitId.value == m.unitId` cho chắc.

### Còn lại của lobby (S4+)
- `ReloadPanels` thật: từng panel con (`PlayerInfoPanel`/currency HUD/Quest/Inbox/… ) cần
  `[SerializeField]` + body `Reload` — slice B chỉ log summary. HUD top (25/20-20/55000/1300)
  vẫn là value mặc định trong scene, chưa đọc `GameManager.data`.
- Fetches chưa port (ràng buộc unlock, S4 theo hệ thống): artifact/treasure/accessory/rift
  inventory, clan/raid, babel, season pass, event (year/eventmode/attendance/surprise/
  card-collecting/shop-event), challenge, deck, PvP/colosseum, daily-consumed currencies.
- `Awake` bỏ qua (stub/no-op, không đụng luồng data): `CheckSavedGame`, `CheckXcd`,
  `CenterText`, `InstantiateFlag`, `SetResolution`/`OnResolutionChanged`, `GameManager.LoadScene`.
- `Update()` để nguyên stub có chủ đích: chứa `FetchNextDay`-relogin 1Hz vector.

## 40. Unity rebuild — S4a: TopPanel HUD port (2026-10-16)

Reverse + port xong HUD top của lobby: `LerpText`, `Gauge`, `TopPanel`, event bus trong
`GameManager`, wire vào fetch-chain terminal của `Scene_Lobby.Init`. Gate **GREEN** —
screenshot `shot_Scene_Lobby.png`: level **100**, gold **290909**, cash **290909** (force →
nhảy ngay), heart gauge **"390/20"** = LerpText đang animate tâm (heart thật 290909, display
leo từ 0, capture đúng lúc ở 390 — đúng hành vi; DB confirm heart account test = 290909).

### RE method batch này
- Ghidra headless batch scripts `/tmp/opencode/s2re/decomp_batch*.java` (pattern:
  `Object[][] = {{decimalRVA, label}}` → `analyzeHeadless /tmp/ghidra_proj KGC -process
  libil2cpp_v17400.so -noanalysis -scriptPath ... -postScript ...`), output `lobby_batch*.txt`.
- **Pitfall decimal→hex**: tự tay đổi hex→decimal rồi truyền vào script → trúng nhầm hàm
  cách hàng nghìn byte (batch7 lần 1 decode nhầm `UICirclePosition.SetDistance` thay vì
  `GetNextPlayerExp`). Luôn tính decimal bằng `python3 -c "print(0x302D5A0)"`.
- Ghidra struct-return mangle: `Gauge.Init` show `param_3/param_4` = s2/s3 của `Rect` return
  (width/height), không phải tham số thật.
- Method-var delegate (closure cache trong `<>c`) resolve qua `.rela.dyn` addend →
  `script.json ScriptMetadataMethod`; ô tĩnh TopPanel: `+0` = `<>c` instance,
  `+8` = `Func<long,long,string>` cache heart format (`<Init>b__32_0` = `"{0}/{1}"`).

### Layout & semantics đã decode (v174, field offset từ decomp)
- **LerpText** (header 0x20): `valueText+0x20, speedRatio+0x28, delay+0x2c, signed+0x30,
  _value+0x38, _displayValue+0x40, _format+0x48, _valueCallback+0x50, _maxCallback+0x58,
  _delayTimer+0x60, _reloadAction+0x68, _minValue+0x70`.
  `Set(value, fmt, force)`: `_reloadAction ??= b__13_0` (viết text); `_value=value;
  _format=fmt; _delayTimer=delay; force→_displayValue=value`; flush `reloadAction(Max(_minValue,_displayValue))`.
  `Update`: countdown delay; `|display−value|<2` → snap; else `display = Lerp(dt*speedRatio,
  display, value)` + ngưỡng ±1 step; rồi `_valueCallback`/`_reloadAction` với `Max(_minValue,display)`.
  String-overload `Set(value,"{0}",force)` = closure quanh format string → port gói thành Func.
- **Gauge** (layout đọc được): `valueText+0x30, valueLerpText+0x38, gauge+0x40, shieldGauge+0x48,
  directGauge+0x50, speedRatio+0x58, delay+0x5c, displayRealValue+0x68, _maxValue+0x78,
  _value+0x80, _displayValueP+0x88, displayValueDivide+0x90, _delayTimer+0xb0,
  _shieldValue+0xc0, _isInited+0xd0, rect captures +0xd4..+0xe4, _isDirty+0xe8,
  _forceNextReload+0xe9`.
  - `Init` (=`Awake`): capture rect size của gauge/directGauge/shieldGauge, lazy `_isInited`
    (anchor self-assign = no-op, bỏ).
  - `Set(value,max,force)`: max/value; `force→_forceNextReload+_displayValueP=div*value`;
    `_isDirty`; tail inline `valueLerpText.Set(display, Func(gauge,b__42_0), force)` —
    `b__42_0 = b__43_0 = b__52_0` = `_textFormatFunc(v, _maxValue)`.
    `SetValue(value,force)` = y hệt + `_delayTimer=delay`.
  - `Update`: nếu delay>0 → countdown, dirty thì flush; animate `step=min(div*max, div*value−disp)
    /5*speedRatio`, `|step|<speedRatio` → snap `disp=div*value`; per-frame
    `_valueCallback(BankersRound(disp/div))`; khi `disp/div==max` → `_maxCallback`; shield-anim
    `_displayShieldValue` step ±.
  - `LateUpdate` = `if(_isDirty) Flush()`; `ReloadGauge` = `Flush()` (2 body decomp giống hệt).
    Flush: `Init`; force → `_displayValueP=div*value`; text chỉ ghi khi
    `valueText!=null && _textFormatFunc!=null && valueLerpText==null`;
    `maxEff = shield>0 ? Max(max, value+shield) : max`; ratio/directRatio clamp [0,1];
    **fill rule**: `horizontal = (value==max) || (max<0 && value>0)` — full thì ngang
    (scale `sizeDelta.x` theo width), chưa full thì dọc (scale `sizeDelta.y` theo height);
    shieldGauge sizeDelta theo shieldFill; `gaugeMarker.Set(value, shield, maxEff)`;
    force tail → `_valueCallback(value)` + `maxCallback nếu max<=value`.
  - `SetTextFormatFunc`: set func; `valueText.text=func(value,max)` (NRE nếu func null);
    `valueLerpText = Utility.Get<LerpText>(valueText)`; inline `Set(disp, b__52_0)` với
    `_displayValue=disp` **không điều kiện** (≈ force:true).
  - `Start`: `Init`; `shieldGauge!=null && _shieldValue<1 → SetActive(false)`;
    `_textFormatFunc ??= (v,_)=>"{0}"`; `valueLerpText ??= Get<LerpText>(valueText)` →
    `Set(disp, b__52_0, force:true)`; `_delayTimer=-1f`.
- **TopPanel** (field region): `Instance`(static), `levelText, expGauge, heartGauge,
  heartTimerText, goldText, cashText, touchBlocker, inMatchmakingObject, _riftWeaponDustText,
  _lastLevel/_lastExp/_lastHeart/_lastGold/_lastGem` (sentinel: heart<0, gold/cash<1).
  - `Awake`: `_instance=this`. `Init`: `heartGauge.SetTextFormatFunc("{0}/{1}")`;
    `ReloadAll(true)`; WorkTimer 0.5s loop → `ReloadHeartTimer` (**port: InvokeRepeating**);
    smart-reroll block (ResourceBase.Get(800)) skip; `touchBlocker?.SetActive(false)`.
  - `OnEnable` subscribe đúng thứ tự: `(Exp,LevelUp)→ReloadLevelExp`, `(LevelUp,Heart)→ReloadHeart`,
    `Gold→ReloadGold`, `Cash→ReloadCash`, rồi **Add thẳng tuple `(RiftWeapon, ReloadRiftWeaponDust)`
    vào `_callbacks`** (không qua Subscribe — Subscribe tương đương trong port). `OnDisable` mirror +
    WorkTimer cleanup (bỏ, key không port). Ngoài cùng: `inMatchmakingObject.SetActive(gm._isInMatchmaking)`
    → phải make `_isInMatchmaking` public.
  - `ReloadLevelExp(force)` (paramless = event target): `levelText.text=level`;
    **lv100 → `expGauge.Set(0,0,force)`, return sớm** (không effect, không update _last);
    else `Gauge.Set(exp, GetNextPlayerExp(level), force)`; effect gate
    `(_lastLevel>0&&_lastLevel<level)||(_lastExp>0&&_lastExp<exp)` → GetMoneyEffect.Show(5) **skip**;
    `_lastLevel/_lastExp = ...`.
  - `ReloadHeart`: `_lastHeart<0 || heart<=_lastHeart` → closure `ReloadGauge` trực tiếp;
    tăng → sound+effect skip, WorkTimer(0.5) → direct call; **luôn** `ReloadHeartTimer();
    _lastHeart=heart`. Closure: `heartGauge.Set(heart, GetMaxHeart(), force:false)` + toggle
    ConditionalImage heart-full trên directGauge (**skip**).
  - `ReloadHeartTimer`: max → tắt timer object, return; else bật, `span=(model.tomorrow_
    −Now)+FromMinutes(1)`, `text=ToPrettyFormat2_2(span)`; `TotalMinutes<=0 → "0h 0m"`.
  - `ReloadGold/ReloadCash(force)`: 2 nhánh tăng/giảm chỉ khác sound/effect (skip hết) →
    thẳng `goldText/cashText.Set(v, "{0}", force)`; `_lastGold/_lastGem=v`.
  - `ReloadRiftWeaponDust(force)`: `_riftWeaponDustText?.Set(GetInventoryItemCount(8000), "{0}", force)`.
- **GameManager.HandlePlayerDataResponse** (@0x3150CAC) event fires: exp đổi → `Shoot(Exp)`;
  level đổi → `Shoot(LevelUp)`; `handlePlayerCurrencies` → gold/cash/heart đổi → set + shoot
  `Gold/Cash/Heart` (gốc qua SetGold/SetCash/SetHeart); sau `d.model=model` →
  `Shoot(ProfileIcon)` **không điều kiện**. Bus port: `_callbacks: List<(CallbackType,Action)>`,
  `Subscribe/Unsubscribe(RemoveAll)/ShootCallback(snapshot ToArray)/ClearCallbacks`.
- **Helpers**: `GetMaxHeart()=20` (hằng); `IsMaxHeart()=heart.v>=20`.
  `Constants.GetNextPlayerExp` (@0x302D5A0): `lv>99→int.MaxValue`, master-data dict key type 6
  index `level-1` — port chưa có bảng → `return 0` (= hệt bản gốc khi table vắng; Gauge guard
  `maxEff>0` nên không chia 0). `Utility.Lerp(long,long,t)=a+BankersRound(clamp01(t)*(b−a))`
  (half-to-even); `Lerp(double,..)=(b−a)*clamp01(t)+a`; `ToPrettyFormat2_2` = `"{H}h {M}m "`;
  `ToSignedString(v)=(v<1?"":"+")+v`. BankersRound port = `(long)Math.Round(v, ToEven)`
  (IL2CPP inline chính là Math.Round; inf → long.MinValue do unchecked cast tự nhiên).
  `Utility.Get<T>` (generic inline, không resolve RVA) port = `GetComponent<T>` (+Find khi có name).

### Port decisions / gotcha
- **`Image.sizeDelta` không tồn tại** → luôn `image.rectTransform.sizeDelta`.
- `CallbackType` là nested enum trong `GameManager` → `GameManager.CallbackType.X`.
- Stub AssetRipper có sẵn `ReloadHeartTimer()` rỗng ở nửa sau file → duplicate CS0111, gỡ bản rỗng.
- `_displayValue` generated property (`=> 0.0`) retype thành accessor thật:
  `displayRealValue ? _value : BankersRound(_displayValueP/divide)`.
- Field name `_gaugeHeight@+0xd4/_gaugeWidth@+0xd8` trong export trái ngược usage decomp
  (width scale x, height scale y); port ghép **semantic** (width↔x, height↔y) — field private
  không serialized nên không ảnh hưởng scene.
- `tomorrow_` property stub → `DateTime.TryParse(tomorrow)` (server gửi ISO next-reset).
- Scene wiring: `TopPanel.Instance?.Init()` sau `ReloadPanels()`, trước `ShowBlack(false)` —
  OnEnable đã subscribe từ lúc scene load, Init chạy lúc data thật về.
- Font số bitmap ở góc phải screenshot render thô (atlas SpriteFont) — tình trạng cũ từ
  trước, không thuộc S4a.

### Bước tiếp theo
- S4b: các panel con trong `ReloadPanels` (`PlayerInfoPanel`, Quest/Inbox/… mỗi cái cần
  `[SerializeField]` nối ref + body `Reload`), rồi ~20 `Fetch*` còn lại theo `route_models.json`.

## 41. Unity rebuild — master-data slice: ResourceBase core + ResourceInventoryItem + ResourceUnit UI subset (2026-10-16)

Mục tiêu: "connect luôn cả master data xml đi để UI nó chuẩn hẳn" — wire bảng XML vào runtime UI.

### Kết quả / gates
- **Compile gate GREEN**: `KGC_MASTER_DATA=/home/nowl/Code/kgc/server/xml_live timeout 420 <Unity> -batchmode -nographics -quit -projectPath unity/kgc-rebuild/ExportedProject -executeMethod Kgc.Editor.MasterDataSmokeTest.Run` → `ResourceUnit: 1043 rows (sample 'Shelda')`, `ResourceInventoryItem: 173 rows (sample '{0} EXP')`.
- **Play-capture gate GREEN**: `KGC_CAPTURE_PLAY=1 KGC_CAPTURE_LOGIN=1 KGC_CAPTURE_DIR=/tmp/opencode/mdcap timeout 420 xvfb-run -a -s "-screen 0 1280x2048x24" <Unity> -batchmode -force-glcore -projectPath … -executeMethod Kgc.Editor.CaptureScene.Run` → `shot_Scene_Lobby.png` **giống hệt baseline S4a** (chỉ 390/20→393/20 = stamina theo thời gian) → không regression localization.

### CRTP constraint (compile lỗi nếu quên)
- `ResourceBase<T>` phải khai `where T : ResourceBase<T>, new()` — `LoadFromString` gọi `item.Init(e)`/`item.id` trên `T`. Mọi subclass đều CRTP (`ResourceUnit : ResourceBase<ResourceUnit>`…), kể cả generic trung gian `ResourceAbstractRankTier<T>` phải mang cùng constraint. Các generic helper sẵn trong export (`IRecursiveInheritable<T>`, `ResourceGachaPool.GetPoolAsResource<T>`, `Utility.GetChild<T>`…) đã khai CRTP từ trước.

### Utility.cs — 3 fix root-cause trong helper dùng chung
- **`ToEnum<T>`/`ToEnumIgnoreCase<T>` là stub `return default`** → sửa = `Enum.TryParse(text[, ignoreCase], out v) ? v : @default` (null → false → default, khớp máy).
- **`Utility.GetVersion()` decode (RVA 0x2CA19B4)**: cache field static+0x108; `Application.version.Replace(".","")` → int (`"174.0.00"`→**174000**, khớp thang MinVersion trong Units.xml: 152100…172000, và các value nhỏ 311-654 đều ≤). Cache chỉ khi ≥1 (parse fail → 0 parse lại lần sau). `ProjectSettings.asset bundleVersion: 174.0.00` ✓.
- XML helpers (`GetChild*/GetAttributeInt/GetSplitInt/…`) port trước slice này — pattern: `child?.InnerText ?? default` với inherit fallback `SelectSingleNode("./"+key)`.

### ResourceUnit.Init (RVA 0x2E268C0) — decode máy + port
- **4 dict phải tạo ở TOP của Init**: export không có `.ctor`/field initializer — máy init trong `.ctor`: `stringValues(0x180)`, `_valuesWithCoefficient(0x1B8)`, `_enumWithValuesDict(0x318)`, `_enumWithValueCoefficientDict(0x310)`. `_temporaryCoefficientNode(0x1C0)` để null (deferred).
- **Inherit**: `inheritFrom = GetAttributeInt("Inherit",-1)`; `≥1 && Get(inheritFrom)≠null` → kế thừa: `pn = parent._xmlNode`, name/subName default theo **parent.id** (không phải parent.root — Units.xml không có Inherit depth≥2 nên trùng thực tế) + inherit=pn, copy `parent.stringValues` (last-wins), `root = parent.id`. Gốc (không parent): default `UnitName_{id}`/`UnitSubName_{id}`, `root = id`.
- **identity/display**: `type` = GetChildText("Type") (inherit, default null) → ToEnum(Type.None); `_prefab`/`spriteName`/`uiSpriteName` (inherit, default null); `portraitName` = `Portrait_{(id%10000000)/10-1000:000}`, `avatarName` = `Avatar_{…:000}` (inherit); `illustName` = `Unit_Illust_{id%10000000}` (**không inherit**); `unitPanelDataId` default = `id%10000000` (inherit); `cost` default 1; `spriteInSheet` default **true**; `atkType` = GetChildText("AtkType", **"Melee"**) → ToEnum(AtkType.None).
- **nameColor + layout (TẤT CẢ không inherit)**: `nameColor`=ToColor("NameColor"→null→white); `illustOffsetX/Y` default 0; `illustScale` default **0.75**; `gachaIllustOffsetX/Y`, `gachaBackIllustOffsetX/Y` default 0; `gradationColor`/`gachaGradationColor`/`gachaExplosionColor` = ToColor.
- **skill ids**: `_skill`="Skill"(-1), `attackSkill`="AttackSkill"(-1), `deathSkill`="DeathSkill"(-1), `activeSkillId`="ActiveSkill"(-1), tất cả inherit=pn.
- **children loop (đầu = `n.ChildNodes.FirstChild`)**: bỏ non-XmlElement; **skip-set 19**: `Name, Prefab, Height, Hp, Atk, Speed, ArrowPrefab, ArrowSpeed, ArrowType, ArrowOffsetY, Boss, SkillAtk, Effect, Potential, LevelRatio, GenExcept, OnClick, AIType` + `#comment` (loại bằng NodeType). Upsert last-wins (`stringValues.Remove` trước); **rule số thuần**: `!value.Contains(",") && double.TryParse(value, NumberStyles.Float, InvariantCulture)` → nhánh coefficient (**deferred, KHÔNG thêm vào stringValues** — và Remove đã chạy nên key biến mất hẳn).
- **Sau loop**: `isDimensionUnit`("IsDimensionUnit",false,pn), `originalUnitId`("OriginalUnit",0,pn), `visible`(**default true**,pn), `summonTrigger`("SummonTrigger",null,pn), `minVersion`("MinVersion",0,pn), `aiType`("AIType", **"MoveAttackAI"**, pn — gốc gọi `AIFactory.CacheConstructor` ngay sau → defer), `clanBossAvatarSpriteName`("ClanBossAvatarSprite",null,pn).
- **Block 0x1F0-0x1FA (deferred — combat/behavior, keys đã resolve)**: `DontDestroyWithParent`(false, **không inherit**), `IgnoreSkillFromParent`(false, không inherit), `RewardGold`(0, inherit — máy default **0**, không phải 500 như ghi nhận cũ), `FixDirection`(false, inherit), `ApplyTeamDirection`(**default true**, inherit), `IsClanRaidBoss`(false, inherit).
- **Tail**: `MaxPlayerUnitId` static = `if (type==Player && visible && MaxPlayerUnitId<id) MaxPlayerUnitId=id`; `stringValues → _enumWithValuesDict`: `Enum.TryParse<UnitTag>(key)` thì `.Add(tag,value)` (XML name không được bắt đầu bằng chữ số → parse số không xảy ra, Add không đụng); `kgWikiCollectable = GetChildBoolean("KGWikiCollectable", true) && type==Player && visible` (**chạy SAU khi visible đã gán**); coefficient dict loop no-op (dict rỗng).

### Getters đã decode + port
- `fullName` = `string.Format("FullNameFormat".L(null), base.name, subNameKey.L(null))` — Strings_EN_US: `{1} {0}` (subName đứng trước); `name` = `GetValueBool(UseFullName=63) ? fullName : base.name`; `pureName` = `base.name`.
- `koreanName`: máy mơ hồ (locale==1 Localize trực tiếp vs reverse-search map KR) → port `nameKey.KR()` (GetKorean key-fallback) + TODO.
- `prefab`: máy có nhánh scene-conditional (`UnitTag.UIPrefab=241` / `StoryModePrefab=242`) → port `_prefab` + TODO.
- `GetSubName(skinID)`: skin branch = `L(skin.name).Replace(name,"").Trim()` — **ResourceSkin là stub** (`GetValueBool→false`, `name→null`) → branch dead, luôn trả `subNameKey` key-fallback. `ResourceSkin.Get(-1)` an toàn: `ResourceSkin.Init` stub không set id → `LoadFromString` skip (`id != 0`).
- **`GetValueText/GetValueBool/GetValueTextList/HasValue/HasStringValue`** đọc `_enumWithValuesDict`:
  - GetValueBool: **key thiếu → @default; key có mà bool.Parse fail → false** (không phải default).
  - GetValueTextList: key thiếu → **List rỗng** (@default bị bỏ qua); có → `Split(',')` giữ nguyên phần tử rỗng, đóng gói List mới.
  - `HasValue` = `HasCoefficientValue || ContainsKey`; `HasCoefficientValue` = ContainsKey dict 0x310 (luôn false khi deferred).
- **`GetValueInt` (cả 2 overload: GameUnit/Func)** = **coefficient-only**: `HasCoefficientValue(key) ? (int)Math.Round(GetValueWithBound(...)) : @default` — round banker's (Math.Round mặc định), cast infinity → int.MinValue. **KHÔNG đọc string dict** → deferred ⇒ luôn `@default`.
- `GetParentIDIfHas`: IsTransform → GetValueInt(TransformRootUnit) (deferred -1) → fallback coeff(TransformUnit); không IsTransform → `!HasValue(Summoner) ? id : coeff(Summoner)` ⇒ dưới deferral quy về `!IsTransform && !Summoner → id`, còn lại -1. `GetParentIfHas` = `Get(GetParentIDIfHas()) ?? this`. `GetChildIDIfHas`: `!HasValue(TransformUnit) || IsTransform ? (HasValue(SummonedUnit) ? -1 : id) : -1`. `IsSubUnit` = `GetValueBool(455) || HasValue(448)`. `GetRootUnitId` = `restoreUnit(0x104) ≥ 1 ? restoreUnit : id` — **KHÔNG phải field `root`**.
- `isPlayerUnit` = `type == Type.Player`.
- `GetAllPlayerUnits(checkFunc)` (RVA 0x2E31B84, verify bằng 2 lambda `b__215_0`/`b__1`): `type==Player && visible && minVersion ≤ Utility.GetVersion() && checkFunc`, **cộng cap `id ≤ GameManager.GetKeyValueInt("LatestPlayerUnitId", HeartTimerHash dword thấp)`** — `GameManager.GetKeyValue` chưa port → **TODO cap = int.MaxValue (mở hết)**.
- `Load()` = `Load("Units.xml"); AfterLoad();` (máy có nhánh queue nền, port đồng bộ). `AfterLoad()` = `_xmlNode = null` (máy còn `_temporaryCoefficientNode=null` + `BuffDictSet.RemoveParsedKeys` ×2 trên dict 0x180/0x1B8 — defer tới khi port BuffDictSet).

### Resolver recipe (PTR_DAT trong decomp)
- `PTR_DAT_06aXXXXXX` → `python3 /tmp/opencode/s2re/resolve_strings.py 0x6aXXXXXX …` (đọc `script.json ScriptString[].Value` qua cell→addend). Raw-garbage (vd `'\x050'`, `'!'`) = **empty string hoặc inline-cache member handle, không phải string** — khi cần dùng dump.cs RVA list thay thế (grep class body theo `RVA:` line).
- Định vị method không có RVA sẵn: grep dump.cs theo tên → lấy `RVA:` predecessor → file offset = RVA − 0x4000 / decomp qua `analyzeHeadless … -postScript decomp_batchNN.java` (batch scripts cache tại `/tmp/opencode/s2re/unit_batch*.txt`).
- Key const hay dùng (Init Units): Type 0x6a528d0, Prefab 0x6a52888, Sprite 0x6a52b38, UISprite 0x6a62cb0, Portrait 0x6a632a8, Avatar 0x6a64860, IllustSprite 0x6a62d90, UnitPanelData 0x6a648c0, Skill 0x6a64a08, AttackSkill 0x6a647c8, DeathSkill 0x6a649f8, ActiveSkill 0x6a648b0, SummonTrigger 0x6a649c0, MinVersion 0x6a52b78, AIType 0x6a64800 (default 'MoveAttackAI' 0x6a649e8), RogueLikeSynergies 0x6a64828, OriginalUnit 0x6a649c8, LatestPlayerUnitId 0x6a64c68; format: `Portrait_{0:000}` 0x6a647e0, `Avatar_{0:000}` 0x6a648b8, `Unit_Illust_{0}` 0x6a64880.

### ReloadPanels original — DECODED (blueprint S4b, giữ nguyên)
- `foreach (p in screenScroller.lobbyPanels) p.Init()` — `ScreenScroller.lobbyPanels : BaseLobbyPanel[]` @obj+0x20; vtable slot 4 = `BaseLobbyPanel.Init`; cờ `inited`.

### Deferred / open từ slice này
- ResourceUnit combat/stat block: hp/atk/def…(0x68-0xE4), height 0x164-0x178 (`Height` default **30f**, `HeightOffset` **-10**, `FloatingY`/`HeightWhenBuff`/`BossHpBarIndex`/`UseGroggyBar`), RangeInfo, sounds, attackInterval/attackCount/restoreUnit-reward parse, skillEnergyType, levelRatio (`.//LevelRatio` + parent-copy `if(!bVar12)`), overcomes, effects, transformConditions, dimensionLevelStats, tileSize (`.//TileSize`), `ParseCoefficientValue` + `_temporaryCoefficientNode` attrs Target/Key/Bound/Min, rogueLikeSynergies `.Select(parse)`, aiType CacheConstructor, block 0x1F0-0x1FA.
- `GetValueInt/Long/Double` coefficient branch (`ValueWithCoefficient.GetValueWithBound` + round) — cần port `ResourceSkill.ValueWithCoefficient`.
- `AfterLoad` `BuffDictSet.RemoveParsedKeys` ×2 (verify kiểu 2 field 0x180/0x1B8).
- `GetValueText(string key)` overload (export @~1271) — không có trong dump scan → giữ stub null, TODO.
- koreanName locale reverse-search; prefab scene-conditional 241/242; `GetChildIDIfHas/GetParentIDIfHas` coefficient round restore; GetAllPlayerUnits cap (`GetKeyValueInt("LatestPlayerUnitId")` — cần `GameManager.GetKeyValue`/keyValues server).
- Utility stubs còn lại: `GetChildTextList`, `GetChildStringArray`, `GetChildVector2Int`, `GetAttributeIntArray`, `GetAttributeLong`, ToEnum non-generic overloads (combat), `SetSprite`/`ToRoman`/`CheckLevelAvailable` (S0 ghi nhận rồi).
- ResourceSkin (+ LoginSkins/MapSkins/TerritorySkins/SkinReturnShopInfos) chưa port — Init stub, Get() trả null an toàn.
- `Role`/`Region` (ToEnum; region default idx 5?) chưa port — rogue-like synergy UI.
- Câu hỏi cũ treo: `~/Downloads/Eternum` folder mất, `~/Downloads/tnt_win_linux.zip` (4.3GB) giữ/xoá.

## 42. Unity rebuild — S4b: ReloadPanels loop + lobby profile binding (2026-10-16)

### Kết quả
- Cả 2 gate GREEN: compile/smoke (1043 units 'Shelda', 173 items) + play-capture **0 exception** (lần đầu — các lần trước lần lượt vỡ ở `WorldPanel.Init` → `PlayerProfile.Set` → `InstantiatePrefab`, debug bằng checkpoint log).
- Ảnh capture: banner NameTag_10000 instantiate thật (quad trắng — sprite art defer), text profile set = `Player3640`/`Castle8223` (khớp server `p-fbc904313418`; trắng-trên-trắng nên không thấy trên ảnh, art defer).

### Đã port (RVA máy)
| Method | RVA | Body |
|---|---|---|
| `Scene_Lobby.ReloadPanels` | 0x36323A8 | vòng lặp vô điều kiện `lobbyPanels[i].Init()` (5 panel: Shop/Deck/World/Clan/Archive) |
| `ArchivePanel.Init` | 0x31DF878 | `Reload(); inited = true;` (Reload body defer archive system) |
| `Utility.CheckLevelAvailable` | 0x2CA1AE4 | `data==null → lv=1`; `return limit <= level` (AwesomeInt `.v`) |
| `ResourceConstant.Init/Get` | Init dump Strip; Get 0x360CDB8 | Init parse Type/Index/Value + **fill `_singleData` ngay lúc parse** (máy fill trong Init/AfterLoad — dump strip, không thấy); `Get`: key vắng → 0, dict null → NRE; `EnsureLoaded()` mở protected |
| `ResourceNameTag.Init` | 0x2C6B9E4 | spriteId/prefab/tier/type; **`prefab = <Prefab> ?? "NameTag_" + id`** (row 10000 không có `<Prefab>` → máy sẽ `InstantiatePrefab(null)` NRE; default theo tên id vì `NameTag_10000.prefab` có thật) |
| `ResourceNameTag.defaultNameTagId` | — | **không thấy writer nào trong dump** → port gán `= 10000` (row có thật trong NameTags.xml); `isTierTag = type ∈ {PvPTier,TowerTier,ColosseumTier}`; `GetSeasonNameTag` STUB `return null` (defer — chỉ dùng cho tag tier trang bị) |
| `GameManager.GetProfileIconId` | 0x31586B0 | `int.Parse(GetKeyValue("ProfileIconId") ?? "-1")` |
| `GameManager.GetEquippedNameTagId` | 0x316591C | inventory model null → default; equipped null → NRE; Get(id) null → default; isTierTag → GetSeasonNameTag (null → default) |
| `GameManager.SetProfileUI` | 0x316FF68 | info rỗng (accountId/nameTagId/iconId = 0) → icon + nametag + castle/king lấy từ `data`; res null → `Get(default)`; `pp==null` → NRE; `pp.Set(...)` + `pp.SetAccountId(...)` |
| `PlayerProfile.Set` | 0x37AFB08 | sprite name: `-1 → Avatar_Default`, `<1e6 → Avatar_{0:000}` (`id/10-1000`), `≥1e6 → Avatar_{0:000}_{1:00}`; icon ẩn khi sprite null (`enabled=false`); tag khác prefab → Destroy + Instantiate dưới `_nameTagRoot` + `SetParent(GetAvatarRoot().transform)`; `_nameTag.Set(res)` + 2 Text set (null → NRE từng bước) |
| `PlayerProfile.SetAccountId/SetOnClick` | 0x37B01F8/0x37B0200 | store `_accountId`; button null → return; onClick null → `interactable=false`; else RemoveAll+AddListener(`onClick(_accountId)`) |
| `NameTag.Set` | 0x37AF840 | `prefab != "NameTag_10000"` → early return; else gán sprite 3 Image (sizeDelta theo sprite.rect defer); `GetAvatarRoot() = _avatarFrameImage.transform`; `GetPrefabName() = _resNameTag?.prefab` |
| `SimpleAssetDB` | 0x2E3835C/0x2E2652C/0x2E38900 | `Awake: _instance = this` (RegistDict defer); `GetSprite/GetPrefab = Resources.Load(name)` (null/empty → null); `InstantiatePrefab = GetPrefab → null? null : Instantiate` |
| `GameManager.InstantiateSimpleAssetDB` | 0x3174468 | `new GameObject("SimpleAssetDB") + DontDestroyOnLoad + AddComponent` (thay Addressables instantiate), guard `Instance == null` |
| `WorldPanel.Init` | 0x35CCB74 | level-gate 5 nút (`LevelLimit_Missions`=**3**, `LevelLimit_SeasonPass`) + event statics; `ClanPanel.Instance = lobbyPanels[3].GetComponent<ClanPanel>() → PreInit()` (body PreInit defer clan); `if (themeSelectPanel != null)`: ReloadIsHardMode + Reload/ReloadLobbyDeck/ReloadProfileIcon/ReloadPassGauge(true)/ReloadMissionBadge/ReloadGachaNewBadge + `inited=true`; **đuôi review-popup defer** |
| `WorldPanel.ReloadProfileIcon` + click | 0x35CDD44/0x35DC8EC | `SetProfileUI(new ProfileUIInfo { playerProfile = _playerProfile })` + `SetOnClick(_ => ReloadProfileIcon_OnClickProfile())`; handler: `_profilePanel.Reload()` (ShowImpl private trong export — port thân ProfilePanel sẽ mở lại; Firebase/GameListBox/TabManager tail defer) |
| `Scene_Lobby.Instance` | — | export **không có điểm gán** (dump static có, không thấy writer) → `WorldPanel.Init` NRE ở ClanPanel lookup; fix: `Instance = this` trong `Awake()` |

### Gotchas (tái sử dụng)
1. **`Resources.Load("name")` bare-name chỉ tìm asset nằm NGAY ROOT của folder `Resources/`** (Unity 2022.3.62f3, verify bằng probe): asset trong `Resources/Sub/` → `Load(name)` = null dù `LoadAll` thấy và `Load(sub/name)` OK. → NameTag prefabs đã **flatten về `Assets/Resources/`**; sprite art về sau phải đặt cùng cách (hoặc load theo subpath).
2. **UI Image sprite null = quad TRẮNG** (không phải trong suốt) → banner nametag trắng đặc khi sprite art defer; text trắng-trên-trắng = không thấy trên ảnh nhưng vẫn set (verify qua 0-exception + giá trị server).
3. **Roslyn không chấp nhận tên method `<...>` trong source** (IL-name style) → đổi `ReloadProfileIcon_OnClickProfile`.
4. Debug NRE kiểu "offset trỏ vào `ret` + line = dấu `}` cuối method" → forensics IL không đáng tin; dùng **checkpoint Debug.Log** khoanh vùng, lần ra ngay.
5. Prefab move giữ `*.meta` cùng folder (guid tham chiếu toàn cục); tên folder Resources phải đúng chính xác `Resources`.

### Deferred / open từ slice này
- `WorldPanel.Reload()` body (30 call) + DeckPanel/ShopPanel/ClanPanel `Init` bodies + `ClanPanel.PreInit` body + review-popup tail — theo system work của S4.
- `GetSeasonNameTag` (pvpData+0x220/colosseum+0x3d0 season map) — chỉ ảnh hưởng tag tier trang bị.
- Sprite art: `Avatar_*`, `Nametag_*` → Resources (theo gotcha #1) — icon ẩn + nametag trắng hiện tại.
- `NameTag.Set` sizeDelta dance theo sprite.rect + frame `SetSizeWithCurrentAnchors` — chờ nameTagSprite data.
- `SimpleAssetDB` RegistDict (material/font) + GetMaterial/GetFont/GetSpriteFromAtlas.
- Profile click tail: `_isOtherPlayerInfo`/`GameListBox.OnClickClose`/`TabManager.OnClick`/Firebase Log + `ShowImpl` (private trong export — đổi access khi port ProfilePanel).

## 43. Unity rebuild — S4b+ part 1: WorldPanel.Reload orchestrator + 2 bug level-gate (2026-10-17)

Port thân `WorldPanel.Reload()` (deferred từ §42) + lung ra 2 bug thật khi đối chiếu decode:

### Decode (v174.0.00, Ghidra batch24 `/tmp/opencode/s2re/const_batch24.txt`)

| Method | RVA | Nội dung |
|---|---|---|
| `WorldPanel.Reload` | 0x35CD0E0 | kim tự tháp gate lồng: `Get<ConditionalBase>(_territoryButton)` (ConditionalGroup trên cùng GO) != null → `SetValue(CheckLevelAvailable(Get(LevelLimit_Territory)))` + `_territoryButton.SetActive(true)` → cùng shape với `_territoryTycoonButton` (SeasonalEventMode) → `ReloadTerritoryTycoonButton`+`ReloadStockEventButton` → `if (GameManager.Instance != null)`: `_streamingButton.SetActive(GetAvailableStreamingIndex() >= 0)` → **23 `Reload*` badge/nút + `RefreshMissions`** → `if (gameListBox != null) GameListBox.Reload(false)` → skin-package gate (`pkg=GetCurrentNewHeroSkinPackage` → `UnitID`→`ResourceUnit.Get` → level gate → `GetVersion() >= unit.minVersion` → `!HasSkin(SkinID)`) → `newHeroPackButton.SetActive(show)` + `SetSprite(icon, unit.avatarSprite)` → `bankBadge=GetShowBankButtonBadge()`; **`bankButton.SetActive(false)` cứng**; `if (bankButtonBadge != null) SetActive(bankBadge)` + đuôi layout defer |
| `ResourceConstant.Init` | 0x360CA74 | `index = GetChildInt("Index", default = -1)` → row **không có `<Index>` store key -1** (LevelLimit_* đều không Index). Value slot 4 kiểu (int/text/intlist/textlist) theo 2 flag bool — port chỉ cần int path |
| `ResourceConstant.Get` | 0x360CDB8 | re-verify: `_singleData` null → NRE; `!ContainsKey(type)` → 0; `d==null` → NRE; `!ContainsKey(index)` → 0 (FindEntry throw bất khả đạt) — port khớp |

### 2 bug fix (cùng slice)
1. **`ResourceConstant.Init` index default `0` → `-1`**: port cũ store row không-Index ở key 0, còn `Get(type)` mặc định index **-1** → miss → trả 0 → `CheckLevelAvailable(0)` = **mọi level-gate LUÔN MỞ** (sai với máy). Máy: `Get(LevelLimit_Missions)=3` (Constants.xml Value), SeasonPass=4, Territory=10, SeasonalEventMode=8, NewHeroPackage=8 → account lv1 bị gate đúng như máy.
2. **`WorldPanel.Init` bỏ wrap `ResourceConstant.Get`**: 2 site `CheckLevelAvailable((int)ResourceConstant.Type.X)` so sánh level với **ordinal enum** (Missions=55!, SeasonPass=56) thay vì Value trong Constants.xml → đổi thành `CheckLevelAvailable(ResourceConstant.Get(Type.X))` theo máy. Test lv100 nên 2 version đều "mở" → gate xanh không phát hiện — chỉ đối chiếu decode mới thấy.

### Verification
- Probe tạm `UnityEngine.Debug.Log` đầu `Reload` (gỡ sau khi xong): `cond=TerritoryButton (ConditionalGroup)` tìm thấy, đủ field (`tycoonBtn/streaming/listBox/pkgBtn/bankBadgeGO` non-null, `gm=True`) → cả pyramid đi qua; **0 exception** cả capture.
- Gates cuối (probe đã gỡ): compile GREEN (1043 units/173 items) + play-capture `shot_Scene_Lobby.png` GREEN 0 exception.
- **Flaky**: run capture đầu卡 ở Scene_Login (auth chain không kịp trong budget 900-frame của `PlayCaptureDriver`) dù server đã trả register 200 → chạy lại là qua. Không phải regression — cùng code run 2 chạy sạch.

### Gotchas
- `WorldPanel.cs` có `using System.Diagnostics` → `Debug.Log` ambiguous (CS0104) → viết `UnityEngine.Debug.Log` (lần này không phải System.Diagnostics; lần trước là ngược — check file nào đang dùng).

### Deferred / open từ slice này
- Đuôi layout popup-package trong `Reload` (FindAll `gm+0x120` shop-item lists + `UILayoutGenerator.GenerateLayout(_popupPackageButtonPrefab, _popupPackageButtonsRoot, count, cb)`) — cần ResourceShopItem family → S4c.
- `GetShowBankButtonBadge()` body thật (FindAll 2 list shop items, cùng family) — stub `return false` ≈ máy khi shop data vắng.
- `ConditionalBase.SetValue(int)` = stub `{}` (visual only — ConditionalGroup không update state) — port body ValueColorPair/ValueSpritePair khi làm conditional family.
- `bankButton.SetActive(false)` **không điều kiện** đúng như máy (nút bank retire; badge GO `Badge` riêng vẫn nhận trạng thái) — đừng "sửa" thành có điều kiện.

## 44. Unity rebuild — S4b+ part 2: Deck/Shop/Clan Init slices (2026-10-17)

Ba panel Init port + gate xanh. DeckPanel làm ở session trước (chưa ghi), ShopPanel là slice lớn nhất (decode batch29/30/31 + ASM), ClanPanel nhỏ và gọn.

### DeckPanel.Init (RVA 0x32ACC0C — v174)
Singleton → dev-mode/offline guard (`Constants.DEVELOPMENT_MODE && GameManager.Get().offlineMode → return`) → `Reload(reloadUnitPage: true)` → `ReloadArtifacts(false, false)` → `ReloadRiftWeaponUI()` → `BarrackAltarBox.Instance.Reload()` (null → abort, `inited` giữ false = máy NRE-fallthrough) → `deckSlotToggle.Init(true)` + `_onExtended = OnDeckSlotExtended` → KGWiki level-gate (`CheckLevelAvailable(Get(LevelLimit_KGWiki))`, không qua → `inited=true; return`) → `Scene_Lobby.Instance.kgWikiPanel.FetchKGWiki(no-op cb)` → `inited = true`. Callback delegate cell không phân giải được → no-op `delegate { }` có comment (wiki data server chưa serve). Tiền lệ cross-class: `DeckSlotToggle._onExtended` đổi `internal`.

### ShopPanel (Init ELF 0x340EE1C, file 0x340AE1C; port ~10 methods)
File export **không có bất kỳ compiler-generated member nào** → mọi lambda được đặt tên người: `OnMainTabClicked` (b__1/`<Init>b__138_1`), `OnPackageTabClicked` (b__2), `OnSpecialTabClicked` (b__4), `OnTabLayoutNextFrame` (b__169_2), predicate `x => x.IsActive()` inline.

| Method | Nội dung |
|---|---|
| `Init` | dev/offline guard → singleton → `!readyToReload` → `Subscribe(CardExp/CardLevelUp, OnCardDataChanged)` (cell 06a85fe8 = paramless void, KHÔNG phân giải được → no-op placeholder) → `_callback` wiring 3 TabManager (method group) → `maxHolidayCount = holidayPackageAreas.Length` → `specialTabManager.OnClick(1)` → `unitBundlePackages.All(x => !x.IsActive())` → hide toggle + OnClick(1) → `!HasActiveSpecialPackage()` → OnClick(0) → idx = `maxHolidayCount; (idx<1 → 0) | (eventPackageItems.Count>0 → idx++)` → `packageTabManager.OnClick(idx)` → `moneyTabManager._callback = ReloadMoney; OnClick(0)` → `SetActive(tabs[2], CheckLevelAvailable(Get(LevelLimit_Hero_PickUp=61)))` → `Reload(true)` → tail `ReloadShopTabEnable()` |
| `OnMainTabClicked(int)` | `idx==5 → goldFreeBadge.SetActive(false)` (Utility ext, Image); `4 → dailyNewBadge`; `3 → packageTabNewBadge` (GameObject) → 9 `anchoredPosition = Vector2.zero` đúng thứ tự: recommendScroll, subscribeScroll, eventPackageArea, `holidayPackageAreas.ForEach(zero)` (b__138_5), unitBundlePackageArea, specialPackageArea, playerPackageArea, dailyArea, moneyScroll → `Reload(false)` |
| `OnPackageTabClicked(int)` | recompute `maxHolidayCount` locally (displayClass field máy; array bất biến → tương đương): `idx < m || idx == m+1 → ReloadEventPackage()`; `idx == m → ReloadPlayerPackage()`; còn lại return. Quirk +1 = trang event cuối cùng nằm SAU trang player |
| `OnSpecialTabClicked(int)` | `0 → ReloadUnitBundlePackage(); 1 → ReloadSpecialPackage()` → tail **unconditional** `ReloadShopSubtabEnable(type)` — type = static cell 0x69538c8 (encoded handle, KHÔNG phân giải được; callee compare đầu `type == <same>` always-true) → port `ReloadShopSubtabEnable(null)` + TODO comment, callee còn stub nên inert |
| `ReloadShopTabEnable` | 3 badge `transform.SetParent(enabledTabs[3/4/5], false)` → 4 tab actives: tabs[0] = `recommendationCarouselView.DataCount < 2 ? recommendPackageItems.Count > 0 : true`; tabs[1] = `unitBundlePackages.Any(IsActive) || HasActiveSpecialPackage()`; tabs[2] = `subscribePackages.Any(IsActive)`; tabs[3] = `CheckLevelAvailable(Get(LevelLimit_PackageShop=65))` → `ForceRebuildLayoutImmediate(tabManager.transform as RectTransform)` → `Observable.NextFrame().Subscribe(OnTabLayoutNextFrame)` (UniRx; `Unit` phải viết **`UniRx.Unit` đầy đủ** — global `Unit` (hero) thắng simple-name lookup) |
| `OnTabLayoutNextFrame(UniRx.Unit)` | loop `i < enabledTabs.Count`: **copy LẠC hướng** — `enabled[i].position = new Vector3(disabled[i].position.x, enabled[i].position.y, 0f)` (ASM: v8 chỉ lưu x của get#1, s1 = y của get#2, `fmov s2,wzr` → z=0) và `enabled[i].sizeDelta = new Vector2(disabled[i].rect.width, enabled[i].rect.height)` (v8=v2/width get#1, v1←v3/height get#2) → 2× `SetParent(enabledTabs[0].parent, false)` (packageTabNewBadge, dailyNewBadge) + 1× một-arg `SetParent(enabledTabs[0].parent)` = default **true** (goldFreeBadge, method-pointer thunk truyền `1`) |
| `HasActiveSpecialPackage` | `specialPackages.Exists(x => x.IsActive()) \|\| _skinBundlePackageItems.FindIndex(0, Count, x => x.IsActive()) != -1` (b__148_0/1 + b__169_0/1 đều = `x => x.IsActive()` — tail-call `Utility$$IsActive`, ASM xác nhận) |
| forwarders | `RecommendActive() = ReloadRecommendPackage(); SubscribeTabActive() = ReloadSubscribePackage();` — **mỗi cái đúng 1 instr `b` tail-jump** (quyết định cũ ghi "empty" là SAI — đã sửa). `SpecialTabActive`/`PackageTabActive` stub + decode pointer trong comment |

- `TabManager._callback` → `internal`; field init `_skinBundlePackageItems`/`_skinBundlePackageItemPrefabNames` = `new()` (máy init trong .ctor, export .ctor rỗng); `using System.Linq` + `using UniRx` thêm vào file.
- **Gate NRE thật + fix**: `ReloadShopTabEnable` NRE ở `recommendPackageItems.Count` — field **không nằm trong YAML scene** của APK (Unity bỏ qua list null khi serialize; máy gốc invariant do `Reload(true)` → `ReloadRecommendPackage()` build list TRƯỚC khiReloadShopTabEnable chạy) — slice này Reload là stub → thêm guard `recommendPackageItems != null &&` + comment gỡ khi ReloadRecommendPackage port.
- **Defer đã ghi trong comment**: Reload body (cấu trúc đã decode: `!readyToReload return; isReloaded=true;` + dispatch 6 tab theo IsActive, moneyTab inline arm offerwall/instantiate), ReloadMoney body, ReloadShopSubtabEnable body (cần resolve string cell 0x69538c8/0x69817e0 — raw encoded handles trong .data struct 0x6BB1E10/0x6BACB60, KHÔNG burn thêm time), OnCardDataChanged body.

### ClanPanel.Init (ELF 0x32338B0)
`clan == null → return` → `clan.id < 1 → return` → foreach `clan.members`: `member.accountId == GameManager.Get().data.model.accountId` → match thì break, hết list → return (machine: MoveNext-false → Dispose+return) → tail `GameManager.Get().isDevTestClanRaid = false` + `Scene_Lobby.Instance.FetchClanRaid()` (async void, state machine còn stub → no-op, gate-safe). Field map: `GameManager.clan` = k__BackingField @0x310 (property `clan`), `data` @0x118, `PlayerData.model` @0xC0, `PlayerDataResponseModel.accountId` @0x2C, `ClanModel.id` @0x10 / `members` @0x80, `ClanMemberModel.accountId` @0x10. Gán value: ASM `mov w0,wzr` → `op_Implicit(false)`; **+0xC8 = `isDevTestClanRaid`, KHÔNG phải `clanRaidEnabled`** (@0x60 đọc nhầm sẽ sai ngữ nghĩa).

### Verification
- 3 vòng gate: compile GREEN ×3 (0 error, chỉ CS0169 quen thuộc) + play-capture GREEN (1 vòng fail NRE → fix guard → 2 vòng sạch, `shot_Scene_Lobby.png` render bình thường, **0 exception**).

### Gotchas mới
- **CaptureScene KHÔNG tự tạo thư mục output**: `rm -rf` trước run → `capture fail: Could not find a part of the path .../shot_Scene_Lobby.png` (exit 2). luôn `mkdir -p $KGC_CAPTURE_DIR`.
- **dump.cs v174 có offset field trong comment** (`public int id; // 0x10`) — cho tên + offset trực tiếp, không cần scan getter qua capstone nữa (vẫn cần ASM cho giá trị hằng/số chiều cột như `mov w0,wzr`).
- Ghidra decompiler **inline tail call** vẫn là law xuyên suốt slice này: Init ShopPanel chứa nguyên thân ReloadShopTabEnable; b__1 tail chứa structure Reload; luôn đối chiếu script.json lấy extent thật.
- Method-pointer thunk (`FUN_02c5690c`/`get-method-pointer-by-name`) truyền `worldPositionStays=1` ở lệnh SetParent thứ 3 trong OnTabLayoutNextFrame — đừng "đồng bộ hoá" 3 lệnh thành cùng một overload.

### Deferred / open từ slice này
- Reload body + mọi `Reload*Package`/`ReloadDaily`/`ReloadMoney`/`ReloadShopSubtabEnable`/`SpecialTabActive`/`PackageTabActive` — decode pointer đã nằm trong comment code từng method.
- `OnCardDataChanged` body (cell 06a85fe8 không phân giải).
- `TabManager.OnClick` port (slice riêng); b__0 wiring ShopPanel; ClanPanel các method còn lại (PreInit/OnClickClanTab/Reload/OnPanelEnabled...).

## 45. Unity rebuild — S4b+ part 3: Awake fetch-chain completion (2026-10-17)

### Scope
Hoàn tất "batch A" của S4b+ part 3: `_isLobbyAlive` thật, port 9 `Fetch*` còn thiếu của
`Scene_Lobby` + toàn bộ `GameManager.Handle*` bodies tương ứng, kéo dài `Scene_Lobby.Init`
chain từ 9 → 17 bước (SeasonPass → ArtifactInventory → Clan → ClanRaid → Babel → Challenge →
DailyAttendanceEvents → SeasonPassEventBooster → [gated] EventCardCollecting). Decode nguồn:
Ghidra batch32 (`0x3164578` HandleClan 7-param, `0x3146338` HandleClanRaid, `0x3185CBC`
HandleChallengeMode, `0x315426C` HandleEventModeResponse, `0x3163198/0x31639F8` SeasonPass/
EventCard) + batch33 (`0x3164458` HandleClan(ClanResponseModel), `0x3145E1C` HandlePlayerBabel,
`0x3154460` HandleArtifactInventory) + MoveNext của từng fetch.

### Ported
- `Scene_Lobby._isLobbyAlive` (`0x3626774`): `this != null && Instance == this && main != null`
  (trước: `=> false` — mọi fetch guard sẽ chết nếu bỏ sót).
- Fetch ports (mẫu callback `Web.Get<T>(path, token, false, r => {…; onDone?.Invoke();})`,
  attribute `[AsyncStateMachine]` giữ nguyên theo precedent FetchShop):
  - `FetchSeasonPass` (GET `/pass`): guard `isLobbyAlive` → `_fetchNextSeason=false` → Handle
    + `ReloadPassGauge(true)` + `ReloadHeart` + `ShopPanel.Reload` +
    `themeSelectPanel.ReloadStartButtonAndFoodBooster` (máy d__239 @0x363F364).
  - `FetchSeasonPassEventBooster` (`/pass/passEventBooster`), `FetchClan` (`/clan`),
    `FetchClanRaid` (`/clan/raid`, success-only, KHÔNG isLobbyAlive), `FetchBabel` (`/babel`),
    `FetchChallenge` (`/story-mode/challenge/info`), `FetchEventMode` (`/game/eventMode`,
    `reloadUI` → `SwitchMode(true,true,true)` — máy truyền x1=x2=x3=1, x4 junk 0),
    `FetchArtifactInventory` (`/artifact/inventory`), `FetchPlayerEventCardCollecting`
    (`/event-card-collecting/fetch`).
  - `FetchClan` tail: `ClanPanel.Instance.inited` → `Reload` + `clanChatPanel.ReloadChat(r.clan.chats)`;
    member popup luôn gọi `Reload(members, joined, maxMemberCount, roleNames)` với
    `joined = r.clan.id == gm.clan.id && Constants.ClanRole.Check(gm.clanRole, Member)` —
    KHÔNG gộp joined vào gate (máy gọi cả khi joined=false).
  - `FetchDailyAttendanceEvents`: `r.eventIds.Count>0` (null → NRE tự nhiên như máy) →
    `dailyAttendanceEventsData = r` → chọn `WorldPanel.Instance ?? this.worldPanel` →
    `StartCoroutine(AfterFetchDailyAttendance(r))` — stub-gap guard `co != null` (stub trả null).
- `GameManager.Handle*` bodies:
  - `HandleClan(ClanResponseModel)` (`0x3164458`): null → NRE tự nhiên;
    `!IsNullOrEmpty(seasonUntilAtDate)` (field +0x50, KHÔNG phải field clan-raid — faithful)
    → set `clanRaidEnabled` + parse 2 date → ủy quyền overload 7-param
    (param_7 `clanRaidLockedByLeaveUntilAt_` máy truyền nhưng **không store** — discard).
  - `HandleClan` 7-param (`0x3164578`): stores clan@0x310/role/clanRequestSupportCooltime/
    canReceiveClanPointAt/canPlayClanRaidAt → `ClanPanel.Instance.clanChatPanel` active →
    `ReloadButtons()` → `BottomPanel.Instance.Reload()`.
  - `HandleClanRaid` (`0x3146338`): `_clanRaid = model` + `ShootCallback(ClanRaid)` (máy inline
    loop `_callbacks` Item1==0x16 — chính là ShootCallback).
  - `HandleChallengeMode` (`0x3185CBC`): null/fail → return; store; difficulty: bestCleared≥1 →
    best+1 cap 24→25; else unlocked: `<6` giữ; ≥6 & `data.bestClearedHardTheme<61` giữ;
    theme≥61 & diff<11 giữ; theme≥61 & diff≥11 & pass gate `CheckLevelAvailable(
    ResourceConstant.Get(Type.LevelLimit_DimensionRift=70))` → giữ + cap 25; fail gate → 6.
    `data` null khi diff≥6 → NRE (máy invariant: player data load trước).
  - `HandleEventModeResponse` (`0x315426C`): `openEventModes = model.eventModes` (ref copy);
    `eventModesFlagCost` lazy-init (export thiếu field initializer, máy init cctor) → Clear →
    fill song song `allEventModes[i]`/`eventModeFlagCost[i]`.
  - `HandleEventCardCollecting` (`0x31639F8`): null → store model rỗng; lazy-init
    `collectionStates`/`eventCardCounts`; store; `WorldPanel.Instance` active →
    `ReloadEventCardCollectingButton()`.
  - `HandleSeasonPass`/`HandleSeasonPassEventBooster`: store `passModel`/`passEventBoosterModel`
    (render tail SeasonPassPanel defer slice panel).
  - `HandlePlayerBabel` (`0x3145E1C`): `babelBarrack = new` + store + `ShootCallback(Babel)`.
  - `HandleArtifactInventory` (`0x3154460`): inventory cũ còn & ret rỗng
    (`artifacts.Count==0 && dustCount==0`) → return giữ bản cũ; store;
    `SetEquippedArtifactPreset(data.currentDeckPreset)` (data+0x7C, KHÔNG phải presetIdx mới);
    `!handlePlayerCurrencies` → ShootCallback(Artifact) sớm; else sync
    `SetGold/SetCash(response, "", "", true)` khi value ≥0 và khác current
    (`AwesomeInt.v` property) rồi callback. Literal productId = metadata pool không đọc được
    (0x6A4FC70→0x13CE0AC) → dùng `""`, chỉ ảnh hưởng analytics log.
- `ClanResponseModel`: 8 getter `*_` `=> default` → `DateTime.TryParse(src, out var d) ? d : default`.

### Gates
- Compile GREEN (exit=0, 0 `error CS`); play-capture GREEN (`shot_Scene_Login.png`,
  **0 exception** — fetch chain mới không bắn NRE trong scene-capture scope).

### Gotchas mới
- **`Constants.ClanRole`/`ClanRoleEnum` lồng trong `abstract class Constants`** — tên trần
  `ClanRole.Check` fail CS0103; `ResourceConstant` thì global-namespace tên trần OK. Đừng
  generalize "Constants.cs không namespace" → check nesting từng class.
- **Lambda chain 17 bước**: đóng đúng `}` + 17 `)` + `;` — sai 2 ngoặc là CS1026/CS1002 row
  line đó; đếm số fetch mở ngoặc = số `)` cần.
- **Resolve PTR_DAT literal qua `.rela.dyn`**: `readelf -rW | grep <addr>` → `R_AARCH64_RELATIVE`
  addend → VMA đích; method ptrs resolve được qua `script.json ScriptMethod` (Scene_Game
  `<Init>b__511_0/1` = enqueue Action targets), nhưng string literals v174 nằm encoded trong
  metadata pool → không đọc ASCII trực tiếp từ `.so`.
- Machine `HandleClan(7-param)` BottomPanel-block dùng `ClanPanel.Instance.clanChatPanel`
  (@0x68 trên ClanPanel), KHÔNG phải field nào của BottomPanel (BottomPanel+0x68 = `dustEffect`
  — đọc nhầm class sẽ ra type mismatch vô nghĩa).

### Deferred / open
- HandleClan prefs block (HasKey + SetInt clan-id + SetString supportCompleted + Save) +
  3 popupQueue enqueue (Localizer literals 0x6A76FF0/FF8/000, cached Action từ Scene_Game
  `<Init>b__511_0/1`) — cần port `HandlePopupAndEvents`/`ShowFromPopupQueue` trước.
- HandleSeasonPass SeasonPassPanel render tail; HandleEventCardCollecting button tail;
  HandleClan(2-param) wrapper.
- FetchYearEvent / FetchSurpriseAttendanceEvent / FetchShopEventCumulativePurchase
  (b__257_0 season-chain-only), FetchSingleArenaRewardInfo (no server route),
  FetchCard / FetchPlayerDailyConsumedCurrencies, HandlePopupAndEvents/ShowFromPopupQueue.

## §46 — S4b+ part 4: popup-queue plumbing + HandleClan prefs/enqueue + ShopEventCumul store (2026-10-18)

### Resolve literal string v174 (recipe tái sử dụng — chốt sai 1 lần mới ra)
Sai lầm tốn kém: `PTR_DAT_06xxxxxx` trong Ghidra là **ELF VMA + 0x100000**. `grep readelf` bằng
địa chỉ Ghidra → đọc nhầm slot hoàn toàn (ra toàn method-ptr/code bytes). Slot thật = Ghidra − 0x100000.

Đúng (2-hop indirection):
1. `slot_elf = ghidra_ptr − 0x100000`.
2. `readelf -rW libil2cpp_v17400.so | grep <slot_elf>` → `R_AARCH64_RELATIVE` **addend**.
3. Addend đó **không** chứa bytes string — nó là **địa chỉ của một slot khác** nằm trong bảng
   `stringliteral.json`/`ScriptString` (dải `0x6b94ea0–0x6bc7e40`). Lookup `stringliteral.json` theo
   `address == addend` → `value`. (Il2CppDumper chỉ map bảng slot này; slot code dùng delegate/literal
   `0x69xxxxxx` trỏ vào nó → hop 2.)
4. Method-ptr slots (delegate cache, vd `0x6b88478/0x6b88480`) **không có reloc tĩnh** (il2cpp init
   điền runtime) → không resolve được target bằng tĩnh; suy ra từ `script.json ScriptMethod` nearby.

Literal đã resolve (slot → value):
| ELF slot | value | dùng ở |
|---|---|---|
| 0x6976FF8 / 0x6977000 / 0x6976FF0 | `Clan_Alert_Joined` / `Clan_Alert_LeaveDelete` / `Clan_Alert_NameBanned` | HandleClan enqueue |
| 0x6977008 / 0x6977010 | `LastClanID` / `LastClanSupportCompletedModel` | HandleClan prefs |
| 0x69920C8 / 0x697D2C0 | `Colosseum_Left_Popup` (StartsWith) / `_Ignored` (EndsWith) | ShowFromPopupQueue routing |
| 0x6991F20 / 0x6991F28 / 0x6964070 | `RogueLikeSaveWarning` / `CantReloadNextSeason` / `RogueLike` | HandlePopupAndEvents part2 (defer) |
| 0x694FC70 | `""` | SetGold/SetCash productId (xác nhận đoán trước) |

Class-gate slots: `PTR_DAT_06a51bf0` → `Scene_Lobby_TypeInfo` (check `is Scene_Lobby`). Fields:
`Scene_Base.popup@0x68` / `popup2@0x70` (kế thừa Scene_Lobby); `Scene_Lobby.tabManager@0x158` /
`outgameTutorialPanel@0x160`; `GameManager.currentScene@0x148` / `popupQueue@0x230` /
`resShopEventCumulativePurchaseData@0x408` / `pvpData@0x220`.

### Ported (gate: compile GREEN 0 `error CS` + play-capture 0 exception, `shot_Scene_Lobby.png`)
- `GameManager.HandleClan(2-param)` @0x3164C10 → ủy quyền 7-param (`default` dates/model).
- `GameManager.HandleClan` 7-param @0x3164578 → điền prefs block + 3 enqueue:
  `HasKey("LastClanID") && !(currentScene is Scene_Lobby)` → `GetInt(-1)`; join (`clan!=null && prevId==0
  && clan.id>=1 && Check(role,Member)`) → enqueue `Clan_Alert_Joined`; leave (`prevId!=0 && (clan==null||
  clan.id==0)`) → `Clan_Alert_LeaveDelete`. tail: `Check(Member)→SetInt(clanIdKey, clan?.id:0)`;
  `clan==null||id==0→SetInt(0)`; `supportCompleted!=null&&supportCompleted→SetString(JsonUtility.ToJson)`;
  `Save`; `BottomPanel.Reload`; namebanned (`clan!=null && nameBanned && Check(Master) && !is-Scene_Lobby`)
  → enqueue `Clan_Alert_NameBanned`. **Tất cả enqueue `action=null`** (defer ack body `b__439_0` = mở tab
  clan / `b__439_1` = 247 dòng). Inert: `Constants.ClanRole.Check` là stub `{return false;}` + gate not-in-lobby.
- `GameManager.HandleShopEventCumulativePurchase` @0x316DDB8 → `resShopEventCumulativePurchaseData = ret`.
- `Scene_Lobby.ShowFromPopupQueue` @0x3631F5C → full: `item=q[0]`; `StartsWith("Colosseum_Left_Popup") &&
  EndsWith("_Ignored")` → `colosseumLeftAlertPopup.Show(key)` (property hiện `=>null` → NRE fallthrough =
  faithful, defer wiring); else `popup.Show(key.L(), Popup.Type.Ok, item.action)`; `q.RemoveAt(0)`.
- `Scene_Lobby.HandlePopupAndEvents` @0x362C8B0 → part1 drain (`Count>0 → ShowFromPopupQueue`, 1 popup/lần).

### Deferred (decode pointer)
- **HandlePopupAndEvents part2** (pvp season-end popup): prefs `RogueLikeSaveWarning` GetString→Parse,
  `pvpData.GetCurrentSeasonUntilAt`, `(until.Day−Now.Day)<4 && lastShown.Day!=Now.Day` → `popup2.Show(
  Format("CantReloadNextSeason","RogueLike"))` + `SetString(Now.ToString(InvariantCulture))`; **gate
  `gm+0x4c8.@0x98` chưa resolve** (`// 0x4c8` không có trong dump.cs GameManager block).
- **HandlePopupAndEvents part3** (outgame tutorial): `outgameTutorialPanel(+0x160).StartTutorial(30,
  GetKeyValueBool(static key 0x6A68AB8+0x68), cached Action 0x6A91F18)` — cần resolve static key + Action.
- **HandleClan ack bodies** `b__439_0` (0x318b2a8, mở tab clan: TabManager.OnClick(tab,3)+clanMenuPanel
  vtable 0x188) / `b__439_1` (0x318b200, 247 dòng) → enqueue với action null.
- **colosseumLeftAlertPopup wiring**: property `=>null`, cần nối ref prefab.

### Gotcha
`Constants.ClanRole.Check(int, ClanRoleEnum)` là **stub `{return false;}`** (dead-gate OK) — enqueue shape
đúng, sẽ fire thật khi Check implement. `ClanRoleEnum`/`ClanRole` đều nested trong `abstract class Constants`.

## §47 — S2 Tier-2: event-fetch surface (4 callback fetch + store-only Handles) (2026-10-18)

Hoàn tất netcode tier S2: port 4 `Fetch*` event của `Scene_Lobby` (UniTask → callback, parameterless
giống export) + 2 `Handle*` store-only. **Unwired** — season chain `Scene_Lobby.<Update>b__257_0`
(@0x36350D4) chưa port, và các event bị patch-off (`IsYearEventAvailable`→false …) — nên đây là
**surface netcode** để wiring sau này chỉ cần nối chain, không phải viết fetch. Endpoint/model lấy
từ `route_models.json` (score ≥1.0), KHÔNG decode path literal.

| Fetch (Scene_Lobby) | endpoint | model | Handle | máy MoveNext |
|---|---|---|---|---|
| `FetchYearEvent()` | `player/year-event` | `FifthHalfYearEventResponseModel` | `gm.HandleYearEvent(r)` | d__241 @0x3641C64 |
| `FetchSurpriseAttendanceEvent()` | `player/surprise-attendance-event` | `SurpriseAttendanceEventResponseModel` | `gm.HandleSurpriseAttendanceEvent(r)` | d__242 @0x36410E4 |
| `FetchShopEvent()` | `shop-event/cumulative-purchase` | `ShopEventCumulativePurchaseResponseModel` | `gm.HandleShopEventCumulativePurchase(r)` | d__255 @0x364080C |
| `FetchPlayerDailyConsumedCurrencies()` | `player/daily-consumed-currencies` | `PlayerCurrenciesResponseModel` | `gm.HandlePlayerDailyConsumedCurrencies(r)` | d__226 @0x363DDF4 |

Gate callback: YearEvent/Surprise = `r!=null && _isLobbyAlive && r.isSuccess`; ShopEvent/DailyConsumed =
`r!=null && r.isSuccess` (máy không có isLobbyAlive ở 2 cái này). `FetchShopEvent` (d__255) **inline store**
`gm.resShopEventCumulativePurchaseData` (@+0x408) chứ không gọi Handle → gọi `HandleShopEventCumulativePurchase`
(store cùng chỗ @0x316DDB8) cho gọn.

**Handles**:
- `HandleYearEvent(ret)` → `fifthHalfYearEventModel = ret` (@GameManager+0x2E8). Monster tail **427 dòng**
  deferred (refresh `FifthHalfYearEventPanel` + attendance/pass reward UI).
- `HandleSurpriseAttendanceEvent(ret)` → `surpriseAttendanceEventModel = ret` (@+0x2F0). Monster tail
  **366 dòng** deferred (refresh surprise-attendance panel).
- `HandleShopEventCumulativePurchase(ret)` → store `resShopEventCumulativePurchaseData` (@+0x408) — **đã port §46**.
- `HandlePlayerDailyConsumedCurrencies(ret)` → **deferred body**. Máy @0x315241C mutate `List<KeyValue>` tại
  `playerData(@+0x118)+0xb8`: find-or-add theo **static-key @0x6A68AB8+0x110** (chưa resolve), value =
  `ret.@0x34.ToString()` (int field @0x34 của `PlayerCurrenciesResponseModel`). Cosmetic (currency-usage tracker).

**Deferred**: `FetchCard(int)` (d__252 @0x363AD28 → `RestAPI.GetCard(cardID)` → `UpdateOrAddCards`) — **unwired,
không có caller**, cần decode endpoint `GetCard` trước. `HandleYearEvent`/`HandleSurpriseAttendanceEvent`
monster tails store-only decode pointers ở trên.

**Gate**: compile GREEN (smoke `ResourceUnit 1043 rows 'Shelda'` / `ResourceInventoryItem 173 rows`, 0 `error CS`)
+ play-capture **0 exception** (`shot_Scene_Lobby.png` 286KB, vào lobby thật).

### Gotcha
Các `Fetch*` event này **không có trong Init chain 17 bước** — chúng do season chain (`b__257_0`) fire khi
phát hiện đổi mùa/event. Port xong = netcode surface đầy đủ; wiring đòi hỏi port `Scene_Lobby.Update` +
`b__257_0` (S4 event-panel tier).

## §48 — S3a: lobby → Scene_Game entry (battle transition) (2026-10-18)

**Chain (v174.0.00, trace by subagent — scan-based hunts FAILED trước đó):**
```
WorldPanel.GameStart (void, d__396 @0x35e1568)
  → build GameStartRequestModel → RestAPI.<GameStart>d__53 @0x2d6fcfc = Web.Post<GameStartResponseModel>("/game/start")
  → success: Scene_Base.ShowLoading(false), CloseGameStartPopup, ConsumeHeart(resp+0x2C heart),
    gm.currentGameId(0x1C8) = resp.gameId(0x48), SetSeasonalEventModePlayCount, SetFlag(resp+0x50 eventFlag),
    ReloadPlayCounts, gm.rankingStageUnits(0x1D8) = resp.rankingStageUnits(0x58), HandleCardListResponse(resp.cards@0x40)
  → WorkTimer.Do(0.5f, WorldPanel.<>c.<GameStart>b__396_1 @0x35dcd00)   // matchmaking guard + fade canvas + UnitStarGameDirection
    → WorkTimer.Do(0.5f, Scene_Lobby.<>c.<StartGame>b__222_1 @0x36363a0) // THE load site: tail-call
      → GameManager.LoadSceneAsync(gm, "Scene_Game", LoadSceneMode.Single) @0x3171d38
        → HandleSceneChanging(gm, "Scene_Game", 0) fires dict gm+0x158 handleSceneChanging
        → SceneManagerAPI.LoadSceneAsyncNameIndexInternal("Scene_Game")
```
- `SimpleStartGame` (d__434) + `StartEventMode` (d__438) **cùng funnel vào `b__222_1`** (mỗi cái có lambda `b__X_1` của nó, 0.5s delay → `b__222_1`).
- **`GameManager.LoadScene` wrapper (@0x3171b78, 20 caller) KHÔNG nằm trên đường này** — 20 caller toàn game-over→lobby exit (GameOverPanel.OnClickClose, RogueLikeSaveAndLobby, SettingsPanel.OnClickLogout…). Hai caller inline state machine của nó: `WorldPanel.LoadTerritoryScene` (→ "Scene_Territory", Additive) + `Scene_Lobby.<CheckLastGameCompleteRequest>b__259_0` (→ "Scene_Login").
- **Scene_Loading chỉ là chiều RA** (exit Scene_Game→Lobby): `GameManager.<LoadScene>d__566 @0x31d5d44` rewrite target → "Scene_Loading" (lưu target thật vào static của Scene_Loading); `Scene_Loading.Start @0x36265dc` load target thật + run callback. **Vào Scene_Game không đụng Scene_Loading.**
- String `"Scene_Game"` literal @ stringliteral 0x6BB0390, String* reloc slot @ ELF 0x6966938 (R_AARCH64_RELATIVE addend 0x6BB0390). **Direct ADRP+ADD/LDR scan → 0 hit** (page data đông: 7249 ADRP landing on page) — đừng scan kiểu này again; trace từ method chain nhanh hơn.
- `WorldPanel.StartSingleArena(targetDeck)` build req `+0x20 = targetDeck` → start `StartEventMode_d__438` state machine (dùng chung generic start).

**Server contract (`r_game_start`, game_routes.py:39):** chỉ đọc `theme` + `stage` (deck/buildings BỊ BỎ — battle chạy client-side hoàn toàn). Deduct heart, mint `gameId` (secrets.token_hex(8) → `_game_store`), trả `{heart, lastHeartTime, buildingData, cards, gameId, eventFlag}`. **Response KHÔNG có theme/stage** → client tự giữ selection.

**gm field offsets (v174):** `currentTheme` @0x144 (GameManager proper, export L2720); `currentGameId` @0x1C8 (export L2754); `rankingStageUnits` @0x1D8 (export L2764); `handleSceneChanging` dict @0x158 (export L2726); `currentStage` @0x18 **thuộc `GameManager.BabelState`** (dump 77512/77517) — **KHÔNG phải GameManager**, `gm.currentStage` không tồn tại → stage plumbing cho InitStage để ở S3b.

**Ported (compile GREEN 0 error, runtime test lùi sang S3b khi Scene_Game init xong):**
- `WorldPanel.GameStart()` → callback tối giản: set `gm.currentTheme` (fallback 1 — stage-select chưa port), `Web.Post<GameStartResponseModel>("game/start", JsonUtility.ToJson(req), …)` → apply `currentGameId`/`rankingStageUnits`/`HandleCardListResponse(cards)` → `WorkTimer.Do(0.5f)` → `gm.LoadSceneAsync("Scene_Game", Single)`. Deferred: deck/artifact request-build (server bỏ), pre-check popup, animation chain. Chú ý: `Awesomepiece.Web`/`RestAPI` phải fully-qualify (WorldPanel thiếu `using Awesomepiece;`).
- `GameManager.LoadSceneAsync` → `HandleSceneChanging` + `UnityEngine.SceneManagement.SceneManager.LoadSceneAsync`.
- `GameManager.HandleSceneChanging` → guarded TryGetValue/Invoke/Remove trên `handleSceneChanging` (hiện inert — `Add/RemoveHandleSceneChangeAction` còn stub → dict luôn rỗng; global-key fire khi Single defer do chưa resolve PTR_DAT_06a4fc70).
- `GameManager.LoadScene` (d__566, qua Scene_Loading) **chưa port** — chỉ cần cho exit; vào Scene_Game đi qua LoadSceneAsync.

## §49 — S3b: Scene_Game init — trigger mechanism + Init structure (2026-10-18)

**Câu hỏi đã giải quyết: "Ai gọi `Scene_Game.Init` khi vào trận lần đầu?"** → **`Scene_Game.Awake` → `ResourceManager.Load(callback)` (async gate) → callback → Init.** `ResourceManager.Load` là **stub `{}` trong export** → callback không bao giờ fire → battle không start (đây là root-cause "vào Scene_Game nhưng không có gì xảy ra").

**Lifecycle đã trace (v174.0.00, imagebase 0x100000, RVA):**
- `Awake` @0x2e63da8 (batch53): `Scene_Base.Awake` → `GameManager.InstantiateSimpleAssetDB` → `Screen.sleepTimeout` → `PopupManager.Clear` → `SetActive(false)` 5 GameObject field (0x298/0x2a0/0x2a8/0x2b0/0x2b8) → `Localizer.SetCanvasRoot(0x268)` → `Localizer.Initialize` → **`Action..ctor(uVar10, this, cachedPtr)` + `ResourceManager.Load(uVar10)`** → `CacheAllUnitAssets` → `ResetMergibleAlpha` → `Utility.SetScreenFirebase` → `GameManager.CheckXcd` → `Action..ctor + WorkTimer.Do(120f, …)` (Action#2, timer unrelated) → 3 `LocalizerUtility.L` so sánh → set byte flags (0x6da/0x6db/0x6dc). Awake **KHÔNG gọi Init**; phần sau `Load` chạy đồng bộ (asset setup), chỉ `Load(callback)` là async → init trigger.
- `Update` @0x2e72ea4 / `UpdateImpl` @0x2e72fa8 (batch55): **KHÔNG gọi Init/LoadGame**. Chỉ gọi `StartStage` (guarded timer `fVar26<=0`) + timer-text helpers + `BattleManager.Update`. → Init KHÔNG phải first-frame check.
- `GameManager.LoadSceneAsync` @0x3171d38 (batch52): path `Single` (param_3==0, Scene_Game dùng path này) → `HandleSceneChanging` (dispatch dict 0x158, không có Init) → `SceneManagerAPI.LoadSceneAsync` → **return, KHÔNG register completion callback**. Path Additive mới register `AsyncOperation.add_completed` — không liên quan Scene_Game.

**Init là battle-setup sequencer, 4100 dòng, mode-branching (batch53, Init @0x2e44008).** Core sequence (không-branch):
`GameManager.Init` → ~15 `LocalizerUtility.L` (string load, defer được) → `Time.maximumDeltaTime/fixedDeltaTime` → **`BattleManager.Init(idx)`** (`idx` = `List<int>.get_Item` param — deck/theme index) → `get_playerBattle` → `GameManager.GetBuildingLevels` → **`BattleManager.InitArtifactAndBuildings`** → `GameManager.GetDefaultDeck` → `GameManager.GetCardInfos` (deck → card infos; 2 nhánh clan-raid vs normal) → **`BattleManager.InitHeroPool(deck, cardInfos, …)`** → [mode branch: `InitColosseumData`/`GameManager.InitRogueLike`/`InitStoryMode`/storyModeGameData] → **`InitMap`** → InitPotentialInfos/InitObstacles → gold/building effects (`GetArtifactValueSum`) → activeSkillManager → [mode branch: **`InitStage`** @L3490] → `OpeningSequence` (chỉ 1 caller = Init @0x2e49690).
- `LoadGame` @0x2e67ef4 (1 caller = Init @0x2e488c8): gọi `InitMap` @0x2e687c8 + `InitStage` @0x2e6945c → LoadGame = "setup map+stage cho state đã cho".

**Init's 6 direct BL callers — TẤT CẢ là re-init/dev/continue, KHÔNG có first-entry:**
`RestartBabel`, `SetTheme` (dev: MainUI.OnClickDevMenu b__260_3 + DevClanRaidPanel.OnClickConfirmButton), `SetCurrentEventDifficulty` (dev), `DevRoguelikeReLoadImpl` (dev), `DevLoadDeckPanel.OnClickConfirm` (dev), `GameOverPanel.<ContinueGame>d__59.MoveNext` (continue sau game-over).

**Tại sao trigger resolve không được (runtime-mediated delegate — ĐỪNG thử lại):**
- Callback method ptr tải qua **2 deref**: `GOT 0x6966928` (R_AARCH64_RELATIVE → 0x6b7a260) → `*0x6b7a260` = **0x60002cb5**. Vùng 0x6b7a200–0x6b7a2b8 là **bảng generic-method-pointer của il2cpp** (toàn giá trị 0x6000xxxx, KHÔNG phải code address — 0x60002cb5 không 4-aligned). Không reloc AT 0x6b7a260 → giá trị do il2cpp runtime resolve, không ra được tĩnh.
- Method-pointer table `&Ready`@0x6a75f70, `&Init`@0x6a76468, `&InitMap`@0x6a76478, `&OpeningSequence`@0x6a76480, `&InitStage`@0x6a76490, `&LoadGame`@0x6a76be8 — **0 direct ADRP+LDR/ADD reference** (dispatch qua runtime delegate, base pointer gián tiếp). → "who invokes Init via delegate" = lrabbit-hole il2cpp runtime, không xử được tĩnh.

**Port decision (deviation, document rõ):** rebuild `ResourceManager.Load(callback)` sẽ **invoke callback đồng bộ** (asset local/sync trong editor), và `Scene_Game.Awake` truyền **`Init`** làm callback (suy luận: Init là sequencer duy nhất; callback gốc dẫn tới Init qua delegate gián tiếp — không show direct BL). Awake ported faithful phần asset setup (base.Awake + InstantiateSimpleAssetDB + PopupManager.Clear + Localizer init + CacheAllUnitAssets); defer 5-GameObject toggles (cần map field-offset 0x298…→tên export), SetScreenFirebase/CheckXcd/WorkTimer.

**S3b port plan (Init core — bước tiếp theo, LỚN, nhiều session):** port Init path tối giản cho arena/story: `GameManager.Init`, `BattleManager.Init(idx)`, `InitArtifactAndBuildings`, `GetDefaultDeck`/`GetCardInfos`, `InitHeroPool`, `InitMap`, `InitStage` (bỏ non-arena mode branches: colosseum/roguelike/clanraid/babel). BattleManager.Init/InitHeroPool + InitMap/InitStage cần decompile riêng (chưa có trong batch).

## §50 — S3b: Scene_Game.Init core port (arena sequencer) (2026-10-19)

**Mục tiêu slice:** port khung `Scene_Game.Init` + `InitMap` + `InitStage` + `OpeningSequence` + `GameManager.Init` + grid/map plumbing để `Awake → Init` hoàn tất mà không throw. **Cổng xanh: compile gate GREEN (0 lỗi CS) + play-capture GREEN (0 exception, `shot_Scene_Lobby.png` 287KB).** Lưu ý: capture harness chỉ chơi scene được mở sẵn → **đường `Scene_Game.Init` CHƯA được exercise runtime**; gate runtime thật là S3e (end-to-end battle).

### RVAs đã decompile & port ở slice này

| Method | RVA | Bản chất đã extract |
|---|---|---|
| `Scene_Game.Init` | `0x2e44008` | sequencer (xem dưới) |
| `Scene_Game.InitMap` | `0x2e66e18` | theme/map-skin resolve + `bm.HandleInitMap` loop |
| `Scene_Game.InitStage` | `0x2e4acd0` | BeforeInitStage → reset flags → ClearEnemies/FieldUnits → `effectPool.Clear` → mode branch → `AfterInitStage` |
| `Scene_Game.OpeningSequence` | `0x2e6a2dc` | DOTween camera/alpha Sequence + `_opening` |
| `Scene_Game.GetDefaultFlagPrefab` | `0x2e6b008` | `return defaultFlagPrefab` (field `0x270`) |
| `Scene_Game.LocalToBattlePosition` | `0x2e5dd0c` | **`pos.x += battleIdx * 1000f; return pos;`** (toàn thân chỉ 1 phép tính, y/z giữ nguyên) |
| `Scene_Game.BattleToLocalPosition` | `0x2e5dd20` | phép nghịch đảo (chưa decompile riêng — suy từ cặp gọi) |
| `Scene_Game.<Init>b__511_0` | `0x2ea7df8` | **`s => s.theme == _theme.v`** — predicate của `ResourceStage.GetAll` |
| `Scene_Game.InitPvPPresetStage` / `InitRankedPvPStage` / `InitClanRaidStage` | `0x2e6cc88` / `0x2e6eed4` / `0x2e4bdf8` | defer (mode PvP) |
| `GameManager.Init` | `0x3148d1c` | `if (_inited) return;` → `data=new PlayerData` → `LoadSetting` → `isEarlyAccessMode=false` → `CheckFirebase` → subscribe `Application.lowMemory`+`quitting` → `_inited=true` → LocalPushManager instantiate |
| `UnitGrid.Init(BattleManager, Color)` | `0x2fa1f7c` | default-color fallback → `_defaultColor` → `Init(size+bonusSize)` → `ClearFocus()` → `battle=bm` |
| `UnitGrid.Init(int,int)` | `0x2fa2060` | `_lastSize` cache → `_width/_height` → `AddTile(x,y)` nested loop |
| `GridMap..ctor(bm,w,h)` | `0x2f791f4` | `_minPos/_maxPos` formula + 5 mảng + 2 HashSet + 4 Queue + 2 List + 1 PriorityQueue |
| `BattleManager.HandleInitMap` | `0x2edae38` | `_resMapSkin` → reuse-or-return map → Instantiate×3 (map / skin / default) → đọc `Map` component → obstacle reset → `localPosition=(0,20,100)` → `SetActive(true)` → `ReloadFog` |
| `BattleManager.<HandleInitMap>g__InstantiateMapPrefab\|228_0` | `0x2edb8d4` | usePool → `Scene_Game.Instance.mapPool.Rent` else giữ `fieldObject`; go≠null → `SetParent(transform, true)`; go==null → `SimpleAssetDB.Instance.InstantiatePrefabWithDefaultName(map, transform)` |
| `BattleManager.ReloadFog` / `SetStageTileBuff` | `0x2edba4c` / `0x2edbdd0` | **defer** (text lookup artifact value, sâu, cosmetic/tile-buff) |
| `EffectPool.Clear` | `0x2f6533c` | `RemoveLoopWorldEffects()` + `foreach t in _byeTriggerTimers: WorkTimer.Stop(t)` + `Clear()` |
| `Utility.ClearSeed` | `0x2c93e70` | clear **cả 2** dict tĩnh: `_seedCallCount` + `_randomWithSeeds` |

### Solved logic (không phải suy đoán — đọc từ decompile)

1. **Theme/Time block của `Init`:** `_theme.v = gm.currentTheme` (field `0x308`) → 12 cờ Localizer (`0x70C..0x719`) → **`if (_theme == 0) { gm.currentTheme = 1; _theme.v = 1; }` else `if (_theme.v < 0) { gm.eliteLevels = new int[5]; gm.difficulty = 0; mainUI.basePanel.SetInvasionDifficulty(0); }`** → `_resTheme = ResourceBase.Get<ResourceTheme>(_theme.v)` (throw nếu null) → Time:
   - `ResourceTheme.useFixedUpdate` (`0x14C`) **false** → `maximumDeltaTime = 0.33333334f (0x3eaaaaab)`, `fixedDeltaTime = 0.02f (0x3ca3d70a)`
   - **true** → cả hai = `0.016666668f (0x3d888889)`
2. **Deck resolve:** `stored = gm.data.currentDeck` (`PlayerData+0x68`, `int[]`). Validate từng phần tử qua `ResourceBase.Get<ResourceUnit>(id, ResourceUnit.Type)` (token `PTR_DAT_06a59b48`). **Tất cả resolve → dùng `stored` + `firstComer = data.currentFirstComerIndex` (`+0x78`); có phần tử fail → `gm.GetDefaultDeck()` + `firstComer = -1`.** (Vòng lặp C# gốc gán `bVar33 = i < count` ở tail — trường hợp `count == 0` cũng rơi vào nhánh "use stored" nghĩa là deck rỗng; rebuild **cố ý** đổi thành fallback `GetDefaultDeck()` để không bao giờ ra deck rỗng.)
3. **`_resStages`:** `isRogueLike || isStoryMode` → `new List<ResourceStage>()`; `isBabel` → `GetBabelStages()`; còn lại → **`ResourceStage.GetAll(s => s.theme == _theme.v)`**. (`ResourceStage.theme` @`0x20`, `.stage` @`0x24`.) Có thêm 2 predicate ứng viên `b__511_2` (`resTheme.<0x94> < s.stage`) và `b__511_16` (`excluded[Scene_Game+0x5D0] !Contains && theme match`, `0x5D0 = _pvpPresetStages`) — chọn `_0` vì nó là predicate `Func<ResourceStage,bool>` khớp kiểu `GetAll`.
4. **`InitMap` arena path:** `theme = _resTheme` (nhánh `isPvPDeckRecord` defer — key literal `PTR_DAT_06a66aa0` chưa resolve). `mapKey = theme.mapPrefab` (`0x28`). **Map-skin override:** `gm.decorationInfo` (`PlayerDecorationInfoResponseModel`, GM `+0x2C0`) `.equipInfo` (`+0x58`) `.appliedMapSkinData` (`Dictionary<int,int>`, `PlayerDecorationEquipInfoResponseModel+0x30`) — key = `theme.id`, value = map-skin id → `ResourceMapSkin.Get(id)`; nếu skin `!= null && !skin.isDefault` (`0x70`) thì `mapKey = skin.mapPrefab`. Rồi `foreach bm: bm.HandleInitMap(mapKey, theme, resMapSkin, usePool: true)`.
5. **`InitStage` arena path:** `Utility.ClearSeed()` khi `isColosseum` → `foreach bm (isSurvived): [isStoryMode → DisposeWorldTrigger(null)] + BeforeInitStage()` → `_isStageStarted=false` (`ObscuredBool` `0x368`) → `stageValueSum=0` (`0x6D4`) → `useStageValueSum=true` (`0x6D8`) → `effectPool.Clear()` → `isRogueLike` **hoặc** `curStage.theme ∈ {2000, 2100}` → `InitRogueLikeStage(); return;` → arena: `mainUI.SetStartButtonState(StartButtonState.RogueLikeStartBattle)` (**giá trị enum `1` — đúng theo bytecode, dù tên nghe lệch mode**) → `randomItemGetCount.Set(0)` + `freeMerchantRefreshCount.Set(0)` → `Constants.IsInvasion(_resTheme.id)` → `remainAdHeroSummonCount = 2` + `mainUI.ReloadAdRandomHeroButton()` → `foreach bm: AfterInitStage(_devilEffectCount, _devilCond)` → key-gated `InitPvPPresetStage`/`InitRankedPvPStage`/`InitClanRaidStage` (defer) → `isBabel → InitBabelStage()` → `isSkinPreview → InitSkinPreviewStage()`.
6. **`GridMap` ctor:** `offX = (w >= 7 ? w-7 : w-6)`, `offY = (h >= 12 ? h-12 : h-11)`, rồi `off = off >= 0 ? -(off >> 1) : 0`. `_minPos = (offX, offY)`, **`_maxPos = _minPos + (w, h)`**. Với default **7x12 → offX=offY=0** (`_minPos=(0,0)`, `_maxPos=(7,12)`). Allocation: `_map/_visited/_targetVisited/_gValue/_hValue` mỗi cái `w*h`; `_holdedUnits=HashSet<GameUnit>`, `_aiMapChangeListeners=HashSet<BaseAI>`; `_pathNodePool/_rented/_bfsQueue/_inverseBfsQueue` = 4 `Queue<PathNode>`; `_lst/_failedNodes` = 2 `List<PathNode>`; `_aStarPriorityQueue` = `PriorityQueue<PathNode>` (**defer — chỉ cần cho A*, S3d**).
7. **`UnitGrid.Init(int,int)`:** `_lastSize` cache → `_width = cellSize.x*w + gapSize.x*max(w-1,0)`, `_height = cellSize.y*h + gapSize.y*max(h-1,0)` → `for y = -offset.y .. h-offset.y-1` / `for x = -offset.x .. w-offset.x-1` → `AddTile(x, y)`. Gọi từ `Init(BattleManager,Color)` với **`w = bonusSize.x + size.x`, `h = bonusSize.y + size.y`** (đọc field `0x30+0x28`, `0x34+0x2c`).
8. **Default color của UnitGrid** = **`Colors.GridColors.DefaultOutlineColor`** (class có static field Color đầu tiên = `Colors.GridColors`, giải được bằng cách tìm class có `static_fields[0..3]` là 4 float). Kiểm tra `defaultColor.sqrMagnitude < eps` → Unity **`Color` không có `sqrMagnitude`**, rebuild dùng `defaultColor == default(Color)` (nguyên nhân: mọi caller truyền `default(Color)` nên cùng kết quả).
9. **`Map` MonoBehaviour là "map info component"** đọc trong `HandleInitMap`: `mapSkinPresets` (`GameObject[]`, `0x40`), `berserkPreset` (`0x48`), `obstacleObjects` (`ObstacleObject[]`, `0x50`), `bossObstacleObject` (`0x58`), `bannedObstacles` (`List<int>`, `0x60`). `fieldObject.transform.localPosition = (0f, 20f, 100f)` rồi `SetActive(true)`.

### Deviations (defer, document trong code)

- `Scene_Game.OpeningSequence`: **không port DOTween Sequence** — set thẳng `worldCam.orthographicSize = _camSize` (`ObscuredFloat`, `0x440`) rồi `_opening = null` (bản gốc tween 600 → `_camSize` + `DOLocalMove(MainUI.GetCameraPosition(0))` + `DOFade` mask + DisplayClass closure). Gọi `CheckGameStartEffects(out bonusTier)` để giữ bonus-tier side effect.
- Localizer feature flags `0x70C..0x719` (12 cờ) — **để false**; Localizer chưa port, key thiếu trả về chính key nên mọi so sánh sẽ sai.
- `isClanRaidDeckRecord` / `isPvPDeckRecord` → `false` (key literal chưa resolve, không liên quan arena).
- `curStage` dev-fallback `return _resStages[^1]` — defer, trả `null`.
- `HandleInitMap`: defer nhánh colosseum/pvp preset + vòng spawn map-effect particles (`resMapSkin.effectPrefabs` = `List<(string,float)>`, dùng `SimpleAssetDB.InstantiatePrefab` + DisplayClass + timer).
- `GameManager.Init`: defer block LocalPushManager (key prefab `PTR_DAT_06a76290` chưa resolve) — chỉ notification plumbing.
- `GridMap`: defer `_aStarPriorityQueue`.
- `ReloadFog` / `SetStageTileBuff` — defer (deep text-lookup, cosmetic/tile-buff).
- Nhánh mode trong `Init`: colosseum multi-battle (`battleCount` luôn 1), dev artifact options (`enemyLevelBonus != 2 && !isRankedPvP`).

### Traps đã gặp (đừng lặp lại)

- **`EffectAreaDrawer` field tên là `battle`, KHÔNG phải `battleManager`** (`SpawnManager` thì đúng là `battleManager` — dễ nhầm).
- **`AwesomeInt` KHÔNG có `op_Equality`/`op_Implicit` trong export** → so sánh qua `.v` (`_theme.v == 0`), ghi qua `.v = x` hoặc `.Set(x)`. `_theme` là class → `_theme == null` là reference check, và bản gốc deref thẳng `get_v` nên **thêm null-guard khởi tạo `new AwesomeInt(0)`** (stub-gap guard law).
- **`Color` không có `sqrMagnitude`** (tính tay 4 thành phần hoặc so bằng `default(Color)`).
- **`_theme`/`resTheme` bị duplicate** — export có stub cũ `public ResourceTheme resTheme => null;` ở ~L2442, phải xóa trước khi thêm bản port.
- **Batch Ghidra:** tách output bằng header `########## 0x<rva> ##########` — nếu filter `^#` sẽ nuốt header và trộn body 2 method liên tiếp với nhau (đã 2 lần đọc nhầm sang method kế). Dùng `sed -n 'N,Mp'` theo dòng của `grep -n "##########"`.

### Bước tiếp theo (S3c)

`StartStage` (`0x2e42a5c`) / `StartStage_d__565` + spawn: `GameUnit.Init` / `AddUnitTo`. Sau đó S3d (`UpdateImpl` → `BattleManager.Update` → `BaseAI.Update`, 62 `Unit*AI` qua `AIFactory`/`SetAI`), S3e (damage/die/win → `POST /game/complete`). Gate runtime thật (Scene_Game render + battle chạy) thuộc S3e.

## §51 — S3c part 1: start-stage chain (Update → StartStage → HandleStartStage → BattleManager.StartStage) (2026-10-19)

**Mục tiêu slice:** dựng chuỗi "bấm Start → battle flagged started". **Cổng xanh: compile GREEN (0 lỗi CS) + play-capture GREEN (0 exception, `shot_Scene_Lobby.png` 287KB).** Gate runtime thật (Scene_Game render) vẫn là S3e.

### RVAs đã decompile & port

| Method | RVA | Bản chất |
|---|---|---|
| `Scene_Game.Update` | `0x2e72ea4` | điều phối `UpdateImpl()` (+ timer-text UI, defer) |
| `Scene_Game.UpdateImpl` | `0x2e72fa8` | **gọi `StartStage()` khi một ObscuredFloat timer (12B @`+0x4FC..+0x508`) `<= 0.0f`**; rồi update start/ranking/story timer text |
| `Scene_Game.StartStage` | `0x2e42a5c` | wrapper **UniTaskVoid** → `AsyncUniTaskVoidMethodBuilder.Start<<StartStage>d__565>` |
| `Scene_Game.<StartStage>d__565.MoveNext` | `0x2ed0324` | ~890 dòng, 5 "await" (xem dưới) |
| `Scene_Game.<>c$$<StartStage>b__565_0` | `0x2ead868` | **`bm => bm != null`** (predicate của `Enumerable.All`) |
| `Scene_Game.<>c$$<StartStage>b__565_1` | `0x2ead880` | **`bm => { BattleManager.StartStage(bm); … }`** (action của `List.ForEach`) |
| `Scene_Game.HandleStartStage` | `0x2e7e06c` | per-bm setup → `battleManagers.ForEach(bm => bm.StartStage())` |
| `BattleManager.StartStage` | `0x2ef102c` | `isBattleStarted=true` → clear dmg dict → RegisterAllUnitsToMap/… → StartEnemiesBattle → `fieldUnits.ForEach(u => u.StartBattle(true))` → `fieldGrid.ClearFocus()` → `ApplyWorldTrigger(BattleStart)` → `dealMeterPanel.LogBattleStart(this)` |

### Solved logic

1. **`Update` → `StartStage` trigger:** bản gốc guard bằng một **ObscuredFloat timer 12B @`Scene_Game+0x4FC..0x508`** (`<= 0.0f` → gọi). Field **chưa identify được tên** trong export (ffoff không match). Rebuild dùng **`if (!_isStageStarted) StartStage();`** — net effect giống vì `StartStage` tự gate và `_isStageStarted` chỉ true khi đã start thật.
2. **5 gate/await của `MoveNext` (rebuild = return sớm để `Update` gọi lại frame sau):**
   - `battleManagers != null` **và mọi `bm != null`** (`All(bm => bm != null)` — lambda `b__565_0`).
   - `isStoryMode && !storyModeStageEntered` (`+0x870`) → return.
   - `mainUI.activeSkillPopupPanel.Close()` (không phải gate — side effect).
   - `AwesomePrefs.GetInt(<key>, 1) == 1 && !isColosseum` → `AutoMoveUnitToField()`.
   - **`mainUI.CheckFieldUnitCount()` == false → return** (đây là await thật sự).
   - Còn lại side effects (xem §).
3. **State mutations sau gate (đọc trực tiếp từ MoveNext):**
   | Field | Offset | Ghi |
   |---|---|---|
   | `mainUI.startTimer` | MainUI+0x498 | `.SetActive(false)` |
   | `_currentBattlePhase` | `+0x178` | `0` |
   | `_isStageStarted` | `+0x368` | `ObscuredBool(true)` ← **đây là battle-started flag** |
   | `_isStageEndPostCalled` | `+0x374` | `ObscuredBool(false)` |
   | `_stageStartAt` | `+0x338` | `ObscuredFloat(GetCurrentTime())` |
   | `_bossTimeCounter` | `+0x350` | `ObscuredFloat(GetCurrentTime())` |
   | `touchCamera.enabled` | `+0x248` | `true` |
   | `pvpStarted` | `+0x5CC` | `true` (chỉ khi `isRankedPvP`) |
   | `_eventModeRoundData` | `+0x6C8` | `= SavePlayerUnits()` (chỉ `isContinuableEventMode`) |
   | (click flag) | `+0x54E` | `1` — **field KHÔNG có trong export** (`IsStartStageClicked` không tồn tại) → defer |
   Gọi kèm: `mainUI.RefreshInvasionSpeedUpButton()`, `MainUI.Instance.SetCamPosition(0)`, `mainUI.PvPLock(true)`, `mainUI.ContinuableEventLock(true)`, `isBabel → StartStage_Babel()`.
4. **`HandleStartStage` (RVA 0x2e7e06c):** `foreach bm: bm.eventTriggerManager.ClearUnitTriggerCoolTimeDic()` → `foreach bm: RefreshCanMerge(); InitStageStartUnitData(); CheckStartStageArtifact(); [mode-gated CheckStartStageStoryChallengeMode/CheckStartStagePickAndPassMode]; StartTileBuff()` → `ResetSingleArenaGoblinHp(); AdjustActiveSkill(); MainUI.Instance.dealMeterPanel.Run()` → `battleManagers.ForEach(bm => bm.StartStage())`.
5. **`BattleManager.StartStage` (RVA 0x2ef102c):**
   ```
   isBattleStarted = true                       // +0x364
   unSummonedUnitTotalDamage.Clear()            // +0xB0  Dictionary<int,Dictionary<int,long>>
   RegisterAllUnitsToMap(); HighestLevelUnitCache(); SaveConnectedBuffersConnectedTargetAtStartBattle();
   StartEnemiesBattle();
   foreach u in fieldUnits (+0x70): u.StartBattle(true)
   fieldGrid.ClearFocus()                      // +0x198 UnitGrid
   _enemyWorldTriggerBundles = null             // +0xE8
   fieldGrid.tiles.ForEach(<GridTile vtable 0x28>)   // defer — GridTile method chưa resolve
   _afterBattleStartSubject.OnNext(<Null>)      // +0x160 Subject<Null> — type token chưa resolve → defer
   ApplyWorldTrigger(WorldTrigger.Conditions.BattleStart)   // 0xb = 11
   MainUI.Instance.dealMeterPanel.LogBattleStart(this)      // MainUI+0x2A8
   ```
6. **`UniTask`/`UniTaskVoid` KHÔNG có source trong export** — `Assets/Plugins/UniTask.dll` là binary DLL. Policy vĩnh viễn: **đổi signature `UniTask`/`UniTaskVoid` → `void`, bỏ body state-machine, chạy đồng bộ** (giống precedent `FetchShop`). Giữ attribute `[AsyncStateMachine(typeof(...))]` cho khớp metadata.

### Deviations / defer (đã document trong code)

- **Music selection** (7 nhánh `AudioController.PlayMusic/GetCurrentMusic`) — defer thuần audio.
- `IsStartStageClicked` (+0x54E) — field không tồn tại trong export.
- babel auto-mode (`babelData.autoMode` → `activeSkillManager.ReserveRandomForAuto()`) — field/key chưa resolve.
- `SpawnManager.SpawnUnit` (RVA của spawn) + `BattleManager.GetAllFieldUnits` stat aggregation + `StoryModeStageStart` + `ReloadWithSkinPreview` + destroy start-prep GOs — **S3c part 2**.
- `GameUnit.StartBattle(bool)` (export stub L2713), `RegisterAllUnitsToMap`, `HighestLevelUnitCache`, `SaveConnectedBuffersConnectedTargetAtStartBattle`, `StartEnemiesBattle`, `RefreshCanMerge`, `InitStageStartUnitData`, `CheckStartStageArtifact`, `StartTileBuff`, `ClearUnitTriggerCoolTimeDic`, `AutoMoveUnitToField`, `AdjustActiveSkill`, `ResetSingleArenaGoblinHp`, `DealMeterPanel.Run/LogBattleStart` — **tất cả đều là stub `{}` trong export**, gọi thẳng là an toàn (no-op).

### Traps đã gặp

- **`WorldTrigger.Conditions.BattleStart = 11`** — `ApplyWorldTrigger` nhận enum, không nhận `int`. (`BattleStart = 11`, `StageStart = 5`, `BattleLose = 10`.)
- **Ghidra batch double-offset:** mảng `targets` phải chứa **RVA thuần** — script tự + `IMAGEBASE_OFFSET`. Đã 1 lần ghi sẵn Ghidra-addr (RVA+0x100000) → kết quả trỏ sai 0x100000 và decompile ra `fn_<sai>` (Ghidra không tìm function → body lộn xộn `unaff_x19`). **Nhận diện:** nếu header in đúng RVA nhưng tên function là `fn_<hex>` thay vì `Scene_Game$$X` → sai offset.
- `UnitGrid.tiles` là **property** (`=> null` stub), không phải field `_tiles` — không dùng trực tiếp field.
- `EffectAreaDrawer.battle` (không phải `.battleManager`), `MainUI+0x498 = startTimer`, `MainUI+0x2A8 = dealMeterPanel`.
- `Scene_Game+0x54E` không phải field (ffoff: "no exact", kẹp giữa `_finalRankingScore`(0x530) và `_gameTimer`(0x558)).

### Bước tiếp theo (S3c part 2)

`SpawnManager.SpawnUnit` (RVA cần tìm) + `BattleManager.AddUnitTo` (RVA 0x2efa530, đã decompile batch62) + `GameUnit.Init` (RVA 0x308f7e8, đã decompile) + `BattleManager.GetAllFieldUnits` (0x2edfe70). Rồi S3d/S3e.

## §52 — S3c part 2: spawn chain (GameUnit.Init + SpawnManager.SpawnUnit + BattleManager.AddUnitTo) (2026-10-19)

**Mục tiêu slice:** "unit thực sự được tạo ra". **Cổng xanh: compile GREEN (0 lỗi CS) + play-capture GREEN (0 exception, 286KB).** Gate runtime thật vẫn là S3e.

### RVAs đã decompile & port

| Method | RVA | Bản chất |
|---|---|---|
| `GameUnit.Init` | `0x308f7e8` | 17 tham số; resolver `ResourceUnit` → identity/state fields → `SetTeam` → `ReloadTerritoryStatBuffs` → `SetResourceUnit` → `InitLevelIcon` → `live=true` |
| `GameUnit.SetTilePosition` | `0x309f958` | `gridObj.tilePos = pos` → `parentGrid.GetPosFromTile(pos)` + `gridObj.offset` → `transform.position = (x, y, GetZ(y,x)+off.z)` ; `applyZPosition` → skip localPosition |
| `BattleManager.GetCard` | `0x2ee8f04` | **`cardInfos.Find(c => c.cardId == unitId)`** (List<CardInfo> @+0xC8) |
| `SpawnManager.SpawnUnit` | `0x3139478` | `unitPool.CanRent(id,skin)` → `Rent` + `SetParent` ; else `Instantiate(Scene_Game.Instance.unitPrefab, bm.transform).Get<GameUnit>()` → `Init(...)` → `SetPosition` → `SetDraggable(false)` → `CacheUnitAssets`/`DivinePowerToUnit`/`HandleSpawnUnit` |
| `BattleManager.AddUnitTo` | `0x2efa530` | resolve `resUnit`/`GetParentIDIfHas`/`GetCard`/rogueCard → level<1 ? lấy từ cardInfo → `SpawnManager.SpawnUnit` → isField ? `fieldUnits.Add`+`SetTilePosition(fieldGrid.GetTilePos)`+`ShowHpGauge(false,true)`+`SetAI(null)`+`CheckTransformCondition(true)`+`RefreshCanMerge`+`SetUnitsOrder` : `waitingUnits.Add`+`ShowHpGauge(true,true)`+`SetAI(AIFactory.GetSuitableAI(unit))` → `_spawnUnitSubject.OnNext(unit)` |
| `AIFactory.GetSuitableAI` | `0x3005bf8` | `unit.resUnit` (+0x2E8) → `.aiClassName` (+0x208) → cache dict → ctor delegate(unit) — **defer (S3d)** |

### Solved logic

1. **`GameUnit.Init` param map** (Ghidra đặt tên theo thứ tự register, KHÔNG khớp chữ ký C# — suy ra bằng offset write):
   | Ghidra param | C# param | Ghi về |
   |---|---|---|
   | `param_2` | `id` | → `ResourceBase.Get<ResourceUnit>`; null → log + return |
   | `param_3` | `team` | → `SetTeam(team, true)` |
   | `param_4` | `level` | → `SetResourceUnit(resUnit, level, skin, true)` |
   | `param_5` | `cardLevel` | `_cardLevel` (ObscuredInt @`0x584`) |
   | `param_6` | `buildingLevels` (Ghidra ghi `undefined4` — sai type) | → `SetBuildingLevels` khi != null |
   | `param_7` | `skin` | → `SetResourceUnit` |
   | `param_8` | `artifacts` | `<artifacts>k__BackingField` @`0x918` |
   | `param_9` | `poolIdx` | `_poolIdx` @`0x948` |
   | `param_10` | `potentialSlot` | `_potentialSlot` @`0x9D8` |
   | `param_11` | `potentialTier` | `_potentialTier` @`0x9DC` |
   | `param_12` | `battleManagerIdx` | @`0xA68` |
   | `param_15/16` | `statueIndex/statueId` | @`0x230`/`0x234` |
   | `param_17/18` | `overcome/dimensionLevel` | `_overcomeLevel` @`0x390` / `_dimensionLevel` @`0x3A0` |
   **Thứ tự:** `initializedForBattle=false`(@`0x1EA`) → `battleManagerIdx` → **`_uid = ++static int`**(@`0x128`, đếm tăng mỗi unit) → defer `_debugColor=Random.ColorHSV` + static phase float → `SetItemCount(0)` → `itemCountGroup.alpha` → `buffPanel.Clear()` → `_cardLevel` → potentials → `_potentialSlot/_potentialTier/_overcomeLevel/_dimensionLevel` → `_iceObject.SetActive(false)`(@`0x888`) → reset `isClone`/`creatureInfo`(@`0x250`)/`forceNoHpGauge`/`ignoreBuildingStatBuff`/`isStatueCandidate`/`cantAttackUntilUseSkill`/`canUseSkillOnlyOnce` → `statueIndex/statueId` → `[defer buff-gauge wiring 0xA8/0xB0/0xD8/0x1F8/0x200]` → `SetBuildingLevels` → `artifacts` → `_poolIdx` → **`SetTeam(team,true)` → `ReloadTerritoryStatBuffs()` → `SetResourceUnit(resUnit, level, skin, true)` → `InitLevelIcon()` → `live=true`(@`0x1E9`)**.
   `potentialSlot == 999` là **sentinel "auto"** (bản gốc đọc `resUnit.GetPotentials(...).First().<0x80>`, null/-1 khi không có).
2. **`SetTilePosition` (RVA 0x309f958):** `gridObj` @GameUnit+`0xC8`; `GridObject` fields: `parentGrid`(UnitGrid) @`0x20`, `tilePos`(Vector2Int) @`0x28`, `offset`(Vector3) @`0x30`, `applyZPosition`(bool) @`0x3C`.
   ```
   if (gridObj.parentGrid == null) return;
   gridObj.tilePos = pos;
   p = parentGrid.GetPosFromTile(pos);   off = gridObj.offset;
   transform.position = (p.x+off.x, p.y+off.y, Scene_Game.GetZ(y,x) + off.z);
   if (applyZPosition) return;           transform.localPosition = (x, y, 0);
   ```
   `Scene_Game.GetZ(float y, float x = 0f)` (export L3719).
3. **`SpawnManager.SpawnUnit`:** `battleManager` (SpawnManager+`0x10`) → `bm.unitPool` (**BattleManager+`0x368`**). Branch:
   - `unitPool.CanRent(unitId, skinId)` → `unitPool.Rent(...)` + `unit.transform.SetParent(bm.transform)`
   - else → `Object.Instantiate(Scene_Game.Instance.unitPrefab (+`0x298`), bm.transform)` → `SetActive(true)` → `go.Get<GameUnit>()` (extension `Utility.Get<T>(this GameObject)` — **KHÔNG PHẢI `GetComponent`**)
   Rồi `unit.Init(..., battleManagerIdx: bm.battleManagerIdx, ...)` → `SetPosition(pos)` → `SetDraggable(false)` → `Scene_Game.CacheUnitAssets(resUnit, skin)` → `DivinePowerToUnit(unit)` → `HandleSpawnUnit(unit)`.
4. **`AddUnitTo` flow:** `resUnit = ResourceUnit.Get(id)` → **`id = resUnit.GetParentIDIfHas()`** (transform-unit map về parent) → `cardInfo = GetCard(id)` → rogueCard (isRogueLike) → `level < 1` ⇒ lấy `cardInfo.level` (skin/potentialTier cũng lấy từ cardInfo) → `spawnManager.SpawnUnit(pos, id, team:0, ...)` → **isField** branch vs waiting branch (xem bảng trên) → `_spawnUnitSubject.OnNext(unit)`.
5. **`BattleManager.GetCard`** = `cardInfos.Find(c => c.cardId == unitId)`. `CardInfo` layout: `cardId`@`0x10`, `level`@`0x14`, `skin`@`0x18`, `potentialTier`, `overcome`, `dimensionLevel`, `isLevelSyncApplied`.

### Deviations / defer (đã document trong code)

- `_debugColor = Random.ColorHSV` + static phase float @GameManager static `+0x28` — cosmetic.
- buff-gauge wiring (`hpDestroyAnim1/2`, `buffManager`, `incapacitatedManager`, `levelIconBattle`) — lookup gián tiếp chưa resolve.
- statue GO SetActive (`statueIndexBox/IndexText/IndexEffect`).
- potentials: giữ sentinel `potentialSlot` thay vì `resUnit.GetPotentials(...).First()`.
- test-mode `CardInfo` copy từ `CardData` (`GameManager.GetCard(id, true)`).
- rogueLike default treasure/accessories (`GetDefaultRogueLikeTreasure/Accessories`).
- `SpawnUnit`: `id == 100000-2` (0x1869E) → `Scene_Game.HandleCustomEvent`; clan-raid & colosseum branches.
- `AIFactory.GetSuitableAI` — **S3d** (cache dict + ctor delegate, 62 `Unit*AI`).
- `team` trong `AddUnitTo` hardcode `0` (player) — chữ ký không có team.

### Traps đã gặp

- **`Utility.Get<T>(this GameObject)` là extension method**, không phải `GetComponent<T>`. Bản gốc gọi `Utility.Get<GameUnit>(go)`.
- **`Scene_Game.DivinePowerToUnit`** — game typo "Divine" (Ghidra cũng ra "Divine"); KHÔNG sửa thành "Divide" nếu muốn khớp metadata.
- **`SpawnManager.SpawnUnit` là instance method** — `AddUnitTo` phải gọi `spawnManager.SpawnUnit(...)` (spawnManager @BattleManager+`0x330`).
- Ghidra đặt tên param theo thứ tự register, **không khớp thứ tự chữ ký C#** — luôn map lại qua offset write.
- `BattleManager+0x368 = unitPool`, `+0xC8 = cardInfos`, `+0x70 = fieldUnits`, `+0x79/0x1A0?` = waitingGrid (`+0x1A0`), `waitingUnits` là field riêng.

### Bước tiếp theo (S3d)

`Scene_Game.UpdateImpl` (đã port minimal) → `BattleManager.Update` → `GameUnit.Update/UpdateImpl` → `BaseAI.Update`. 62 `Unit*AI` qua `AIFactory.CacheConstructor` + `GetSuitableAI` (`unit.resUnit.aiClassName` @`ResourceUnit+0x208`). Cần decompile: `BattleManager.Update`, `AIFactory.CacheConstructor`, `ResourceUnit+0x208` field name, `GameUnit.Update`.

## §53 — S3d part 1: tick entry (GameUnit.Update/FixedUpdate + BaseAI.Update) + recon BattleManager.Update & GameUnit.UpdateImpl (2026-10-19)

**Mục tiêu slice:** vào được vòng lặp tick. **Cổng xanh: compile GREEN (0 lỗi CS) + play-capture GREEN (0 exception, 286KB).** Gate runtime thật vẫn là S3e.

### RVAs đã decompile & port

| Method | RVA | Bản chất |
|---|---|---|
| `GameUnit.Update` | `0x3098b88` | `Scene_Game.Instance.resTheme.useFixedUpdate == true` → return ; else `UpdateImpl()` |
| `GameUnit.FixedUpdate` | `0x3098c14` | **mirror suy luận** (chưa decompile — batch66 chạy ra kết quả batch cũ, cần rerun) |
| `GameUnit.UpdateImpl` | `0x3098ca0` | **RECON ONLY** — 414 dòng, chưa port |
| `BattleManager.Update` | `0x2ed9e9c` | **RECON ONLY** — 442 dòng, input/UI handler, chưa port |
| `AIFactory.CacheConstructor` | `0x3005d08` | **RECON ONLY** — reflection (`Type.GetTypeFromHandle` ×2 + ctor delegate cache), chưa port |
| `BaseAI.Update` | `0x303c0a8` | `if (!enabled) return; OnActionFixed(currentAction); if (keep) return; time -= dt; if (time<=0) OnActionEnd(currentAction)` |

### Solved logic

1. **`GameUnit.Update` (RVA 0x3098b88)** — 8 dòng, gate theo theme:
   ```csharp
   var scene = Scene_Game.Instance;               // Scene_Game static field 0
   if (scene == null || scene.resTheme == null) throw new NullReferenceException();
   if (scene.resTheme.useFixedUpdate) return;      // ResourceTheme.useFixedUpdate @+0x14C
   UpdateImpl();                                    // vtable call
   ```
   `GameUnit.FixedUpdate` = mirror (`!useFixedUpdate` → return). **Chưa verify bằng Ghidra** — batch66 bị lỗi regex nên ra lại output batch59; rerun khi port `UpdateImpl`.
2. **`BaseAI` layout** (foff): `me`(GameUnit) @`0x10`, `currentAction`(struct `AIAction`) @`0x18`, `skillId` @`0x24`, `enabled`(bool) @`0x28`.
   `AIAction = { State state(int)@+0, float time@+4, bool keep(bool)@+8 }` size 12 → tại BaseAI: `state`@`0x18`, `time`@`0x1C`, `keep`@`0x20`.
   `BaseAI.Update`:
   ```csharp
   if (!enabled) return;
   OnActionFixed(currentAction);                    // vtable +0x188, AIAction by value (12B → 2 chunk)
   if (currentAction.keep) return;
   currentAction.time -= dt;
   if (currentAction.time <= 0f) OnActionEnd(currentAction);   // vtable +0x1A8
   ```
   Ghidra render thành `(this, param_2[3]=*(this+0x18) long, (int)param_2[4]=*(this+0x20), *(vtable+400))` — tức **struct 12 byte passed by value** + `MethodInfo*`. Slot 0x188 (=vtable[49]) & 0x1A8 (=vtable[53]) nhận diện **bằng semantics** (per-frame hook vs expiry hook), CHƯA đối chiếu slot index thật. BaseAI có đúng 4 virtual nhận `AIAction`: `OnActionStart`/`OnAction`/`OnActionFixed`/`OnActionEnd` (dump.cs L65239–65248, khai báo theo thứ tự đó, `Update(float)` ở L65251).

### Recon — `BattleManager.Update` (RVA 0x2ed9e9c, CHƯA port)

Input/UI handler (KHÔNG đụng battle sim), cấu trúc:
```csharp
private void Update()
{
    if (battleManagerIdx != 0) return;            // +0x34 — chỉ bm chính tick
    var scene = Scene_Game.Instance;
    var mainUI = scene.mainUI;                    // Scene_Game+0x268 = MainUI
    if (Input.GetMouseButtonDown(0))
    {
        if (mainUI.tutorialPanel.<blockRaycast>)  // MainUI+0x3F0 = IngameTutorialPanel; +0x8C = <blockRaycast>
            ... /* tutorial block */
        if (Utility.IsPointerOverUIObject()) { /* colosseum invade panel */ }
        else if (ColosseumInvadeInfoPanel.Instance.isActiveAndEnabled
                 && Utility.IsPointerOver(ColosseumInvadeInfoPanel.Instance.transform)) { /* keep open */ }
        else ColosseumInvadeInfoPanel.Instance.Hide();
        if (Scene_Game.Instance.isRogueLike) { /* roguelike branch */ }
        else {
            if (Input.GetMouseButtonDown(0) && Utility.IsPointerOver(mainUI.itemInfoPanel.transform)) { /* keep open */ }
            mainUI.itemInfoPanel.Hide();          // MainUI+0x158 = ItemInfoPanel
            mainUI.basePanel.devilInfo.SetActive(false);   // MainUI+0x3D0 = BasePanel; +0x198 = Border devilInfo
            mainUI.basePanel.eliteInfo.SetActive(false);   // BasePanel+0x168 = Border eliteInfo
            ...
        }
    }
    /* ... 300 dòng còn lại: drag/selection, fieldGrid(+0x198), waitingGrid, unit picking ... */
}
```
Field đã resolve: `MainUI.mainUI`/`Instance`, `MainUI+0x158=itemInfoPanel`, `+0x3D0=basePanel`, `+0x3F0=tutorialPanel` (`IngameTutorialPanel+0x8C=<blockRaycast>`), `BasePanel+0x198=devilInfo(Border)`, `+0x168=eliteInfo(Border)`. `Utility.IsPointerOverUIObject()` / `Utility.IsPointerOver(Transform)` có sẵn (Utility.cs L1802/L1807). `ItemInfoPanel.Hide()` L75, `ColosseumInvadeInfoPanel.Hide()` L29.

### Recon — `GameUnit.UpdateImpl` (RVA 0x3098ca0, CHƯA port)

414 dòng; call graph (thứ tự xuất hiện):
```
sizeRatio / height / transform.localPosition  (visual offset — +0x5E0 là 1 list/timer)
battle (get_battle) -> if (!battle.isBattleStarted) return-ish   // BattleManager+0x364 = isBattleStarted
  Rigidbody2D.velocity set (khi Object.op_Inequality(...))       // GameUnit+0x30 = rigidbody
  if (live /*+0x1E9*/) {                                          // live @0x1E9
    ... Time.deltaTime accumulator (+0x7DC, +0x7A8 counters)
    if (!<+0x228>) CheckNextPath();  TileMoveUpdate();
    if (buffManager(+0x1F8) != null) ...
    UpdateChannelingBar();  UpdateInvincibleTimers();
    CanUseSkill() / atkRange / skillRange / CheckRangeTo(...) / SetTarget(null)  // target invalidate
    ... ShowEffect(...) when height timer expires
    UpdateCCTimers();
    if (<+0x22A>) ...
    UpdateAITimers();       // <- đây gọi BaseAI.Update
    ...
  }
```
**Đã resolve đủ field (foff) — việc còn lại là transcription, không phải discovery:**

| Offset | Field | Ghi chú |
|---|---|---|
| `+0x5E0` | `private readonly List<ValueTuple<DamageInfo.BlockedBy, GameObject>> _superShieldEffects` | đầu method: đếm >0 rồi set `transform.localPosition` theo `sizeRatio`/`height` + `Time.time` |
| `+0x7DC` | `public bool isSummoning` | |
| `+0x7A8` | `private int _tileMoveWaitFrame` | |
| `+0x228` | `private bool _isMoving` | `if (!_isMoving) CheckNextPath();` |
| `+0x22A` | `public bool isField` | |
| `+0x30` | `public Rigidbody2D rigidbody` | `set_velocity` khi battle đang chạy |
| `+0x1E9` | `public bool live` | tick body bao bởi `if (live)` |
| `+0x1F8` | `public BuffManager buffManager` | |
| getters | `sizeRatio` (GameUnit.cs L1045, stub `=> 0f`), `height` (L1047, stub `=> 0f`), `battle` | stub → gọi được ngay |

Các `Update*Timers` (`UpdateChannelingBar`/`UpdateInvincibleTimers`/`UpdateCCTimers`/`UpdateAITimers`/`TileMoveUpdate`/`CheckNextPath`/`CheckRangeTo`/`SetTarget`/`ShowEffect`/`CanUseSkill`) đều là stub trong export → **an toàn khi gọi**. `BattleManager.isBattleStarted` @`+0x364` là gate ở đầu nhánh battle.

### Recon — `AIFactory.CacheConstructor` (RVA 0x3005d08, CHƯA port)

```csharp
public static void CacheConstructor(string aiName)   // ResourceUnit.aiType @+0x208
{
    if (_cache.ContainsKey(aiName)) return;
    var type = <Type.GetTypeFromHandle(...)×2>;       // reflection
    var ctor = type.GetConstructor(new[]{ typeof(GameUnit) });
    _cache[aiName] = ctor;
}
```
`GetSuitableAI(unit)` = `if (unit?.resUnit == null) throw; var aiType = unit.resUnit.aiType; if (!_cache.ContainsKey(aiType)) CacheConstructor(aiType); return _cache[aiType](unit);`
**Ponytail:** reflection-based AI loading = 62 class name → ctor. Thay vì port reflection, có thể map `aiType` string → `new XxxAI(unit)` qua 1 dict tĩnh (an toàn, không AOT/IL2CPP issue, đúng semantics). Quyết định này thuộc S3d part 2.

### Deviations / defer (đã document trong code)

- `GameUnit.FixedUpdate` — mirror **suy luận**, chưa Ghidra-verify (batch66 failed).
- `BaseAI.Update` — 2 virtual slot nhận diện bằng semantics, chưa đối chiếu slot index.
- `BattleManager.Update` (input/UI, 442 dòng) — chưa port.
- `GameUnit.UpdateImpl` (414 dòng) — chưa port.
- `AIFactory.CacheConstructor` / `GetSuitableAI` — reflection, chưa port (S3d part 2).

### Traps đã gặp

- **`GameManager+0x460 = rogueLikeSystem`, KHÔNG phải `_resTheme`.** `_resTheme` @`Scene_Game+0x460`. Cú pháp Ghidra `**(long**)(cls + 0xb8) + 0x460` nghĩa là *singleton của class PTR_DAT_06a51c58 (= Scene_Game)* rồi +0x460 — KHÔNG đọc nhầm là GameManager.
- **Batch Ghidra chạy lại ra output cũ** khi regex thay targets array fail (decomp_batch66.java giữ nguyên targets của batch59). Luôn `grep -n "##########"` để verify header khớp RVA mới trước khi split.
- `BaseAI.currentAction` là **struct field** — `currentAction.time -= dt` mutate in-place được (C# struct field trên class là lvalue).
- `BattleManager+0x158 = _gridUpdateSubject` (Subject<GameUnit>), `+0x3D0 = _nullInts` — **KHÔNG** phải itemInfoPanel/basePanel (đó là MainUI offsets).

### Bước tiếp theo (S3d part 2)

1. Port `GameUnit.UpdateImpl` (resolve `sizeRatio`/`height`/`battle` getters + 5 field offsets + `Update*Timers`).
2. Port `AIFactory` bằng dict tĩnh (không reflection) + `GetSuitableAI` + 62 `Unit*AI` skeleton.
3. Port `BattleManager.Update` (input handler) — thấp nhất ưu tiên, không ảnh hưởng sim.
4. Rerun Ghidra verify `GameUnit.FixedUpdate`.

## §54 — S3d part 2: unit tick body + AI factory (GameUnit.UpdateImpl + AIFactory) (2026-10-19)

**Mục tiêu slice:** 1 unit trên field thật sự tick mỗi frame (AI + di chuyển + timer + target invalidation). **Cổng xanh: compile GREEN (0 lỗi CS) + play-capture GREEN (0 exception, 286KB).** Gate runtime thật vẫn là S3e.

### RVAs đã decompile & port

| Method | RVA | Bản chất |
|---|---|---|
| `GameUnit.UpdateImpl` | `0x3098ca0` | tick body — xem cấu trúc bên dưới |
| `AIFactory.GetSuitableAI` | `0x3005bf8` | `unit.resUnit.aiType` → cache dict → `ctor(unit)` |
| `AIFactory.CacheConstructor` | `0x3005d08` | `Type.GetType(aiName).GetConstructor([GameUnit])` → cache delegate |

### Solved logic — `GameUnit.UpdateImpl` cấu trúc

```
1) _superShieldEffects (List<ValueTuple<BlockedBy, GameObject>> @+0x5E0):
   nếu Count > 0 thì bay quanh unit — step = (360f/n) * PI/180, ang = Time.time * 1.5f,
   mỗi phần tử: localPosition = (cos*sr*25, height*0.5 + sin*sr*25, 0)   [sincosf -> Mathf.Sin/Cos]

2) gate: var b = battle; if (b == null) return;  if (!b.isBattleStarted) return;
   if (rigidbody != null) rigidbody.velocity = Vector2.zero;       // GameUnit+0x30
   if (!live) return;                                               // +0x1E9

3) if (_interactionOffTime > 0) -= dt;                              // +0x834

4) if (!isSummoning) { ...toàn bộ tick body... }                    // +0x7DC
   - ai.Update(Time.deltaTime);                                     // ai @+0x2D8, vtable +0x1C8
   - if (_tileMoveWaitFrame > 0) _tileMoveWaitFrame--;              // +0x7A8
   - if (!_isMoving) CheckNextPath();  TileMoveUpdate();            // _isMoving @+0x228
   - if (buffManager != null) buffManager.Update();                 // +0x1F8
   - UpdateChannelingBar(); UpdateInvincibleTimers();
   - if (_moveStopTime > 0) { -= dt; if (<=0) { var r = CanUseSkill() ? skillRange : atkRange;
                                                if (!CheckRangeTo(target, r)) SetTarget(null); } }   // +0x28C, target @+0x1D0
   - if (_addDamageMultCooltimeTimer > 0 && -=dt <= 0) ShowEffect(null, (0, height*0.5, -1), zero,...)  // +0x500
     rồi _addDamageMultCooltimeTimer -= dt
   - UpdateCCTimers();
   - if (buffManager != null && isField) { var di = default(DamageInfo);
       buffManager.ApplyBuffOption(BuffOption.Conditions.DuringBattle, ref di); }     // Conditions.DuringBattle = 29
   - if (defDenListCurrentFrame != null) Clear();                    // +0x808 (List<GameUnit>)

5) BA TIMER ƯU TIÊN (if/else-if/else): _stopTime (+0x838) > buffChannelingTime (+0x850) > ice/AI-timers
   a) _stopTime > 0:
      -= dt; if (<0) { =0; if (resUnit.GetValueBool(ManaLockWhenStop)) SwapManaAndBuffBar(); ai.HandleStopEnd(); }
      if (resUnit.GetValueBool(ManaLockWhenStop)) {
          v = GetSkillValueDoubleSum(resSkill, SkillTag.StopTime);
          if (v <= 0) return;
          buffGaugeOrBossBuffGauge?.Set((long)(_stopTime*1000), (long)(v*1000)); }
   b) buffChannelingTime > 0:
      -= dt; if (<0) { =0; if (GetValueBool(ManaLockWhenBuffChanneling)) SwapManaAndBuffBar(); ai.HandleStopEnd(); }
      if (GetValueBool(ManaLockWhenBuffChanneling)) {
          v = GetSkillValueDoubleSum(resSkill, SkillTag.BuffChannelingTime);
          if (v > 0) buffGaugeOrBossBuffGauge?.Set((long)(buffChannelingTime*1000), (long)(v*1000)); }
      then if (_iceTime (+0x26C) > 0) { -= dt; if (>0) return; EndIce(true); }
   c) else:
      if (_iceTime > 0) { -= dt; if (>0) return; EndIce(true); return; }
      UpdateAITimers();
      // fixedTarget invalidation:
      if (fixedTarget (+0x1D8) == null) return;
      if (fixedTarget.live) return;
      if (fixedTarget.killedBy (+0x7A0) != this) return;
      if (_isSkillAttacking (+0x221) && _curControllerSkill (+0xAA0) != null
          && GetSkillValueBool(_curControllerSkill, SkillTag.CancelWhenNoTarget)) return;
      if (_curControllerSkill != null && GetSkillValueBool(_curControllerSkill, SkillTag.SetCurControllerSkill)
          && GetAttackSkillID() == _curControllerSkill.id) return;
      if (_channelingTime (+0x274) > 0
          && !resUnit.GetValueBool(UnitTag.CancelWhenFixedTargetIsDeadWhileChanneling, true)) return;
      if (_isSkillAttacking && resUnit.GetValueBool(UnitTag.ForceContinueWhenFixedTargetIsDeadDuringSkill)) return;
      if (_isAttacking (+0x220) && _curControllerSkill != null
          && GetAttackSkillID() == _curControllerSkill.id
          && resUnit.GetValueBool(UnitTag.ForceContinueWhenFixedTargetIsDeadDuringSkill)) return;
      CancelMotion(); fixedTarget = null;
```

### ★ Magic-key decode — `UnitTag` & `SkillTag` (đây là "tên code" của 4 tag)

`ResourceUnit.GetValueBool(UnitTag key, bool @default)` (ResourceUnit.cs L1363) và
`GameUnit.GetSkillValueDoubleSum(ResourceSkill resSkill, SkillTag key, double seed)` (L3559):

| Số | Tên | Dùng ở đâu trong UpdateImpl |
|---|---|---|
| `UnitTag` 206 (0xCE) | **`ForceContinueWhenFixedTargetIsDeadDuringSkill`** | `_isSkillAttacking` / `_isAttacking` → GIỮ target đã chết |
| `UnitTag` 207 (0xCF) | **`CancelWhenFixedTargetIsDeadWhileChanneling`** | `_channelingTime > 0`, default **`true`** (khác các tag khác!) |
| `UnitTag` 208 (0xD0) | **`ManaLockWhenBuffChanneling`** | nhánh `buffChannelingTime` |
| `UnitTag` 209 (0xD1) | **`ManaLockWhenStop`** | nhánh `_stopTime` |
| `SkillTag` 535 (0x217) | **`SetCurControllerSkill`** | fixedTarget invalidation |
| `SkillTag` 536 (0x218) | **`CancelWhenNoTarget`** | fixedTarget invalidation |
| `SkillTag` 537 (0x219) | **`BuffChannelingTime`** | max value của buff-channeling gauge |
| `SkillTag` 538 (0x21A) | **`StopTime`** | max value của stop gauge |

Các enum này nằm trong file `ResourceUnit.cs` L14+ (`public enum UnitTag`) và `ResourceSkill.cs` L~546 (`public enum SkillTag`) — **tra bằng `grep -rn "= 206,\|= 207,..." ResourceUnit.cs`**, KHÔNG cần Ghidra.

`Gauge.Set(long value, long maxValue, bool force = false)` (Gauge.cs L149). `buffGaugeOrBossBuffGauge` là property stub `=> null` (L962) → cả gauge branch đều no-op cho tới khi port property.

### Solved logic — `AIFactory`

`ResourceUnit.aiType` (+`0x208`) là **string**; `GetSuitableAI(unit)`:
```csharp
if (unit == null || unit.resUnit == null) throw new NullReferenceException();
var aiName = unit.resUnit.aiType;
if (!_constructorDict.ContainsKey(aiName)) CacheConstructor(aiName);
return _constructorDict[aiName](unit);        // delegate (GameUnit) -> BaseAI
```
`CacheConstructor`: `Type.GetType(aiName).GetConstructor([typeof(GameUnit)])` → cache `u => (BaseAI)ctor.Invoke([u])`.
99 file `*AI.cs` trong export (đều global namespace, Assembly-CSharp) → `Type.GetType(<tên>)` resolve được trong Editor.
**Defer/ghi chú:** bản gốc dùng **indexer** (ném `KeyNotFoundException` nếu type không resolve) — port guard + `Debug.LogWarning` để 1 aiType sai không crash cả trận. Nếu build IL2CPP link-strip 62 class AI → thay bằng dict tĩnh `aiName -> new XxxAI(u)`.

### Deviations / defer (đã document trong code)

- `_superShieldEffects` hằng `_UNK_013e3510` = `PI/180` (đổi độ→radian); `sincosf` → `Mathf.Sin`/`Mathf.Cos` (Unity 2022.3 **không có** `Mathf.SinCos`).
- `ai.Update(Time.deltaTime)` (vtable +0x1C8) & `ai.HandleStopEnd()` (vtable +0x418) — nhận diện **bằng semantics**, chưa đối chiếu slot index.
- `ShowEffect(null, (0, height*0.5, -1), Vector3.zero, 0f, false, false, null, default, this)` — đọc lại theo overload `(string, Vector3, Vector3, float, bool, bool, ResourceSkill, ResourceSkill.Effect, GameUnit)`; Ghidra tách `ResourceSkill.Effect` 288B ra cuối và đảo thứ tự.
- `buffGaugeOrBossBuffGauge` là stub `=> null` → 2 gauge branch no-op.
- `GetSkillValueDoubleSum`/`GetSkillValueBool`/`Update*CCTimers/Invincible/Channeling/AITimers/TileMoveUpdate/CheckNextPath/CheckRangeTo/SetTarget/CancelMotion/EndIce/CanUseSkill` đều là stub trong export → an toàn khi gọi.
- `buffManager.ApplyBuffOption(BuffOption.Conditions.DuringBattle, ref di)` — `DuringBattle = 29` (0x1D); `DamageInfo` struct 264B zero-init.
- `AIFactory`: guard thay vì indexer.

### Traps đã gặp

- **`Mathf.SinCos` không tồn tại trong Unity 2022.3** → dùng `Mathf.Sin`/`Mathf.Cos` (sinh lỗi CS0117).
- **`UnitTag` là nested enum của `ResourceUnit`** → phải viết `ResourceUnit.UnitTag.X` (sinh lỗi CS0103 nếu viết裸 `UnitTag`).
- **`AIFactory.cs` thiếu `using UnityEngine;`** (chỉ có `System` + `System.Collections.Generic`) → `Debug` không resolve.
- `_UNK_013e3510` / `_UNK_013e4080` trong Ghidra = hằng float trong `.rodata` — đọc trực tiếp bằng con số (`PI/180`, `1000.0`) thay vì đoán.

### Bước tiếp theo

1. Port `BattleManager.Update` (442 dòng input/UI handler — recon §53, không ảnh hưởng sim).
2. Rerun Ghidra verify `GameUnit.FixedUpdate` (§53 batch66 fail).
3. S3e: damage/die/win-lose → `/game/complete` — **đây là gate runtime thật** của Scene_Game.

## §55 — S3e part 1: win/lose decision core (CanEndStage + CheckStageEnd + HandleStageClear/Lose) (2026-10-19)

**Mục tiêu slice:** luồng thắng/thua của 1 trận. **Cổng xanh: compile GREEN (0 lỗi CS) + play-capture GREEN (0 exception, 286KB).** Gate runtime thật (đánh 1 trận thật) vẫn cần `GameUnit.Damaged`/`Die`.

### RVAs đã decompile & port

| Method | RVA | Bản chất |
|---|---|---|
| `BattleManager.CanEndStage` | `0x2ef163c` | đếm unit sống sót → `(canEnd, isWin)` |
| `<CanEndStage>g__CountLeftUnit\|331_0` | `0x2ef1778` | helper đếm (bản gốc là display-class lambda) |
| `BattleManager.CheckStageEnd` | `0x2ef1ecc` | cache → `CanEndStage` → dọn battle → `HandleStageClear`/`HandleStageLose` |
| `BattleManager.HandleStageClear` | `0x2ef23dc` | clear → `ApplyBuffsToFieldUnits(BattleWin)` → `StageEnd()` |
| `BattleManager.HandleStageLose` | `0x2ef26a8` | mirror, `BattleLose` + `ApplyWorldTrigger(BattleLose)` |

### Solved logic — chuỗi thắng/thua

**`CountLeftUnit(list, cnt)`** (RVA `0x2ef1778`, cnt là `int[3]`):
```csharp
foreach (var u in list) {
    if (u.isMimic) continue;      // GameUnit+0x22E = isMimic  (KHÔNG PHẢI isClone như +0x22D)
    if (!u.live) continue;        // +0x1E9
    // [defer] nhánh type-check u.ai (Il2CppClass type-token của PTR_DAT_06a69e70)
    if (u.originalTeam == Constants.Team.Player) {
        if (!u.isSummoned) cnt[0]++;    // +0x548 = isSummoned
        cnt[1]++;
    }
    if (u.originalTeam == Constants.Team.Enemy) cnt[2]++;
}
```
→ `cnt[0]` = player sống **không** tính summon ; `cnt[1]` = player sống **có** tính summon ; `cnt[2]` = enemy sống.

**`CanEndStage()`**:
```csharp
var cnt = new int[3];
_countLeftUnit(fieldUnits /*+0x70*/, cnt);
_countLeftUnit(enemies     /*+0x98*/, cnt);
_countLeftUnit(summonedUnits /*+0xA0*/, cnt);
bool useSummoned = resTheme.GetValueBool(<key>, true);   // def = true
int playerAlive  = useSummoned ? cnt[1] : cnt[0];
return (playerAlive < 1, cnt[2] < 1);                    // (canEnd, isWin)
```

**`CheckStageEnd()`** (trả `(bool,bool)`, cache qua `_stageEndResult` Nullable @`+0x3D8`):
```csharp
if (_stageEndResult.HasValue) return _stageEndResult.Value;
var r = CanEndStage();  canEnd = r.Item1;  isWin = r.Item2;
if (!isBattleStarted (+0x364)) { if (!canEnd && !isWin) return (false,false); }   // chưa start -> không dọn
else {
    if (!canEnd && !isWin) return (false,false);
    isBattleStarted = false;  DisposeDisposables();  KGCRegistry.ClearAll();
    ApplyBuffsToFieldUnits(BuffOption.Conditions.BattleEnd /*3*/, ref DamageInfo);
    MainUI.Instance.dealMeterPanel.LogBattleEnd(this);      // MainUI+0x2A8
    UnEquipTemporalItems();
    win = isWin;                                            // [defer] seasonal-quiz branch
    if (battleManagerIdx == 0) {                            // +0x34 — chỉ bm chính
        if (!win) { winningStreak (+0x360) = 0; HandleStageLose(); }
        else      { winningStreak++;             HandleStageClear(); }
    }
    // [defer] colosseum: StaticColosseumDataClass.GetColosseumData(this) -> HandleEndColosseumBattle(...)
}
return (canEnd, isWin);
```

**`HandleStageClear` / `HandleStageLose`** — đều: `ClearSummonedUnits()` → `ClearArtifactSkillUnits()` → `ApplyBuffsToFieldUnits(BattleWin=6 / BattleLose=7, ref di)`; Lose thêm `ApplyWorldTrigger(WorldTrigger.Conditions.BattleLose = 10)`; rồi `StageEnd()`. `battleManagerIdx != 0` thì về thẳng `StageEnd()` (bỏ qua UI).

### ★ Constants.Team — đọc từ tên, không cần giá trị

`Constants.Team` (Constants.cs L258) là `public static class` với **4 static int**: `None`(+0) / **`Player`(+4)** / **`Enemy`(+8)** / `End`(+12) — đúng 2 offset mà Ghidra đọc (`*(staticFields + 4)` và `+ 8`). Dùng symbol `Constants.Team.Player`/`.Enemy` nên không cần biết giá trị; bản gốc cũng không hardcode.
Cùng class này xuất hiện ở nhánh seasonal-quiz của `CheckStageEnd` — cùng 2 offset.

### Deviations / defer (đã document trong code)

- `CountLeftUnit` viết thành **private static helper `_countLeftUnit`** thay vì display-class lambda `<CanEndStage>g__CountLeftUnit|331_0` — cùng semantics, ít file hơn.
- `CanEndStage`: key string của theme flag (`ResourceTheme.GetValueBool(string, bool)` — **string key**, không phải enum) chưa resolve khỏi `.rodata` (`PTR_DAT_06a67668`) → hằng `_STAGE_END_SUMMONED_KEY` = `"<TODO...>"` với **default `true`**. Với theme thường thì default là đúng.
- `CountLeftUnit`: nhánh type-check `u.ai` (Il2CppClass type-token) bỏ qua.
- `CheckStageEnd`: seasonal-quiz branch (so `Scene_Game.selectedTeamForQuiz` ObscuredInt @`+0x670` với 2 static answer) → giữ `win = isWin`; colosseum end-of-battle → defer.
- `HandleStageClear`/`HandleStageLose`: `MainUI.ShowBattleAnim(trigger)` / `AudioController.Play(clip)` / `CenterText.Show(..., 0.5f, MainUI+0x170, LocalizerUtility.L(key))` — 3 string trong `.rodata` chưa resolve, **cosmetic** → defer. `isSeasonalQuizMode`/`isRankedPvP` chỉ đổi chuỗi, không đổi control flow.

### Traps đã gặp

- **`GameUnit+0x22E = isMimic`** (khác hẳn `+0x22D = isClone`) — `CountLeftUnit` skip `isMimic`, không phải `isClone`.
- **`ResourceTheme.GetValueBool` nhận STRING key** (ResourceTheme.cs L202), không phải enum — khác `ResourceUnit.GetValueBool(UnitTag, bool)` (L1363, enum). Đừng nhầm.
- `BattleManager.winningStreak` @`+0x360` (không phải `_stageClearCount`); `_stageEndResult` Nullable<(bool,bool)> @`+0x3D8`.
- `BattleManager+0x98 = enemies`, `+0xA0 = summonedUnits` (không phải waitingUnits).

### Bước tiếp theo (S3e part 2)

`GameUnit.Damaged` (RVA `0x30cb664`, export L2053, 604 dòng decompile sẵn trong `batch67.log`) →
`GameUnit.Die` (RVA `0x30c9588`, export L2169, 832 dòng) → `BattleManager.HandleUnitDead` (RVA `0x2eef840`, export L1181, 869 dòng) →
`Scene_Game.HandleStageLose`(`0x2e75af4`) / `HandleGameEnd`(`0x2e59770`) / `HandleGameEndImpl`(`0x2e85b3c`) → `POST /game/complete`.
Cả 3 method lớn đều đã decompile sẵn — việc còn lại là transcription.

## §56 — S3e part 2: damage pipeline core (DamageInfo + ApplyDamage + ApplyDamageToHpImpl) (2026-10-19)

**Mục tiêu slice:** damage đi được từ entry xuống HP và xuống `Die()`. **Cổng xanh: compile GREEN (0 lỗi CS) + play-capture GREEN (0 exception, 288KB).**

### RVAs đã decompile & port

| Method | RVA | Trạng thái |
|---|---|---|
| `DamageInfo.GetDamage(bool apply)` | `0x02f61f90` | ✅ port |
| `DamageInfo.GetDamage()` | `0x02f62540` | ✅ port |
| `DamageInfo.DamageBlocked()` | `0x02f628c4` | ✅ port |
| `GameUnit.ApplyDamage(ref DamageInfo, GameUnit)` | `0x30c7ddc` | ✅ port |
| `GameUnit.ApplyDamageToHpImpl(ref DamageInfo, GameUnit)` | `0x30c856c` | ✅ port |
| `GameUnit.get_battle` | `0x0308f760` | ✅ port (sửa stub `=> null`) |
| `GameUnit.OverwriteDamage(ref DamageInfo, GameUnit)` | `0x30c5340` | ⏸ decompile sẵn (374 dòng), **defer** |
| `GameUnit.Damaged` | `0x30cb664` | ⏸ decompile sẵn (604 dòng), part 3 |
| `GameUnit.Die` | `0x30c9588` | ⏸ decompile sẵn (832 dòng), part 3 |

### ★ DamageInfo — layout đầy đủ (47 field, dump.cs TypeDefIndex 1644)

Static: `UniqueIdCounter`@0x0, **`NonBlockedList`**@0x8 (`static readonly List<BlockedBy>`).
Instance chính: `value`@0x8, `uniqueDamageCompoundMult`@0x10, `damagePer`@0x18, `damageMult`@0x20,
`damageInc`@0x28, `team`@0x30, `resSkill`@0x38, `damageIdx`@0x40, `type`@0x44, `isCritical`@0x48,
`blockedBy`@0x4C, `systemScaler`@0x50, `stunTime`@0x58, `splashRoot`@0x5C, `splashRootPos`@0x60,
`isSplash`@0x68, `isExecution`@0x69, `isShared`@0x6A, `damageWithShieldReduction`@0xD8,
**`_applied`**@0xE0, `damageLog`@0xE8, `damageLogPostFix`@0xF8, `useSkillOnHit`@0x100. Struct = **0x108 = 264 byte**.

> `foff.py` đọc được struct (`python3 foff.py DamageInfo 0xNN`) — cùng cách với class. **Tra struct bằng dump.cs, không đoán.**

### ★★ Damage formula — đọc ra được và cross-check bằng "neutral reset"

```
d = ( value * (Max(MinDmgRelatedValue, damagePer) + 1)
            * (Max(MinDmgRelatedValue, damageMult) + 1)
            *  Max(MinDmgRelatedValue + 1, uniqueDamageCompoundMult)
       + damageInc )
  * ( systemScaler + 1 )
```
Rồi round **banker's** (`MidpointRounding.ToEven`), Infinity → `long.MinValue`.

**Làm sao biết 3 floor là hằng `MinDmgRelatedValue` chứ không phải 0 bừa:** 3 lần đọc cùng1 static
(`PTR_DAT_06a6c820 -> staticFields+0x10`). Grepping `dump.cs` với pattern `static double .* // 0x10`
ra **đúng1 dòng**: `Constants.StatLimit.MinDmgRelatedValue` (dòng 9595, class `public static class
Constants.StatLimit`). Xác nhận thêm bằng 4 câu **reset về neutral** ở nhánh apply:
`damagePer=0, damageMult=0, uniqueDamageCompoundMult=1.0(0x3ff0000000000000), systemScaler=0`
— đúng là các giá trị使得 `Max(m,x)+1 = 1` / `Max(m+1,x) = 1`. Nếu floor khác 0 thì reset này không neutral.
→ Dùng **symbol** `Constants.StatLimit.MinDmgRelatedValue` (trong export = 0 vì `.cctor` stub) — không hardcode.

**Banker's rounding:** Ghidra unroll thành `modf` + `if (frac == ±0.5) { if (ip odd) ip += ±1 } else ip = (long)(x±0.5)`.
Đây **chính xác** là `Math.Round(x, MidpointRounding.ToEven)` → viết 1 dòng thay 25 dòng
(`DamageInfo.RoundToLong`), giữ guard `== PositiveInfinity -> long.MinValue`.

### ★ `GetDamage(apply)` — "bake một lần", side-effect là thứ quan trọng

```
!_applied && !apply  -> d = compute (không mutate)          -> return Round(d)
apply && !_applied   -> d = compute
                        _applied = true
                        value = damageWithShieldReduction = Round(d)   // NƯỚNG vào struct
                        damagePer=0, damageMult=0, uniqueDamageCompoundMult=1, systemScaler=0
                        -> return Round(d)
_applied (bất kỳ)    -> d = value thô                       -> return Round(value)
```
**`ApplyDamage` gọi `GetDamage(true)` rồi BỎ kết quả** — nó cần đúng side-effect `value` được nướng
+ `_applied = true`, để mọi `GetDamage()` phía sau (shield math, hp math) trả số đã nướng.
`GetDamage()` (no-arg) ≡ `GetDamage(false)`.

### ★ `DamageBlocked()` = `!NonBlockedList.Contains(blockedBy)`

`BlockedBy` = `None(0) Miss(1) SuperShield(2) SuperMAtkShield(3) SuperAtkShield(4) Ignore(5)`.
`.cctor` stub → `NonBlockedList == null` → **guard**: coi list đúng = `{None, Ignore}`
(None = "không bị chặn", Ignore = "bỏ qua chặn"); `Miss`/`SuperShield*` vẫn chặn.
Nếu list đúng là null thật thì `!Contains(x)` = **true với mọi x = mọi damage bị chặn hết** → không ai đánh trúng ai, nên guard là bắt buộc.

### ★ `GameUnit.battle` — stub `=> null` là bug chặn cả pipeline

Getter thật (RVA `0x308f760`): **`Scene_Game.Instance.battleManagers[GameUnit.battleManagerIdx @+0xA68]`**.
Gốc ném `ArgumentOutOfRangeException`/NRE khi index hỏng; port trả `null` + guard (documented).
`Damaged`/`ApplyDamageToHpImpl`/`Die` đều deref `battle` — không sửa getter này thì **mọi damage bail ra chỗ khác**.

### Solved logic — `ApplyDamage(ref di, from)`

```
di.GetDamage(true)                 // bake (side-effect)
OverwriteDamage(ref di, from)      // [STUB defer] hub 374 dòng
if (shield != null && shield > 0):  // guard: AddShield là stub -> field null
    dmg = di.GetDamage()
    if (shield < dmg) { di.damageWithShieldReduction -= shield
                        buffManager.ConsumePriorityShield(shield); SetShield(0, handleShieldBroken:true) }
    else              { SetShield(shield - dmg, handleShieldBroken:true)
                        buffManager.ConsumePriorityShield(dmg); di.damageWithShieldReduction = 0 }
r = ApplyDamageToHpImpl(ref di, from)
RefreshHpBar(); return r
```

### Solved logic — `ApplyDamageToHpImpl(ref di, from)` → (bool,bool)

```
ApplyHpRatioTriggers(ref di, from)                                  // [stub]
overkill = (curHp < di.value && !di.isExecution)
             ? Round(di.damageWithShieldReduction) - curHp : 0
if (resUnit.GetValueBool(UnitTag.ApplyDamageToHp /*155*/, true))     // Instance! không phải static
    hp = (long)hp - Round(di.damageWithShieldReduction)
if (di.isExecution) di.value = 0
if (hp < 1) {
    hp = 0
    battle.ApplyBuffsToFieldUnits(BuffOption.Conditions.BeforeTeamDead /*40*/, ref di, [this])
    buffManager.ApplyBuffOption(BuffOption.Conditions.BeforeDead /*41*/, ref di, [this])
    rev = PrepareReviveIfCan()
    if (rev.Item1 || rev.Item2) return rev                          // sống lại -> trả kết quả revive
    from.HandleBeforeKillUnit(this, ref di)
    Die(reward:true, deathSkill:_canDeathSkill /*+0x83C*/, suicide:false, from:from,
        doNotTreatAsDead:false, disableEffect:false)
    from.HandleKillUnit(this, ref di)                               // virtual, vtable +0x288
    range = from.GetSkillValueIntSum(di.resSkill, SkillTag.OverKillSplashRange /*129*/, 0)
    if (overkill > 0 && range > 0 && from.overKillSplashFlag /*+0x94C*/)
        HandleOverKillSplashDamage(from, overkill, range)
}
return (false, false)   // CẢ HAI nhánh sống lẫn chết đều (false,false)
```

> **`ApplyDamageToHpImpl` trả (false,false) cả khi chết** — tuple này KHÔNG mang nghĩa "đã chết"
> mà mang nghĩa "đã revive (r.Item1/Item2)". `ApplyDamage` check `r.Item2` chỉ để gate nhánh
> thorns, và sau khi `Die()` thì `live == false` nên nhánh đó tự tắt. **Đừng "sửa" thành `(true,false)`.**

### ★ Tra magic-key enum — kỹ thuật §54 tái sử dụng, không cần Ghidra

`grep -nE "=\s*155," ResourceUnit.cs` → `ApplyDamageToHp = 155`. Tất cả key dùng ở slice này:
`UnitTag`: `InteractionOff=94 (0x5E)`, `DamagedManaOffset=125 (0x7D)`, `DontSwapManaAndBuffBar=128`,
`DamageOwnerToSummoner=153 (0x99)`, `DamagedColor=154 (0x9A)`, **`ApplyDamageToHp=155 (0x9B)`**.
`SkillTag`: `FromDirEffect=125`, `BreakExecutionLimit=126`, `AddExecution=127`,
`DamageColor=128`, **`OverKillSplashRange=129 (0x81)`**.
`BuffOption.Conditions`: **`BeforeTeamDead=40 (0x28)`**, **`BeforeDead=41 (0x29)`** (còn `BattleEnd=3`, `BattleWin=6`, `BattleLose=7` xem §55).

### Deviations / defer (đã document trong code)

- **`OverwriteDamage` (RVA `0x30c5340`) = stub no-op** — hub 374 dòng: `UnitTag 0xA4` zero+`SetBlocked(5)`,
  `ResourceUnit.GetValueDouble` fixed-damage override, magic/physical guard
  (`GetConditionalGuard`/`GetGuardValue`), invincible + `SkillTag 0x82` zero, `GetArtifactValueDoubleSum`.
  Mọi nhánh đều ghi `di.value`/`di.damageWithShieldReduction`. **Đây là defer lớn nhất của slice.**
- `GetDamage(apply)` : nhánh damage-log (`object[5]` + `string.Format`, gate bởi static ObscuredBool).
- `ApplyDamage` : thorns/reflect visual (`UnitController.ShootColor`), **class-K AI redirect**
  (ai có vtable type `PTR_DAT_06a70c88` thì `target = ai.+0xB0` thay vì `this`, + nhánh copy hp từ đó).
- `ApplyDamageToHpImpl` : damage-stat accumulators — `ObscuredLong` blocks @`+0x680` physical /
  `+0x6A8` magic / `+0x6D0` special (chọn theo `Utility.IsMagicDamage/IsSpecialDamage(di.type)`),
  `+0x748` (khi `!_isSkillAttacking && _channelingTime<=0`), `+0x750 = damagedSumDuringChanneling`
  (khi `_channelingTime > 0`), `+0x340 = _strongestSkillDamage` + `+0x330 = _strongestSkillHaveBeenDamaged`,
  và `DealMeterPanel.LogDev(from, to, di, killed)` — **telemetry thuần**.
- `GameUnit.battle` port trả `null` thay vì ném exception (index hỏng).

### Traps đã gặp

- **`ResourceUnit.GetValueBool` là INSTANCE method** (`resUnit.GetValueBool(key, def)`), **không phải static**
  — Ghidra luôn hiện `ResourceUnit__GetValueBool(this, key, def, 0)` nên dễ viết sai 3 tham số.
  (Còn `ResourceTheme.GetValueBool(string key, bool def)` — string key, xem §55.)
- **`hp` là `EncryptedLong` class** với `implicit operator long` + `implicit operator EncryptedLong(long)`
  → `hp = (long)hp - dmg;` và `hp = 0L;` đều hợp lệ, không cần `new`.
- `DealMeterPanel.LogDev(GameUnit from, GameUnit to, DamageInfo info, bool killed)` — có sẵn trong export,
  `Utility.IsMagicDamage/IsSpecialDamage` là **extension trên `DamageInfo.Type`**.
- **`GameUnit.battle` stub `=> null`** — chặn toàn bộ pipeline; getter thật ở `Scene_Game.battleManagers[idx]`.

### Bước tiếp theo (S3e part 3)

`GameUnit.Damaged` (`0x30cb664`, 604 dòng sẵn trong `batch67.log`) → `GameUnit.Die` (`0x30c9588`, 832 dòng) →
`BattleManager.HandleUnitDead` (`0x2eef840`, 869 dòng) — **chain còn thiếu vì `Die()` gọi `HandleUnitDead`**
để gỡ unit khỏi `fieldUnits`, nếu không `CanEndStage` (§55) không bao giờ thấy enemy chết → trận không kết thúc.
Sau đó: `Scene_Game.HandleStageLose`(`0x2e75af4`) / `HandleGameEnd`(`0x2e59770`) / `HandleGameEndImpl`(`0x2e85b3c`) → `POST /game/complete`.

## §57 — S3e part 3: damage entry + unit death + removal + stage-end dispatch (2026-10-19)

Chain hoàn chỉnh: `Damaged` → `ApplyDamage`(§56) → `ApplyDamageToHpImpl`(§56) → `Die` →
`HandleUnitDead` → `Scene_Game.CheckStageEnd` → `HandleStageClear`/`HandleStageLose`.

### GameUnit.Damaged (RVA `0x30cb664`, 604 dòng — `batch67.log` L1930)
`Damaged(DamageInfo damageInfo, GameUnit from, bool forceShowHitEffectOnDeadUnit = false)`.
Ghidra: `param_1 = this`, `param_2 = &damageInfo`, `param_3 = from`, `param_4 = forceShow…`.
Thứ tự đã port:
1. Đồng bộ cờ CC-state: `isFearing(0x7E8) = _fearTime>0`, `isCharming(0x7E9) = _charmTime>0`,
   `isIcing(0x7EA) = _iceTime>0`.
2. `if (!live) { if (!forceShow…) return; ShowHitEffect(); return; }`
3. `if (battle == null || !battle.isBattleStarted(0x364)) return;`
4. `if (from == null || from.resUnit == null) return;`
5. **`UnitTag.DamageOwnerToSummoner(153)` hoặc `from.isMimic(0x22E)` → `from = from.parentUnit(0x538)`**
   (redirect damage về summoner — quan trọng để kill credit đi đúng chỗ).
6. `if (!damageInfo.DamageBlocked() && !isInvincible)` → `FindDamageReductionBuffUnit()`
   → `reducer.buffManager.GetValueDoubleSum(BuffManager.BuffTag.BuffDamageReduction /*=11*/)`
   → `damageInfo.uniqueDamageCompoundMult *= (1 - red/100)`.
   **Lưu ý: `GetValueDoubleSum` nhận `BuffTag`, không phải int.**
7. `if (!damageInfo.DamageBlocked()) ApplyDamage(ref damageInfo, from);`
Deferred: `this is <3 class>` early-return (3 `Il2CppClass*` global, chưa resolve),
`UnitTag.Executable(152)` execution branch, totem-chain (`TotemUnit.Damage`),
projectile (`DamageInfo.ToDamageShootData` + `DamageShooter.Shoot` + `Damage.ChainTo`),
`ShowHitEffect` local-fn, `CheckBlockDamage`/`AdjustBeforeDamaged`/`HandleHitUnit`/`HandleTakeDamage` (vẫn stub).

### GameUnit.Die (RVA `0x30c9588`, 832 dòng — `batch67.log` L1098)
Signature `Die(bool reward, bool deathSkill, bool suicide, GameUnit from, bool doNotTreatAsDead, bool disableEffect)`.
**Ghidra tham số lệch +4**: `param_(4+i)` = C# param_i. Đã xác nhận bằng 3 mốc độc lập —
`param_4 = this`, `param_6 = deathSkill` (gate `GetResUnitDeathSkillID`), `param_8 = from`
(vào `DisplayClass+0x18`), `param_10 = disableEffect` (gate `DieAnim`). `param_1..3` là artifact
của HFA `transform.position` (`_diePosition`@0x900 = 3 float trả về s0/s1/s2, decompiler gán
`_diePosition.y/z = (int)param_2/param_3`). **Law: nếu callee map được `this` ở index 4 thì thứ tự
còn lại khớp y hệt chữ ký C#.**
- CLOSURE `DisplayClass711_0` chỉ chứa `{ +0x10 = this, +0x18 = from, +0x20 = !suicide }` → inline hết.
- Toàn bộ `GameUnit.GetUnitEffects` / `ShowEffect(s)` / `AudioController.Play` / tile-effect tweens
  / pre-grab·fear·charm·ice cleanup (`0x858/0x860/0x868/0x870` + `_fearTime`…) → deferred.

**★ FLAG 0x70F DECODE** — nhánh `if (**(class+0xb8) != 0) if (*(byte*)(*static_fields + 0x70f))`
là `Scene_Game.Instance.useRemoveSummonedUnitsAfterHandleUnitDead`
(**instance** field @ Scene_Game 0x70F, KHÔNG phải static — `**(long**)(class+0xb8)` = static
field `_instance`, rồi `+0x70F` là offset instance). Scene `Assets/Scene_Game.unity` set = 1.
Nghĩa: nó chỉ chọn **điểm gọi** `HandleUnitDead`:
```
removeSummonsFirst = Scene_Game.Instance?.useRemoveSummonedUnitsAfterHandleUnitDead;
if (removeSummonsFirst)  battle.HandleUnitDead(this, from, reward, doNotTreatAsDead);  // early
// … summoned-units cascade (deferred) …
if (!removeSummonsFirst) battle.HandleUnitDead(this, from, reward, doNotTreatAsDead);  // late
```
→ đúng 1 lần gọi. Không phải "có/gọi không".
- `HandleUnitDead(unit, from, reward, ignoreArtifact)` — **`ignoreArtifact` nhận `doNotTreatAsDead`**.
- Cuối method: `incapacitatedManager(0x200).EndSubdue()` → `handleDead(0x1F0)?.Invoke()` →
  `buffManager.ApplyBuffOption(BuffOption.Conditions.Dead /*=39*/, ref default(DamageInfo))` → `Clear(true)`.
- UnitTag đã resolve: `DieWhenOnlySummonsLeft=139`, `DeathTrigger=140`, `UnreserveOnDie=141`(default true).
- Field mới: `parentUnit(0x538)`, `tauntedFrom(0x7F0)`, `hpGauge(0x40)`+`Gauge.canvasGroup(0x28)`,
  `cloneUnitIcon(0x118)`, `hpDestroyAnim(0xB8)`, `summonedUnits(0x528)`, `incapacitatedManager(0x200)`,
  `handleDead(0x1F0)`, `_fearTime(0x264)`, `_charmTime(0x268)`, `_iceTime(0x26C)`,
  `isGrabbed(0x7DD)`, `isFearing(0x7E8)`, `isCharming(0x7E9)`, `isIcing(0x7EA)`.

### UseDeathSkillImpl (local fn `Die.g__UseDeathSkill|4`, RVA `0x3127584`)
Tách closure → method riêng. `CancelMotion()` → `_isMoving=_isAttacking=_isSkillAttacking=false`
→ `resSkill = ResourceSkill.Get(id)` → `_canDeathSkill(0x83C)=false` →
`SkillTag.DeathSkillToFrom(229)` → `targets=[from]` → `UseSkill(resSkill.id, forceSelfTrigger:true, skillTargets:targets)`.
**`isAttacking`/`isSkillAttacking` là read-only property trong export — field thật là `_isAttacking`/`_isSkillAttacking`.**

### BattleManager.HandleUnitDead (RVA `0x2eef840`, 869 dòng — `batch67.log` L229)
`(this, unit, from, reward /*x4*/, ignoreArtifact /*x5*/)`:
1. `if (unit.parentUnit != null) unit.parentUnit.HandleSummonedUnitDead(unit);`
2. `_unitDeadSubject(0x148)?.OnNext((unit, from));`
3. `CheckUnitDeadTriggerArtifacts(unit);`
4. `if (summonedUnits(0xA0).Contains(unit)) { summonedUnits.Remove; fieldUnits(0x70).Remove;
   allFieldUnits(0x68).Remove; [defer] unSummonedUnitTotalDamage rollup; gridMap(0x208).UnregisterAIMapChangeLister(unit.ai(0x2D8)); }`
5. `if (unit.team == Constants.Team.Player)` → [defer] roguelike `RogueLikeBasePanel.ReloadHero`
   `else if (unit.team == Constants.Team.Enemy)` → `unit.battle.gridMap.UnregisterAIMapChangeLister(unit.ai)`;
   `enemies(0x98).Remove`; `allFieldUnits(0x68).Remove`
6. `Scene_Game.Instance.CheckStageEnd();`

**★ `fieldUnits` CHỈ bị Remove ở nhánh summoned-units.** `CanEndStage`/`CountLeftUnit` (§55) đếm theo
cờ `live` chứ không theo membership list — nên unit Player chết vẫn chặn được battle-end dù list chưa dọn.
Không phải bug, đừng "sửa".
`Constants.Team` = static ints: `None@+0 / Player@+4 / Enemy@+8` (Ghidra so `iVar6 == *(static+N)`).

### Scene_Game.CheckStageEnd (RVA `0x2e80824`, `batch72.log` L55)
```csharp
if (_resTheme == null) return;                      // NRE guard
if (_resTheme.isStoryMode /*0x76*/) return;
if (gameEndProcessed /*0x6D9*/) return;
var results = new List<(bool,bool)>();
foreach (bm in battleManagers /*0x230*/) results.Add(bm.CheckStageEnd());
bool canEnd = any Item1, isWin = any Item2;
if (canEnd || isWin) { if (isWin) HandleStageClear(); else HandleStageLose(); }
```
**Khác `BattleManager.CheckStageEnd` (§55)** vốn tự xử lý winningStreak + `ApplyBuffsToFieldUnits(BattleEnd)`
bên trong. Ở đây Scene_Game gom kết quả rồi dispatch.
Deferred: quiz-mode branch (`selectedTeamForQuiz@0x670` / `_pvpWinCount@0x680`) + `WorkTimer.Do`;
`_resTheme.isRankedPvP(0x65)` stage-value-sum bookkeeping.

### Ghidra batch recipe — thêm 1 bẫy mới
Script template clone phải **đổi tên class bên trong file** (`public class decomp_batchNN extends GhidraScript`),
nếu không `analyzeHeadless` báo `ClassNotFoundException: decomp_batchNN not found` và **skip** —
log không có line `##########` nào → nhận ra ngay, không phải đọc nhầm output batch cũ.

### Gate
Compile GREEN (0 `error CS`, `ResourceUnit: 1043 rows`, `ResourceInventoryItem: 173 rows`) +
play-capture GREEN (`shot_Scene_Lobby.png` 291KB, 0 exception). Scene_Game vẫn CHƯA chạy thật
trong capture — gate thật là S3e part 4 (POST `/game/complete` + `GameOverPanel`).

---

## §58 — S3e part 4: runtime gate thật — Scene_Game chạy được trong Editor + master-data generic `Init` (2026-10-19)

### Kết quả

`KGC_CAPTURE_GAMESTART=1` (harness mới) giờ chạy trọn chuỗi: guest login → Scene_Lobby →
`WorldPanel.GameStart()` → `POST /game/start` → `WorkTimer.Do(0.5f, LoadSceneAsync("Scene_Game"))`
→ `Scene_Game.Awake` → `Init` (InitMap → InitStage → OpeningSequence) → `Scene_Game.StartStage()`
→ **0 runtime exception**, screenshot `shot_Scene_Game.png` render map + UI Summon/Expand Troop
+ unit trên field + banner "고블린 도적단 8번째 침락".

Trước khi sửa: 3605 exception/2 phút chạy (2× `GameUnit.Update`, 2× `GameUnit.FixedUpdate`,
1× `Scene_Game.Init`), Scene_Game render được nhưng battle không tick.

### 4 blocker, mỗi cái là một bug class

**1. `WorkTimer.Do` là stub rỗng** (`WorkTimer.cs`) — gate `LoadSceneAsync("Scene_Game")`.
`GameStart` POST xong `200` nhưng scene không bao giờ switch. `WorkTimer` là scheduler được gọi
rải rác (HandleStageClear ×4, Die, CheckStageEnd, Scene_Game.Init…), không phải game logic.

Decode (v174): `UpdateItem` `time@+0x10 timer@+0x14 callback@+0x18 condition@+0x20 loop@+0x28
loopCount@+0x2c index@+0x30` (`UpdateItem..ctor` `0x2cafab0` == `Set` `0x2cafa18`).
`Do(float,cb,cond,loop,loopCount)` (`0x2cb00d4`) = `Do(GenerateSimpleKey(), …, refresh:false)`
→ core `Do` (`0x2cb0024`): key đã có → `refresh=false` thì bỏ qua, `true` thì `item.Set(...)`;
chưa có → `RentItem` + `map[key]=item`.
`IsDone(key)` (`0x2cb0830`): key không trong map → **true**; có → `item.timer <= 0f`
(**item KHÔNG bị xoá khỏi map khi xong**, chỉ timer ≤ 0).
`GenerateSimpleKey` (`0x2caffbc`) = `++_keyIndexer`.
`UpdateImpl` (`0x2cb11bc`) tick: `condition()==null || condition()` → `timer -= dt`; `timer <= 0`
→ invoke; loop → reset timer, hết `loopCount` → bỏ.
Bản gốc dùng object-pool (`UpdateList` sort keys → `PriorityQueue` + `HashSet` return-list) —
đó là tối ưu, không phải semantics. Port thẳng 1 vòng + snapshot key list (callback gọi
`Do`/`Stop` giữa chừng không làm hỏng enumerator). `Instance` lazy-tạo `GameObject("[WorkTimer]")`
+ `DontDestroyOnLoad` (export không có scene object nào chứa MonoBehaviour này).

**2. `readonly` collection bị AssetRipper bỏ initializer — 292 fields, một bug class.**
`public readonly List<BattleManager> battleManagers;` không có `= new …()` → Unity KHÔNG serialize
`readonly` → runtime `null` → `battleManagers.Count` NRE ngay đầu `Scene_Game.Init`.
Bản gốc các field này non-null (initializer chạy trong instance ctor; export không có ctor nào
đăng ký trong `script.json` → cctor/ctor bị strip). Fix root-cause **toàn cục** thay vì patch từng
caller:

```python
# instance: (public|private|…) readonly (List|Dictionary|HashSet|Queue|Stack)<…> name;
#           → name = new T();
# static:   thêm optional 'static' — cctor bị strip nên initializer cũng không chạy.
```

242 instance + 50 static, `Scene_Game` 7, `BattleManager` 6, `GameUnit` 2, `DamageInfo`
(`NonBlockedList` — trước đây phải null-guard ở `GetDamage`), `Constants` 3, `Utility` 3…

**3. Master-data `ResourceTheme.Init` / `ResourceStage.Init` là stub rỗng** → `datas` trống →
`ResourceTheme.Get(1) == null` → `Scene_Game.Init` throw, và mọi `GameUnit.Update/FixedUpdate`
ném NRE 3000 lần/phút (guard `scene.resTheme == null`).

Gần như **mọi** `Resource*.Init` trong export đều là stub. Port tay từng bảng là khoản đầu tư sai
(`ResourceTheme.Init` `0x2e1c6b8` ≈ 2400 dòng decompile, map 147 element name → 94 field).
Thay vào đó `ResourceBase<T>.InitGenericFields(n, aliases)` — reflection, per-T field cache:

- element name == field name, case-insensitive  (`<MaxStage>` → `maxStage`)
- bool nhận thêm prefix `is`                     (`<StoryMode>` → `isStoryMode`)
- alias table cho tên lệch                       (`<Map>`→`mapPrefab`, `<Fog>`→`fogPrefab`,
  `<LobbyRewardIcon>`→`lobbyRewardIconName`, `<Barricade>`→`barricadePrefabs`, `<StartItem>`→`startItems`)
- `List<int>`/`List<string>` **append** (XML lặp element, `<Barricade>`×3 phải tích luỹ)
- type khác (List<struct/class>, Dictionary<int,T>) → bỏ qua, không set

`ResourceTheme` thêm `values` dict (`Dictionary<string,Value>` field **+0xF8**, xác nhận bằng
`HasValue` `0x2e203c8` / `GetValueBool` `0x2e20560` đọc `param_1+0xf8`) = mọi child element
name → innerText. **key == element name** được xác nhận nhân chứng: code gọi
`GetValueText("BattleObserver")` ↔ XML có `<BattleObserver>`.

> **Trap: `Inherit` copy không được đụng field của `ResourceBase<T>`.**
> `GetFields(Instance|Public|NonPublic)` **có** trả về public field của base class →
> `InitInheritFrom` copy `id` từ row cha → row con ghi đè `datas[parentId]`, row con biến mất
> khỏi bảng (`ResourceStage.Count()` 932 thay vì 1224, `Get(101)` = null, `theme` rải rác
> 2100/1001/300…). Fix: `if (fi.DeclaringType != typeof(T)) continue;` — áp cho cả
> `InitGenericFields` (element `<ID>`/`<Name>` sẽ đè `id`/`nameKey` nếu không chặn).
> Cùng guard trong `InitInheritFrom` phải **deep-copy list** (`new List<int>(src)`), không
> share reference — nếu không `InitGenericFields` append làm hỏng row cha.

**Trap: thứ tự trong `ResourceStage.Init`.** `Stages.xml` phẳng, KHÔNG có `<Theme>` child —
`<Stage ID='101' Theme='1' Inherit='1'>` để trong **attribute**. `InitInheritFrom` copy mọi field
đơn giản từ row cha (template stage 1 có `theme=0`) → attribute phải set **SAU** `InitInheritFrom`,
không thì bị đè.

**4. `_stage` không được set.** `_resStages` đã có 13 rows cho theme 1 nhưng `_stage.v == 0` →
`curStage` lấy `_resStages[-1]` → `ArgumentOutOfRangeException`.
Bản gốc đọc từ state đã lưu trên `GameManager`; `WorldPanel.GameStart` chỉ gửi `theme`
(server `r_game_start` cũng tự default `stage=1`). Fallback `_stage.v = 1` như `_theme`.
Kèm fix asymmetry trong getter: `else if (_stage.v - 1 >= 0 && _stage.v - 1 < _resStages.Count)`.

### Bonus: `Constants.xml` drift → `ResourceConstant` fail-closed

`Enum.Parse<Type>(t)` ném trên type lạ (`RerollArtifactCash`, `RerollArtifactGold`,
`LevelLimit_ArtifactSupport` — master data `server/xml_live` mới hơn client build) → **cả bảng
`Constants` fail**. Fix tại đúng 1 chỗ (site parse dùng chung): `Enum.TryParse` + `return` trước
khi store → 1 type lạ chỉ mất row đó. Log warning kèm `ID` để dễ dò.

### Harness: `KGC_CAPTURE_GAMESTART=1` (+ `KGC_CAPTURE_BATTLE_FRAMES`, mặc định 900)

`CaptureScene.cs` thêm phase thứ ba sau login + lobby settle:
1. active scene == `Scene_Lobby` → `FindObjectOfType<WorldPanel>().GameStart()`
2. chờ sang `Scene_Game` (budget 1800 frame) → chờ `curStage != null && playerBattle != null`
   (nghĩa là `Init` xong) → `Scene_Game.Instance.StartStage()`
3. đợi `KGC_CAPTURE_BATTLE_FRAMES` frame rồi chụp

> **Trap: `KGC_MASTER_DATA` PHẢI set cả trong play-capture**, không chỉ trong compile gate.
> `ResourceBase.ReadDataFile` resolve root qua env; không set thì **không có warning nào** —
> master data simply never loads, và triệu chứng đầu tiên là `ResourceTheme.Get(1) == null`
> ở tận `Scene_Game.Init`, rất dễ đoán sai hướng.

### Gate hiện tại

```
compile  : ResourceUnit: 1043 rows / ResourceInventoryItem: 173 rows
           ResourceTheme: 77 rows, theme1 maxStage=10 map=Field_01
           ResourceStage: 1719 rows, theme1 n=13 stage1=1
play     : KGC_CAPTURE_GAMESTART=1 → 0 runtime exception, shot_Scene_Game.png render map+UI+unit
```

`MasterDataSmokeTest` giờ assert luôn 4 contract của generic Init (`ResourceTheme.Get(1) != null`,
`HasValue("MaxStage")`, `maxStage > 0`, `mapPrefab` không rỗng, bool flags của theme 1 đúng,
`ResourceStage.GetAll(theme==1).Count > 0`, `stage > 0`) — fail nhanh trong 3 phút compile gate
thay vì 10 phút play run.

### Deferred (không block gate)

- `Scene_Game.HandleStageLose` (`0x2e75af4`, 567 dòng, đã decompile `batch72.log` L749) /
  `HandleStageClear` (877 dòng, `batch73.log` L54) — UI + reward tail, stub rỗng hiện giờ.
- `HandleGameEnd`/`HandleGameEndImpl` = **async void** → logic nằm trong
  `<HandleGameEnd>d__595.MoveNext` (`0x2ebf91c`) / `<HandleGameEndImpl>d__597.MoveNext`
  (`0x2ec1078`) → `POST /game/complete` → `GameOverPanel`. **Chưa decompile.**
  Lưu ý: `HandleStageClear`/`HandleStageLose` KHÔNG gọi `HandleGameEnd` — chúng gọi `StageEnd`
  (`0x2e81834`, UI teardown + `ClearStageEndDestroySelf` + `GiveItemRewards`) và `StageEndPost`
  (`0x2e823c8`, UI reload + `DealMeterPanel.Stop`) — cả hai đều không đụng network.
- `_stage` chưa được `HandleStageClear` tăng (chạy đa stage) — chỉ stage 1 mới đúng.
- Generic `Init` chưa fill: `ResourceTheme.stageInfos`/`spawnSets`/`effectPrefabs`/
  `upgradeSlotCost`/`rewardGaugeIcons`; `ResourceStage.SpawnData`/`ObstaclePreset`/`RandomEquip`.
  → enemy spawn chi tiết, obstacle, world-trigger chưa có data.
- `ResourceConstant` unknown-type rows bị skip (drift giữa `server/xml_live` và client build).

---

## §59 — S3e part 5: end-of-stage pipeline (StageEnd + HandleStageClear/Lose + NextStage) (2026-10-19)

S3e part 4 (§58) mở được Scene_Game + chạy battle. Part 5 đóng **vòng lặp arena**: thắng stage →
`_stage++` → `InitStage()` stage kế. Gate = `KGC_CAPTURE_KILL_ENEMIES=1` (kill hết enemy để force
battle end — combat thật quá dài/kinh nghiệm để làm gate deterministic).

### 59.1 — `HandleStageClear` (RVA `0x2E767A4`, 877 dòng, `batch73.log` L54)

`_stage++` **ở đây**, không phải `NextStage`. Guard là `!isColosseum && !isSkinPreview && !isStoryMode`:

```
if (!_isStageStarted) return;
activeSkillManager.OnStageClear();
mainUI.activeSkillPopupPanel.Reload()            // defer (accessor stub => null)
int n = playerBattle.itemRewards.Count           // ★ snapshot TRƯỚC StageEnd (StageEnd dọn list)
StageEnd()
reward item counting (playerBattle.items / _itemQueue)   // defer
if (usingTimeScore) { AddStageClearScore(0); ReloadTimeScorePanel(); _stageClearScore = 0 }
music (defer)
if (!isPvPMode && !isColosseum) GiveReward(delay)         // defer — server authoritative
else if (isRankedPvP || isSingleArena) RankedPvPEnemyInfoPanel.RegisterScore / PvPGameOverPanel.RegisterScore
if (isFinalStage && isClanRaid) clanRaidScore += GetClanRaidScore()
if (IsSeasonalQuizMode()) SeasonalEventAnswerPanel.Show(...)
if (isFinalStage && !isColosseum && !isClanRaidDeckRecord) { WorkTimer.Do(1f, <final>); return }
HandleCustomEvent(curStage.GetValueText(<stage custom-event key>))
if (!isColosseum && !isSkinPreview && !isStoryMode) {
    foreach (bm in battleManagers) bm._beforeNextStageSubject.OnNext(true);
    _stage.v++;                                        // ★★★ ADVANCE
    CrashReportHandler.SetUserMetadata("stage", _stage.v.ToString());
}
if (!isColosseum && !isStoryMode) WorkTimer.Do(rewardCount*k + 2f, () => NextStage(false, addedDelay))
```

★ **Trap**: `playerBattle.itemRewards` (BattleManager `+0x230`, `List<Item>`) phải snapshot **trước**
`StageEnd()` — `StageEnd` gọi `GiveItemRewards()` làm cạn list, đọc sau ra 0 → delay sai.
(Chưa dùng vì `GiveReward` còn defer, nhưng giữ nguyên comment để port `GiveReward` không tái bẫy.)

★ **Trap**: `_beforeNextStageSubject` là field `private Subject<bool>` @ BattleManager `+0x170` —
AssetRipper **giữ field, bỏ accessor body** (`beforeNextStageSubject => null`). accessor stub trả
`null` → `OnNext` thành no-op âm thầm, không NRE. Sửa accessor về `=> _beforeNextStageSubject`.

### 59.2 — `HandleStageLose` (RVA `0x2E75AF4`, 567 dòng, `batch72.log` L749)

```
if (!_isStageStarted) return;
activeSkillManager.OnStageLose(theme GetValueBool(<key>))   // key chưa resolve -> false
StageEnd()                                                  // ★ UNCONDITIONAL (hsl.txt L161)
live-- (playerBattle.life / CheckLifeAnim)                  // defer: guard gồm 2 theme key lạ
```

★ **Trap**: `StageEnd()` ở lose path gọi **vô điều kiện** — KHÁNG cái suy nghĩ "chỉ clear mới teardown".
Nếu chỉ `StageEnd()` trong `HandleStageClear`, lose = battle treo với `touchCamera.enabled=false`.

### 59.3 — `StageEnd` (RVA `0x2E81834`, ~150 dòng, `batch73.log` L931)

```
eventMode max-damage rollup (defer: GameUnit.allDamageSum stub => 0L)
if (!skipCamChange) mainUI.SetCamPosition()
_isStageStarted = false;                                    // ★ ObscuredBool @+0x368
if (touchCamera != null) {
    touchCamera.enabled = false;
    if (Time.timeScale < 4f && _theme != _themeEnd) { mainUI.ShowOvertime(); Time.timeScale = 1f; }
}
if (_resTheme != null) {
    if (_resTheme.GetValueBool(<key>)) currentMerchantPopup = null;
    if (!isColosseum) playerBattle.GiveItemRewards();
    mainUI.ReloadWithSkinPreview();
    ClearStageEndDestroySelf();
}
```

★ `_isStageStarted` là `ObscuredBool` 12 byte @ `+0x368`; gán `false` = clear flag end-to-end.
★ `param_1+899` = `+0x383` = **`skipCamChange`** (bool). Đọc qua `Scene_Game.Instance.skipCamChange`.

### 59.4 — `NextStage` (RVA `0x2E821E0`) + `StageEndPost` (RVA `0x2E823C8`)

`NextStage(obstacleChanged, addedDelay)` — bản gốc **trả `float`** (addedDelay đã điều chỉnh),
chỉ gọi nội bộ từ lambda trong `HandleStageClear`:

```
StageEndPost(true);
if (!obstacleChanged) { if (isColosseum) SetStage(_stage.v + 1); InitStage(); }
else { WorkTimer.Do(addedDelay, () => InitStage()); CenterText.Show(<Stage Start key>); }
t = (curStage.HasValue(k1) || curStage.HasValue(k2) || isFinalStage) ? 2.0f : 1.5f;
if (Instance.skipCamChange) { addedDelay = 0; Instance.skipCamChange = false; }
if (playerBattle.isSurvived) WorkTimer.Do(addedDelay, closure ShowStageSurrender);
```

`StageEndPost(win)`:
```
_isStageEndPostCalled = true;                               // ObscuredBool @+0x374
mainUI._showPvPInfoAfterRandomItem = 0;                     // defer (+0x5D8)
foreach (bm in battleManagers) { bm.AddPreventSellUnitStageCount(-1); bm.AddUnlimitedSpawnLevelUpStageCount(-1); }
mainUI.ReloadStageText(win); mainUI.ReloadButtons(true);
mainUI.dealMeterPanel.Stop();
boss-hp-bar teardown loop (defer) ; playerBattle.StageEndPost(); IngameTutorialPanel.StartTutorial (defer)
```

### 59.5 — Field map decode (ResourceTheme + Scene_Game + BattleManager)

`ResourceTheme` bool block @ `+0x60..+0x76` (đọc từ `dump.cs`, khớp 1-1 offset decompile):

| +0x60 | `isEventMode` | | +0x64 | `isPvPMode` | | +0x65 | `isRankedPvP` |
| +0x71 | `isClanRaid` | | +0x72 | `isRogueLike` | | +0x73 | `isColosseum` |
| +0x74 | `isBabel` | | +0x75 | `isSkinPreview` | | +0x76 | `isStoryMode` |
| +0xB0 | `normalMusic` (string) | | +0x94 | `maxStage` | | +0x88 | `stageInfos` |

`Scene_Game`: `+0x2F8 _stage`(AwesomeInt 16B), `+0x308 _theme`(AwesomeInt), `+0x383 skipCamChange`,
`+0x468 gameCompleteRequestModel`, `+0x4D0 _stageClearScore`, `+0x708 _currentStageTimeScalePhase`,
`+0x720 stageEndDestroySelfs (List<DestroySelf>)`, `+0x830 recentlyKilledBossIds`,
`+0x838 currentMerchantPopup`.
`BattleManager`: `+0x170 _beforeNextStageSubject (Subject<bool>)`, `+0x188 items (List<ItemUnit>)`,
`+0x228 _itemQueue (List<Item>)`, `+0x230 itemRewards (List<Item>)`, `+0x3B0 _curObstacle (int)`.

### 59.6 — Properties port

- `isFinalStage` (RVA `0x2E5968C`): `isRogueLike→false; isBabel→true; isSkinPreview→false;`
  `else _stage.v == _resStages.Count`. Defer branch `IsSeasonalModeWithoutDeck()` (đọc `_themeEnd` `+0x300` + `_resTheme.maxStage`).
- `BattleManager.beforeNextStageSubject` → sửa stub `=> null` về `=> _beforeNextStageSubject`.
- `ResourceTheme` mode-bool getters đã port sẵn từ §50 — không phải viết lại.

### 59.7 — Gate: `KGC_CAPTURE_KILL_ENEMIES=1`

Harness `CaptureScene.cs` thêm phase **kill-enemies** sau khi battle chạy `KGC_CAPTURE_BATTLE_FRAMES`:
`foreach (e in playerBattle.enemies) e.Die(false)` (try/catch từng con) rồi chờ 900 frame cho
`HandleStageClear → StageEnd → _stage++ → WorkTimer(1s) → NextStage → InitStage` chạy hết.

Lý do không gate bằng combat thật: thời gian end phụ thuộc AI/stats, không deterministic;
`GameUnit.Clear()` là stub rỗng nên không kill được bằng cách đó — `Die()` là đường chính
(`Die → HandleUnitDead → RemoveUnit → Scene_Game.CheckStageEnd → HandleStageClear`).

### 59.8 — Defer list của part 5 (không block)

`GiveReward`/`GiveRewardImpl`(RVA `0x2E81CF0`)/`AddItemReward`/`CheckBarricadeFromStage` (reward UI —
trên private server gold/item đến từ `POST /game/complete`, server authoritative);
`GetThemeRandomItems`(RVA `0x2E81B30`, đọc `_resTheme.randomItems`)/`GetThemeMerchants`;
`HandleCustomEvent`(RVA `0x2E81D40`, string-dispatch vào `BossSkillGauge.Show/SetStep`);
music selection (`AudioController.PlayMusic` + `_resTheme.normalMusic`); PvP/colosseum/quiz/clan-raid
score registration; `CrashReportHandler.SetUserMetadata`; event-mode round bookkeeping
(`gameCompleteRequestModel` round list); `CheckStageEndImpl`; `HandleGameEnd`/`HandleGameEndImpl`
+ `<HandleGameEnd>d__595.MoveNext`(`0x2ebf91c`)/`<HandleGameEndImpl>d__597.MoveNext`(`0x2ec1078`)
→ `POST /game/complete` → `GameOverPanel`; `MainUI.ShowStageSurrender` + skipCamChange camera tail;
`GameUnit.allDamageSum` (stub `=> 0L`); `activeSkillManager` accessor (stub `=> null`).

### 59.9 — ★★★ BLOCKER MỚI: battle THẬT CHƯA BAO GIỜ CHẠY (khám phá từ gate part 5)

Gate `KGC_CAPTURE_KILL_ENEMIES=1` dispatch `Scene_Game.CheckStageEnd()` trực tiếp
(`isWin=true` vì 0 enemy) → **`HandleStageClear` KHÔNG được gọi, 0 exception**.
Đi ngược ngược dòng tìm được **3 stub chặn chuỗi battle, xếp theo thứ tự chặn**:

1. **`MainUI.CheckFieldUnitCount()` (RVA `0x2FE7818`) stub `return false`**
   → `Scene_Game.StartStage()` **abort TẠI ĐÂY**, trước khi chạy
   `startTimer.SetActive(false); _currentBattlePhase=0; _isStageStarted=true; ... HandleStartStage()`.
   → `_isStageStarted` không bao giờ = true → `HandleStageClear/Lose` guard
   `if (!_isStageStarted) return;` nuốt sạch dispatch.
   Bản gốc (batch82.log):
   ```
   var pb = Scene_Game.Instance.playerBattle;
   if (pb == null || pb.fieldUnits == null) return false;
   if (pb.fieldUnits.Count == 0) { mainUI.centerText.Show(L(key_0unit)); return false; }
   if (pb.fieldUnits.Count == 1 && pb.fieldUnits[0].resUnit.id == 100000-2 /*0x1869E*/)
       { mainUI.centerText.Show(L(key_special)); return false; }
   return true;
   ```
   → **Điều kiện qua gate = có ≥1 unit trên field.**

2. **`Scene_Game.AutoMoveUnitToField()` (RVA `0x2E81090`) stub rỗng**
   → `waitingUnits` không bao giờ được chuyển lên field. Bản gốc (batch82.log):
   ```
   mainUI.CancelDrag();
   int free = playerBattle.maxUnitCount - playerBattle.GetPlayerFieldUnitCount();
   while (free-- > 0) {
       var u = playerBattle.waitingUnits[0];
       if (_resTheme.isColosseum) { ... } else {
           playerBattle.HandleBeforeUnitGridMove(u);
           u.gridObj.parentGrid = playerBattle.fieldGrid;      // gridObj@+0xC8, parentGrid@+0x20
           u.gridObj.Set(playerBattle.fieldGrid.GetEmptyPos());
           playerBattle.HandleUnitGridMoved(u, playerBattle.fieldGrid);
       }
   }
   ```

3. **`BattleManager.AddUnitTo` KHÔNG BAO GIỜ ĐƯỢC GỌI** — grep toàn Assembly-CSharp chỉ ra
   định nghĩa, không có call-site. → `waitingUnits` (BattleManager `+0x78`) và `fieldUnits`
   (`+0x70`) rỗng từ đầu. `BattleManager.maxUnitCount` cũng stub `=> 0`.

4. **Không có enemy** (§59 phần trên): `enemies.Add` không tồn tại trong export;
   `BattleManager.ReBatch`(`0x2EE98D4`)/`AfterBatchEnemies`(`0x2EEA1BC`)/
   `CheckAndSpawnCreatures`(`0x2F0258C`) + `SpawnManager.BatchAIUnit`/`GenSpawnData`/
   `BatchValueSumEnemies`/`HandleSpawnInfoList` đều stub.
   `ReBatch()` thật (batch81.log): iterate `List<BattleManager.LastStageInfo>` (`+0x218`)
   → `SpawnManager.BatchAIUnit(spawnManager, pos, id, level, bm.?, ...)` từng con →
   `AfterBatchEnemies()` → `SetStageTileBuff()`.

★ **Kết luận trung thực**: screenshot §58 (`shot_Scene_Game.png`) chỉ là **map + UI + banner** đã
render đúng — **chưa có combat nào chạy**. `Scene_Game.Init/Awake/InitMap/InitStage` OK,
nhưng seed unit (deck → waiting → field) và spawn enemy đều là stub.

### 59.10 — S3f (tier kế tiếp): pipeline seed unit + spawn enemy

Thứ tự port đề xuất (mỗi bước 1 gate riêng):
1. `MainUI.CheckFieldUnitCount` (2 nhánh, ~20 dòng) — bỏ block ngay.
2. `BattleManager.maxUnitCount` + `GetPlayerFieldUnitCount` (đang `=> 0` / stub).
3. `Scene_Game.AutoMoveUnitToField` (~40 dòng, code ở §59.9).
4. **Seed deck**: tìm call-site gốc của `AddUnitTo` — khả năng nằm ở
   `HandleStartStage`(`0x2E7E06C`) / `InitStage`(`0x2E4ACD0`, đã port §50 nhưng chỉ Init map/stage)
   / `BattleManager.InitHeroPool`(`0x2ED89E0`) / `InitBuildings`(`0x2ED8D04`).
5. **Spawn enemy**: `ResourceStage.SpawnData`/`ResourceTheme.spawnSets` →
   `lastStageInfos`(`+0x218`) → `ReBatch()` → `SpawnManager.BatchAIUnit` (đổ vào `enemies`)
   → `AfterBatchEnemies()`.
6. Khi đó gate kill-enemies mới thật sự exercise được `HandleStageClear`/`HandleStageLose`.

---

## §60 — S3f: seed-deck + spawn-enemy pipeline, phần 1 (decode + 2 stub âm thầm chặn) (2026-10-19)

### 60.1 Kết quả runtime

Capture `KGC_CAPTURE_GAMESTART=1` (2026-10-19, `cap_s3f/shot_Scene_Game.png`):
`exit 0`, **0 exception**, `Scene_Game.Init: theme=1 stage=1 maxStage=10 map=Field_01`,
Scene_Game render thật (HUD "고블린 도적단 8번째 침략", Summon 3 / Expand Troop 10 / 0-5 slot),
**1 knight sprite trong world**. Không có marker `[S3e§59] HandleStageClear` → chưa hề clear stage
(chữ "8번째 침략" là text placeholder, không phải stage thật).

### 60.2 ★ Theme 1 (arena thường) KHÔNG CÓ `StartUnitLevels` → bàn cờ bắt đầu TRỐNG

`CheckGameStartEffects` chỉ seed hero khi
`_resTheme.startUnitLevels != null && Count >= 1 && !_loadBabel` (nhánh `[D]`).
Quét `server/xml_live/Themes.xml`: **chỉ theme 1000 và 1002** có `<StartUnitLevels>`
(`3,3,3,3,3,3`) + `<StartItem>101</StartItem>`. Theme 1 (`고블린 습격`, `Map=Field_01`,
`MaxStage=10`, `BossUnit=20040`) **không có element đó, cũng không `<Inherit>`** →
`startUnitLevels == null` → nhánh `[D]` bị bỏ qua → 0 unit được seed.

**Suy ra (khẳng định bằng BL-scan)**: trong arena thường, unit chỉ vào bàn cờ qua
`BattleManager.AddUnitToWaitings`, và caller duy nhất hợp lý là **`GenRandomHero` (nút Summon)**.
Các caller còn lại: `CheckGameStartEffects`(chỉ theme có startUnitLevels), `InitSingleArenaRecordStage`,
`HandleInstantItem`, các lambda của `UpdateImpl`, `LoadColosseumSnapshot`,
`MainUI.OnClickDevMenu`, `OnClickRandomHero`. `BattleManager.AddUnitTo`
(giỏi `fieldUnits`/`waitingUnits`) **không có caller arena-fresh nào**.
→ `CheckFieldUnitCount()==false` → `StartStage()` return sớm → `_isStageStarted` không bao giờ true
là **hành vi đúng**, không phải bug. Muốn có unit phải Summon (port `GenRandomHero`, §60.8).

### 60.3 ★ 2 stub âm thầm đã sửa (compile xanh nhưng chặn seeding)

| File | Stub cũ | Đã sửa thành | Vì sao chặn |
|---|---|---|---|
| `Scene_Game.cs` | `public int stage => 0;` | `public int stage => _stage.v;` | `AddUnitToWaitings` auto-place unit lên field chỉ khi `stage == 1` (hoặc `isBabel`). Stub `0` ⇒ mọi unit nằm mãi ở `waitingUnits`. |
| `BattleManager.cs` | `public EncryptedInt[] heroPool => null;` | `=> _heroPool;` | `CheckGameStartEffects` đọc `pb.heroPool.ToList()` ⇒ stub `null` ⇒ `ArgumentNullException`. |

> **Bài học**: stub có kiểu trả về hợp lý (`=> 0`, `=> null`) không bao giờ gây `error CS`.
> Khi port một hàm dùng accessor X, kiểm tra X **đã port chưa** — grep stub `=> 0` / `=> null`
> trong accessor mà code mới đọc, không chỉ trong hàm mới.

### 60.4 `CardInfo` — class data thật (dump.cs @234009, KHÔNG nhầm với `CardInfoPanel.*`)

```
cardId@0x10  level@0x14  skin@0x18  potentialTier@0x1C  overcome@0x20  dimensionLevel@0x24
isLevelSyncApplied@0x28  treasure@0x30  accessories@0x38(List<AccessoryModel>)
```
`BattleManager.GetCard(int unitId) → CardInfo` (RVA ~0x2EFD0D8, dump.cs L46885).
Tất cả field là `int` thuần (không `ObscuredInt`) — disasm có gọi `ObscuredInt.op_Implicit`
là round-trip int→ObscuredInt→int của compiler, giá trị cuối vẫn bằng field.

### 60.5 `AddUnitToWaitings` (RVA 0x2EF9A7C) — đã port (§60.6) với mapping disasm-proven

Đọc disasm toàn khung, mapping **chuẩn** (Ghidra reorder + drop args, không tin decompile):

| Arg `SpawnManager.SpawnUnit` | Nguồn (disasm) |
|---|---|
| `pos` | `Vector2` static field đầu tiên của class @`0x694fd70` → `Vector2.zero` (placeholder, bị `gridObj.Set` ghi đè ngay) |
| `id` | `w21` (param) |
| `team` | `w2 = 1` = `Constants.Team.Player` |
| `level` | `[sp,#0x23c]` = `w24` = **param `level`** |
| `cardLevel` | `w4 = 1` — **hardcode 1**, KHÔNG lấy từ card |
| `buildingLevels` | `null` |
| `skin` | `[sp,#0x238]` = `w23` = `cardInfo.skin` |
| `artifacts` | `get_artifacts()` (vẫn là stub → null) |
| `poolIdx` | `w20`: `_heroPool[i]==id` → `i+1` (1-based), không thấy → `-1` |
| `potentialSlot` | `w26`: `potentialSlots[i]` khi tìm thấy poolIdx,否则 `-1` |
| `potentialTier` | `[sp,#0x74]` = `w20` = `cardInfo.potentialTier` |
| `parent` | `null` |
| `treasure` / `accessories` | `x27` / `x24` = `cardInfo.treasure` / `cardInfo.accessories` (đọc `ldp x27,x22,[x25,#0x30]`) |
| `fixPos` | `false` |
| `statueIndex` / `statueId` | `-1` / `-1` |
| `overcome` / `dimensionLevel` | `w29` / `w22` = `cardInfo.overcome` / `cardInfo.dimensionLevel` |

Nhánh `isRogueLike` đọc `rlCard+0xc8`(potentialTier)/`+0xe4`(overcome)/`+0xe8`(dimensionLevel)
— **defer** (chỉ dùng cho roguelike).

Tail: `u.isField=false` → `if (battleManagerIdx != 0) SetActive(false)` → `waitingUnits.Add(u)`
→ `u.gridObj.parentGrid = waitingGrid; u.gridObj.Set(waitingGrid.GetEmptyPos())` →
`SetDraggable(true); ShowHpGauge(false,true); SetAI(null)` → nếu `(stage==1)||isBabel`
và `maxUnitCount > GetPlayerFieldUnitCount() && !isBattleStarted && !isStageStarted && !isTestMode`
và `!(battleManagerIdx==0 && !colosseumIsReady && isColosseum)` thì
`HandleBeforeUnitGridMove(u)` → `gridObj.parentGrid = fieldGrid` → `Set(fieldGrid.GetEmptyPos())`
→ `HandleUnitGridMoved(u, fieldGrid)` → `CheckPopItemQueue()` (0x2EF6F1C) →
`CheckTransformCondition(u, false)`.

Field map mới: `Scene_Game.colosseumIsReady@0x118`, `BattleManager.battleManagerIdx@0x34` (int!).

### 60.6 Đã port trong phần này

1. `BattleManager.AddUnitToWaitings` (xem 60.5).
2. `Scene_Game.CheckGameStartEffects(out int bonusTier)` — nhánh `[B]` `startItems`→`GetItem(id,true)`,
   `[C]` `InitArtifactItems()`, `[D]` seed `SlotUp(n - slotBonus)` + `heroPool.ToList()` +
   `Shuffle()` (trừ `isBabel`) + loop `AddUnitToWaitings(pool[i], levels[i])` +
   `SetTilePosition(new Vector2Int(i + i/3, 0))` (magic div-by-3 = disasm `umull #0xAAAAAAAB; lsr #33`),
   exit-branch `fieldUnits.Find(x => x.resUnit.id == 99998)` →
   `SetTilePosition(new Vector2Int(gridMap.width/2, 0))`. Defer `[A]` (DOTween tarot delay +
   isSingleArena early-return đã port `bonusTier=0; return;`).
3. Sửa 2 stub (§60.3).

Compile gate `s3f2gate.log`: **0 `error CS`**, đủ 4 dòng smoke.

### 60.7 Cấu trúc master-data cho enemy spawn (đã decode)

```csharp
ResourceStage.SpawnData (class):            y@0x10, spawn: SimpleSpawn[]@0x18
ResourceStage.SpawnData.SimpleSpawn (struct, 0x10): pos@0x0, boss@0x4, level@0x8, id@0xC
ResourceTheme.SpawnSet (class):             stages(List<int>)@0x10, levels(List<int>)@0x18
BattleManager.LastStageInfo (struct, 0x28): unitId@0x0, pos(Vector2Int)@0x4, level@0xC,
                                            boss@0x10, skin@0x14, equips(List<int>)@0x18,
                                            preservedItems(List<Item>)@0x20
```
`GridMap.width@0x10` (outer class; dump grep sẽ va nhầm nested `PathNode.operation@0x10`).
`ResourceStage` còn có `mySpawnDatas@0x40`, `spawnDatas@0x48` (Dictionary<int,List<Spawn>>);
`ResourceTheme.spawnSets@0x128`.

### 60.8 Chuỗi spawn enemy — TOÀN BỘ còn là stub

**BL-scan (v174) chứng minh wiring:**

```
Scene_Game.InitStage()
  └─ bm.AfterInitStage(_devilEffectCount, _devilCond)      [BattleManager.cs:861 — STUB]
       ├─ DisposeWorldTrigger(null)
       ├─ AddWorldTriggerBundle(theme-res @ curStage+200) / AddWorldTriggerBundle(stage-res)
       └─ spawnManager.InitStage(devilEffectCount, devilCond)   [SpawnManager.cs:10 — STUB, RVA 0x3131E24]
            ├─ GenSpawnData(...)              [SpawnManager.cs:14 — STUB, RVA 0x3134CA0]
            └─ BatchValueSumEnemies(...)      [SpawnManager.cs:18 — STUB, RVA 0x31363B8]
                 └─ BatchAIUnit(...)          [SpawnManager.cs:22 — STUB, RVA 0x3137E74]
                      └─ SpawnManager.SpawnUnit(...)  ← ĐÃ PORT
```
`GenSpawnData`/`BatchValueSumEnemies` còn có caller thứ hai: `Scene_Game.InitRogueLikeStage`.

**`ReBatch()` (RVA 0x2EE98D4, `BattleManager.cs` STUB)** — sinh lại enemy từ `_lastStage(+0x218)`:
```csharp
public void ReBatch() {
    if (effectAreaDrawer != null) effectAreaDrawer.Clear();      // +0x58
    if (_lastStage != null)
        foreach (var info in _lastStage)
            if (Scene_Game.Instance.isTestMode) { /* defer: batch preset test (ResourceUnit.GetValueBool(key 0x1D9, true)) */ }
            else {
                var u = spawnManager.BatchAIUnit(info.pos, info.unitId, info.level, 1 /*team arg*/,
                        info.boss, info.equips, reBatch:true, ..., info.skin, ...);
                if (info.preservedItems != null) foreach (var it in info.preservedItems) u.Equip(it);
            }
    AfterBatchEnemies();
    // nếu "đã batch" → SetStageTileBuff()
}
```
`ReBatch` ← `Scene_Game.{Revive, TestRun, HandleStageLoseCallback_Babel, <HandleStageLose>b__0}`.
`AfterBatchEnemies` ← `Scene_Game.{InitStage, LoadGame, InitRogueLikeStage, BatchFinalRogueLikeBossUnit}` + `ReBatch`.
`AfterBatchEnemies` (RVA 0x2EEA1BC) đọc `Scene_Game.curStage`:
`curStage+0xA8 == 100` → `Dictionary<int,object>()`, ngược lại → `bm.enemies(+0x98).ForEach(...)`.

**`BatchAIUnit` (RVA 0x3137E74) — 25 param, core đã decode:**
```csharp
public GameUnit BatchAIUnit(int id, Vector2Int pos, int level, int team = 2, int boss = 0,
    List<int> equips, bool reBatch = false, int cardLevel = 1, int[] buildingLevels,
    int skin = 0, List<ArtifactModel> artifacts, int poolIdx = -1, int potentialSlot = -1,
    bool equipExcept4TierOption = false, int potentialTier = 0, bool loaded = false,
    TreasureModel treasure, List<AccessoryModel> accessories, bool skipAnimation = false,
    bool fixPos = false, bool fixEquip = false, int statueIndex = -1, int statueId = -1,
    int overcome = 0, int dimensionLevel = 0)
```
Flow: tạo display-class; `if (Scene_Game.Instance.???@+8 != team) pos = pos.ToReversePos(gridMap)`
(dùng `Scene_Game.Instance.playerBattle.gridMap`); bounds-check `pos` so với
`gridMap+0x58`(min) và `gridMap+0x60`(max) → sai thì `Debug.LogError` + `return null`;
`if (Scene_Game.Instance.???@+8 == team) level = Scene_Game.Instance.GetUnitLevelByDifficulty(level)`;
`GridMap.GetPosition(gridMap, pos)` → `spawnManager.SpawnUnit(...)` → lưu vào holder@+0x18;
`u.SetAI(AIFactory.GetSuitableAI(u))`; `u.tilePos@+0x568` ↔ `creatureInfo.prevPos@+0x28`;
`u.gridObj.parentGrid@+0x20 = fieldGrid(+0x198)`; `boss==2` → `Scene_Game+0x740 = resUnit.GetValueInt(key 0x4F)`;
`u.RefreshLevelIcon()`; `!skipAnimation` && `!isTestMode` → alpha/`SetActive`/`UnitEffect` loop.

**`GenRandomHero(bool isAdSummon = false)` (RVA 0x2EF8738, `BattleManager.cs:1736` STUB)**
= nút Summon. Core: guard `Scene_Game.Instance.isSingleArenaPreparationBattle` → return;
`waitingUnits.Count`/`fieldUnits.Count`; mana-gate `EncryptedInt@+0x388` (spawn cost) +
`ResourceConstant.Get(0x4A)` + `Utility.CheckLevelAvailable` + `Constants.IsInvasion/IsEventBattle`;
chọn id từ `_heroPool(+0x200)`; rồi **`AddUnitToWaitings(id, level=uVar8 + 1)`** (line 566).
`MainUI.OnClickSummon` RVA `0x3305770` (decompile batch90).
→ **chưa port**.

### 60.9 Các RVAs mới trong phần này

| Hàm | RVA | Trạng thái |
|---|---|---|
| `BattleManager.AddUnitToWaitings` | 0x2EF9A7C | **PORTED §60** |
| `Scene_Game.CheckGameStartEffects` | 0x2E4A0F0 | **PORTED §60** |
| `<CheckGameStartEffects>b__515_1` | 0x2EACA90 | `u => u.resUnit.id == 99998` (inlined) |
| `BattleManager.AfterInitStage` | 0x2EDE390 | decode — cần port |
| `SpawnManager.InitStage` | 0x3131E24 | decode — cần port |
| `SpawnManager.GenSpawnData` | 0x3134CA0 | decode — cần port |
| `SpawnManager.BatchValueSumEnemies` | 0x31363B8 | chưa decode |
| `SpawnManager.BatchAIUnit` | 0x3137E74 | decode — cần port |
| `SpawnManager.HandleSpawnInfoList` | 0x313AAB8 | chưa decode (gọi từ `EventTriggerManager.HandleEventTriggered`) |
| `BattleManager.GenRandomHero` (Summon) | 0x2EF8738 | decode — cần port |
| `MainUI.OnClickSummon` | 0x3305770 | decompile batch90 |
| `BattleManager.ReBatch` | 0x2EE98D4 | decode — cần port |
| `BattleManager.AfterBatchEnemies` | 0x2EEA1BC | decode — cần port |
| `BattleManager.SetStageTileBuff` | ? | stub |
| `BattleManager.CheckPopItemQueue` | (gọi 0x2EF6F1C) | gọi từ AddUnitToWaitings |
| `Utility.ToReversePos(pos, gridMap)` | static | `Utility.cs:1045` |

### 60.10 ★ Enemy spawn thực sự của arena thường = `BatchValueSumEnemies` (ngân sách `ValueSum`)

Quét `server/xml_live/Stages.xml` (21 stage theme 1):

| Stage | `ValueSum` | `<Spawn>` explicit | id |
|---|---|---|---|
| 101 | 0 | 7 | `99999` (KHÔNG có trong `Units.xml` → ô placeholder rỗng) |
| 102 | 3 | 0 | — |
| 103 | 4 | 0 | — |
| 104 | 5 | 0 | — |
| 105 | 4 | 1 | `20020` (boss/elite) |
| 106 | 5 | 0 | — |

→ **`ResourceStage.valueSum`(@+0x78) là ngân sách**, `BatchValueSumEnemies(valueSum, …)`
tự chọn enemy từ `enemyPool` sao cho tổng "giá trị" ≤ ngân sách. `<SpawnData>` chỉ dành cho
wave đặc biệt (boss/elite). `GenSpawnData` xử lý `<SpawnData>` explicit.
`<Inherit='N'>` kế thừa row khác (stage 102 `Inherit=2`, 103 `Inherit=3`, …) —
`ResourceBase<T>` đã xử lý inherit, `InitGenericFields` COPY list tránh share reference.

→ **Thứ tự port còn lại của S3f (mức ưu tiên)**:
1. `SpawnManager.BatchValueSumEnemies` (`0x31363B8`) — generator chính của arena.
2. `SpawnManager.GenSpawnData` (`0x3134CA0`) — wave explicit (`<SpawnData>`).
3. `SpawnManager.BatchAIUnit` (`0x3137E74`) — decode xong (§60.8), port.
4. `BattleManager.GenRandomHero` (`0x2EF8738`, nút Summon) — CHẶN mọi unit của player.
5. `BattleManager.ReBatch` (`0x2EE98D4`) + `AfterBatchEnemies` (`0x2EEA1BC`) + `SetStageTileBuff`.
6. `BattleManager.InitStageStartUnitData` (`0x2EE6560`) — **SNAPSHOT** fieldUnits/enemies vào
   `stageStartData@+0x2A0` / list@+0x2A8 (mỗi entry 0x18 byte: `+0x20`=tilePos, `+0x24`=0,
   `+0x28`=resUnit, `+0x30`=level, `+0x34`=0); bỏ qua unit `resUnit.id==0x1869E`(99998).
   Đây là "ghi lại bàn cờ lúc bắt đầu trận" để restore khi retry — KHÔNG phải seeder.

`AfterInitStage` đã port trong phần này (chỉ giữ nhánh `DisposeWorldTrigger` +
`spawnManager.InitStage`; 2 nhánh `AddWorldTriggerBundle(curStage+0xC8 / +0x58)` defer).

**Gate**: `s3f3gate.log` — 0 `error CS`, đủ 4 dòng smoke. `cap_s3f` (GAMESTART) — exit 0, 0 exception.

## §61 — S3f: enemy-spawn pipeline — runtime-proven end-to-end (2026-10-19)

### 61.1 Chuỗi spawn enemy (đã port + chạy thật)

```
Scene_Game.InitStage
  → BattleManager.AfterInitStage        (port: chỉ giữ DisposeWorldTrigger + spawnManager.InitStage;
                                         2 nhánh AddWorldTriggerBundle defer)
  → SpawnManager.InitStage   (0x3131E24) — bản gốc ~1000 dòng, port bản arena-core
  → SpawnManager.GenSpawnData (0x3134CA0)
  → SpawnManager.BatchAIUnit  (0x3137E74) — funnel spawn-info → SpawnUnit + bookkeeping + đăng ký
  → SpawnManager.SpawnUnit    (0x3139478) — unitPool.Rent / Instantiate → unit.Init(...)
```

- `GenSpawnData(data, team, addLevel, usedPos, applyStoryModeSpec)`: duyệt `{Y → List<Spawn>}` của
  `Stage.spawnDatas` (Team=2 → địch) / `mySpawnDatas` (Team=0 → player, chỉ mode đặc biệt).
  `usedPos` dedup: cùng ô chỉ 1 spawn địch. `[SPAWN-DIAG]` log từng dòng để chẩn.
- `BatchAIUnit`: `pos.ToReversePos(gridMap)` cho team != Player (địch trượt nửa đối diện bàn —
  grid cao 12: reqPos y=2 → tile y=9, chứng minh runtime `(2,2)→(2,9)`) → bounds-check
  minPos/maxPos (out → LogError + null) → enemy: `level = scene.GetUnitLevelByDifficulty(level)`
  → `SpawnUnit(worldPos,…)` → `AIFactory.GetSuitableAI` → **tilePos bookkeeping** →
  `SetAI/SetLevel/SetBoss/RefreshLevelIcon` → **đăng ký vào list team**.

### 61.2 Hai khối bookkeeping then chốt (port từng bỏ sót — "0 enemy để kill")

1. **tilePos** (sau `GetSuitableAI`, trước `SetAI`): `unit.tilePos@0x568 = gridMap.GetTilePosition(worldPos)`;
   `unit.gridObj.tilePos@0x28 = tilePos`. Hai hàm `GetPosition`/`GetTilePosition` là hai chiều
   ngược nhau → round-trip = pos gốc; port dùng thẳng `pos` (đã ToReversePos) để tránh mất số
   nguyên. **Trước đây bỏ → mọi unit tile=(0,0) → grid/battle logic đọc sai ô.**
2. **Đăng ký team** (cuối `BatchAIUnit`, bản gốc):
   ```csharp
   if (!reBatch && bm.allFieldUnits != null) {
       bm.allFieldUnits.Add(unit);                       // LUÔN
       if (team == Constants.Team.Player) bm.fieldUnits.Add(unit);
       else bm.enemies.Add(unit);                        // Constants.Team đọc statics @+0xb8+4
   }                                                      // re-batch KHÔNG re-add (tránh double-count)
   ```
   **Root cause kép của "0 enemy để kill"**: (a) port arena-core bỏ khối này; (b) AssetRipper bỏ
   field initializer → `bm.enemies/fieldUnits/allFieldUnits` = null (cùng gốc rễ với §58's 292-site
   fix) → CanEndStage đếm 0 enemy → isWin ngay lập tức.

### 61.3 Exonerations (các nghi phạm đã được xử sạch, KHÔNG phải lỗi)

- **Master data/server**: `[SPAWN-DIAG]` chứng minh server phục vụ đủ 7 dòng `<Spawn>` stage 101.
- **id 99999 không có trong `Units.xml`**: benign — spawn thành unit shell dùng sprite placeholder
  (`Sample_Stun_0`, sprite thật `Unit_10000_18` khi resUnit resolve được), vẫn register/kill được.
- **tilePos=(0,0)**: không phải lỗi grid/mapping — chỉ là bookkeeping bị bỏ (§61.2.1).
- **`Utility.GetWeightedRandom` stub** (trả về index 0): không chặn enemy (không dùng cho enemy pool);
  summon thì đã có guard `idx<0 → 0`.

### 61.4 Constants.Team + Spawn attr map

- `Constants.Team` là **static-class**, `cctor` (0x3033C94) gán các statics; offset đọc trong code
  là **byte-offset trong static-fields** (Player@+0xb8+4…) — KHÔNG phải giá trị. `GetOtherTeam`
  (0x3033BE0). Port: inline initializer giống runtime.
- `<Spawn>`/`<SpawnData>` attr map (đã port trong `Spawn` class): id/level/pos-x/pos-y/count/boss/
  equips/fix-equip/statue-index… Theme 1 stage 101 = 7 scarecrows id 99999 (§60.10).
- **Sửa note cũ sai**: `0x3305770` = `MapSkinInfoPanel.OnClickSummon` (panel skin), KHÔNG PHẢI nút
  summon của battle (nút thật = `MainUI.OnClickRandomHero` §62).

### 61.5 Verification (runtime)

- `cap_s3f7`: 7 scarecrows spawn + register (`bmEnemies=7`) + kill được bằng `e.Die()` thật.
- `cap_s3f9`: tilePos thật `(1,10)`.
- **`cap_s3f13` (full loop hai phía, gate `s3f13gate` xanh)**: login → lobby → GameStart →
  `Init` (seed slotBonus=3 → maxUnitCount=3) → `GenRandomHero` (chosen=10000) → unit auto-place
  `playerField=1` → StartStage → 7 enemies spawn tile=(2,9)/(4,9) (`bmEnemies=7`) → combat tick
  (`[SHOT-DIAG]` 7 mục tiêu) → kill-all → `CheckStageEnd` → **`HandleStageClear → _stage++ = 2`**
  → PNG `shot_Scene_Game.png`. **0 exception.**

### 61.6 Deferred (S3f enemy pipeline)

BatchValueSumEnemies (stages 102+, generator chính — stub); GenSpawnData: conditionKey filter /
equip-gen / clan-raid idList / story snapshot / challenge statue / spawnPeriod / destroy-duplicate;
BatchAIUnit: bm+0x218 enemy bookkeeping (spawn-info pos/equips — không liên quan win-count),
boss==2 `bossTimeBonus` (key 0x4f không resolve) + DOTween spawn-drop anim; SetResourceUnit tail;
SetTeam tint; team z-layer.

## §62 — S3f: summon / deck / slot — mở khoá battle start (2026-10-19)

### 62.1 ★★★ EncryptedInt là stub HOÀN TOÀN — nguyên nhân gốc sâu nhất của chuỗi "battle không start"

`AwesomeData.Encrypted.EncryptedInt` (byte[] `_value` + int `_key`, gốc mã hoá XOR anti-tamper):
stub cũ = ctor **rỗng** (không lưu), `GetDecrypted()`→0, `implicit operator int` → **`return 0`**,
`implicit operator EncryptedInt(int)` → **`return null`**. Compile xanh, chạy sai âm thầm (§60.3
mức độ class — một GIÁ TRỊ TYPE stub thì MỌI `(int)x`=0):

- `GenRandomHero` filter: `ResourceUnit.Get((int)id)` = `Get(0)` = null → **afterFilter=0** →
  không summon được (log `cap_s3f12`: `heroPool.len=6 nonNull=6 afterFilter=0`).
- `BattleManager.slot/slotBonus`: setter `_slot = op_Implicit(value)` = **NULL**, getter stub → 0
  → seed loop chạy mà `maxUnitCount` vẫn 0 → `AutoMoveUnitToField` không place gì.

**Fix**: bản rebuild là plain-value wrapper (`_plain` int; null-guard `op_Implicit`→0 giữ hành vi
stub cũ). Protocol/save KHÔNG serialize class này (wire dùng int nguyên) → anti-tamper không cần.
Sau fix: `cap_s3f13` `afterFilter=5` (1 hero bị loại thật bởi LateComers), `chosen=10000`,
`playerField=1` (tức maxUnitCount=3 đã sống).

→ **Luôn nghi ngờ một GIÁ TRỊ CLASS stub trước khi port caller đọc nó**: EncryptedInt (đã fix),
ObscuredInt (CodeStage — THẬT, proven: `.value` cho id/level chuẩn), AwesomeInt (`.v` — THẬT).

### 62.2 Deck: GetDefaultDeck + currentDeck

- `PlayerData.currentDeck` **KHÔNG BAO GIỜ được gán** trong port (grep `.currentDeck =` → 0) →
  `Scene_Game.Init` LUÔN fallback `GetDefaultDeck()`.
- `GameManager.GetDefaultDeck` (0x314BAE4, batch101): cache path (static+0xb0, `GetCard` stub→null
  nên All luôn false anyway) **defer**; compute: `data.cards` có `level.value>0 && ResourceUnit.Get!=null`
  → sort desc theo level → take 6 → `unitId.value[]`. Runtime: 6 hero mặc định.
- `BattleManager.InitHeroPool` (0x2ED89E0): `_heroPool = deck.Select(id => new EncryptedInt(id)).ToArray()`
  (sửa EncryptedInt là đủ —之前 ctor rỗng nên mọi entry _plain=0).

### 62.3 ★ Init slot-seed loop (RVA 0x2E463C4, trong `Scene_Game.Init`) — chốt maxUnitCount

```csharp
if (_resTheme != null && !isRogueLike)
    foreach (var bm in battleManagers) {
        bm.tileBuffs?.Clear();      // _tileBuffs@+0x220 (List, §58 initializer)
        bm.slot = 0;
        bm.slotBonus = 3 - (int)bm.GetArtifactValueSum("MinusSlot");
    }
```

- Disasm-proven: `w22=3` hằng; `(int)+Inf` idiom = `FCVTZS` + `fcmp +Inf` + `csel w1,0x80000003,…`
  = unchecked wrap mặc định của C# → biểu thức C# thường là đủ; `GetArtifactValueSum` stub → 0.0
  → slotBonus=3.
- **Key `"MinusSlot"`** (artifact penalty slot — base 3, không artifact → 3): resolve bằng
  **★★★ ADRP LAW**: `disasm_ctx.py` (capstone theo FILE offset) in ADRP target theo **trang file**;
  target VMA/GOT thật = printed + **0x4000** (code delta). `0x6961b20` → `0x6965b20` →
  `R_AARCH64_RELATIVE` → `0x6baa860` → ScriptString `"MinusSlot"`. Mọi key GOT resolve theo cách
  này trước đây bị lệch 1 trang (PTR_DAT_* lookup trực tiếp thì đúng, không ảnh hưởng).
- **Math cross-check**: theme CÓ `StartUnitLevels` (count=6): `SlotUp(6 − slotBonus=3)` → `_slot=3`
  → maxUnitCount=6=count ✓; theme 1 (không có → khối bỏ qua): slot=0+slotBonus=3 → **maxUnitCount=3** ✓.
  → KHÔNG cần theme-SetSlot key cho theme 1 (path SetSlot chỉ theme 2000/2100).
- Hai call `playerBattle.GetArtifactValueSum` phía trên (→ `EncryptedInt` @Scene_Game+0x6b8/+0x6b0):
  key đã resolve = `"MerchantRefreshCost"` (GOT 0x6965ac0→0x6baa4c0) / `"MerchantRefreshTime"`
  (0x6965a38→0x6baa4c8) — merchant UI/economy fields, defer (không ảnh hưởng battle).
  Post-loop field inits (+0x3f8/+0x530/+0x37c) defer.
- `_slot`/`_slotBonus` writer map: `set_slot` ← Scene_Game.Init / LoadGame / LoadPlayerUnits /
  HandleInstantItem / GameManager.InitRogueLike; `set_slotBonus` ← same + InitSingleArenaRecordStage /
  LoadRogueLikeImpl / RogueLikeRoom.EnterRoom / DevRogueLikeItemPanel.Close.
- `LoadPlayerUnits` (0x2E6C420): `SetGold(data+0x88); slot=data+0x8c; slotBonus=data+0x90;
  SetSpawnLevelUpCount(data+0xc4)` — mọi bước `cbz data → no-op`; **chỉ caller = InitStage**;
  fresh stage (data=null) → không ghi đè slot.

### 62.4 Property stubs đã sửa (BattleManager)

- `slot`/`slotBonus`: stub `return 0`/no-op → wrapper thật quanh `_slot`/`_slotBonus` (EncryptedInt).
- `tileBuffs` getter `=> null` → `_tileBuffs` (không caller nào phụ thuộc null); `_tileBuffs`/
  `_itemQueue` thêm `= new List<…>()` (§58-class).
- `SetSlot(count)` (0x2EFB51C) = `_slot = count`; defer: mainUI slot-label refresh + đếm enemy
  +0x7E9 (UI-only). `SlotUp` (0x2EFB090) decode xong nhưng **để sau stub `CanSlotUp()`→false**
  (theme 1 không cần; body gồm ReloadUnitCount/ShowAnim/Firebase/ApplyWorldTrigger(6) — defer).
- `HandleCheckGameStartEffects` (0x2EDD93C) = **`_itemQueue.Clear()`** (list @+0x228; original NRE
  nếu null → guard). Không battle-critical.

### 62.5 CheckGameStartEffects — LAB tail theme 1 = no-op (early-return là tương đương)

LAB tail (shared, khi `startUnitLevels != null`): (a) `HasValue("SetSlot")` → foreach bm SetSlot
(theme 1 KHÔNG có element → no-op; key PTR_06a65ba8 không resolve — defer); (b) `currentMerchantPopup`
(+0x838) = null (đã null); (c) `startSpawnLevelUp(+0xE8)>0` → spawnLevelUpCount += (theme 1 = 0);
(d) foreach bm `HandleCheckGameStartEffects()` (= _itemQueue.Clear, queue rỗng).
Theme 1: `startUnitLevels` null/empty → either LAB hoặc bỏ qua → **port early-return là tương đương**,
không restructure (comment trong code ghi rõ).

### 62.6 Nút Summon (MainUI) — decode xong, chưa wire

- `MainUI.get_battleManager` (0x2FE1860) = `Scene_Game.Instance.battleManagers[battleManagerIdx@+0x5B0]`
  (Instance/list null → original NRE; out-of-range get_Item → throw; port guard cả hai).
- `OnClickRandomHeroImpl` (0x2FED718, private, `bool isAdSummon=false`) = `battleManager.GenRandomHero(isAdSummon)`
  + nhánh save defer: gate `Scene_Game.testMode(+0x388, ObscuredInt) < 0` (mặc định 0 → KHÔNG chạy)
  && `_canSave(+0x851)` && `_theme != field+0x310` && theme GetValueBool(key) && !isStory && !isColosseum
  && !isRogueLike → `StartCoroutine(SaveGameImpl(restoreFromLastSave, restoreWaiting))` / `SaveRogueLikeImpl`
  (SaveGame write-path vốn deferred).
- `OnClickRandomHero` (public bool, 0x2FED4B4): `bm.fieldGrid`-adjacent grid @bm+0x1a0 →
  `GetEmptyPos() == (-1,-1)` → CenterText "full" + false; `ConsumeGold(getRandomHeroCost)` false → false;
  `Scene_Game.isTutorial` (stub→false) → tutorial branch (IngameTutorialPanel.GetHero) bypass; else Impl.
  **Chưa port/gán** (cần ConsumeGold thật + getRandomHeroCost; capture gọi thẳng `playerBattle.GenRandomHero()`).
- `OnClickAdRandomHero`/`ReloadAdRandomHeroButton`/`OnRandomHeroPointerDown/Up` defer (ad-UI).

### 62.7 GenRandomHero (0x2EF8738) — port đã chạy thật

Guard `isSingleArenaPreparationBattle` → return; `pool = _heroPool.ToList()`; filter RemoveAll
`ResourceUnit.Get((int)id)==null || res.GetValueBool(UnitTag.LateComers=451)` (b__383_0/b__383_3);
`Utility.GetWeightedRandom` stub → idx 0 (guard `idx<0 → 0`); `level = 1`;
`AddUnitToWaitings(chosen, 1)` → unit vào waiting → `AutoMoveUnitToField` đẩy sang field
(StartStage). Runtime: 6→5 (1 LateComers thật) → chosen=10000 → field=1.

### 62.8 Verification

- `s3f13gate.log`: GATE_EXIT=0, 0 `error CS`.
- **`cap_s3f13`**: `afterFilter=5 chosen=10000 → unit=ok` → StartStage → `playerField=1 playerWaiting=0`
  → 7 enemies (§61.5) → kill-all → `HandleStageClear → _stage++ = 2` → PNG. **0 exception —
  battle hai phía đầu tiên chạy trọn vòng.**

### 62.9 Deferred (§62)

GenRandomHero: late-comers branch (`+0x388` count/SetLateComersLeftCount), ad-summon, composition-weight,
theme+0xec summon-chance path, RemoveRange edge-trim, deck-value, trumpet/Firebase; GetDefaultDeck cache
(static+0xb0); Init post-loop field inits (+0x3f8/+0x530/+0x37c) + 2 merchant-EncryptedInt dùng liệu;
SetSlot UI-label + enemy+0x7E9; SlotUp body sau khi CanSlotUp được decode; save-sau-summon
(SaveGameImpl/SaveRogueLikeImpl); OnClickRandomHero gate wiring (ConsumeGold/getRandomHeroCost/+0x1a0 grid id).
**FUN_02c56950** = per-slot lazy init (bss flag) — decode nó sẽ mở khoá toàn bộ key `PTR_DAT_*`
còn treo (EventDispatcher/CheckFieldUnitCount/InitStage keys…).

## 63. S3f — BatchValueSumEnemies (value-sum generator, stage 102+) — RUNTIME-PROVEN (2026-10-19)

Mục tiêu: stage 102+ không có `<SpawnData>` tường minh → trước đây 0 enemy auto-win. Nguồn:
`SpawnManager.BatchValueSumEnemies` RVA **0x31363B8** (call trong InitStage @file 0x312f4xx),
closure `<>c__DisplayClass3_0` (valueSum/monsters/y/usedPos/this/resStage/addLevel),
lambda `b__2` filter @0x313DC84, `g__UpdateY|0` @0x313907C, `g__BatchEnemy|1` @0x31390E0,
sorters `b__3_4..8`, `DisplayClass3_1.b__3` (obstacle) @0x313DD58, `DisplayClass3_2.b__9`
(LastStageInfo match) @0x313DE04. InitStage extract: `/tmp/opencode/s2re/b105_3131e24.txt`,
body: `/tmp/opencode/s2re/batch_value_sum.txt`; Ghidra batch105/106 extracts `b105_*.txt`.

### 63.1 Chuẩn bị decode (những mảnh ghép bắt buộc)

- **Stages.xml reveal key names** (không cần resolve PTR): `<ValueSum>`(1301), `<BatchSameLine>`(581),
  `<BatchWithEmpty>`(445), `<MaxValueAdd>`(473 = cap), `<MonsterLevel>`, `<MinMonsterPool>`/`<MaxMonsterPool>`,
  `<RandomEquip>`(67)/`<RandomItem>`(32 — 2 key của equip-tail), `<StatPer>`.
- **UnitTag**: `CanEquip=80, Order=81, MaxGen=82, GenStageFrom=84, GenStageTo=83, Value=115, Theme=440, LateComers=451`.
- **ResourceStage field map** (offset khớp thứ tự khai báo): `+0x60 defaultGen (List<(int,int)>)`,
  `+0x78 valueSum` (base budget), `+0x7C monsterLevel`, `+0x98 values (Dict<string,string>)`, `stage@+0x24`.
- **ResourceUnit**: `type@+0x30` (`Type.Enemy=2`), `genStageExcept@+0x200 (List<int>)`, `id@+0x10`, `resUnit@+0x2e8` (GameUnit).
- **BattleManager map** (đúng class): `enemies@0x98`, `allFieldUnits@0x68`, `fieldUnits@0x70`,
  `waitingUnits@0x78`, `obstacles@0xA8`, `fieldGrid=UnitGrid@0x198`, `waitingGrid=UnitGrid@0x1A0`
  (← giải luôn TODO grid của OnClickRandomHero), `gridMap@0x208`, `_lastStage(List<LastStageInfo>)@0x218`.
- **UnitGrid.size@0x28 = Vector2Int** → `fieldGrid.size.x` = width (center=size.x/2, mirror=width-1-x).
- **Scene_Game._enemyLevelBonus** (ObscuredInt@0x318) — BatchEnemy level = `(int)enemyLevelBonus + monsterLevel + addLevel`.
- **addLevel = GameManager.eliteLevels[1] + devilBonus** (eliteLevels int[]; gate `eliteLevels!=null && Length>=2`;
  devilBonus = `devilEffectCount>0 && devilCond∈[4,6] ? 1 : 0`; devil multiplier = floatTable[cond-1]×(bonus+base)).
  CẢ eliteLevels VÀ ratio bonus đều bị null-gate trong port → addLevel=0, bonus=0 (deviation đã document).
- Stages.xml theme-1: stage 101 `ValueSum=0`+7 scarecrows tường minh; 102=3; 103=4; 104=5; 105=4+boss 20020;
  pool theme-1 stage2: 20000(Value1)/20010(Value1,from2)/10020000(Value1) — 20020 from6, 20040 Value0 → loại.

### 63.2 Algorithm (decode → port)

```csharp
closure { budget=valueSum, monsters={}, y=-1, usedPos, this, resStage, addLevel }
prefill: defaultGen [(id,cnt)] → monsters[ru]=cnt; budget -= ru.Value*cnt
while (budget >= 1):
    candidates = enemyPool.FindAll(b__2: Value<=budget && (!picked || cnt < MaxGen默认int.Max))
    if empty → budget--; continue
    pick = Utility.Pick(candidates, bm.actionSeed); budget -= pick.Value; monsters[pick]++
// exit (budget<1) → spawn phase (non-batchSameLine):
sort monsters desc-by-count (b__3_4 — máy là bool-compare degenerate, thứ tự cosmetic)
foreach kv: UpdateY(); (count lẻ → BatchEnemy((width/2, y)))
    weights = [1]*(width/2); loop: x = GetWeightedRandom(weights, -1, actionSeed)
    x<0 (dòng kín) → UpdateY + weights mới (defer batchWithEmpty edge-zeroing)
    BatchEnemy((x,y)) + BatchEnemy((width-1-x,y)) [mirror]; weights[x]=0; count -= ok1+ok2
BatchEnemy(pos,id): obstacles.Any(o=>o.tilePos==pos.ToReversePos(bm.gridMap)) → false;
    usedPos[y].Add(x); BatchAIUnit(id,pos,level,team=Enemy,cardLevel=1)
UpdateY: do { y++; } while (usedPos.ContainsKey(y))
```

Tail (defer, cosmetic/difficulty): batchSameLine branch (group-by-line sort theo UnitTag.Order),
RandomEquip/RandomItem loop (`resStage.values` 2 key → PickRandomEquip(battleSeed) → target =
enemies.FindAll(team==2).Pick / Find(team==0 && resUnit.CanEquip parse true) → remove+re-Add
LastStageInfo với equips list → target.Equip(item) → buff), MinMonsterPool/MaxMonsterPool clamp.

### 63.3 Stub-gap fixes (bắt buộc — nếu thiếu: pool rỗng hoặc infinite loop)

1. **`ResourceUnit._numericValues`** (mới): parser vốn `continue`-bỏ các số thuần khỏi stringValues
   (coefficient path deferred) → `GetValueInt` KHÔNG BAO GIỜ thấy `<Value>1</Value>`. Fix: nhánh
   continue ghi `_numericValues[ntag] = (int)Math.Round(nv)` (upsert last-wins). `GetValueInt` 2 overload
   trả từ dict này (statFunc/me-scaling deferred).
2. **`Utility.GetWeightedRandom(int[])` thật** (sum<0 → tự tính; all-0 → **-1**; Random(seed) deterministic).
   Caller cũ duy nhất GenRandomHero có guard idx<0→0 → an toàn, summon-weight giờ thật.
3. **`Utility.Pick(List<T>)` thật** (seed-deterministic; empty → default). 2 overload kia defer (0 caller).
4. **`Scene_Game.enemyLevelBonus`** property → đọc `_enemyLevelBonus` thật (trước `=> default`).
5. CS0121 trap: `GetValueInt(tag, null, -1)` mơ hồ 2 overload → dùng named arg `GetValueInt(tag, @default: -1)`.
6. `BatchAIUnit` là **method của SpawnManager** (không phải BattleManager) — port GenSpawnData gọi
   không qualifying; BatchEnemy cũng gọi unqualified.

### 63.4 InitStage wiring

Sau GenSpawnData 2 wave (usedPos đã có dữ liệu wave → UpdateY tự tránh):
`enemyPool = ResourceUnit.GetAll(b__1)` (trong port: lambda inline — type==Enemy && Theme==targetTheme(=1,
máy là GetKeyValueInt key PTR unresolvable, default 1) && GenStageFrom<=curStage.stage<=GenStageTo(默认20)
&& !genStageExcept.Contains(stage) && Value>0) →
`BatchValueSumEnemies(curStage.valueSum, addLevel=0, curStage, enemyPool, usedPos, curStage.defaultGen,
GetValueBool("BatchSameLine"), GetValueBool("BatchWithEmpty"))`.
GATEeliteLevels omitted (null trong port → machine sẽ skip, ta gọi thẳng — deviation, ratio bonus=0).

### 63.5 Verification (gate s3f14gate + cap_s3f14, 2026-10-19)

- Compile: GATE_EXIT=0, 0 error CS.
- Play-capture (KILL_ENEMIES=1, 900 frame sau kill): **CAP_EXIT=0, 0 exception**, PNG OK.
  - Stage 101: `[VSUM-DIAG] valueSum=0 picks=0 pool=2` → không sinh thêm (đúng, budget 0); 7 bù nhìn tường minh.
  - Stage 101 clear: `killed 7 → HandleStageClear → _stage++=2 → WorkTimer(1s) → NextStage → InitStage`.
  - Stage 102: `[VSUM-DIAG] valueSum=3 picks=1 totalUnits=3 budgetLeft=0 pool=3` →
    `[VSUM-DIAG] spawn id=20000 count=3` — 3 Goblin(20000), budget 3 / Value 1 = hết sạch.
    Stack thật: `WorkTimer.Update → <HandleStageClear>b__751_0 → NextStage → Scene_Game.InitStage →
    BattleManager.AfterInitStage → SpawnManager.InitStage → BatchValueSumEnemies`.
- DIAG: `[VSUM-DIAG]` 2 dòng/pick-phase + 1 dòng/unit-type (SpawnManager.cs ~225) — giữ cho tới khi
  CaptureScene tự verify stage-2 thì xoá.

### 63.6 Deferred (§63)

batchSameLine branch (sort UnitTag.Order + group-by-line), batchWithEmpty edge-zeroing
(positions[0]/[last]=0 khi count≥4), RandomEquip/RandomItem equip-tail, eliteLevels/eliteLevelRatio
ratio bonus + addLevel (cần port GameManager.eliteLevels data từ server), MinMonsterPool/MaxMonsterPool
clamp, FUN_02c56950 (per-slot lazy init — mở khoá PTR_DAT keys: targetTheme key, MaxValueAdd/BatchSameLine
đã khỏi need nhờ XML nhưng các key khác còn).

### 64. Gold cluster + nút Summon gate (2026-10-19)

**Decode** (batch107/108/110 + b109 + b104, resolve key qua `.rela.dyn` `R_AARCH64_RELATIVE`
→ addend → `script.json.ScriptString`):
- `MainUI..ctor` RVA **0x2FF3C58** (dump.cs omit!) — initializers ghi trực tiếp: `sellCost=2`,
  `randomHeroCosts={3}` (summon cost), `randomItemCosts={10}`, `randomHeroLevelUp={7}`,
  `addUpgradeSlotCost=0`, `_camPosition=1`, `_cachedUnitMaxLevelEffectObjs=Dictionary`,
  `basePanelPos={-442,0,-570}`, `subStartButtonPos={244,320}`; defer blob-init: `SELL_GOLD[7]`,
  `camSize[3]`, `RANDOM_HERO_FIRST_DELAY@+0x690`. **readonly fields không có trong YAML** →
  port BẮT BUỘC có ctor (máy dựa vào managed ctor).
- `HasGold(v) = v <= _gold`; `getRandomHeroCost = randomHeroCosts[0]`.
- `SetGold(v)` (BM 0x2EF6494): equal→early-out; `_gold=v`; `_maxOwnedGold=max`;
  focused→`mainUI.SetGold`; bmIdx==0→`gameCompleteRequestModel.maxGold` record (@0x84).
  Defer tail: `BasePanel.SetReward(curStage)` refresh + items-listener.
- `AddGold` (0x2EF0B14): `amt = round((GetArtifactValueSum("RoguelikeGoldPer")/100+1)*value)`
  (stub→0 → amt=value; param `addDeckValue` chết trong binary) → focused→`ShowAddGold`
  (+RogueLike) → bmIdx==0→`deckValue+=amt` → `HandleAddGold` (no-op) → `SetGold(gold+amt)`.
- `ConsumeGold(value, checkUnitCount)` (0x2EF67B4): bmIdx!=0→true; `gold<value`→toast
  **"NotEnoughSilver"**→false; `checkUnitCount && gold-value<3 && field+waiting rỗng`→false;
  success: `HandleAddGold(-value)` + `SetGold(gold-value)` + `totalUsedGold+=value`.
- `MainUI.SetGold` (0x2FE6CE8): `goldText.text=Format("{0}",v)` + tint cost-labels theo affordance
  (defer tint). `OnClickRandomHero` (0x2FED4B4): GetEmptyPos==(-1,-1)→toast **"FieldSlotFull"**
  →false; `ConsumeGold(cost,false)` fail→false; !isTutorial→`OnClickRandomHeroImpl()`→true.
- **Start-gold** (init_body 3030-3077): `model.startGold=playerBattle.gold` (trước reset);
  foreach bm: `startGold = GetBuildingEffect("StartGoldBonus") + (ResourceTheme.startGold<0 ? 7 : startGold)`;
  player bm → `_deckValue=startGold`; `bm.SetGold(0); bm.AddGold(startGold,true,false,false)`.
  **`ResourceTheme.startGold = GetChildInt("StartGold", -1)** — XML không có → -1 → fallback **7**
  (port field原本=0 → không fallback → bug gold=0, fix: initializer `= -1` vì `InitGenericFields`
  chỉ ghi đè khi element CÓ).
- Kill-gold: `HandleUnitDead`→`reward = GetChildInt(node,"Reward",0)` (**resolve key =
  'Reward' qua rela; Units.xml không có `<Reward>` → luôn 0** — kill không cho gold ở theme1);
  `HandleKillUnit` bonus = SkillTag.AddGoldOnSkillKill(200) + UnitTag.KillGoldBonus(114) +
  BuffTag.KillGoldBonus(175) + `_cloneKillGoldBonus` — cũng 0 với unit thường. Nguồn gold
  theme1 = start gold + GiveReward.

**Port** (§64): MainUI ctor + `getRandomHeroCost` + `MainUI.SetGold` + `OnClickRandomHero`;
BM `gold/maxOwnedGold/SetMaxOwnedGold/SetGold/HasGold/ConsumeGold/AddGold`;
`Scene_Game.deckValue` property (gắn `_deckValue` — stub cũ get=0/set no-op làm mất record);
Init start-gold block (giữa InitMap và InitStage, đúng thứ tự máy); `ResourceTheme.startGold=-1`;
CaptureScene summon giờ gọi `mainUI.OnClickRandomHero()` thật (bỏ GenRandomHero thẳng).

**Verification (gate s3goldgate + cap_s3gold, 2026-10-19)**: GATE_EXIT=0/0 error;
capture CAP_EXIT=0/0 exception: `[PLAYCAPTURE] OnClickRandomHero (summon): ok=True gold 7 -> 4`
+ `[SUMMON-DIAG] chosen=10520 -> unit=ok` + `after StartStage: playerField=1`.
(`waiting=0` là pre-existing — stage1 auto-to-field, log cũ cũng vậy.)

**Deferred (§64)**: SetGold/AddGold tail (SetReward refresh + items-listener), MainUI.SetGold
cost-label tint (resolve statics Color class), CenterText toasts (key đã resolve — wire
`centerText.Show`), `UnitGrid.GetEmptyPos` + `GridTile.tilePos` thật (stub (0,0) → full-grid
branch không nổ; multi-summon placement), blob-init SELL_GOLD/camSize/RANDOM_HERO_FIRST_DELAY,
AddGold banker's-round chi tiết (chỉ khác với artifact % ≠ 0), kill-gold nếu sau này master data
có `<Reward>`.

## §65 — S3f: game-end cluster (HandleGameEnd / HandleGameEndImpl / POST game/complete / GameOverPanel) — RUNTIME-PROVEN (2026-10-20)

### 65.1 Caller-scan law: PHẢI scan cả B lẫn BL (mới, quan trọng)

Scan chỉ BL (`(w>>26)==0x25`) **bỏ sót mọi tail-call `b`** (`(w>>26)==0x05`) — HandleStageClear
bình thường tới HandleGameEnd qua `b`, không qua `bl`. Công thức: 4-byte aligned từ 0x4000; BL
`imm26` sign-extend ×4; B cùng công thức. dump.cs name: `^\s*// RVA: (0x…)` rồi dòng kế =
signature. **HandleGameEnd (RVA 0x2E59770) trigger map — 16 site (B+BL đầy đủ)**:

| Site (RVA) | Callable / bối cảnh | semantics |
|---|---|---|
| 0x2eeefec (BL) | `SetLife` | `battleManagerIdx==0 && life<1 && !isColosseum` → `HandleGameEnd(false)` |
| 0x2eef4d8 (B) | `ForceSetLife` tail | defeat override |
| 0x2e77188→0x2e7769c (B) | `HandleStageClear` final-branch | **WIN**: final + !colosseum + !clanraid + !story |
| 0x2EB2F80 (B) | `<HandleStageClear>b__1` | `ldr x0,[x0,#0x10]; mov w1,#1; b HandleGameEnd(true)` |
| 0x2ea87f4 (B) | `<StageEndPost>b__583_1` | `mov w1,#1; b HandleGameEnd(true)` — gate HeroRevive (xem 65.3) |
| 0x2ea87fc (B) | `<HandleGameEnd>b__595_0` | `mov w1,wzr; mov w2,wzr; b HandleGameEndImpl(false,false)` |
| 0x2eb2abc / 0x2eb2d48 (B) | `<HandleStageLose>b__0 / b__2` | lose-skip |
| 0x2e4bb4c / 0x2e584e4 / 0x2e9a5e0 / 0x2ea8894 / 0x2ea9b9c / 0x2ecb338+0x2ecb39c / 0x2d1ad30+0x2d24680 / 0x2fe8f40 / 0x2fef66c | InitStage CanComplete (colosseum) / WaitForNextPhase / ShowSingleArenaDeckChoice / OnClickSkipRanking / HandleReadyPhase d__168 (roguelike) / story / OnClickDevMenu / OnClickStageComplete | mode-specific, defer |

`HandleGameEndImpl(bool cleared, bool adBonus)` @0x2E85B3C — callers: LoadGame 0x2e69340,
RankedPvPGiveUp 0x2e8875c, LoadRogueLikeImpl 0x2e95158, `HandleGameEnd` d__595 0x2ec0348/0x2ec0c54.
`RestAPI.GameComplete(UniTask)` @0x2d31310 — callers: d__597 0x2ec7964, PausePanel <>c 0x2ffe0c8
(give-up), DimensionRiftStartPanel 0x354f2bc.

### 65.2 WIN path: final-branch + elite-gate + **encoded-method-index resolver** (kỹ thuật mới)

`HandleStageClear` (0x2e77188): `isFinalStage && !isColosseum && !isClanRaidDeckRecord &&
!isStoryMode` → **jump FORWARD tới 0x2e7769c, BỎ QUA `_stage++`** (0x2e77298/0x2e772ac —
get_v/set_v) → elite gate → `Action.ctor(x1=displayClass575_0, x2=*slot)` → `WorkTimer.Do(2.0,
action)` (CẢ 2 nhánh đều 2.0s — dùng chung `fmov s0,#2.0` sau join 0x2e7779c):

- gate PASS = `GetEliteLevelSum()==0xf && !this.@0x47C && !theme.@0x60(isEventMode) &&
  AwesomePrefs.GetInt("RankingStageEnable",1,1)==1` → slot **0x6967120**
- gate FAIL (bình thường) → slot **0x6967128**

**Slot → lambda identity (không thể resolve bằng adrp/ldr thường — BỎ QUA method-pointer
"cells"):**

1. Slot static (vd `adrp x8,#0x6967000; ldr x8,[x8,#0x120]` → 0x6967120) → rela r_offset →
   **addend = cell address `.data`** (vd 0x6b8e688). `.data` vaddr 0x6a028d0/file 0x69f68d0 →
   **delta 0xC000: file offset = vaddr − 0xC000**. Đọc 8 byte tại cell → **encoded method index
   `0x6000xxxx`** (KHÔNG rela, KHÔNG có store nào trong code — chính nó là giá trị khởi tạo file).
2. Decode: index **tăng +2 mỗi lambda theo thứ tự dump.cs** (method definition order).
   Anchor chốt: slot **0x6967130** (common-path schedule NextStage @0x2e77364) → cell 0x6b8e698 →
   `0x600032a3` — `DisplayClass575_0` dump order: b__0, b__1, b__2… → **b__2 (NextStage) = 0x32a3**
   ⇒ b__0=0x329F, b__1=0x32A1.
3. Kết luận: gate-FAIL (bình thường) → 0x600032A1 = **b__1 → `HandleGameEnd(true)` @2.0s** ✓;
   gate-PASS (ranking) → 0x6000329F = b__0 @0x2EB2DB8 (iterate list@0x230 → remove-buff — ranking
   flow, defer). Cross-check cell block 0x6b8e680: `…329b 329f 32a1 32a3 32a7 32a5 32a9…` —
   b__4 đứng TRƯỚC b__3 trong dump (RVA 0x2EB31C8 < 0x2EB31FC) nên cell 0x6b8e6a0=b__3(0x32a7),
   0x6b8e6a8=b__4(0x32a5) — khớp.

**⚠ TRAP capstone mới**: bản capstone này in `op_str` CÓ ngoặc vuông (`adrp [x8, #0x…]`) →
`re.match(r'x…')` FAIL THẲNG — mọi scan full-binary dùng `re.match` trước đó đều im lặng sai.
Dùng `re.search`. (Bug này đã làm 5 scan liên tiếp trả về rỗng.)

Delegate "raw pointer cells" (0x6a77c18→0x2eb2f80…, rela addend = code addr) **không có ai
đọc** — chỉ là data artifact; identity lấy qua encoded index như trên, không qua cells đó.

### 65.3 StageEndPost — decode lại SẠCH (checkpoint cũ bị lệch offset)

`StageEndPost(bool win)` @0x2e823c8 (đúng slice `data[RVA−0x4000:]`, base=RVA): ObscuredBool
@+0x374=true, EncryptedInt(0) @mainUI+0x5d8, list@0x230 `AddPreventSellUnitStageCount(-1)` +
`AddUnlimitedSpawnLevelUpStageCount(-1)`, `ReloadStageText(win)`, `ReloadButtons(true)`, boss-bar
hide loop, `playerBattle.StageEndPost()` @0x2ef2c40, timeScale restore, `ReloadUnitCount()`, rồi:

```
if (!_resTheme.GetValueBool(key=*slot 0x6967668 /* "HeroRevive" */, default:true))   // w2=1
    if (!Any(list@0x230, cachedPred /* *0x6967660 */ /* 0x3bdc328 */))
        WorkTimer.Do(2.0, Action(x1=this, *0x6967658 = b__583_1));   // → HandleGameEnd(true)
```

`<StageEndPost>b__583_1` @0x2ea87f4 = `mov w1,#1; b HandleGameEnd`.
**HeroRevive=false CHỈ có trong theme event 1000/1002/2000** (Themes.xml, 3 hits: 2 active +
1 comment) — theme 1 vắng key → default true → **skip → StageEndPost KHÔNG end game ở theme 1**
(mọi NextStage đều gọi nó). `NextStage` @0x2e821e0 gọi `StageEndPost(true)` trước → port đã có
body này (Scene_Game:4329). Ghi nhận: checkpoint §64 ghi "HeroRevive branch defer" — ĐÚNG, và
branch này chỉ phục vụ event themes.

### 65.4 Life / SetLife / lose path

- `_life = new EncryptedInt(0)` trong ctor (@0x2f04288); **không có writer khởi tạo từ theme**
  → fresh game life=0. Theme 1 (server/xml_live/Themes.xml) **thiếu cả 3 flag**
  SkipStageWhenLose / DecreaseLifeWhenSkipStage / GiveAllGoldWhenLose → GetValueBool all false →
  stage-lose LUÔN `life--` (comment §59 "theme 1 không rơi vào" SAI — đã sửa trong port).
  Stage-lose đầu: `SetLife(0−1=−1)` → life<1 → `HandleGameEnd(false)` — life start 0 là ĐÚNG máy,
  **không artificial-init**.
- Port `BattleManager.SetLife(int, bool anim=true)`: clamp trần `value ≤ Scene_Game.Instance.
  startLife` (mới — property đọc `_resTheme.startLife`, vì `_resTheme` private trên Scene_Game);
  `_life = value`; focused → `mainUI.SetHp`; `RefreshFlags()` (stub an toàn);
  `battleManagerIdx==0 && life<1 && !isColosseum → Instance.HandleGameEnd(false)` + log.

### 65.5 Ports (tất cả gate-pass, compile 0 error)

- **BattleManager.cs**: `life` property get/set `_life` (trước stub `=> 0`); `SetLife` body (65.4).
- **Scene_Game.cs**: `startLife` property; `InitGameCompleteModel()` (`_startTime=UtcNow`, model
  `{gameId=gm.currentGameId, theme, stage}`, ẩn gameOverPanel) gọi trong `Init()` trước
  `InitStage()`; `InitStage` top set `model.stage=_stage.v`; `HandleStageLose` mở rộng (đọc 2 flag,
  `loseCount++`, `ReloadInGameMissions`, `pb.SetLife(pb.life-1)`, `pb.life<1 return`,
  `WorkTimer.Do(bmCount*0.5f+2, HandleStageLoseDelayed)`); NEW `HandleStageLoseDelayed` (b__0:
  gold vơi 50%, `StageEndPost(false)`, flag==0 ReBatch, flag==1 final→HandleGameEnd(true) else
  `_stage.v++ + InitStage`, tail `mainUI.HandleStageEnd(false,2.5f) + SaveGame(false,true)`);
  **win-gate** `HandleStageClear`: `bool finalWin = isFinalStage && !isColosseum &&
  !isClanRaidDeckRecord && !isStoryMode` tính TRƯỚC khối `_stage.v++` (chỉ chạy khi `!finalWin`) →
  `finalWin ? WorkTimer.Do(2f, ()=>HandleGameEnd(true)) : WorkTimer.Do(1f, ()=>NextStage(false,0f))`;
  `HandleGameEnd` (guard `gameEndProcessed` → `ClosePausePanelIfActive` → `SaveGame(false,true)` →
  `WorkTimer.Do(cleared?1.8f:0.3f)` → win&&!story `AudioController.StopMusic()` (static) →
  `!isPvPMode && !isColosseum && !isStoryMode → HandleGameEndImpl(cleared,false)` else defer log);
  `ClosePausePanelIfActive` (pausePanel SetActive(false)); `HandleGameEndImpl` (điền model
  `gameId/theme/stage/win/adBonus/endTime/playTime` → `Web.Post<GameResponseModel>("game/complete",
  …, callback)` → fail: log+`mainUI.ShowRestRetry()` → ok: `GameOverPanelData{win,addGold,addExp}`
  → `mainUI.gameOverPanel.Show`).
- **GameOverPanel.cs**: `Show(data)` minimal = `SetActive(true)` + `_resultText.text =
  win ? "VICTORY" : "DEFEAT"` (chính là banner text field — render đúng).
- **CaptureScene.cs**: `KGC_CAPTURE_FORCE_FINAL=1` — reflection set `_stage.v = resStages.Count`
  (1-based; `isFinalStage = _stage.v == Count`) TRƯỚC kill-loop; `KGC_CAPTURE_FORCE_DEFEAT=1` —
  `playerBattle.SetLife(-1,false)` SAU StartStage (không kill env).
- Traps đã tránh: `GameOverPanelData` là nested class → `GameOverPanel.GameOverPanelData`
  (CS0246); `RefreshFlags(bool init=false)` default-arg; `_stage` là **struct** AwesomeInt →
  reflection phải unbox/`SetValue` trả về; `SaveGame(bool,bool)` stub rỗng (an toàn gọi thật);
  `Scene_Game.isFinalStage` computed — capture phải set `_stage`, không set được isFinalStage.

**Verification (gate s3f_gate65b + cap_s3end + cap_s3lose, 2026-10-20)**:

- GATE_EXIT=0 / 0 `error CS`.
- **WIN** (cap_s3end, CAP_EXIT=0, **0 exception**): `[PLAYCAPTURE] FORCE_FINAL: _stage → 13
  isFinalStage=True (resStages=13)` → `killed 7 enemies` → `[S3f§65] final-stage win (theme 1
  stage 13) → HandleGameEnd(true) sau 2.0s` (**KHÔNG có log `_stage++`** — nhánh final bỏ
  increment đúng máy) → `[S3f§65] HandleGameEnd(cleared=True)` → `[S3f§65] POST game/complete
  (gameId=8ccf64306d102d1f theme=1 stage=13 win=True)` → `[S3f§65] game/complete ok: addGold=1600
  addExp=120` → `GameOverPanel.Show win=True`; server `/tmp/kgc_local_http.log`:
  `POST /game/complete → GameResponseModel 200 OK`. Screenshot: banner **VICTORY** + Theme 1
  header + reward rows.
- **DEFEAT** (cap_s3lose, CAP_EXIT=0, **0 exception**): `FORCE_DEFEAT: SetLife(-1) life 0 → -1
  idx=0` → `[S3f§65] SetLife: life<1 → HandleGameEnd(false)` → `HandleGameEnd(cleared=False)` →
  `POST game/complete (… stage=1 win=False)` → `ok addGold=600 addExp=120` →
  `GameOverPanel.Show win=False`; server 200 lần 2. Screenshot: banner **DEFEAT**.
- Theme 1 runtime `resStages = 13` (101–110, 11001, 115, 120 — 21 rows regex-match nhưng 8 rows
  nằm trong `<!-- -->` comment; `_resStages = GetAll(theme==1)` = 13 khớp non-comment rows).

**Deferred (§65)**: elite/ranking gate → b__0 flow (ranking stage result; slots 0x6967120/
0x6967128 không cần resolve thêm — semantics đã chốt); StageEndPost HeroRevive branch (event
themes 1000/1002/2000 + `Any(list@0x230)` predicate); `<HandleStageLose>b__2` @0x2eb2d48;
mode-specific GameOver branches (pvp/colosseum/babel/story/roguelike → panels riêng);
revive panel/flow + `b__595_0` revive-decline; retry AwesomePrefs storage + `_sendGameComplete`
guard + 3.0s timeout WorkTimer; `FetchPlayerTutorialStatus`; **GameOverPanel full UI** (reward
rows hiện static `+600 (3/3)` từ prefab — CHƯA map từ `GameResponseModel.addGold=1600`; cấp
thực: map addGold/addExp/newRecord/newThemeClear/beforeLevel/beforeExp + artifact/accessory/
exp-card lists, localize key Win/Lose thay "VICTORY"/"DEFEAT" literal, `Fit()`);
`model.endTime` format (server không đọc — ISO giả); deck/endFieldUnits/endTime payload đầy đủ;
post-win lobby progression (server bestCleared* đã ghi nhưng client chưa hiện world-clear flow);
HandleStageLoseDelay TAIL `playerBattle` action @delay+k; MerchantCheckTerm.

## §66 — S3 (method cuối): BattleManager.Update (input/UI pick + hide-cascade) — RUNTIME-PROVEN (2026-10-20)

**Scope**: `BattleManager.Update` RVA `0x2ED9E9C` (file `0x2ED5E9C`, dài đến `CheckSpawnTimers`
@`0x2EDA7E4` = 0x948 byte, ~442 dòng decompile — `bmupdate_2ed9e9c.c`, Ghidra batch114).
Method **luôn chạy mỗi frame** trong Scene_Game nhưng body chính là input branch
(`GetMouseButtonDown/Up`) — batchmode không có chuột → input branches không fire trong capture;
runtime proof = 0-exception trong 900-frame battle (Update chạy mọi frame, guard/field-read
path exercised). Port vào stub rỗng `BattleManager.cs` (old line 716).

**Gate/capture evidence**: compile gate `GATE_EXIT=0`, 0 `error CS`
(`/tmp/opencode/s3upd_gate.log`); play-capture `CAP_EXIT=0`,
`[PLAYCAPTURE] play capture ok (exit 0)`, **0 `NullReferenceException`**
(`/tmp/opencode/s3upd_cap2.log`, shot `/tmp/opencode/cap_s3upd/shot_Scene_Game.png`).
Lưu ý: lần capture đầu fail `Could not find a part of the path .../shot_Scene_Game.png` —
**`KGC_CAPTURE_DIR` phải tồn tại trước** (harness không mkdir).

### §66.1 Cấu trúc nguồn (disasm-verified)

```
Update():
  if (battleManagerIdx != 0) return;                 // field int @+0x34
  var mainUI = Scene_Game.Instance.mainUI;           // static[0]=Instance (NRE nếu null) → +0x268
  if (Input.GetMouseButtonDown(0)) {
    if (!mainUI.tutorialPanel.blockRaycast) {        // NRE-check mainUI/tutorialPanel TRƯỚC test
      bool overUI = Utility.IsPointerOverUIObject();
      // ColosseumInvadeInfoPanel.Instance != null (UnityEngine.Object.op_Inequality):
      //   !overUI → Instance.Hide();
      //   else nếu Instance.isActiveAndEnabled && !IsPointerOver(Instance.transform) → Hide();
      //   (Hide/transform/isActiveAndEnabled mỗi lần re-fetch static → Roslyn emit lại cbz — faithful)
      if (!Scene_Game.Instance.isRogueLike)          // get_isRogueLike(Instance)
          item/rogue-panel keep/hide (unified xem §66.2)
      BasePanel 7-child cascade (unified xem §66.2)
      if (!overUI && gameCanvasGroup.blocksRaycasts) // gameCanvasGroup @BM+0x1C8
        pick: wp = Scene_Game.Instance.worldCam.ScreenToWorldPoint(Input.mousePosition);
              hits = new Collider2D[8];
              n = Physics2D.OverlapPointNonAlloc(wp, hits);   // 2 arg thật (script.json)
              for i<n: col = hits[i];
                if (col.name.Equals("ButtonCollider"))        // instance String.Equals(this=name, literal)
                  unit = Utility.Get<GameUnit>(col.transform.parent);
                  if (unit != null) _clicked = unit;          // @BM+0x3A0, KHÔNG cast (T=GameUnit)
    }
  }
  if (Input.GetMouseButtonUp(0)) {
    if (mainUI.tutorialPanel.blockRaycast) return;   // early return → KHÔNG clear _clicked
    overUI = IsPointerOverUIObject();
    if (!overUI && gameCanvasGroup.blocksRaycasts) {  // pick loop y hệt,
      ... if (unit != null && _clicked == unit) unit.OnClick();   // KHÔNG store
    }
    _clicked = null;                                  // mọi mouse-up khác tutorial-block
  }
```

**7-child cascade order** (BasePanel, dump.cs field types): `devilInfo`+0x198 (Border),
`eliteInfo`+0x168 (Border), `difficultyInfo`+0x180 (Border), `arenaInfo`+0x208 (ArenaInfoUI),
`seasonalEventInfo`+0x218 (**GameObject**), `pvpDeckRecordInfo`+0x158 (**GameObject**),
`divinePowerInfo`+0x1b0 (Border). Item panels: `itemInfoPanel` MainUI+0x158,
`rogueLikeItemInfoPanel` +0x160 (non-rogue/rogue mutually exclusive).

**Form unified NRE-faithful** (mỗi child 1 statement):
```csharp
if (!(overUI && Utility.IsPointerOver(bp.devilInfo.transform)))
    bp.devilInfo.SetActive(false);
```
- `overUI=true` → evaluate check: `bp.devilInfo.transform` — basePanel null → NRE, child null → NRE
  (khớp cbz kép của check-block @0x2eda3d8…).
- `overUI=false` → short-circuit → hide: Border/ArenaInfoUI bind **extension**
  `Utility.SetActive(this MonoBehaviour,…)` (null → KHÔNG NRE, khớp 0x2eda418 không cbz field);
  `GameObject.SetActive` là instance (null → NRE, khớp check `lVar9==0 → NRE` @0x2eda568/0x5c8).
- **Disasm chứng minh fall-through** (không đoán từ decompile print order — print order ≠ address order):
  `hide-devil` @0x2eda3a8: `tbz w20,#0,0x2eda418` (w20 = overUI) → overUI=false **skip toàn bộ
  check-blocks**, hide → hide → … → `hide-pvp` @0x2eda5e4 `tbz → 0x2eda628` = **hide-divine
  thẳng** (check-divine @0x5e8 chỉ chạy ở over-path). over-path: check → over? keep : hide →
  check kế. `hide-divine` @0x650: `tbnz w20,#0 → 0x2ed9f88` (overUI=true → skip pick);
  fall → 0x658 `gameCanvasGroup.blocksRaycasts` gate → pick. → tức unified short-circuit
  **khớp máy 100% kể cả NRE nhánh divine-null**.
- Rogue/non-rogue entry: overUI=true → goto check-path (0x368); overUI=false → goto hide-path
  (0x3a8) — unified form tự hội tụ.

### §66.2 Cell/token scheme (.got → .data token table) — RESOLVED

Update preamble bắn `FUN_02c56950(cell)` cho 8 cell; resolver `0x2b00290(slot,1)`:
bit0==0 → no-op epilogue (rela'd pointer đã relocate); bit0==1 → decode
`(type=bits29–31, index=(t>>1)&0x0FFFFFFF)` → table lookup → `str x0,[x19]` ghi về slot.
**.data regions là mảng token liên tiếp** (qword, step +2 = index tăng dần):
- `cellC` (GOT 0x69673d8 → addend 0x6b9d660): tokens type5 `0xa00021f1,0xa00021f3,…` =
  stringLiteral indices 4344,4345,… → `ScriptString[4344]` = **`"ButtonCollider"`** —
  operand `ldr x1,[cellC→slot]` của `String.Equals` = literal inline.
- `cellB` (GOT 0x69673b8 → 0x6b7eef8): tokens type6 — **ĐÂY LÀ `MethodInfo*` cell ẩn của
  `Get<object>`, KHÔNG phải arg C#** — disasm `ldr x1,[x29]; mov x0,x22; bl Get` —
  script.json Signature: `Il2CppObject* Utility__Get_object_(Component_o* target, const MethodInfo_3D41914* method)`
  = **1 arg thật**. Decompile `Get(uVar14, *cellB)` = (target, methodinfo). T instantiation
  canonical = `object` (generic sharing) — source = `Utility.Get<GameUnit>(parent)` (return
  gán thẳng `_clicked` không castclass → T phải là GameUnit). Port `Get<T>(Component)` =
  `target.GetComponent<T>()`.
- `cellA` (0x6a67378→0x6b27a98): elem klass token → `FUN_02c569f4(elemKlass, 8)` = `new Collider2D[8]`.
- `cellD` ColosseumInvadeInfoPanel klass, `cellE` Scene_Game klass, `cellF` Utility klass,
  `cellG` UnityEngine.Object klass, `cellH` Physics2D klass (init-guard `klass+0xe0`/`thunk_FUN_02c6124c`).
- Class-init thunks + `cbz` NRE guards trong decompile = boilerplate IL2CPP/Roslyn → C# tự sinh,
  KHÔNG port (NRE fidelity đến từ expression tự nhiên như §66.1).

**Invoke**: `(**(code**)(*obj + 0x3b8))(obj, *(*obj + 0x3c0))` = vtable slot 40 →
dump.cs `GameUnit.OnClick() … Slot: 40` (vtable start 0x138 + 40*16 = 0x3B0 {method,ptr} →
ptr@0x3B8) → port `unit.OnClick()` (virtual dispatch, port stub @GameUnit.cs:3231).

### §66.3 Laws/thuật toán dùng lại

- **script.json ScriptMethod keys** = `Address/Name/Signature/TypeSignature` (**KHÔNG có
  `Class`/`ClassName`** — KeyError nếu đoán); Name dạng `"Class$$Method"`,
  `Signature` = C-signature thật (giải quyết arity/hidden-MethodInfo), `TypeSignature` = `iii`.
- BL scan trong range: `(w>>26)==0x25`, imm26 sign-extend ×4 → `bisect` vào ScriptMethod
  sorted-by-Address, match nếu `target - entry.Address < 0x8000`.
- **Decompile print order ≠ machine address order** — mọi nhánh control-flow quyết định
  bằng disasm thật tại fall-through (xem §66.1 `tbz` map), không tin vị trí label in output.

**Deferred**: spawned units của port chưa đặt child collider tên `"ButtonCollider"`
(không gặp trong capture — input không fire; kiểm tra khi S4 test click trong battle);
`Utility.Get<T>(Component)` = GetComponent là suy đoán hợp lý (1-arg, đã ghi S4a) — nếu
original là recursive-find sẽ sửa khi test pick thật.

## §67 — S4-1: deck (data flow) — RUNTIME-PROVEN (2026-10-20)

Scope slice 1: REST deck → GameManager sync → data.currentDeck sống → Scene_Game seed
stored deck. DeckPanel UI (Equip/UnEquip/Swap/Reload) = slice 2. Capture chứng minh:
`[web] GET /deck -> 200`, `[DECK1] GET /deck ok deckInfos=5 preset=0
currentDeck=[10000..10050]`, `[DECK1] Scene_Game deck resolve useStored=True`,
0 NRE, `play capture ok`.

### §67.1 Nguồn dữ liệu deck (định luật)

**Deck đến từ MỘT mình `GET /deck`** — `PlayerDataResponseModel` không có
deckInfos/currentDeck (chỉ `currentDeckPreset @0x88`); GET /deck có đúng 1 BL-caller =
`DeckPanel.<RestoreDeckFromServer>d__161.MoveNext`. Không có auto-fetch tại panel-open
qua BL-scan (SaveDeck-failure path + 0 BL-caller còn lại → trigger gốc delegate/UnityEvent-
invisible, không tìm ra). **Wiring chủ động của port**: `DeckPanel.OnPanelEnabled()` gọi
`RestoreDeckFromServer()` (comment rõ trong code) — không otherwise data.deckInfos luôn
null → Scene_Game luôn fallback `GetDefaultDeck()`. `HandlePlayerDataResponse` chỉ
`store preset + Ensure()` khi `data.model == null || accountId khác` (refresh /player
bình thường KHÔNG đè preset đổi local).

PlayerData: currentDeck@0x68 (int[]), currentPotential@0x70 (int[]), currentFirstComerIndex
@0x78 (int), currentDeckPreset@0x7C, deckInfos@0x80 (DeckInfo[]). DeckInfo = {deck,
potential, firstComerIndex} — refs được COPY (không alias) từ deckInfos[preset].

### §67.2 Port (các file)

- **RestAPI.cs** (callback, d__107/110/111/114 MoveNext URI qua cell-decode type5):
  `GetDeck → Web.Get<DeckResponseModel>("/deck", accessToken, false, cb)`;
  `SetDeck → Web.Post("/deck/set", JsonUtility.ToJson(req), …)`;
  `BuyDeckSlot → Web.Post("/deck/buyDeckSlot", JsonUtility.ToJson(model), …) → ResponseModel`;
  `SetDeckSlotName → Web.Post("/deck/set-deck-slot-name", JsonConvert.SerializeObject(req), …)`
  — **riêng set-deck-slot-name dùng Newtonsoft JsonConvert, 3 cái kia JsonUtility** (binary
  nói rõ). `Web.Combine` tự xử slash → "/deck" hay "deck" đều ok.
- **GameManager.cs**:
  - `EnsureCurrentDeckSynced` (0x3153DE8): điều kiện sync = `deck != di.deck ||
    potential != di.potential` (không so firstComer!); log `string.Format("[GET - <color=…>
    RESPONSE</color>] REST API ", preset)` — fmt ScriptString[18785] **KHÔNG placeholder**
    (Format bỏ thừa arg = chuỗi hằng) — giữ y. Copy order: potential(+0x70)←di+0x18,
    deck(+0x68)←di+0x10, firstComer(+0x78)←di+0x20. Log wrapper FUN_02da98b4 →
    `Debug.LogWarning` (26 callers, mức log leaning — cosmetic).
  - `HandleDeckResponse` (0x3153F20) — **disasm: mọi null (model/data/deckInfos/di/
    defaultPotential/dip) → NRE pad; preset OOB → IndexOutOfRange pad** — port C# tự nhiên
    KHÔNG null-guard (khác với suy đoán từ decompile trước). Thành công = loop
    `defaultPotential.Clear(); for i<dip.unit.Count: Add(dip.unit[i], dip.potential[i])`
    rồi ret. **`defaultPotential` (@0x360) phải luôn != null** → port field-initializer
    `new Dictionary<int,int>()` (máy: Roslyn ctor-init); `GetDefaultPotential(int)` =
    `defaultPotential.TryGetValue(...)` (tail-call 0x3153d8c — ready để port sau).
    Server luôn trả `defaultPotentialInfo` (card_routes r_deck/r_deck_set) → dip không null.
  - `SetCurrentDeckPreset` (0x31513D0): store preset + Ensure (máy inline → port source call).
- **DeckPanel.cs**:
  - `CheckDeckDesynced` (0x32B0DB0): cùng `Time.frameCount` đã check → true; Ensure fail →
    false; else set _deckDesyncedFrame, `SetDraggingCard(null)`,
    `_deckSlotToggles.ForEach(<lambda cell 0x6a7e6d8 — type1/table chưa map — DEFER>)`,
    `Reload(true)`, true.
  - `OnPanelEnabled` (0x32B1028): base → CheckDeckDesynced →
    `Utility.SetScreenFirebase("DeckPanel","BarrackPanel")` (cell decode) →
    `BarrackAltarBox.Instance.Reload()` (null → NRE pad) → **deferred tail**: loop
    list GameManager+0x38 = `devTestClanRaidDeckInfos` (dev-test-only, server thật rỗng
    → no-op) invoke cached Action (cell 0x6a7e6e0 chưa map) → **+ wiring RestoreDeckFromServer**.
  - `SaveDeck` (d__160 MoveNext 0x32BC104): desync → skip; `ShootCallback(DeckChange=5)`
    TRƯỚC khi build `{presetIdx,deck,potential,firstComerIndex}`; SetDeck callback:
    `res.isSuccess` → HandleDeckResponse; else `Debug.Log("Saved to client version is
    {0}" + res.msg)` + `RestoreDeckFromServer()`. res null → NRE (máy throw pad — port
    deref tự nhiên, KHÁC Restore có null-check).
  - `RestoreDeckFromServer` (d__161): GetDeck → `res != null && res.isSuccess` →
    HandleDeckResponse + `Reload()`; else im lặng.
  - `SaveFirstComerIndex` (d__163): `SetFirstComerIndex(idx, toast:1)` → build SetDeck req
    (KHÔNG CheckDeckDesynced, KHÔNG ShootCallback) → fail chỉ log (KHÔNG Restore).
  - `SetFirstComerIndex` (0x32B23E4): `idx>=0` → `currentDeck[idx] as DraggableUnitCard`
    (máy: currentDeck null → NRE, OOB → IndexOutOfRange) → `unitPrefab != null →
    Attack()` (plVar8[0x15] = **0xA8 = decimal 0x15×8** ← BẪY hay nhầm thành 0xA0=
    unitObjCanvas!); chọn lại index hiện tại → idx=-1; `deck[idx] < 1` → -1 (OOB thì giữ
    idx, không ném — outer `idx<len` gate); toast (`&& currentFirstComerIndex != idx`) →
    log key `idx<0 ? "StatB" : "SetTarotPhase"` (gốc CenterText.Show delay=1f ctx=
    GameManager+0x148→+0x60 — convention toast→log); `_firstComerSettings.
    CloseFirstComerSettingUI(idx)` (null → NRE pad, KHÔNG có else-return);
    `data.currentFirstComerIndex = idx`; **tail-call `GameManager.ShootCallback(0x17=
    FirstComerChange=23)`** (mov w1,#0x17; ldp epilogue; b 0x3145e88 — decompiler render
    thành inline loop get_Item = BODY của ShootCallback bị inlining, disasm mới thấy tail-call).
  - `GetCurrentDeck` (0x32B626C): singleton/data null → null; else data.currentDeck.
    `GetCurrentFirstComerIndex` (0x32B630C): `int? ?? -1` dance → null → -1.
- **Scene_Game.cs**: đã có stored-deck resolve (§50/S3b) — chỉ thêm log
  `[DECK1] … useStored=` để verify.

### §67.3 RE laws tái-validation + pitfalls mới

- **Decimal-index trap**: `plVar8[0x15]` trong decompile = ×8 = **0xA8**, KHÔNG phải 0xA0
  (đọc nhầm = field sai ngầm — may có cross-check type UnitController@0xA8).
- **Tail-call bị decompiler inline**: `b <callee>` cuối function + epilogue restore trước nó
  = tail-call; Ghidra render ra BODY callee (loop get_Item…) thay vì call — quyết định
  bằng disasm (0x32b27f8-0x32b280c).
- **HandleDeckResponse semantics chỉ có ở disasm**: decompile render `if (x != 0) {body}`
  + throw-pad cuối thành "fall through", dễ hiểu nhầm thành optional-guard — physical
  `cbz → 0x3154074(bl NRE)` chứng minh mọi null ĐỀU throw. Luôn disasm tail khi decompile
  kết thúc bằng FUN_02c56ba0.
- **Log FUNs (chốt)**: FUN_02d4fdb4 = `Debug.Log` (Web.Get d__14 gọi đúng 2× = REQUEST/
  RESPONSE fmt pair 18784/18786 → không thể LogError); FUN_02da98b4 = `Debug.LogWarning`
  (leaning, 26 callers).
- **type1/type3 token → table vẫn unresolved**: idx=raw>>1; type1 (klass token, ví dụ
  GameManager cell51b30 = 0x2001503f idx43039) tra cả 4 bảng đều garbage → các cell
  klass/action (0x6a765b8, 0x6a7e4e8→DraggableUnitCard suy ra từ field @0xA8, 0x6a7e6c0,
  0x6a7e6e0) resolve bằng usage-context. type3 = type token (ScriptMetadata Name
  kết thúc `_TypeInfo` — 2/2 mẫu) nhưng delegate-method cell vẫn sai → lambda defer.
- Toast keys decode qua cell (dùng y): EquipCard dupe=`AlreadyUsingUnit` ("hero already
  recruited"), slot-full=`DeckNameLengthOver` (key lạ nhưng binary nói vậy — không sửa),
  SetFirstComer=`SetTarotPhase`/`StatB`.
- Caller map: EquipCard/UnEquipCard/SwapDeckCard/SaveFirstComerIndex/SetCurrentDeckPreset/
  GetCurrentDeck = **0 BL-caller** → UnityEvent/delegate (UI slice 2); SetDeck ← d__160+
  d__163; `PotentialButton.<SetPotential>d__19.MoveNext` → HandleDeckResponse (setPotential
  response cũng là DeckResponseModel — slice potential sau); DeckPanel.Reload() 0-arg ←
  Restore + HandlePlayerLevelSyncData + IAPManager + CardInfoPanel + OutgameTutorial.
- `CallbackType`: DeckChange=5, FirstComerChange=23 — nested trong GameManager →
  `GameManager.CallbackType.X` khi gọi từ DeckPanel (global-namespace file, không có
  `using Awesomepiece;` → qualify `Awesomepiece.RestAPI.` — precedent Scene_Game/WorldPanel).

### §67.4 Deferred (slice 2+)

EquipCard (0x32B14A4 — scan slot trùng unitId → toast AlreadyUsingUnit; slot full →
toast; `AddToDeck2(idx, unitId, false)`), UnEquipCard (0x32B1BEC — `Utility.Find` +
vtable+0x178 visual-call chưa naming), SwapDeckCard (0x32B2018, ~800 dòng, gọi
SetFirstComerIndex), AddToDeck2/RemoveFromDeck2 → RestAPI AddToDeck/RemoveFromDeck
(d__108/109), Reload(bool) 0x32ADDD4 (700 dòng) + ReloadDeck 0x32AEEB0 + ReloadFirstComer
0x32AF580, OnPanelEnabled notify-tail, CheckDeckDesynced lambda cell 0x6a7e6d8,
type1/3/6 bảng, GetDefaultPotential port. RestAPI stubs còn lại: SetAllCardPotential/
SetCardPotential (d__112/113). Nguồn: `/tmp/opencode/decomp115.log` + `decomp116.log`
(tmpfs — re-run từ `/tmp/opencode/s2re/decomp_batch11{5,6}.java` nếu mất).

## §68 — S4-2: deck UI (DeckPanel + UnitCard + DeckSlotToggle) — COMPILE-PROVEN (2026-10-20)

Scope: render grid unit + deck slot + preset + sort + page. **Gate PASS 0 error CS** (gate_deck2b/2c;
MasterDataSmokeTest ok). Chưa play-capture. `/tmp` bị wipe giữa session → decomp116–120 logs mất;
port đã nằm trong project files (bền). Muốn đọc lại: re-run Ghidra batch (template §67.4).

### §68.1 Field map ground truth (dump.cs — KHÔNG dùng declaration order của AssetRipper!)

AssetRipper xếp field theo *declaration order*; IL2CPP layout thật lấy từ **dump.cs comment**.
DeckSlotToggle (dump.cs:100647): `rectTransform@0x20, deckNameInput@0x28, nameInputIcon@0x30,
toggles(Toggle[])@0x38, toggleText(Text[])@0x40, toggleLockIcon(GameObject[])@0x48,
changeSlotPageButton@0x50, <curPage>@0x58(int), _deckPanel@0x5C, _extended@0x5D, _inited@0x5E,
_showingBuySlotPopup@0x5F, _onExtended(Action)@0x60`.
**`toggles` = 10 phần tử = 2 trang × 5** (ReloadDeckPanelDeckSlotToggle loop cứng 10; SetActive theo
`GetDeckPageByToggleIndex(i)`). `ReloadToggles` threshold "+" = `_deckPanel ? 4 : 5` (**KHÔNG phải
`_extended`** — dễ nhầm; cả điều kiện nhãn "+" `deckIdx==slotCount` cũng gate `_deckPanel`).

DeckPanel: `currentDeck(UnitCard[])@0x158, cardDatas(List<CardData>)@0x198,
unitCards(List<DraggableUnitCard>)@0x1A0, _deckSlotToggles@0x90, _currentUnitPage@0x220,
_maxUnitPage@0x224, _showSoul@0x1E0, curSort@0x1D0, curSortDesc@0x1D4`.
DraggableUnitCard: `slot@0x84, bg@0x88, uis@0x90, unitObj@0x98, unitObjCanvas@0xA0,
unitPrefab@0xA8, statusText@0xB0, statusBox@0xB8, setEffect@0xC8, artifactEffects@0xD0,
newObject@0xD8, accountNameText@0xE0, potentialLevelBox@0xE8, _lightEffectGroup@0xF0,
_uiLightEffect@0xF8, _spriteLightEffect@0x100, _treasureItem@0x108, _unitPrefabDraggingRoot@0x110`.

### §68.2 Các method ĐÃ PORT (compile pass)

- **UnitCard.cs**: `usingCard/ownCard` getters; `Awake` (Subscribe callback 6 CardExp / 7
  CardLevelUp / 5 DeckChange → ReloadFromCallback); `OnDestroy` (unsubscribe); `ReloadFromCallback`;
  full `Set(CardData, Action<UnitCard>, own, usingCard, showSkin, canNotUseCard, showOriginLevel,
  showExpGauge, showPotential)`; full `Reload`; `OnClick`; `MaxUnitLevel=29` const + color placeholders.
  Offsets: unitSprite@0x20, spriteEffect@0x28, nameText@0x30, levelText@0x38, expGauge@0x40,
  emptyObject@0x48, gaugeCond@0x50, levelBox@0x58, levelBoxCond@0x60, _usingCard@0x68,
  _ownCard@0x69, cardData@0x70, _onClickCallback@0x78, _awaked@0x80, _showOriginLevel@0x81,
  _showExpGauge@0x82, _showPotential@0x83.
  Sprite offset: `res.GetValueDouble(ResourceUnit.UnitTag.SpriteOffsetX, (GameUnit)null, 0.0)` /
  `SpriteOffsetY` (enum 470/469). **`res.GetValueDouble` là stub return 0.0** → offset chưa áp.
- **GameManager.cs**: `GetKeyValue` (null list → null), `GetKeyValueInt` (TryParse /
  `CultureInfo.InvariantCulture` — **KHÔNG phải NumberFormatInfo**), `GetDeckSlotCount`
  (`GetKeyValue("DeckSlotCount") ?? "5"`, cell 0x6a4ff30 defer), `GetDeckSlotName`.
- **FirstComerSettings.cs**: `SetFirstComerAvatar`, 2× `SetFirstComerSettingUI` (SetDraggable(value==0);
  GameManager is-inst tail defer).
- **DeckPanel.cs**: 5 property getters (unitCountPerPage placeholder 10f — cell 0x6a77208 class
  statics colsA/colsB defer), `SortCards` (5 comparers, §68.3), `ReloadItemCountUI`, `SetSortDesc`,
  `ReloadAllToggles`, `OnToggle`, `SetAllToggleInteractable`, `ReloadPrefab(int unitId)`,
  `OnClickUnitPageMove(bool)` + `(bool, int)`.
- **DeckSlotToggle.cs**: `GetDeckPageByToggleIndex` (ceil((i+1)/5)), `SetToggle`,
  `ReloadToggles`, `ReloadDeckPanelDeckSlotToggle(bool extended, int idx=-1)`.

### §68.3 SortCards (static, 5 comparator)

`desc = curSortDesc ? -1 : 1`; `Instance==null → throw`. **Mọi comparer: unowned (level==0) → 1/-1
để dồn cuối**. ByName=`string.Compare(a.name,b.name,InvariantCulture)*desc` (dùng `ResourceUnit.Get`);
ByID=`((int)a.unitId).CompareTo((int)b.unitId)*desc`; ByLevel=level→potentialTier→exp (mỗi cái *desc);
ByRegion=`RegionSortFunc(ra.region,rb.region)*desc`, tiebreak `((int)b.level).CompareTo((int)a.level)`
(NOT *desc) rồi name; ByRole=`ra.role.CompareTo(rb.role)*desc`, tiebreak level rồi name.
**ObscuredInt `.CompareTo` KHÔNG public** → phải `((int)x).CompareTo((int)y)`; `== 0` thì OK nhờ
implicit op. (Compile fix: 6 dòng CS7036 MemoryExtensions.CompareTo.)

### §68.4 Laws mới (rút ra session này)

- **Tail-call overlap**: lambda `b__168_0` @0x32b8978 cách ReloadToggles @0x32b898c **20 byte** →
  thân "lambda" thực ra là **tail-call body của ReloadToggles**; ReloadAllToggles chỉ là
  `foreach (t) t.ReloadToggles()`. Dấu hiệu: hai RVA liền nhau (<0x20) + body trùng.
- **ObscuredInt CompareTo** → cast `(int)` (compiler rơi vào MemoryExtensions.CompareTo của
  ReadOnlySpan<char>, đòi comparisonType).
- **OnToggle(int idx, DeckSlotToggle from)** @0x32B2C3C: `SetDraggingCard(null)` →
  `data.currentDeckPreset=idx`; copy `currentDeck/potential/firstComerIndex ← deckInfos[idx]`
  (+0x10/+0x18/+0x20) → `SetEquippedArtifactPreset(idx)` + `SetEquippedRiftWeaponPreset(idx)` →
  `ReloadDeckArtifactOptions()` → `BarrackAltarBox.Instance?.Reload()` → foreach toggles
  `ReloadDeckPanelDeckSlotToggle(false, idx)` + `toggles[i].SetIsOnWithoutNotify(idx-curPage*5==i)` →
  `ShootCallback(DeckChange=5)` → [defer LogFirebase] → foreach currentDeck `((DraggableUnitCard)w)
  .unitPrefab?.Attack()`. `from` param KHÔNG dùng. [defer] block GetDeckPageByToggleIndex ×2
  (singleton +0x158/+0x20==1) — 2 kết quả bị discard, decompiler mất branch.
- **ReloadPrefab(int unitId)** @0x32B38E4: null currentDeck/unitCards → **throw NRE pad**; quét
  currentDeck + unitCards, `cardData.unitId == unitId → d.ReloadPrefab(true)` rồi `d.Idle()`;
  null cardData trong unitCards → throw, trong currentDeck → bỏ qua.
- **OnClickUnitPageMove(right, count)** @0x32B3CA8: lặp count: trái `_currentUnitPage--; <0 →
  _maxUnitPage-1`; phải `+1 < _max ? +1 : 0` (wrap). Thu pageCards =
  `cardDatas[page*per .. +per]`. Loop unitCards[i]: `i < pageCards.Count` →
  `w.SetActive(i<per); w.SetDeck(this); w.Set(pageCards[i], ShowCardInfo, pageCards[i].level>0,
  false, true, false, false, true, true)`; else `w.SetActive(false)`. OnClickUnitPageMove(bool) =
  tail-call `(right, 1)`. [defer] NEW-badge (AwesomePrefs GetInt/SetInt cell 0x6a7e6a8, threshold
  max unitId; rightPageNewObject.SetActive) + page-dots (DisplayClass176_1, CanvasGroup.DOFade) +
  `w.<field@0x160> = (int)(cardDatas.Count/per)`.
- **ReloadDeckPanelDeckSlotToggle(extended, idx)**: idx=-1 → currentDeckPreset; page=ceil((idx+1)/5);
  `!extended` → `toggles[i].SetActive(page==ceil((i+1)/5))`; [defer] extended → Utility.ForEach
  (lambda b__28_0 cell0x6a7e970); `deckNameInput.SetTextWithoutNotify(GetDeckSlotName(idx))`;
  `_extended = extended`; `_onExtended?.Invoke()`.
- **SetSortDesc** @0x32B34EC: `SetDraggingCard(null); curSortDesc=!curSortDesc; Reload(true);
  AwesomePrefs.SetString(key0x6a7e508, curSortDesc.ToString(), true)` [key placeholder "DeckSortDesc"];
  [defer] LogFirebase + tail inlined GetString decrypt (default cell 0x6a51278/0x6a51280).
- **ReloadToggles** @0x32B898C: "+"-button `SetActive(slotCount > (_deckPanel?4:5))`; loop 10:
  deckIdx=curPage*5+i; `deckIdx<slotCount` → `toggleText[i].text=(deckIdx+1).ToString()`,
  lockOn; `deckIdx==slotCount && _deckPanel` → text "+" (cell 0x6a54dc0), lockOn; else text ""
  (statics 0x6a50260) [defer], lockOff; **`SetToggle(data.currentDeckPreset)`**.

### §68.5 Compile fixes ghi nhớ

`NumberFormatInfo.InvariantCulture` → `CultureInfo.InvariantCulture`; ObscuredInt `.CompareTo` →
`(int)` cast; `MakeOriginSize(Image, float)` (không phải `(float, Image)`); GetValueDouble key là
`ResourceUnit.UnitTag` (không phải `ResourceSkill.SkillTag`); 2 overload GetValueDouble trùng khi
`null` → cast `(GameUnit)null`.

### §68.6 Còn stub (cần re-decode sau /tmp wipe)

DraggableUnitCard: `Set` override (0x…), `Reload` override, `SetDeck`, drag system
`OnBeginDrag/OnDrag/OnEndDrag/SwapCard/Restore`; DeckPanel: `Reload()` + `Reload(bool)` +
`ReloadDeck` + `ReloadFirstComer` + `ReloadUnitPage` + `AddCard` + `OnClick*` + `ShowCardInfo` +
`SetDraggingCard` + `EquipCard` + `UnEquipCard` + `SwapDeckCard` + `Awake`; DeckSlotToggle:
`Init/Awake/OnToggle/ReloadToggles`done/`ChangeSlotPage`/`BuyDeckSlot`; RestAPI d__108/109/112/113.
`ReloadAllToggles` đã nối đúng vào `ReloadToggles`.

## §69 — Cửa ngõ data trước ngày ship: `getPatchFolder` version-gate + notice hub `/en` (2026-10-20)

**`POST kgc-k8s-1.awesomepiece.com/auth/getPatchFolder`** — body/headers AES-ECB key
`a6072ad6b9c959ff` (header `time` = hex AES của `"beforeLogin"`), **response cũng mã hoá** cùng key.
Gate theo header `version`: `174.0.00` → folder cũ, **`≥174.1.00` (kể cả `999.0.00`) → folder mới
nhất**. `platform` (Android/iOS/PC/Windows/AOS/Amazon/OneStore) cho cùng kết quả; `isDev:true` →
`patchFolder: ""`. ⇒ Dùng `999.0.00` làm probe "luôn newest" (đã nối vào `official_patch_folder()`).

**Notice hub đổi route 2026-10-20**: `kgcastle-notice.awesomepiece.com/<news-page-id>` giờ **301 →
`/en`**; `GET /en` trả `__NEXT_DATA__.props.pageProps.recordMap` của News page (~33 page block,
title nằm ở `block[].value.properties.title`). Trang detail vẫn là `/<block-id>` **không** prefix
(`/en/<id>` trả về hub). `scripts/kgc_new_unit_watch.py` đã đổi `NOTICE_LIST_URL` sang `/en`.

**Cloud Run dev envs đã bị xoá**: `*-x4bivlxmuq-du.a.run.app` (single-treasure-gacha, unit-10820,
qa-1008…) → 404 toàn bộ; `castle-infra-server-…/api/cloud-run/services` → 404. Không còn swagger
diff để đọc trước tính năng. Kênh còn sống: getPatchFolder (data đã public), CDN object GET,
notice hub, `kgc-k8s-1` `/health` `/healthcheck` `/promo-test` (AES), `kgc-ranking-1` `/health`
(còn lại 401 `WrongTokenError`).

## §70 — Service dev còn sống: hash project KHÔNG đoán, nhưng tên service thì đoán được (2026-10-20)

**Sửa lại kết luận §69**: "không còn swagger diff" là SAI. Project hash `x4bivlxmuq` **vẫn dùng
được** — cái chết chỉ là gateway *liệt kê* service (`/api/cloud-run/services` → 404). Hash không bao
giờ phải đoán: nó được **đọc** từ JSON của gateway đó (host gateway thì lấy từ string literal trong
`libil2cpp.so`). Chỉ **project GCP mới** mới cần leak.

**Oracle**: `GET https://<name>-x4bivlxmuq-du.a.run.app/health`
- `404` + body **272 B** `text/html` (`Error: Page not found`) = service không tồn tại
- bất kỳ mã nào khác = service có thật

> Bẫy: đo `len(e.read(200))` sẽ khiến mọi 404 thành "200B" và báo dương tính giả hàng loạt. So
> `content-length` thật hoặc md5 body với body của một hostname bịa.

**Sống (sau khi sweep ~200 tên)**: `default-x4bivlxmuq-du.a.run.app` — game API dev, branch mới nhất.
`qa-ranking-default-…` sống nhưng 500 mọi path. Toàn bộ 7 env cũ (balancing, update-1008main,
qa-1008, qa-0923, unit-10820, single-treasure-gacha) đã xoá.

**`default` — recipe**:
```bash
curl -s https://default-x4bivlxmuq-du.a.run.app/v2/api-docs -o /tmp/v2.bin
python3 - <<'P'
from Crypto.Cipher import AES; import json
d=AES.new(b'cnf1tl65djs2wp3g',AES.MODE_ECB).decrypt(open('/tmp/v2.bin','rb').read()).rstrip(b'\0')
print(len(json.loads(d)['paths']))   # baseline 2026-10-20: 469 paths / 159 definitions
P
```
- `/v2/api-docs`, `/swagger-ui.html`, `/swagger-resources` **mở** (key legacy `cnf1tl65djs2wp3g`)
- `/health`, `/healthcheck` **plaintext** (khác prod, prod mã hoá)
- `/version`, `/actuator/*` → 401 `WrongTokenError`
- `/auth/getPatchFolder` → `patchFolder: ""` cho mọi `version`/`isDev` (dev env không map CDN).
  Request body phải mã hoá bằng key **hiện tại** `a6072ad6b9c959ff` (body hex + header `time`); key
  legacy cho body → 400 `Bad Request`.
- Không có endpoint master data ⇒ **không** đọc được treasure/Bảo Cụ ở đây; chỉ là tín hiệu API.

**Delta 469 vs 463 (spec 1021 staging)**: `+20/-0`, toàn bộ là `/incarnation-unit/*` +
`/single-arena/*` (+ test twins). Xác nhận branch hiện tại = incarnation + single arena; **không** có
endpoint treasure mới ⇒ Bảo Cụ 11-05 tái dùng `/treasure/*`.

Dùng làm early-warning: diff số path + danh sách path mỗi lần chạy watcher; path mới = feature đã merge.

## §71 — S4-2 hoàn tất: drag & drop deck, DeckSlotToggle, lobby 0 NRE (2026-10-20)

**Runtime proof**: `tools` capture `KGC_CAPTURE_PLAY=1 … CaptureScene.Run` → `[PLAYCAPTURE] play
capture ok (exit 0)`, **0 NullReferenceException** trong toàn bộ chuỗi login → Scene_Lobby →
`Scene_Lobby.Init → ReloadPanels → DeckPanel.Init → Reload → ReloadDeck`. Ảnh lobby render đủ
bottom-nav (Shop/Barracks/Gate/Alliance/Battleground) và currency.

### 3 luật mới (đã trả giá bằng 3 lần capture)

1. **AssetRipper làm RƠI tham chiếu serialized trên instance trong Scene** (không phải trên prefab).
   6 `DraggableUnitCard` của deck trong `Scene_Lobby.unity` có `unitSprite: {fileID: 0}`,
   `spriteEffect: 0`, `emptyObject: 0`, `levelBoxCond: 0` (component vẫn là DraggableUnitCard —
   guid `841addb1…`, KHÔNG phải UnitCard `0d93b393…`; YAML Unity serialize cả field của base class
   nên dễ đọc nhầm). Hệ quả: `UnitCard.Set` NRE ở `unitSprite.sprite`.
   → Vá tại chỗ dùng được: trong `DraggableUnitCard.Set`, nếu `unitSprite == null && unitObj != null`
   thì `unitSprite = unitObj.GetComponent<Image>()` (ảnh unit chính là Image trên child "UnitObj";
   con duy nhất của UnitObj là "RecommendIcon"). Card sinh từ prefab `unitCardPrefab` có ref đủ nên
   không bị ảnh hưởng.
   *Cách kiểm tra data loss nhanh*: `grep -c "unitSprite: {fileID: 0}" Assets/Scene_*.unity`.
2. **AssetRipper bỏ field initializer của private field** (`= new List<T>()`) → null lúc runtime.
   Biểu hiện: `DeckPanel.AddToggleListner` NRE (`_deckSlotToggles.Contains`). Field **public/serialize**
   thì Unity tự tạo list rỗng từ scene YAML (`cardDatas: []`), nên chỉ private mới chết.
   Đã thêm initializer cho `_deckSlotToggles`, `_unitBgObjects`, `_pageConds`, `_artifactCards`,
   `_artifacts`, `_riftWeaponInfo`.
3. **`GameManager.GetCard/GetCards/GetCardOrMakeZeroLevel` từng là stub `return null`** — đây là gốc
   của NRE `DeckPanel.SortCards` (comparer deref null) chứ không phải lỗi deck panel. Đã port:
   - `GetCard` RVA `0x314B424`: nguồn `data.cards` (@0x88), `List.Find(c => c.unitId == id)`;
     `ignoreTemporaryRecruitedUnit && card.isTemporaryRecruited` (@0x61) → null.
   - `GetCards` RVA `0x314C008`: `data.cards.FindAll(condition)` (FindAll không bao giờ null).
   - `GetCardOrMakeZeroLevel` RVA `0x314BEB4`: `GetCard(id) ?? new CardData { unitId = id, level = 0 }`
     rồi `data.cards.Add`.
   - `[defer]` nhánh rogue-like (`inGame && currentRogueLikeDataSet.<0x90>.<0x10>`): property chưa port.

### IDraggableDeck — default interface body là code THẬT, không phải stub

`dump.cs` liệt kê 6 method `virtual` có RVA trong interface (slot 10,12,13,18,19,20). Đã port đúng:
`GetDeckBgObject`/`GetLayoutBgObject` → `null`; `GetIndexFromCurrentLayout` → **-1** (export ghi `0`);
`CheckBeforeEquipCard` → `ret`; `HasToCheckBeforeEquipCard` → `false`;
`CanEquipCard` RVA `0x32CD074` = gate "trùng `ResourceUnit.aiType` trong deck" (card/cardData null →
true; `resUnit == null || aiType != <literal>` → true; ngược lại duyệt `GetCurrentDeck()`, bỏ qua idx,
trùng → `CenterText.Show(<key>)` + false). **`[defer]`**: literal `aiType` + key nằm trong
**metadata-usage table** (`0x6C185xx`), KHÔNG resolve được qua `.rela.dyn` → hiện `return true`
(đúng cho mọi unit không thuộc nhóm bị giới hạn). `DeckPanel` KHÔNG override 6 method này —
đừng đi tìm chúng trong DeckPanel.cs.

### Drag & drop (DraggableUnitCard) — port xong

| Method | RVA | Semantics |
|---|---|---|
| `OnBeginDrag` | 0x32CA3D0 | guard `cardData == null \|\| !_draggable`; `_deck.SetDraggingCard(this)`; `_dragging = true`; Button.interactable = false; `_originUiY = uis.localPosition.y`, `uis.SetParent(unitObj)`; `unitObj.localEulerAngles = (0,0,20)`, sortingOrder +2; `_unitPrefabOriginRoot = (parent as RectTransform, siblingIndex)` rồi SetParent(`_unitPrefabDraggingRoot`); `AudioController.Play("se_unit_drag_start", null)` |
| `OnDrag` | 0x32CA9C0 | `unitObj.position = ScreenToWorldPoint(evt.position) + (0,20,0)`; `uis` theo unitObj; highlight qua `Utility.GetCurrentSelectedObject<DraggableUnitCard>()` |
| `OnEndDrag` | 0x32CB0C4 | trả unitObj về `_unitPrefabOriginRoot`; `AudioController.Play("se_unit_drag_end", null)`; `DraggableRange.type == Unit` → `SetDraggingCard(null)`+`SaveDeck()`+`SetEffect()`; fallback `FindCardFromCurrentDeck` khi con trỏ trên `GetDeckLayout()`; nhánh đích là ô deck → `CanEquipCard` → (`HasToCheckBeforeEquipCard` ? `CheckBeforeEquipCard(idx, this, …, Restore)` : trực tiếp) `SwapCard`; nhánh kéo RA khỏi deck → `CheckIsInMatchmakingAndShowCenterText(-1)`, `UnEquipCard(cardData)`, `SaveDeck()` |
| `SwapCard` | 0x32CBF60 | `GetCurrentFirstComerIndex() == targetIdx` → `SetFirstComerIndex(-1, true)`; `selected != null` → `UnEquipCard(selected.cardData)`; `EquipCard(targetIdx, this)`; `SaveDeck()`; `SetEffect()` |
| `Restore` | 0x32C0D58 | `_dragging = false`; unitObj local pos/euler = 0, sortingOrder = `_baseSortingOrder`; `uis.SetParent(transform)` + `(0,_originUiY,0)`; `_lightEffectGroup` về transform; statusBox SetAsLastSibling; spriteRenderers.sortingOrder reset; trả bg `_oldSelectedCard` / `_oldSelectedBg` |

### DeckPanel / DeckSlotToggle port xong

`DeckPanel`: `Awake` (Instance=this, tắt 2 prefab, prefs sort, Subscribe 12 callback, 
`FirstComerSettings.Initialize`, `SetDeck(this)` cho từng card), `ReloadCrystalBadge`
(`AwesomePrefs.HasKey("NewRiftCrystalAdded") | CanAdChargeRiftGauge()`, `_riftCrystalBadgeCond.SetValue`),
`ReloadDeckCombatPower`, `OnPanelDisabled` (`_dragging?.Restore()`), `OnSortChange`
(`curSort = (curSort+1)%5; Reload(true)`).
**`Awake` KHÔNG được gọi `Reload(true)`**: máy chỉ gọi trong nhánh tween cuối (khối
`_unitPageArrowButtons`), còn Awake chạy trước khi `/player` trả về → `data == null` → NRE
`ReloadDeck`. Nơi Reload chạy đúng là `Scene_Lobby.Init → ReloadPanels → DeckPanel.Init`.
`DeckSlotToggle`: `Awake` (`Init(DeckPanel.Instance.deckSlotToggle == this)`), `Init(bool)`,
`OnToggle(int)` (allOff → SetIsOnWithoutNotify), `OnToggle(int,bool,bool)` (slot = curPage*5+idx,
gate `GetDeckSlotCount()`, `BuyDeckSlot()` khi slot == count && _deckPanel),
`ChangeSlotPage`, `OnClickChangeSlotPage`.

### Còn `[defer]` ở deck (không chặn build)
`ApplyBoxBgEffects` ×2 (tô màu bg), `ReloadArtifactEffects`/`ReloadArtifacts*`/`ReloadRiftWeaponUI`
(chờ slice artifact), tween page-arrow + page-dot fade, NEW-badge prefs, `SetStatusBox`,
`SetAccountName`, `ShowDimensionUnitOvercome`, nhánh rogue-like của GetCard(s), literal `aiType`.

### Bước kế tiếp
Slice 3 (Barracks mở panel deck bằng capture), rồi S4 theo thứ tự plan: gacha → artifact →
territory → pvp → clan → rogue-like → story.

## §72 — Build APK từ Unity Editor: ĐÃ RA APK (2026-10-21)

**Kết quả**: `unity/kgc-rebuild/ExportedProject/Builds/kgc-mono.apk` — 99.9 MB, `com.awesomepiece.castle`,
versionCode 174 / versionName 174.0.00, `armeabi-v7a`, đủ 6 scene (Logo/Login/Lobby/Game/Territory/Loading).
`Build Finished, Result: Success`, exit 0.

### Lệnh build

```bash
# Mono (đường đang chạy được), ~10 phút:
KGC_BUILD_SKIP_IL2CPP=1 /home/nowl/Unity/Hub/Editor/2022.3.62f3/Editor/Unity \
  -batchmode -quit -projectPath unity/kgc-rebuild/ExportedProject \
  -buildTarget Android -executeMethod Kgc.Editor.BuildApk.Run -logFile /tmp/build.log
```
Script: `Assets/Game/Editor/BuildApk.cs` (Kgc.Editor.BuildApk): `Run()` (IL2CPP trước, fallback Mono nếu
`KGC_BUILD_SKIP_IL2CPP` khác `1`), `BuildMono()`, `Probe()` in cấu hình. Output `Builds/kgc.apk` /
`Builds/kgc-mono.apk`.

### 6 lỗi export phải sửa (tất cả do AssetRipper, không phải code game)

| # | Triệu chứng | Nguyên nhân thật | Sửa |
|---|---|---|---|
| 1 | `UnityException: Target architecture not specified` (dù `AndroidTargetArchitectures: 2`) | `ProjectSettings.asset` export để kiến trúc trống; **Mono + ARM64-only** bị prerequisite từ chối và thông báo sai lệch | IL2CPP + ARM64, hoặc Mono + **ARMv7** |
| 2 | `The Assembly UnityEditor.CoreModule is referenced by UnityEngine.UI ('Assets/Plugins/UnityEngine.UI.dll')` | DLL `UnityEngine.UI.dll` **giả 5 KB** do AssetRipper sinh; project còn **không cài** `com.unity.ugui` nên phải dựa vào nó | thêm `"com.unity.ugui": "1.0.0"` vào `Packages/manifest.json`, **xoá** DLL giả |
| 3 | 9 lỗi `CS0246 UnityAds*` khi build Android | đã đặt DLL giả `UnityEngine.Advertisements.dll` thành Editor-only → Android mất type | thay bằng shim thật `Assets/Scripts/Assembly-CSharp/UnityAdsShim.cs` (enum + 3 interface; `UnityAdsManager` vốn no-op), **xoá** DLL giả |
| 4 | `Fatal error in Unity CIL Linker … ResolveFromAssemblyStep.ProcessExecutable` (IL2CPP) | chưa xác định — `__Generated.dll` (assembly rỗng, ref `Unity.IL2CPP.Metadata`) chỉ là 1 nghi phạm; 88 DLL trong `Assets/Plugins` đều hợp lệ (monodis: đủ type, không trùng tên, **0 ref không resolve**) | **còn mở**; Mono không chạy linker nên đây là lý do dùng Mono |
| 5 | Gradle `android.defaultConfig.versionCode is set to 0` | `AndroidBundleVersionCode: 0` trong ProjectSettings | `AndroidBundleVersionCode: 174` + ép trong `BuildApk.Run` |
| 6 | bundle id rỗng → `com.Awesomepiece.` | `applicationIdentifier: {}` | `applicationIdentifier: { Android: com.awesomepiece.castle }` |

### Luật rút ra

- **DLL 2–5 KB trong `Assets/Plugins` = stub AssetRipper** (chỉ khai báo type, không có thân hàm).
  Chúng compile được nhưng **không được vào player build**: gây lỗi tham chiếu `UnityEditor.*` hoặc
  UnityLinker NRE. Kiểm tra nhanh: `find Assets -name '*.dll' -printf '%s %p\n' | sort -n | head`.
  Plugin nào game dùng thật ở runtime thì phải thay bằng package thật hoặc shim trong
  `Assets/Scripts/Assembly-CSharp/`.
- **Trước khi build, kiểm tra `ProjectSettings.asset`**: `AndroidTargetArchitectures`,
  `AndroidBundleVersionCode`, `applicationIdentifier`, `scriptingBackend` — export hay để trống.
- **Mono + ARM64 = không hợp lệ** ở Unity 2022; muốn Mono thì ARMv7 (hoặc thêm ARMv7 vào bitmask).
- Build Mono ~10 phút (8 phút phần lớn là Gradle/assets), IL2CPP chết sớm ở UnityLinker (~2 phút).

### Còn mở

- **IL2CPP**: UnityLinker NRE. Bước tiếp: thử (a) IL2CPP + ARMv7 để loại trừ yếu tố kiến trúc,
  (b) chạy lại linker thủ công với `Temp/StagingArea` được giữ lại, (c) gỡ dần DLL stub khỏi
  `Assets/Plugins` theo nhóm (chỉ những plugin game không dùng ở runtime).
- Chưa cài lên redroid để test runtime (`adb devices` trống lúc build).

## §73 — S4-3: mua deck slot, keyValues, IsPointerOver (2026-10-21)

### Kết quả
- **Deck slot mua được** (client-authoritative): `DeckSlotToggle.BuyDeckSlot` → popup BuyConfirm →
  `RequestBuyDeckSlot` → `POST /deck/buyDeckSlot` → `SetDeckSlotCount(count+1)` →
  `DeckPanel.ReloadAllToggles()` → `OnToggle(count - curPage*5, force:true, expand:true)`.
- Gate compile `gate_deckslot4` **PASS** (0 `error CS`).

### Bảng RVA (v174.0.00, file offset = RVA − 0x4000)
| Method | RVA | Ghi chú |
|---|---|---|
| `DeckSlotToggle.OnDestroy` | 0x32BDBDC | chỉ `_onExtended = null` (field @0x60) |
| `DeckSlotToggle.SetDeafultState` | 0x32BDBE4 | `ReloadDeckPanelDeckSlotToggle(false,-1)`; nhánh `!_deckPanel` gọi `ClickOutsideClose.Show` qua interface slot 51 ⇒ [defer] |
| `DeckSlotToggle.Update` | 0x32BDCE8 | `_extended(0x5D) && !_showingBuySlotPopup(0x5F) && Input.GetMouseButtonDown(0) && !Utility.IsPointerOver_New(transform)` → thu gọn |
| `DeckSlotToggle.BuyDeckSlot` | 0x32BE2D4 | giá = `ResourceConstant.Get(Type.DeckSlot=15, GetDeckSlotCount()+1)`; `Scene_Lobby.Instance.popup2.Show(key BuySlotCostAlert, Popup.Type.BuyConfirm, cb, 0, cash, 0)`; gate `EarlyAccessModeClickableObject` [defer] |
| `DeckSlotToggle.RequestBuyDeckSlot` | 0x32BE5EC | async `RestAPI.BuyDeckSlot(new DeckRequestModel())` (d__33) |
| `RequestBuyDeckSlot` continuation | 0x32BF208 (trong d__33.MoveNext) | `SetDeckSlotCount(count+1)` → `DeckPanel.ReloadAllToggles` (0x32B2B40) → `OnToggle(count - curPage*5, 1, 1)` |
| `GameManager.SetDeckSlotCount` | 0x3162F64 | `Int32.ToString` + ghi keyValues ⇒ `SetOrAddKeyValue("DeckSlotCount", …)` |
| `GameManager.HandleSetDeckSlotName` | 0x3162FCC | `SetOrAddKeyValue(prefix, index.ToString(), name)` |
| `GameManager.GetDeckSlotName` | 0x3163064 | `GetKeyValue(prefix, index)`; rỗng → `Format(L(DeckSlotNameDefaultFormat), index+1)` |
| `Utility.IsPointerOver_New` | 0x2C98714 | null/`!activeSelf` → false; `GetMousePosition()` + `GetTopmostCanvas()` + rect test |
| `Utility.IsPointerOver(Transform)` | 0x2C98364 | cùng logic |

### Bài học / quy ước mới
- **`DeckSlotCount` KHÔNG phải state server**: client đọc/ghi trong `PlayerData.keyValues`
  (`GetKeyValue("DeckSlotCount") ?? "5"`). Server chỉ cần trả success; đã thêm
  `DYNAMIC_OVERRIDES["/deck/buyDeckSlot"]` trong `server/server.py`.
- **Endpoint mua slot**: literal `/deck/buyDeckSlot` (gom từ metadata: `/deck`, `/deck/buyDeckSlot`,
  `/deck/set`, `/deck/setPotential`). `RestAPI.BuyDeckSlot` đã ở dạng callback trong port.
- **keyValues chỉ có overload 1 key** trong port; bản máy dùng `(key, index)` ⇒ đã thêm overload
  `GetKeyValue(key, index)` / `SetOrAddKeyValue(key, index, value)` (nối chuỗi `key + index`).
  `SetKeyValue` = chỉ ghi đè; `SetOrAddKeyValue` = ghi đè hoặc thêm mới.
- **`ResponseModel` không có `success`** — dùng `isSuccess` (`code == 200`). Build_model của server
  set `code = 200`, nên handler chỉ cần trả `{}`/`code`.
- **`Popup.Type.BuyConfirm = 2`**, `Popup.Show(string text, Type type, Action<bool> cb, int gold, int cash, int heart)`.
  Popup của lobby là `Scene_Lobby.Instance.popup2` (field @0x70 của `Scene_Base`), fallback `.popup` @0x68.
- **Caller-scan BL dùng lại được**: quét `(w>>26)==0x25`, `site = i*4 + 0x4000`, `target = site + imm*4`
  → tìm được continuation của async MoveNext (0x32BF208) mà grep annotation bỏ sót.

### Còn mở (§73)
- `DeckSlotToggle.OnSlotNameChanged` / `OnSlotNameEndEdit` / `SetDeckSlotName` (d__35/d__36) +
  `CheckDeckNameValidity`: chuỗi async đổi tên slot (await `DeckResponseModel`) — chưa port.
- `DeckPanel.OnDestroy` (0x32AC570), `ReloadLevelLockedUI` (0x32B0674), `ReloadRiftWeaponUI`.
- Nhánh `ClickOutsideClose.Show` và gate `EarlyAccessModeClickableObject`.

### Runtime verify (§73)
- `ShopPanel.ReloadShopTabEnable` NRE: `goldFreeBadge` **không được serialize trong scene export**
  (AssetRipper mất ref) → guard null. Đây là NRE mới lộ ra khi chain `ReloadPanels` chạy tới
  `ShopPanel.Init` (qua `FetchSeasonPassEventBooster`).
- Capture `cap_s73b` (login → lobby, settle 150): **0 NullReferenceException**,
  `[PLAYCAPTURE] play capture ok (exit 0)`, ảnh `shot_Scene_Lobby.png`.
- Gate compile `gate_s73b`: 0 `error CS`.

## §74 — iOS: ký lại IPA là chết ở FairPlay, trước khi Unity kịp chạy (2026-10-21)

Câu hỏi: có thể mod skin và chơi trên **official server** bằng IPA ký lại (ESign/VSign) không?

**Đã kiểm chứng bằng IPA thật** (`ipatool download -b com.awesomepiece.castle`, v174.0.00, 815MB):

- **Static patch: không thể.** Mọi Mach-O trong IPA đều FairPlay (`cryptid=1`), không chỉ binary
  chính — `ProductName`, `UnityFramework`, `xigncode`, `appsign4i`, `Airbridge`. ESign không decrypt.
- **Nhưng `UnityFramework` export 241 symbol il2cpp** (`il2cpp_class_from_name`,
  `il2cpp_class_get_method_from_name`, `il2cpp_domain_get`, `il2cpp_runtime_invoke`) — export table
  nằm trong `__LINKEDIT`, không bị mã hoá. Nên về lý thuyết inject dylib rồi hook theo **tên**
  (giống `stub.cpp` bên Android) là làm được **không cần dump offset**.
- **`appsign4i` export** `AsGetCookie2Impl`, `AsGuardValidate`, `AsGuardGetSalt`, `AsGuardGetKey64`,
  `AsGuardUpdateTimestamp`, `AsReportTamper` → đúng cơ chế AppSign cookie (bản iOS của
  `libappsign4a.so`), kèm chống replay + báo tamper.

**Test quyết định (VSign, bundle id giữ nguyên, IPA stock 100% không sửa, không inject gì):**
app cài được nhưng **văng ngay khi mở**, trước cả khi Unity vào scene nào.

Crash report `/ProductName-2026-10-21-005652.ips`:

```
EXC_BAD_ACCESS / KERN_PROTECTION_FAILURE at 0x1045f520c
pc = far = 0x1045f520c        (nhảy vào vùng không thực thi)
xigncode.framework/xigncode  0x104598000 + 0x5d20c
  <- dyld4::LibSystemHelpers::callInitializer
  <- dyld4::Loader::findAndRunAllInitializers
```

Chữ ký sau khi ký lại: `SignerIdentity = "iPhone Distribution: Beihang University"`,
`application-identifier = ZXB3TS7QD4.cn.edu.buaa.wxwork.notifyext`, team `ZXB3TS7QD4` — tức
application-identifier **không còn khớp bundle id**, chứ không chỉ đổi cert.

**Loại trừ XIGNCODE (2026-10-21, cùng ngày):** dựng `scripts/strip_ios_framework.py` để xoá
`Frameworks/xigncode.framework/` (12 entry) và đổi `LC_LOAD_DYLIB` → `LC_LOAD_WEAK_DYLIB`
(`0x80000018`) trong `ProductName`, giữ nguyên `appsign4i`. Ký lại bằng VSign → **vẫn văng**, nhưng
crash **đổi chỗ**:

```
/ProductName-2026-10-21-010950.ips
EXC_BAD_ACCESS / KERN_PROTECTION_FAILURE at 0x102ca005c
appsign4i  base 0x102c9c000 + 0x405c  ->  RegisterInitializeObserver + 0x0
  <- dyld4::LibSystemHelpers::callInitializer
```

Cùng một kiểu lỗi, ở framework mã hoá kế tiếp, ngay **instruction đầu tiên của initializer**. Và
đây là mấu chốt: `0x405c` nằm trong `__TEXT` của `appsign4i` (`vm=0x0+0x8000`, `initprot=5` = RX)
— trang **đáng lẽ phải executable** mà kernel vẫn từ chối cấp exec. Không phải anti-cheat phát hiện
gì cả: **FairPlay không giải mã được sau khi ký lại**, nên `__TEXT` không được map executable và
lệnh đầu tiên trong hàm là fault.

Đây cũng là lý do các tool sideload đều đòi IPA **đã decrypt**: `cryptid=1` + chữ ký khác Apple =
chết ở instruction đầu tiên của mọi image mã hoá (`ProductName`, `UnityFramework`, `xigncode`,
`appsign4i`, `Airbridge` — tất cả đều `cryptid=1`).

**Kết luận cuối: đường ESign/VSign/AltStore/Sideloadly lên official server là bất khả thi trên iOS
với IPA lấy từ App Store.** Chặn ở tầng thấp nhất (FairPlay), trước cả anti-cheat, trước cả auth —
nên bỏ xigncode, inject dylib, hay đổi cert đều vô nghĩa: chưa có dòng code nào của game chạy được.
Đường đi tiếp chỉ còn: **IPA đã decrypt** (cần jailbreak để dump, hoặc lấy từ nguồn ngoài) — và kể
cả có IPA decrypt thì `appsign4i` vẫn tính AppSign cookie trên chữ ký mới, mà server official
kiểm tra cookie đó (xem `docs/handoff-official-token.md`). iOS 26.7.1 không có jailbreak → đóng.

Công cụ thêm vào repo: `scripts/inspect_ios_ipa.py` (stdlib, có `--selftest`) — đọc `cryptid` từng
Mach-O, tách marker il2cpp mạnh/yếu (`il2cpp_init` vs `global-metadata.dat`), in quan hệ
RVA→file offset; `scripts/strip_ios_framework.py` (có `--selftest`) — xoá 1 framework + hạ load
command xuống weak, dùng cho chẩn đoán kiểu "lib nào giết app". Lưu ý: `ipatool` phải là bản
**linux-amd64**; tarball `linux-arm64` tải nhầm trên máy x86_64 chỉ cho ra
`qemu-aarch64-static: Could not open '/lib/ld-linux-aarch64.so.1'`.

### §73b — Đổi tên deck slot (port xong)
- `DeckSlotToggle.CheckDeckNameValidity` (0x32BE7AC): quá `ResourceConstant.Get(Type.DeckSlotNameMaxLength=33)`
  → popup `DeckSlotNameLengthOver`; rỗng/chỉ space → `DeckSlotNameCannotBeEmpty`. (Regex pattern còn [defer].)
- `DeckSlotToggle.SetDeckSlotName` (0x32BE70C / d__36): popup lỗi → revert `InputField.text =
  GetDeckSlotName(idx)`; hợp lệ → `DeckNameRequestModel{presetIdx, name}` →
  `RestAPI.SetDeckSlotName` (callback) → `HandleSetDeckSlotName(idx, name)`.
- `OnSlotNameEndEdit` (0x32BE680 / d__35) → `SetDeckSlotName(currentDeckPreset, deckNameInput.text, deckNameInput)`.
  `OnSlotNameChanged` (0x32BE67C) = `ret` trong bản máy.
- Gate `gate_s73c` PASS (0 error CS).

### Mức hoàn thành thật (2026-10-21, đo bằng regex trên `Assembly-CSharp`)
`20.654` method khai báo trong port, **`14.503` (70%) vẫn là stub rỗng**. Đó là thước đo trung thực cho
"giống 100%": phần hành vi còn thiếu nằm ở các hệ S4/S5 (gacha, artifact, territory, pvp, clan,
rogue-like, story, battle). Nhiều stub rỗng là hợp lệ (Unity message rỗng, interface no-op), nên con số
thật thấp hơn 70% một chút — nhưng vẫn còn rất xa 100%.

## §74 — S4 tiếp theo: gacha (bản đồ điểm vào, cho phiên sau)

### Trạng thái
- `GachaPanel.Close()` **đã port** (override ở `GachaPanel.cs:393`, không phải stub).
- `GachaPanel` còn **36 stub**, toàn bộ là animation/state-machine của màn mở hộp.

### Bản đồ RVA (v174.0.00, file = RVA − 0x4000) — `GachaPanel`
| Method | RVA | Ghi chú |
|---|---|---|
| `get_curBox` / `get_dismantleAllSelected` | 0x33AD248 / 0x33AD284 | property nhỏ |
| `Show()` / `Show(ResourceGacha, GachaResultCollection, …)` | 0x33AD378 / 0x33AD37C | entry chính; nhận `(gacha, results, x3, w4, x5)` |
| `ShowOvercomeRewardChromaSkinResult(List<GachaResult>, Action)` | 0x33AD44C | dimension hero |
| `Hide()` | 0x33AD4F4 | animation đóng |
| `Close()` | 0x33AD7C0 | `if (field 0x190) base.PopupPanel.Close()` — ĐÃ CÓ |
| `OnClick()` | 0x33AD7D8 | |
| `BoxOpen()` / `SkipBoxOpen()` / `SkipCardOpen()` | 0x33ADAB0 / 0x33AD9D4 / 0x33ADC08 | |
| `ShowNextItem()` | 0x33ADD30 | |
| `ShowResult()` / `ShowResultOnly(...)` | 0x33AE6FC / 0x33AF2D4 | |
| `ShowCardEffect(Animator, bool)` | 0x33AE554 | |
| `UnFoldResult()` | 0x33B05F0 | |

### Đường request (server đã xong)
- Server: `server/shop_routes.py` xử lý `/shop` với `gachaId` (2 nhánh: mua trực tiếp + mua scroll),
  trả `newUnitIds`, `cardExpResults`, `upgrade`, reward `DimensionOvercome` — §"Dimension hero gacha".
- Client: `RestAPI` đã có sẵn stub callback cho `/shop`; việc cần làm là **port `ShopPanel` apply kết quả
  → `GachaPanel.Show(resGacha, result)`** rồi animation.
- Cách tìm nhanh call-site: quét BL tới `GachaPanel$$Show` (0x33AD37C) bằng numpy
  (`(w>>26)==0x25`, `site=i*4+0x4000`, `target=site+imm*4`) — không cần Ghidra.

### Thứ tự làm gacha (đề xuất)
1. `RestAPI` gacha request nếu còn stub + `ShopPanel` apply `newUnitIds`/`cardExpResults`.
2. `GachaPanel.Show(...)` (dựng list + `SetActive(true)`), rồi `ShowResult`/`UnFoldResult`.
3. Animation: `BoxOpen`/`SkipBoxOpen`/`SkipCardOpen`/`ShowNextItem` — port sau cùng, có thể
   tạm cho `SkipCardOpen` nhảy thẳng `Hide()`.
--- GachaPanel.Show(args) (0x33ad37c) callers=17
   site 0x3387d20  in BuyGachaButtonGroup$$HandleNewUnitGachaResult +0x578
   site 0x338b700  in BuyGachaButtonGroup.<>c__DisplayClass33_0$$<HandleUnitGachaResult>g__OpenGacha|0 +0x103c
   site 0x338be8c  in BuyGachaButtonGroup$$<HandleArtifactGachaResult>g__OpenGacha|34_0 +0x508
   site 0x33939e0  in BuyGachaConfirmPanel.<>c__DisplayClass34_0$$<BuyFourGacha>g__OpenGacha|1 +0x6a0
   site 0x3393fa0  in BuyGachaConfirmPanel.<>c__DisplayClass34_0$$<BuyFourGacha>g__OpenGacha|2 +0x448
   site 0x3406bbc  in ShopItem.<>c__DisplayClass91_0$$<BuyProcess>g__OpenGacha|1 +0x3b8
--- ShowOvercomeRewardChromaSkinResult (0x33ad44c) callers=1
   site 0x33b5228  in GachaPanel.<ShowOvercomeRewardChromaSkinResult>d__55$$MoveNext +0x4bc
--- ShowResult (0x33ae6fc) callers=1
   site 0x33b5468  in GachaPanel.<ShowResultOnly>d__64$$MoveNext +0x98

### §74b — Call-site của `GachaPanel.Show` (quét BL, v174)
17 caller. Nhóm theo đường request:
- **`BuyGachaButtonGroup`**: `HandleNewUnitGachaResult` (+0x578), `HandleUnitGachaResult` g__OpenGacha|0,
  `HandleArtifactGachaResult` g__OpenGacha|34_0, `HandleBoxGachaResult`… ⇒ đây là **trung tâm** của flow gacha
  một-lần (unit / artifact / box).
- **`BuyGachaConfirmPanel.<BuyFourGacha>g__OpenGacha|1|2`** ⇒ flow mua 4 lần (x10 liên tiếp).
- **`ShopItem.<BuyProcess>g__OpenGacha|1`** ⇒ flow mua qua shop item (scroll).
- `ShowOvercomeRewardChromaSkinResult` chỉ được gọi từ chính `d__55.MoveNext`;
  `ShowResult` chỉ từ `ShowResultOnly(d__64).MoveNext` ⇒ 2 hàm này là animation nội bộ, port sau.
⇒ **Việc cần port trước**: `BuyGachaButtonGroup.Handle*GachaResult` (apply result + gọi `GachaPanel.Show`),
rồi `BuyGachaConfirmPanel.BuyFourGacha`, rồi `ShopItem.BuyProcess`.

### §74c — RVA entry gacha (đã chốt, port theo đúng thứ tự này)
| Method | RVA |
|---|---|
| `BuyGachaButtonGroup.HandleNewUnitGachaResult(BuyResponseModel)` | 0x33877A8 |
| `BuyGachaButtonGroup.HandleUnitGachaResult(BuyResponseModel, int, int)` | 0x33872B0 |
| `BuyGachaButtonGroup.HandleArtifactGachaResult(BuyResponseModel, int, int)` | 0x3387640 |
| `BuyGachaButtonGroup.HandleTreasureGachaResult(BuyResponseModel, int)` | 0x3387E2C |
| `BuyGachaButtonGroup.HandleSkinGachaResult(BuyResponseModel, int)` | 0x33881BC |
| `BuyGachaButtonGroup.OnClickBuy` / `Buy` | 0x3385DA8 / 0x3386C48 |
| `BuyGachaConfirmPanel.BuyFourGacha()` (async d__34) | 0x33930C4 |
| `ShopItem.<BuyProcess>d__91` (async, nhánh scroll) | — (MoveNext 0x3B78704 là Start) |

Cách port: `HandleNewUnitGachaResult` là entry nhỏ nhất (chỉ nhận `ret`), nó dựng
`GachaResultCollection` rồi gọi `GachaPanel.Show(...)` (17 call-site đã liệt kê ở §74b).
Thứ tự: HandleNewUnit → HandleUnit → HandleArtifact → BuyFourGacha → ShopItem.BuyProcess → animation.

## §75 — Hàng đợi "hoàn thiện toàn bộ" (đo 2026-10-21, xếp theo đòn bẩy)

Quét stub rỗng (`{ }`) trên `Assembly-CSharp` — 1.697 file còn stub, tổng 14.503/20.654 (70%).

| # | File | stub/tổng | Nhận xét / cách làm |
|---|---|---|---|
| 1 | `Awesomepiece/RestAPI.cs` | **906/1359** | **Đòn bẩy lớn nhất, cơ học**: mỗi method chỉ là `Web.Post/Get<T>(uri, json, token, false, cb)`. URI + verb + model lấy từ binary (mỗi hàm 30–60 lệnh; literal URI + `Web.Post<T>` là annotation). Port được theo lô, mỗi lô 20–40 hàm + 1 gate. Mở khoá gần như mọi panel. |
| 2 | `Scene_Game.cs` | 420/549 | vòng đời battle: init → Update → GameOver. Cần `BattleManager` trước. |
| 3 | `GameManager.cs` | 328/718 | phần lớn là handler response (`Handle*`) — làm cùng RestAPI từng cặp. |
| 4 | `GameUnit.cs` | 314/584 | unit runtime trong battle (stat/skill/kéo thả). |
| 5 | `BuffOption.cs` | 286/407 | parse `BuffOptions.xml` — thuần dữ liệu, test bằng master data. |
| 6 | `WorldPanel.cs` | 149/180 | lobby world map. |
| 7 | `WorldTrigger.cs` | 119/153 | trigger map — dữ liệu. |
| 8 | `BattleManager.cs` | 110/212 | điều phối battle. |
| 9 | `Scene_Lobby.cs` | 96/137 | còn lại là các panel reload. |
| 10 | `MainUI.cs` / `SettingsPanel` / `CardInfoPanel` | 95+90+85 | UI panel. |

### Thứ tự đề xuất (mỗi mục = 1 phiên có gate + capture)
1. **RestAPI theo lô** (ưu tiên: auth/player/deck/shop/gacha/card → mission/clan/pvp/territory).
2. **GameManager.Handle\*** tương ứng từng lô (dùng `_apply_*` đã có).
3. **BuyGachaButtonGroup.Handle\*GachaResult** + `GachaPanel` (§74c) ⇒ gacha chạy thật.
4. `BuffOption` + `WorldTrigger` (dữ liệu, không cần scene).
5. `BattleManager` → `GameUnit` → `Scene_Game` (S5 battle).
6. Panel còn lại theo bảng trên.

### Nguyên tắc khi port lô lớn
- Mỗi lô: `kdis.py <RVA>` → lấy URI + `Web.*` + model → viết callback-style (netcode law) → gate.
- Không port animation/particle cho tới khi logic chạy; chúng là stub rỗng hợp lệ.
- Đo lại % sau mỗi lô bằng đúng script regex ở đầu §75 để biết còn bao xa.

### §75b — Danh mục URI client (bền, không nằm ở /tmp)
`docs/restapi-uris.txt` = **392 literal URI** trích từ `script.json` `ScriptString` (v174.0.00), sắp xếp.
Dùng để khớp `RestAPI` stub ↔ endpoint thay vì dò từng hàm:
```
python3 - <<'PY'
import json
ss=json.load(open('il2cpp/v174.0.00/script.json'))['ScriptString']
uris=sorted({x['Value'] for x in ss if isinstance(x.get('Value'),str) and x['Value'].startswith('/') and len(x['Value'])>3})
open('docs/restapi-uris.txt','w').write('\n'.join(uris)); print(len(uris))
PY
```
Phân bố: player 39, clan 38, territory 27, colosseum 23, shop 15, auth 15, rift-weapon 14,
artifact 14, ranking 13, card 13, accessory 11, rogueLike 10, …
**Nhiều stub dùng chung 1 URI (khác model/overload)** ⇒ khớp theo *cặp* (uri, kiểu response), không chỉ uri.

### §75c — CẢNH BÁO khi sinh bảng stub↔RVA (đừng lặp lại lỗi)
Script regex ngây thơ `[\w<>\[\],\.]+\s+(\w+)\s*\(([^;{}()]*)\)\s*\{\s*\}` chỉ khớp **2/906**
stub trong `RestAPI.cs` (bắt nhầm `MoveNext`/`SetStateMachine` của struct state-machine). Nguyên nhân:
regex dừng ở `(` đầu tiên của **attribute**/generic, không bắt được khai báo thật.
Cách đúng để liệt kê stub: dùng regex đã kiểm chứng ở §75
(`(?:public|private|protected|internal)[^;{}=\n]*\([^;{}]*\)\s*\{\s*\}`) rồi tách tên bằng
`re.search(r'(\w+)\s*\(', tail)` trên phần `name(params)`, KHÔNG khớp từ đầu chuỗi.
Chưa có file `docs/restapi-stub-rvas.txt` (đã xoá bản sai) — sinh lại bằng cách trên ở lô RestAPI #1.

## §76 — Lô RestAPI #1: 380 endpoint callback (gate PASS 2026-10-21)

### Đã làm
1. `scripts/restapi/restmap.py` — sinh bảng `method → (verb, model, uri)` cho mọi
   `RestAPI.<X>d__N.MoveNext` bằng capstone + `.rela.dyn` + `ScriptString`.
   Kết quả: **453 dòng, 403 URI resolve được** → `docs/restapi-endpoints.txt`.
   *Lưu ý tên đầy đủ là `Awesomepiece.RestAPI.<X>d__N$$MoveNext`* (lọc `RestAPI.<` sẽ ra 0 dòng).
2. `scripts/restapi/gen_restapi.py` — sinh overload callback từ bảng trên, dựa vào
   **khai báo sẵn có trong port** (`public static UniTask<Resp> X(params)`) để lấy kiểu response
   và danh sách tham số; chèn trước `}` của class.
   Kết quả: **380 method** `public static void X(params, Action<Resp> onDone)` gọi
   `Web.Post/Get<Resp>(uri, [JsonUtility.ToJson(model),] accessToken, false, onDone)`.
3. `Web.Get/Post<T>` đổi constraint `where T : ResponseModel, new()` → `where T : new()`
   (6 endpoint trả `ServerListResponse` không kế thừa `ResponseModel`; `Send<T>` vẫn
   `is ResponseModel` runtime check nên `code/msg` vẫn set được khi là ResponseModel).

Gate `gate_restapi5`: **exit=0, 0 `error CS`, `Exiting batchmode successfully`**.

### Bẫy đã gặp (đừng lặp)
- Chèn code phải tính index trên **nguyên** `src` (`i1=src.rfind('}')`, `idx=src.rfind('}',0,i1)`);
  dùng `src.rstrip()` rồi cắt `src` ⇒ lệch vài ký tự, đổ vào trong method cuối → 1725 lỗi giả.
- JSON rỗng phải là chuỗi `"{}"` (không phải `{}`).
- Tham số optional (`= default`) phải bị bỏ default trong overload mới, không thì `CS1737`
  (75 lỗi) vì `onDone` nằm sau.
- `uri` có `{0}` mà method không có tham số ⇒ giữ nguyên literal, đừng `string.Format`.

### Còn lại của RestAPI (bước kế, cơ học)
- 7 endpoint không sinh được (`skip_nosig`): không có khai báo `UniTask<...>` trong port.
- **906 stub thật** của `RestAPI.cs` là body `MoveNext` của các state-machine — vô dụng với
  netcode callback. Đừng port chúng.
- **Việc đúng**: đổi 453 method `UniTask<Resp> X(params) { return default; }` thành
  `void X(params, Action<Resp> onDone)` (dùng đúng URI bảng §76) rồi sửa call-site
  `await RestAPI.X(...)` → `RestAPI.X(..., res => { ... })`. Trình tự: đổi một nhóm
  (auth/player/deck/shop) → gate → sửa call-site theo danh sách lỗi → gate.
- Đo lại: tổng method 21.034, stub rỗng 14.502 — **% không giảm** vì stub thật nằm ở body
  `MoveNext`/`return default`, không phải `{ }`. Chỉ số đúng để đo tiến độ là
  *số method còn `return default;` / body rỗng trong file logic* (RestAPI 906 state machine).

### §76b — ĐÃ CONVERT (không chỉ thêm overload)
`scripts/restapi/conv_restapi.py` đổi **tại chỗ** 380 method
`public static UniTask<Resp> X(params) { return default; }` →
`public static void X(params, Action<Resp> onDone) { Web.Post/Get<Resp>(uri, …); }`
(URI lấy từ `docs/restapi-endpoints.txt`).

Gate `gate_restapi6`: **exit=0, 0 `error CS`** ⇒ **không còn call-site nào dùng
`await RestAPI.X(...)`** (các panel gọi chúng vẫn là stub). Nghĩa là tầng API client
giờ đã chạy thật theo netcode callback, dùng được ngay cho mọi panel port sau này:
```csharp
RestAPI.BuyGacha(model, res => { if (res.isSuccess) … });
```
Port panel mới: chỉ cần gọi overload `(params, Action<Resp>)`, không phải viết `Web.*` tay nữa.

Chạy lại toàn bộ chuỗi sinh bảng khi cần (sau khi thêm/sửa gì ở RestAPI):
```
python3 scripts/restapi/restmap.py          # -> docs/restapi-endpoints.txt
python3 scripts/restapi/conv_restapi.py     # -> sửa RestAPI.cs tại chỗ
```
Lưu ý: `conv_restapi.py` chỉ khớp body đúng `return default;` **một dòng** — nếu file đã
được chỉnh tay, kiểm tra số `converted` in ra (kỳ vọng 380).

### §76c — Lobby sạch NRE sau khi đổi tầng API (capture `cap_r76f`)
Sau khi convert RestAPI, play capture lộ ra chuỗi NRE do **export drop tham chiếu serialized**;
đã sửa tận gốc từng lớp:

| Vị trí | Nguyên nhân | Sửa |
|---|---|---|
| `UnitCard.Set` | `unitSprite`/`nameText`/`levelText`/`expGauge` (fileID 0 trên prefab UnitCard) | `Awake()` tự tìm `Image` qua `GetComponentInChildren`; các chỗ dùng còn lại null-guard |
| `UnitCard.Reload` | `throw new NullReferenceException()` khi `gaugeCond == null` | guard, không throw |
| `Utility.SetActive(MonoBehaviour/Transform/CanvasGroup/...)` | `@this == null` → NRE ở **mọi** call-site | guard `if (@this == null) return;` trong **tất cả** overload (fix một chỗ, sửa cả lớp lỗi) |
| `DeckPanel`/`FirstComerSettings`/`DeckSlotToggle` | 23 NRE-pad `throw new NullReferenceException()` khi ref null | đổi thành guard `return;` (`return default;` cho hàm trả int) |

Bẫy: NRE-pad nằm trong hàm **trả về int** (`DeckPanel` sort comparer) ⇒ `return;` gây
`CS0126`; phải `return default;`. Đọc số dòng từ log rồi vá theo dòng là nhanh nhất.

Capture `cap_r76f`: **0 `error CS`, 0 `NullReferenceException`,
`[PLAYCAPTURE] play capture ok (exit 0)`** — lobby + DeckPanel.Reload chain chạy trọn,
không còn cảnh báo đỏ nào (trước đó `cap_s73b` vẫn còn 1 NRE).
Ảnh xác nhận: `/tmp/opencode/cap_r76f/shot_Scene_Lobby.png`.

## §77 — S4 gacha bắt đầu từ `ShopPanel` (2026-10-21)

### Đã port (gate `gate_s77`: exit 0, 0 error CS)
| Method | RVA | Nội dung |
|---|---|---|
| `ShopPanel.Reload()` | 0x34101B8 | tail-call `Reload(false)` |
| `ShopPanel.Reload(bool init)` | 0x340F5DC | `!readyToReload → return`; `isReloaded = true`; init → Recommend+Special+Subscribe rồi return; không thì dispatch theo `Utility.IsActive(...)` của `recommendTab(0x40) specialTab(0x58) subscribeTab(0x60) packageTab(0x48) dailyTab(0x50) moneyTab(0x78)` |
| `ShopPanel.Update()` | 0x34105F4 | tail-call `UpdateDaily()` |
| `ShopPanel.SpecialTabActive()` | 0x34105FC | ReloadUnitBundle+ReloadSpecial; `unitBundlePackages(0x1E0).All(x => !x.IsActive())` → `unitBundlePackageToggle(0xC0).SetActive(false)` + `specialTabManager(0xD0).OnClick(1)`; `!HasActiveSpecialPackage()` → `OnClick(0)`; `ReloadShopSubtabEnable("Special")` |
| `ShopPanel.PackageTabActive()` | 0x341077C | ReloadPlayer+ReloadEvent; `ReloadShopSubtabEnable("Package")`; `Utility.ScrollToIndex(packageTabsLayout(0x138).GetComponent<LayoutGroup>(), packageTabManager(0x130).index(0x20))` |

**Literal cell**: `0x69538C8 → "Special"`, `0x69817E0 → "Package"` (giải bằng `.rela.dyn` + `ScriptString`,
đúng Cell-resolver law §). Đây là mẫu để decode mọi `ReloadShopSubtabEnable(<cell>)`.

### Đã decode nhưng CHƯA port (đủ dữ kiện, port nhanh)
`UpdateDaily()` 0x34101C0 (121+ lệnh): `if (!isReloaded) return;` → so `DateTime.Now.Second` với
field `0x2F0` (private DateTime, cache giây) → nếu khác thì cập nhật `expRefreshTime(0x160)` =
`Utility.GetRemainTimeText(<shop>.nextRefreshTime_, strA, strB, true, true, true, null)` rồi
so `moneyItems(0x210).Count` với `list@+0x18` của shop data để rebuild lưới money.
Còn thiếu: tên class của static cell `0x6950B30` (→ `static_fields[]` → `+0x120` = shop response).

### Chưa decode (việc kế tiếp của file này)
`ReloadRecommendPackage` 0x3411394 · `ReloadUnitBundlePackage` 0x3413BD4 · `ReloadSpecialPackage`
0x34141DC (đã thấy: `ForEach` action + `hasBundlePackageSkins` + `IsSkinBundlePackageItemsValid` +
`RebuildSkinBundlePackageItems` + `PackageItem.InitByPrefabType` + `transform.SetSiblingIndex` → pooling item)
· `ReloadSubscribePackage` 0x3414CB4 · `ReloadPlayerPackage` 0x3415220 · `ReloadEventPackage` 0x3415AD8
· `ReloadDaily` 0x340C7C0 · `ReloadMoney` 0x3410840 · `ReloadDailyCashPackages` 0x3418744
· `ReloadPackageBadge` 0x3418114 · `ReloadShopSubtabEnable` 0x3418930 · `IsSkinBundlePackageItemsValid`
0x3414418 · `RebuildSkinBundlePackageItems` 0x341452C · `GetSkinBundlePackageItemPrefabName` 0x3414A08
· `GetSkinBundlePackageItemPrefab` 0x3414A94 (trả `null` hiện tại → NRE tiềm ẩn).

### Thứ tự đúng cho gacha (đã xác nhận bằng call-site scan §74b)
`ShopPanel.Reload` → tab handlers (§77 xong khung) → `BuyGachaButtonGroup.Buy` 0x3386C48
→ `RestAPI.BuyGacha` (đã có, §76) → `Handle*GachaResult` (0x33872B0/0x3387640/0x33877A8/0x3387E2C/0x33881BC)
→ `GachaPanel.Show` 0x33AD37C → animation (`ShowResult` 0x33AE6FC, `UnFoldResult` 0x33B05F0).

### §77b — Skin bundle package items (gate `gate_s77c` PASS)
| Method | RVA | Port |
|---|---|---|
| `IsSkinBundlePackageItemsValid(List<ShopItemModel>)` | 0x3414418 | so `_skinBundlePackageItemPrefabNames.Count` với list đầu vào (khác → false), rồi so từng tên với `GetSkinBundlePackageItemPrefabName(list[i])` |
| `GetSkinBundlePackageItemPrefabName(ShopItemModel)` | 0x3414A08 | `ResourceShopItem.Get(model.itemId).GetValueText("PackageItemPrefab", "")` (cell `0x6986300` = `"PackageItemPrefab"`, `0x694FC70` = `""`) |
| `GetSkinBundlePackageItemPrefab(string)` | 0x3414A94 | `Utility.IsNullOrEmpty → null`; `SimpleAssetDB.Instance.GetPrefab(name,false)?.GetComponent<PackageItem>()` |

Field map xác nhận: `0x1F8 = _skinBundlePackageItems (List<PackageItem>)`,
`0x200 = _skinBundlePackageItemPrefabNames (List<string>)`, `0x1F0 = playerPackageItems`,
`0x130 = packageTabManager (index @0x20)`, `0x138 = packageTabsLayout (RectTransform)`,
`0x1E0 = unitBundlePackages`, `0x1E8 = specialPackages`, `0xC0 = unitBundlePackageToggle`,
`0xD0 = specialTabManager`, `0x160 = expRefreshTime (Text)`, `0x210 = moneyItems (List<ShopItem>)`.

`FindSkinBundlePackageItem(int skinId)` 0x3414928 = `_skinBundlePackageItems.Find(x => x.resSkin != null && x.resSkin.id == skinId)`.
Cách giải: lambda cached `<>c__DisplayClass149_0.<FindSkinBundlePackageItem>b__0` @ **0x341CF9C** cho thấy
`[x1,#0xE8]` = `ShopItem.resSkin (ResourceSkin*)`, null → `-1`, ngược lại đọc `[resSkin,#0x10]` = `ResourceBase<ResourceSkin>.id`.
→ **Bài học**: field 0xE8 không có trong `PackageItem` mà thuộc `ShopItem`; `ResourceSkin` không khai báo field 0x10,
nó là `id` của `ResourceBase<T>` — khi tra offset luôn đi ngược lên base class.

### §77c — `ShopPanel.OnClickProvabilityInfo` (gate `gate_s77e` PASS)
RVA 0x3418610: `Utility.LogFirebase("click_provability_info")` → `Application.OpenURL("ProvabilityInfoURL".L())`
(cell `0x6986528` = `"click_provability_info"`, `0x6986530` = `"ProvabilityInfoURL"`; phần tử thứ 2 của
`LogFirebase` là `params Parameter[]` nên truyền rỗng).

### §77d — `ShopPanel.SetCashItems` / `OnClickDailyInfo` / `ReloadDailyCashPackages` (gate `gate_s77h` PASS)

- **`SetCashItems(ShopItemModel[] items)`** 0x341848C: `moneyItems == null || Count == 0` → return;
  `items == null || items.Length < 1` → return; loop `moneyItems[i].Init(items[i])`.
  vtable `+0x178` = **`ShopItem.Init(ShopItemModel)`** — `ShopItem.Set` **không tồn tại** (CS1061 đã mắc 1 lần).
- **`OnClickDailyInfo()`** 0x3418558: `expInfoPopup` null-guard (NRE-pad → guard) → `SetActive(true)` →
  `Utility.Get<CanvasGroup>(popup)`, null-guard → `cg.alpha = 0f; cg.DOFade(1f, 0.3f)` (**thiếu `using DG.Tweening;`** = CS1061).
  Hằng duration đọc từ binary: `ldr s1, [x8, #0x90c]` với `adrp x8,#0x12E3000` → địa chỉ là **`0x12E3000+0x90C = 0x12E390C`**
  (đọc nhầm `0x12E3090` ra 0.0f) — **bẫy: luôn cộng đúng `page + imm12`, đừng gộp thành hex chẵn**.
- **`ReloadDailyCashPackages()`** 0x3418744: 4 khối `if (pkg != null) pkg.Reload();` cho
  `dailyCashPackage 0xE0` · `dailyCashPackage2 0xE8` · `dailyGoldPackage 0xF0` · `dailyHeartPackage 0xF8`
  (thứ 4 là tail-call `b`).
- **★ Bài học init-block quanh `!=`**: trước mỗi `Object.op_Inequality` có chuỗi
  `ldr x0,[x21]` → `ldr w8,[x0,#0xe0]` → `cbnz skip` → `bl 0x2b56a84`. Resolve cell (`0x694FD90`) qua
  `.rela.dyn → ScriptMetadata` = **`UnityEngine.Object_TypeInfo`** ⇒ đó là codegen `il2cpp_runtime_class_init`
  mà il2cpp sinh ra cho **extern operator** `op_Inequality` của `UnityEngine.Object`. **C# tự sinh nó — bỏ qua, không port**
  (kết quả kiểm tra không hề được dùng lại). Vòng resolve: `adrp+ldr` → cell → addend → `ScriptMetadata`.
- Add `using DG.Tweening;` vào `ShopPanel.cs`.

### §77e — `ShopPanel.ReloadPackageBadge` (gate `gate_s77i` PASS, method khó nhất cụm ShopPanel)

RVA 0x3418114 (0x378 byte). Cấu trúc thật:

```csharp
var list = GameManager.Get().currentShop.packageItems;   // 3 cbz chain -> return nếu null
bool anyHigh=false, anyLow=false;
foreach (ShopItemModel m in list) {
    var res = ResourceShopItem.Get(m.itemId);            // ResourceBase<T>.Get(int) static, cbz -> return
    int v = res.GetValueInt("ConditionValue", -1);
    if (AwesomePrefs.GetInt(string.Format("CheckPakage{0}", m.itemId), -1, true) == 1) continue;
    if (m.soldOut) continue;
    if (v > 50) anyHigh = true;
    if (v < 51) anyLow = true;                           // OR = "còn gói chưa đọc"
}
if (tabManager?.tabs == null || tabs.Length <= 3) return;
packageTabNewBadge.SetActive((anyHigh||anyLow) && Utility.IsActive(tabManager.tabs[3]));
```

**Bài học tra cứu:**
- **Decode chuỗi static**: `ldr x8,[klass,#0xb8]` = `static_fields` → `ldr x8,[x8]` = block[0] = `_singleton` →
  `[+0x120]` = `GameManager.currentShop` (offset xác nhận trong dump.cs) → `[+0x50]` = `ShopResponseModel.packageItems`
  (`List<ShopItemModel>`). Cell `ScriptMetadata` type + `static_fields` layout là 2 bước tách bạch.
- **Phân biệt codegen vs logic**: 12× `bl 0x2b56950` (init 1 lần theo cờ `ldrb/strb` @`0x6e0a000+...`) = class-init codegen →
  bỏ; `bl 0x2b56a8c` với `x0=int_TypeInfo, x1=&int` = **box** int cho `string.Format`; `mov x1,xzr` thừa sau
  `op_Inequality`/`IsActive`/`SetActive` = dead register (dump chỉ có 1-2 params) → đừng cố tìm thêm arg.
- **Array index qua bounds check**: `ldr w9,[x8,#0x18]; cmp w9,#3; b.ls -> pad` = `max_length` (array law) +
  `[x8,#0x38]` = `elements + 3*8` ⇒ **`tabManager.tabs[3]`**; pad = guard `Length <= 3 -> return`.
- **Field tìm được nhờ grep bờ**: `bool @0x22` không có trong `ResourceShopItem` → grep `; // 0x22` cả dump ⇒
  `ShopItemModel.soldOut @0x22` (cùng class có `itemId @0x10`) → element type = `ShopItemModel`.
- 4 NRE-pad (`0x34183EC/3F0/3F4/3F8`) → guard `return;`.

### §77f — `ShopPanel.ReloadSpecialPackage` + `hasBundlePackageSkins` (gate `gate_s77k` PASS)

`ReloadSpecialPackage()` 0x34141DC (không tham số):

```csharp
if (_skinBundlePackageItems == null) return;
_skinBundlePackageItems.ForEach(x => x.InitByPrefabType(-1));      // lambda b__147_0 @0x341A094
List<ShopItemModel> pkgs = hasBundlePackageSkins;                  // get_ 0x340E72C
if (!IsSkinBundlePackageItemsValid(pkgs)) RebuildSkinBundlePackageItems(pkgs);
for (int i = 0; i < _skinBundlePackageItems.Count; i++) {
    var item = _skinBundlePackageItems[i];
    Utility.SetActive(item, true);          // 0x2C84C00
    item.InitByPrefabType(i);               // 0x33D3704
    item.transform.SetSiblingIndex(i);      // 0x6284270 get_transform + 0x6295574
}
specialPackageToggle.SetActive(HasActiveSpecialPackage());          // 0xC8 + 0x340F434
// [defer] 0x34143E4..0x3414410: specialPackageArea.GetComponent<T>() rồi `ldp x2,x1,[x8,#0x178]; br x2`
```

**★ Bài học lớn (giải luôn bí ẩn "tham số thừa" của các session trước)**: tham số `x1`/`x2` đứng
trước các `bl` **static generic** là **`MethodInfo*`**, không phải tham số C#. Ví dụ
`Enumerable.Where(list, pred, methodInfo)` → x1 = delegate, x2 = MethodInfo; `Enumerable.ToList(src)`
→ x1 = MethodInfo; còn `List<T>.RemoveAll(pred)` (instance, mutate tại chỗ, trả chính list) thì
`x2 = delegate`. Vì vậy các lệnh `mov x1,xzr` trước `op_Inequality`/`IsActive`/`SetActive` (đã gặp
ở §77d/§77e) là **register chết** — đừng đi tìm overload 2 tham số nữa.

**`hasBundlePackageSkins`** 0x340E72C = LINQ trên `GameManager.Get().currentShop.eventShopItems`
(`static_fields[0]` → `+0x120` → `+0x68`):

```
Where(b__133_0 @0x3419A58)  → x => ResourceShopItem.Get(x.itemId).GetValueInt("ConditionValue",-1) > 0
ToList()
Select(b__133_1 @0x3419ADC) → ResourceShopItem.Get(item.itemId) rồi ResourceSkin.GetValue... + Utility.GetVersion
                              rồi `new ShopItemModel()` (0x2DCE020) với stp w8,w19,[+0x10] (itemId, unitId)
ToList()
RemoveAll(b__133_2 @0x3419C38) → x => x == null
```

⇒ **[defer]** `hasBundlePackageSkins` tạm trả `new List<ShopItemModel>()` (property stub cũ là
`=> null`): 3 lambda đã có RVA, chỉ còn chốt nhánh `ResourceSkin.GetValue` + `Utility.GetVersion`
trong `b__133_1`. Hệ quả: special tab không dựng skin bundle; phần còn lại của ShopPanel không đổi.

### §77g — `ShopPanel.RebuildSkinBundlePackageItems` (gate `gate_s77l` PASS)

RVA 0x341452C (0x3FC byte, 255 lệnh — hàm dài nhất còn lại của cụm skin-bundle):

```csharp
_skinBundlePackageItems.ForEach(x => { Utility.SetActive(x, false); Object.Destroy(x.gameObject); }); // b__151_0 @0x341A160
_skinBundlePackageItems.Clear();            // List.Clear inlined: _size=0, _version++, Array.Clear(_items,0,oldSize)
_skinBundlePackageItemPrefabNames.Clear();  // 0x200
if (skinBundlePackages == null) return;
foreach (ShopItemModel model in skinBundlePackages) {
    string prefabName = GetSkinBundlePackageItemPrefabName(model);   // 0x3414A08
    PackageItem prefab = GetSkinBundlePackageItemPrefab(prefabName); // 0x3414A94
    _skinBundlePackageItems.Add(Object.Instantiate(prefab, specialPackageArea));  // 0x3C393FC = Instantiate<T>(T, Transform)
    _skinBundlePackageItemPrefabNames.Add(prefabName);
}
```

**Bài học decode:**
- `List<T>.Clear()` **inline** trong codegen: `ldp w2,w9,[list,#0x18]` (size+version) → `version+1` → `stp wzr,w9`
  → `if (oldSize >= 1) Array.Clear(_items, 0, oldSize)` (`ldr x0,[list,#0x10]`, `bl 0x58B0360`). Thấy mẫu này là Clear.
- `List<T>.Add` **inline**: `version++` → nếu `_size >= _items.max_length` → `bl 0x40C9380` (AddWithResize) →
  ngược lại `_items[_size] = value; _size++`; element ghi ở `[array + 0x20 + i*8]` = array elements law.
- `Object.Instantiate` generic: `bl 0x3C393FC` với `x0=prefab, x1=parent, x2=MethodInfo` ⇒ `Instantiate<PackageItem>(prefab, specialPackageArea)`
  (parent = `specialPackageArea` @0xB0 — đúng là RectTransform).
- Lambda pool-destroy `b__151_0`: `Utility.SetActive(x,false)` rồi `Object.Destroy(x.gameObject)` (`0x62842AC` get_gameObject → tail `b 0x628C198`).

### §77h — `ShopPanel.ReloadUnitBundlePackage` (gate `gate_s77h` PASS)

RVA 0x3413BD4. `... [0x120 currentShop] +0x50 packageItems` (giống `ReloadPackageBadge`):

```csharp
List<ResourceShopItem> items = shop.packageItems
    .Select(x => ResourceShopItem.Get(x.itemId))    // b__146_0 @0x3419FB0
    .ToList()
    .FindAll(r => r.unitBundlePackage);             // b__146_1 @0x341A000 → ResourceShopItem.0x169 bool
PackageItem prefab = unitBundlePackages.Find(p => p.packageType == PackageItem.PackageType.UnitBundle);
                                                    // b__146_2 @0x341A01C → PackageItem.0x2A8 enum, UnitBundle = 9
for (int i = 0; i < items.Count; i++) {
    var pkg = (i < unitBundlePackages.Count) ? unitBundlePackages[i]
                                             : Object.Instantiate(prefab, unitBundlePackageArea);  // 0xA8
    Utility.SetActive(pkg, true);
    pkg.InitByPrefabType(items[i].GetValueInt("Index", -1));   // literal cell 0x6954100 = "Index"
    pkg.transform.SetSiblingIndex(i);
    if (i >= unitBundlePackages.Count) unitBundlePackages.Add(pkg);
}
unitBundlePackageToggle.SetActive(unitBundlePackages.Any(x => Utility.IsActive(x)));
                                                    // b__146_3 @0x341A03C, 0xC0, Enumerable.Any 0x3BBF664
```

**Bài học decode (bổ sung luật đọc codegen):**
- **Danh sách delegate cache của `<>c`** nằm ở `[<>c_TypeInfo] → +0xb8` (static_fields) `+ 0x80/0x88/0x90/0x98`
  cho `<>9__146_0..3`. Mẫu `ldr x21,[block,#0x88]; cbnz x21,ok` + khối `bl 0x2b56b98` +
  `bl 0x5563708 (Func ctor)` / `bl 0x44d9990 (Predicate ctor)` + `str x21,[block,#0x88]` = **cached delegate**.
- `Enumerable.Select` 0x3BD3C68, `Enumerable.ToList` 0x3BE1A6C, `Enumerable.Any` 0x3BBF664 — đều static generic
  nên **`x2` (Select) hay `x1` (ToList/Any) = `MethodInfo*`**, không phải tham số.
- **`List<T>.FindAll(pred)` 0x40C9A88** (trả list mới) vs **`List<T>.Find(pred)` 0x40C99E0** (trả 1 phần tử):
  phân biệt bằng kiểu trả về được dùng sau đó (FindAll → `.Count`/`get_Item`; Find → truyền làm prefab cho `Instantiate`).
- `GameObject.SetActive` 0x6287480; `Component.GetComponent` 0x3B8CAC4; `Utility.IsActive` 0x2C8F0A0.
- `if (Count <= i)` (mẫu `b.le` ngay sau `cmp w8,w22`) = nhánh tái dùng pool thất bại → Instantiate; `Add`
  đặt **sau** `SetSiblingIndex`, điều kiện tương đương "vừa Instantiate" (viết lại bằng if/else vẫn đúng).
- **[defer] chung**: cả `ReloadSpecialPackage` (0xB0 `specialPackageArea`) và hàm này (0xA8
  `unitBundlePackageArea`) kết thúc bằng `GetComponent<T>()` (cell `0x69555F8`) rồi
  `ldp x2,x1,[x8,#0x178]; br x2`. Đuôi này là hiệu ứng layout sau khi dựng item (không ảnh hưởng dữ liệu);
  muốn giải cần đọc `Il2CppClass+0x178` của type trong cell 0x69555F8 (addend 0x6B6B778, KHÔNG có trong
  `ScriptMetadata`) + xác định virtual method 1 tham số.

### §77i — `ShopPanel.Awake` / `Start` (gate `gate_s77i` PASS)

`Awake()` 0x340EA24 (360 byte — **lifecycle, trước đây rỗng nên ShopPanel không có Instance/singleton**):

```csharp
if (Instance == null) Instance = this;         // static field block[0] của ShopPanel_TypeInfo (0x6976880 → +0xb8 → [0])
canvasGroup.alpha = 0f;                        // BaseLobbyPanel.canvasGroup @0x20 (CanvasGroup.set_alpha 0x6484F50)
GameManager.Get().Subscribe(GameManager.CallbackType.AddCard, OnCardDataChanged);  // 0x3149C1C, type = 4
```

`Start()` 0x340EB8C:

```csharp
for (int i = 0; i < tabManager.maxIndex; i++) {          // get_maxIndex 0x2F26D6C
    TabComponent[] tabs = tabManager.tabs;               // TabManager.tabs @0x30
    if (tabs == null || i >= tabs.Length) return;        // 0x2B56BA8 = throw IndexOutOfRange → port: return
    TabComponent t = tabs[i];
    if (t == null) return;
    if (!t.isActiveAndEnabled) continue;                 // Behaviour.get_isActiveAndEnabled 0x6283834
    tabManager.OnClick(i);                               // 0x2F26DE0
    return;
}
```

**Bài học decode:**
- `AsyncVoidMethodBuilder$$Create` (0x57C4F14) + `AsyncVoidMethodBuilder$$Start<ShopPanel.<X>d__N>(ref)` =
  method **`async void`**; thân thật nằm ở `<X>d__N.MoveNext` (tra RVA trong dump.cs). Gặp 2 call
  CompilerServices liên tiếp + `movi v0.2d,#0` zero 0x40 byte stack = state machine local, **không phải**
  string interpolation.
- `ShopPanel.DevResetDailyShopRefreshCount` 0x3419284 → `d__171.MoveNext` 0x341D234;
  `DevSetUnitBundlePackageUntilAt` 0x34194D4 → `d__173.MoveNext` 0x341D5DC. **Chưa port** (dev-only, async).
- `OpenOfferWallButton` 0x3418870: `if (GameManager.Get() == null) return; if (Get().CheckIsInMatchmakingAndShowCenterText(-1)) return;
  if (offerWallPanel == null) return; offerWallPanel.Show();` — **chờ** `ShopPanel.offerWallPanel` getter
  (`get_offer...` 0x340DE34) đang là stub `=> null`, nên chưa port.
- **Cell method-ptr = 0**: `*cell(...)` (vd 0x6985FF8 → addend 0x6B6E798) đôi khi **bằng 0 trong file**
  (il2cpp điền lúc runtime) ⇒ không resolve được bằng ScriptMethod; phải suy từ ngữ nghĩa
  (đây là callback `CallbackType.AddCard` → `OnCardDataChanged`).
- `PreInit()` 0x340EE18 = đúng **1 lệnh `ret`** ⇒ thân rỗng là bản port đúng, không phải stub thiếu.

## §78 — Crit: damage type nào crit được (v174.0.00) — **Special KHÔNG crit** (2026-10-21)

Câu hỏi: "special damage có crit được không?" → **Không**, trừ khi unit có buff
`BuffTag.ApplyCriticalHighest (349)`.

### Chuỗi quyết định

1. `Utility.IsPhysicalDamage` @ `0x2CA4BE0` = `type < 2 || type == 5` → `{NormalPhysical, SkillPhysical, ExtraPhysical}`
2. `Utility.IsMagicDamage` @ `0x2CA4BFC` = `(type & ~1) == 2 || type == 6` → `{NormalMagic, SkillMagic, ExtraMagic}`
3. `Utility.IsSpecialDamage` @ `0x2CA4BD4` = `type == 4` (đúng 1 lệnh `cmp w0,#4; cset`)

`GameUnit.AdjustDamage` @ `0x30E08D8` (khối crit ~`0x30E15AC`, sau vòng `foreach`, **không** có nhánh
lọc type nào trước nó) gọi `GameUnit.GetCriticalInfo` @ `0x30FACC0`:

```
p  = clamp(GetCriticalProbWithBound(resSkill), 0, 100)     // slot 29 / 0x30E9010
pm = GetCriticalDamageMulWithBound(0)                     // 0x30E9094
m  = clamp(GetMCriticalProbWithBound(resSkill), 0, 100)    // 0x30E91A4
mm = GetMCriticalDamageMulWithBound(0)                    // 0x30E91F4

if (IsPhysicalDamage(type)) { prob = p;  mul = pm; }
else if (IsMagicDamage(type)) { prob = m; mul = mm; }
else                        { prob = -1.0f; mul = 0.0; }  // <-- Special(4) / NotADamage(7) / None(8)

if (buffManager.GetValueBoolOr(BuffTag.ApplyCriticalHighest /*349*/)) {
    prob = max(p, m);  mul = max(pm, mm);                 // ghi đè, KHÔNG lọc type
}
return (prob, mul)
```

Roll (tại `0x30E1618`): `if (prob/100 >= Random.value)` → `di.isCritical = true` và
`di.uniqueDamageCompoundMult *= 1 + mul/100`. Với `prob = -1` ⇒ `-0.01` luôn `< random[0,1)`
⇒ **không bao giờ crit**.

### Ngoại lệ duy nhất

`ApplyCriticalHighest` (buff, không phải stat) thay prob/mul bằng **max(p, m)** bất kể damage type
⇒ lúc đó special damage crit được, dùng crit phys/magic cao hơn của unit. Nguồn buff trong master data:
`AccessorySynergyBuffs.xml` ID `10022` (set 예리/Sharp 5 món: +20% HybridCriticalProb, +10%
HybridCriticalDamageMul, + custom buff `ApplyCriticalHighest`). Đây là hiệu ứng phụ ngoài ý đồ mô tả
("물리/주문 중 더 높은 수치" chỉ nói phys/magic), nhưng là hành vi thật của build.

### Special damage vẫn ăn multiplier riêng

`AdjustDamage` @ `0x30E18C4`: `if (IsSpecialDamage(di.type)) di.damageMult += GetSpecialDamageMul()/100`
(vtable slot 33, `0x30E92D0`; stat tương ứng là `BaseSpecialDamageMul` trên phụ kiện), rồi
`di.uniqueDamageCompoundMult *= buffManager.GetValueDouble(BuffTag 306, 1)`.
Damage type `Special` do master data chọn: `<ForceDamageType>Special</ForceDamageType>` (Skills.xml
50035, 700507) / `<UseSpecialDamage>true</UseSpecialDamage>` (9300200).

### Áp dụng: Chungah (10260) + bộ Tuyệt Mệnh (synergy 11)

- `AccessorySynergyBuffs.xml`: set 11 = `10110` (2 món, +10% `SpecialDamageMul`/lần cast, stack 5),
  `10111` (3 món: +25% special cuối; hero **Mana/Technique/Void ≤ 45** hoặc channeling thì đổi thành
  **−50% crit damage cuối + +100% special**), `10112` (5 món: −10% Atk/MAtk, khi deal `SkillMagic/
  SkillPhysical` thì thêm 1 hit `Special` 20%).
- **Set 11 KHÔNG có `ApplyCriticalHighest`** ⇒ special damage của nó không crit, `BaseMCriticalProb`
  (crit phép) chỉ áp cho type 2/3/6. Chungah `Mana=15` ≤ 45 ⇒ rơi vào nhánh 3 món −50% crit damage.
- Muốn special crit phải dùng set **2 (Sắc Bén)** 5 món (`10022`) — 5 slot nên không thể đồng thời có
  5 món cả 2 set.

### Tra RVA

`dump.cs` RVA → file offset = `RVA - 0x4000`; disasm bằng capstone trên `il2cpp/v174.0.00/libil2cpp_v17400.so`.
Caller của một method: quét `BL` (`(w>>26)==0x25`), `B`/`B.cond`/`CBZ`/`TBZ` như §56.

## §79 — Official client trên emulator: qua được NEO, chết ở core XIGNCODE (2026-10-21)

Thử dựng **client v174.0.00 stock** (giữ nguyên host official, TLS pinning, `libxigncode.so` thật,
package id, metadata) chỉ vá đúng phần NEO + inject `libil2cpp` đã giải mã - tức là bỏ mỗi cái
`System.exit` của packer:

- **Packer v174 = `libxpoulled.so`** (115,966,484 B, SONAME `libappsign4a.so`). Loader của nó
  **giống hệt v173.0/173.1**: 8 integrity site cùng offset/byte
  (`0x43914 0x4391c 0x43924 0x43954 0x43ae0 0x43b24 0x43b40 0x43b50`) và pattern
  `08008012e89700b9` hit đúng 4 chỗ (`0x12ba6c 0x12bb14 0x12bb2c 0x12bbb4`). Chỉ cần NOP 12 chỗ
  như `patch_neo_loader()` là packer thôi `System.exit(1)`.
- `il2cpp/v174.0.00/libil2cpp_v17400.so` (unpack từ chính packer đó) inject vào
  `lib/arm64-v8a/libil2cpp.so` là Unity load được; không cần swap metadata.
- **Kết quả: qua bytehook + packer, nhưng chết ~2 s sau launch trong XIGNCODE thật**:
  `SIGSEGV SEGV_ACCERR`, cùng một `fault addr 0x77f0b1bd0dda` ở cả 3 lần chạy. Địa chỉ đó nằm
  trong mapping `r--` của **`/system/lib64/libndk_translation.so`** (không phải heap của game).
  Backtrace ARM: `memset` ← core XIGNCODE (`xraphael_arm64.xem`) ← `ZCWAVE_SendCommandVa` ←
  `ZCWAVE_SendCommand` ← JNI shim `libxigncode.so`, tức là path **AppSign `SetUserInfo`**
  (`Java_..._AppSignClientSystem_ZCWAVE_1SetUserInfo`) - đúng bước xigncode lấy device info trước
  `GetCookie2`.
- Đây **không phải lỗi của packer/NEO patch**: core xigncode lấy từ `libgabriel.so` (mapping `.xem`)
  và không hề bị sửa. Client v173.1 private + đúng lib xigncode v174 đó thì core chạy (đó là cách
  §36 lấy được cookie), nhưng chính client v173.1 lại chết ở `UnityMain` null-deref ~18 s
  (ndk_translation), nên cả hai hướng đều không dùng được lâu.
- **Hệ quả:** không có patch client nào cứu được. Cookie official do chính core đang crash tính ra;
  thay/stub nó thì không còn AppSign cookie để `/auth/xcd` mint token. Muốn official + XIGNCODE thật
  thì phải chạy **ARM native** (máy thật, hoặc container/VM ARM64), không phải lớp dịch x86.
- Build recipe (không đưa vào repo vì là dead-end cho official): copy 3 split của
  `apk/xapk_stock_174`, NOP 12 NEO site trong `libxpoulled.so`, inject
  `il2cpp/v174.0.00/libil2cpp_v17400.so` (đã stub `CheckFirebase` @ file `0x3145340` và 2 overload
  `FirebaseAnalytics.LogEvent` @ `0x384EA08`/`0x384EA6C` → `ret`, vì redroid không có Play Services),
  zipalign + ký debug. APK thử nghiệm: `/tmp/opencode/kgc-official174/`.

## §80 — Vá lớp dịch ndk_translation: XIGNCODE hết SEGV_ACCERR (2026-10-21)

§79 kết luận "phải chạy ARM native" là **sai**. Cú crash 2s trong core XIGNCODE là lỗi của
**ndk_translation**, và sửa được bằng đúng **1 byte** trong `libndk_translation.so`.

**Cơ chế thật**: `fault addr 0x77f0b1bd0dda` nằm trong mapping `r--` của
`/system/lib64/libndk_translation.so`, tại **offset 0x66dda** → nằm giữa string literal
`/system/bin/arm64/app_process64` (bắt đầu `0x66dc8`), đúng **+0x12** = ngay sau
`/system/bin/arm64/`, tức `basename` của argv[0]/AT_EXECFN. Guest (core XIGNCODE, path
`ZCWAVE_SetUserInfo`) **memset basename của argv[0]** - việc hoàn toàn hợp lệ trên ARM thật - nhưng
translator đưa cho guest một con trỏ trỏ thẳng vào **.rodata của chính nó** (LOAd#1 chỉ có quyền R),
nên `memset` → `SEGV_ACCERR`. Địa chỉ giống hệt nhau qua nhiều lần chạy vì `randomize_va_space=2`
nhưng layout của lib trong process app là tất định.

**Fix**: cho LOAD#1 (segment R-only chứa .dynsym/.dynstr/.rodata) quyền **W**.

```
# file offset 0x7c = p_flags của LOAD#1 trong program header (phoff 0x40, phentsize 0x38)
# 04 00 00 00 (R) -> 06 00 00 00 (RW)
printf '\x06' | dd of=libndk_translation.so bs=1 seek=$((0x7c)) conv=notrunc
```

- md5 gốc `8e750abfb70a9fbd670301b08aa2a5f2` (2,467,648 B, BuildId `9805a5ea90f28caa52fbba663bbe87b7`),
  md5 đã vá `2a563c08057ac2b6cab5faf5bcecaea1`. `cmp -l` chỉ ra **1 byte khác**.
- Redroid 12 (`redroid/redroid:12.0.0-latest`) mount `/` bằng **overlay rw**, nên chỉ cần
  `adb shell 'cp /data/local/tmp/libndk_translation_rw.so /system/lib64/libndk_translation.so'`
  (backup gốc ở `/data/local/tmp/libndk_translation.orig.so`), rồi `adb shell stop; adb shell start`
  (zygote preload native bridge; chỉ khởi động lại app là không đủ). Mapping đầu tiên sau đó là
  `rw-p`, và **không còn** SIGSEGV.
- Không cần đổi `libnb.so` (nó là symlink → `libndk_translation.so`).

**Kết quả**: client v174 dựng theo §79 (NEO NOP + inject libil2cpp) chạy **qua** XIGNCODE, vào tới
`Scene_Login:Awake()`, hiện màn hình login + "Failed to connect to the server" (vì
`/system/etc/hosts` đang redirect domain official về 127.0.0.1). Trước đó chết ở 2s, 100% reproducible.

**Giới hạn còn lại**: client **stock nguyên bản** vẫn chết trước đó ở packer:
`bytehook init ... return: 3` → Java `System.exit(1)` (lặp vô hạn). Đây là blocker độc lập, **không**
do segment R-only (guest code page của translator cũng là `r--`, nhưng bytehook fail ngay ở init).
Muốn chạy stock không sửa gì thì phải làm bytehook init thành công dưới ndk_translation - chưa tìm ra;
còn không thì vẫn phải dùng build NEO-NOP.

**Bài học**: `SEGV_ACCERR` với fault addr nằm trong mapping của chính translator ⇒ **guest đang ghi
vào dữ liệu host mà translator đưa cho nó** (string literal, argv/auxv, bảng hằng). Đừng kết luận
"phải chạy ARM native" trước khi map fault addr về string/section: đọc `readelf -l/-S`, tính
`offset = fault - mapping_start`, rồi `data.rfind(b'\0',0,o)` để lấy nguyên string.

**Sau khi vá translator (2026-10-21, cùng ngày)**: build `kgc-official174` (hosts official, TLS pinning
thật, xigncode thật) boot **qua** XIGNCODE → màn hình login → `Scene_Login:Awake()` → "Loading
resources…" → tải patch CDN **31/31** → **"Ready to go! Starting the game now!"**. Tức là blocker
§79 đã hết; những gì còn lại là lỗi khác:

- **Crash `UnityMain` null-deref** (Crashlytics): `x0=0`, `ldr x8,[x0]` tại libunity **vaddr
  0x584164** (file `0x580164`; mapping in-APK entry `0xfe8000` → nhớ trừ entry offset khi symbolize).
  Ngay trước là `bl #0xba4d80` trả `x0 = NULL`, rồi `ldr x8,[x0]; ldr x8,[x8,#0xa28]; blr x8`
  (virtual call trên con trỏ null). Cùng chữ ký với crash ~18-21 s của build private v173.1
  (`com.nowl.castle`, cũng `x0=0`, `lr==pc`) ⇒ **không phải** Play Services, mà là một subsystem
  của Unity trả null (nghi timing/timeout vì máy chạy qua translate).
- **Thoát sạch `exit(0)` ~50 s sau `Scene_Login:Awake`** ở các lần chạy sau (asset đã cache):
  log `FORTIFY: pthread_mutex_lock called on a destroyed mutex` chỉ là **hệ quả lúc teardown**
  (mutex thuộc `.bss` của libunity, có lần thuộc `.bss` của chính libndk_translation) rồi
  `Zygote: Process … exited cleanly (0)`. Nghi XIGNCODE tự `exit(0)` khi không lấy được cookie
  hoặc client tự quit sau timeout - chưa xác định.
- **Chưa có request `/auth` nào** tới `castle-infra-server-*.run.app`; các kết nối TLS thấy được là
  `kgc-k8s-1.awesomepiece.com` (API), `kgc-cdn-1` (CDN) và SDK ads/attribution.
- Redroid **không có Google Play Services** (`GooglePlayServicesUtil: … missing`), nên kể cả khi
  hết crash thì login Google chính thức vẫn không chạy được.

Cách lấy địa chỉ mutex → lib: `adb shell cat /proc/<pid>/maps` (chụp **trong lúc app còn sống**, ASLR
đổi mỗi lần), rồi tìm mapping chứa địa chỉ; entry trong APK (lib load thẳng từ `split_config_*.apk`)
suy ra lib bằng `data_offset` của zip entry (`lib/arm64-v8a/libunity.so` = `0xfe8000`).

**Nguyên nhân "game tự văng" (2026-10-21)**: `dumpsys activity exit-info com.awesomepiece.castle` →
`reason=1 (EXIT_SELF) status=0` ⇒ app **tự gọi exit(0)**; dòng `FORTIFY: pthread_mutex_lock called on
a destroyed mutex` chỉ là nhiễu lúc teardown (mutex nằm trong `.bss` của libunity / của
libndk_translation), không phải nguyên nhân. Thủ phạm là **`libxigncode.so` thật**: thay nó bằng stub
(`server/xigncode_stub/arm64/libxigncode.so`, build `/tmp/opencode/build_noxign174.py`) thì process
sống >10 phút, lên đủ màn hình login (nút "Sign in with Google Play" + "Guest Login"), hook theo tên
vẫn khớp v174 (`Hooked BattleManager.Update`, `Scene_Login.AutoRegisterImpl`, ...).

**Nhưng login official bị chặn bởi integrity check**: bấm "Guest Login" → `Authenticating…` →
dialog *"File integrity check failed. The account could not be logged in. - Game wasn't installed
normally from Google Play - Temporary error"*. Đây chính là XIGNCODE AppSign (server/client so chữ ký
APK với bản Play). ⇒ **không thể login official bằng APK đã sửa/ký lại**, dù có stub hay không.

⇒ Con đường duy nhất còn lại để login official trên emulator: APK **nguyên bản** + XIGNCODE thật,
tức phải vượt `bytehook init … return: 3` của packer dưới ndk_translation (blocker duy nhất còn lại
của stock).

## §81 — ĐÃ login official bằng client stock (APK nguyên bản): 4 miếng vá ngoài APK (2026-10-21)

Kết quả: client **Play-signed nguyên bản** chạy trên redroid, **tự login guest lên server chính thức**
(`Guest_4M8QR22RTR`, tên server cấp `D3747448`), vào lobby thật (38 mail, event "ISEKAI GATE",
Alliance lv13), chơi được tutorial battle. Không sửa 1 byte nào trong APK — mọi thứ nằm ở system /
mount-ns / RAM. Bộ script: `scripts/stock-redroid/` (`up.sh`, `kgcdev.c`, `hosts-adblock`).

### (1) `bytehook init … return: 3` = bhook đọc sai linker, không phải "translator không hỗ trợ"

XIGNCODE NEO packer gọi `bytehook_init`; bhook `dlopen` **đúng path hard-code `/system/bin/linker64`**
để lấy `.symtab` của linker guest, trong khi linker thật của guest nằm ở `/system/bin/arm64/linker64`
(`AT_BASE`). Trên redroid, `/system/bin/linker64` là **symlink → linker x86_64 của host**, nên bhook
parse ELF x86_64 như ELF arm64 → `e_shstrndx` ngoài range → `INITERR_SYM` (3) → packer `System.exit(1)`.
Không liên quan gì tới việc "translator không chạy được bytehook".

Vá: bind-mount linker arm64 đè lên path đó **trong mount namespace của riêng zygote64** (không đụng
namespace của init/adbd, nên `adb shell` vẫn chạy binary x86_64 bình thường):

```
nsenter -t $(pidof zygote64) -m -- mount --make-rprivate /
nsenter -t $(pidof zygote64) -m -- mount --bind /system/bin/arm64/linker64 /system/bin/linker64
```

Sau đó `bytehook init(mode: AUTOMATIC, debuggable: false), return: 0, real-init: yes`.

**Cái bẫy**: trong namespace đó **không exec được binary x86_64 nào nữa** (`PT_INTERP` của chúng cũng
là `/system/bin/linker64`, giờ là linker arm64) ⇒ `crash_dump`/`debuggerd` chết với
*"Accessing a corrupted shared library"* ⇒ **không có tombstone**, và chính `nsenter … mount` cũng
chết sau lần bind đầu tiên. Vì vậy helper `kgcdev` (static x86_64, không `PT_INTERP`) tự làm
`setns()` + `mount(2)`: `kgcdev nsbind <zygote_pid>`. Mount này **mất mỗi lần zygote/container
restart** → chạy lại `up.sh`.

### (2) `Firebase modules failed to initialize: messaging` giết luôn chuỗi login

Máy ảo không có GMS ⇒ `FirebaseApp` init ném `InitializationException` **từ trong `GameManager.Init()`**
(qua `GameManager.CheckFirebase`), exception thoát ra khỏi `Scene_Login.<LoadAfterAssetBundleImpl>d__84.MoveNext`
⇒ không tải patch CDN ⇒ `Scene_Login.OnResourceLoadCompleted()` NRE ⇒ ~30-70 s sau crash native
(`libunity` vaddr `0x584164`, PhysX `TaskManager` `pthread_getspecific` trả NULL). Đây là *hệ quả*,
không phải bug TLS của translator.

Vá (RAM-only, APK vẫn nguyên): đổi instruction đầu của `GameManager.CheckFirebase` thành `ret` **trong
image `memfd:libil2cpp.so` mà packer vừa giải mã**:

| | v174.0.00 |
|---|---|
| `dump.cs` Offset | `0x3145340` |
| RVA (`Offset + 0x4000`) | `0x3149340` |
| prologue gốc | `fe0f1bf8fa6701a9f85f02a9f65703a9` |
| patch | `c0035fd6` (`ret`) |

`kgcdev patch <pkg> <rva> <expect_hex>` poll `/proc` 20 ms/lần, dò mapping `libil2cpp.so` có
`offset 0` (= vaddr 0) ⇒ `addr = base + RVA`, đọc qua `/proc/pid/mem`. **Packer ftruncate memfd rồi
giải mã dần**, nên lần đọc đầu có thể ra 0 hoặc ra rác: chỉ coi là xong khi prologue khớp (hoặc khi
đọc ra đúng `ret` = đã bị process khác vá rồi — đừng "kẹt" ở trạng thái mismatch, đó là bug thật đã
gặp: 2 daemon cùng chạy thì cái sau thấy prologue đã đổi và poll mãi).

### (3) Crash 50-90 s — hai kiểu, và **cả hai không do miếng vá của mình**

Đo bằng cách relaunch nhiều lần (mỗi lần 120-150 s, đếm số lần còn sống):

| cấu hình | kết quả | thời điểm chết |
|---|---|---|
| patch `CheckFirebase` (giữ nguyên) | 2/4 sống | 57-75 s |
| patch + **hoàn nguyên** prologue sau 25 s | 0/4 sống | process chính `exited cleanly (0)` ở ~118 s |
| **không patch gì** (đối chứng) | 0/2 sống | SIGSEGV ~70-80 s |

⇒ Đối chứng quan trọng nhất: **không patch gì cũng chết cùng kiểu, cùng khoảng thời gian**. Vậy
instability là của *stack* (redroid + ndk_translation + Unity 2022 + XIGNCODE + ads), không phải do
byte `ret` trong `CheckFirebase`. Đừng đi tìm "XIGNCODE phát hiện patch" nữa.

Ba kiểu chết đã thấy:

| kiểu | log | luồng |
|---|---|---|
| SIGABRT | `FORTIFY: pthread_mutex_lock called on a destroyed mutex (0x…)` | `UnityChoreograp` |
| SIGSEGV có backtrace | `Cause: null pointer dereference`, `pc == lr`, `x0 = 0`, ngay trước đó Unity log `Graphics device is null.` | `UnityMain` |
| SIGSEGV **không** backtrace | chỉ `Zygote: Process <pid> exited due to signal 11`; **không** có `F libc: Fatal signal`, **không** tombstone | ? |

Chi tiết đáng nhớ:

- Crash hay xảy ra **ngay sau khi tải xong asset** (`31/31`, "Ready to go! Starting the game now!")
  khoảng 10-30 s. Trong lần crash có ghi được log: 13 s trước đó app `dlopen(libGLESv2_angle.so)` và
  dựng WebView (`cr_*`) — SDK consent/ads. Đây mới là **nghi phạm**, chưa có bằng chứng.

- SIGSEGV có backtrace nằm ở `libunity` vaddr **`0x584164`** = `bl 0xba4d80 (GetGfxDevice)` rồi
  `ldr x8,[x0]`. Getter `0xba4d80` khi TLS rỗng thì log `"Graphics device is null."` rồi **vẫn trả
  NULL**, caller không kiểm tra ⇒ deref null. (Đây đúng là crash từng bị coi là "hệ quả của chuỗi
  init hỏng" ở §80 — sai: nó xảy ra cả trên client đã login sạch.)
- **Bẫy khi vá chỗ này**: thay `ldr x8,[x0]` bằng `cbz x0,+0x14` là **hỏng** — chính instruction đó
  là chỗ nạp `x8`, nên khi `x0 != NULL` thì fallthrough với `x8` rác và chết ở
  `ldr x8,[x8,#0xa28]` (quan sát được: `pc 0x584170`, `x8 = 0xab34242b4b8633d5`). Guard đúng phải là
  trampoline: `cbz x0,skip; ldr x8,[x0]; b 0x584168; skip: b 0x584178`. Nhưng segment RX của
  `libunity` **không có run zero/nop nào ≥16 B** → phải tìm cave ở lib khác trong ±128 MB hoặc ở
  vùng RW (translator đọc code từ trang `r--p`/`rw-p` nên chỗ đặt không cần quyền X).
- SIGABRT: `pthread_mutex_destroy` set `__kind = 0xffff` (disasm libc `0xa3088`), lần `lock` sau đó
  gặp sentinel ⇒ FORTIFY abort. Vá được ở tầng hệ thống (xem (3b)).
- Đường **thoát êm**: `Web.HandleErrorCode` gọi `Web.HandleUpdateAlert` khi `errorCode`/HTTP **403**
  (`0x193`), mà `HandleUpdateAlertImpl` là coroutine có `deadline` rồi gọi `Application.Quit()`.
  Toàn bộ client chỉ có 2 chỗ gọi `Application.Quit()`: coroutine này và `SimpleCameraController.Update`
  (script mẫu của Unity). Nên "app tự thoát, exit code 0" thường là do server trả 403 (update alert).

### (3b) Vá `pthread_mutex_destroy` trong guest libc (đã áp dụng)

`/system/lib64/arm64/libc.so` (arm64 guest, **không** phải libc của host x86_64), file offset
`0xa3088` (`pthread_mutex_destroy`): `fd7bbfa9fd030091` → `00008052c0035fd6` (`mov w0,#0; ret`).
Backup: `/data/local/tmp/libc.so.orig`. Sau khi vá phải **restart framework** (`adb shell stop;
adb shell start`) để không process nào còn map trang cũ từ page cache — và nhớ chạy lại `up.sh` vì
mount-ns của zygote mất. **`adb reboot` KHÔNG reboot container redroid** (uptime không đổi) — đừng
dựa vào nó.

### (4) Không có GMS ⇒ chỉ login guest, và chỉ với APK Play-signed

`/auth/login` id-less bị server từ chối (xem `docs/multi-account-login.md`), nhưng client stock tự
chạy **guest auto-register**: PlayerPrefs `Guest_<id>`, lobby hiện tên do server cấp. Đây là tài khoản
**rác** — dùng để nghiên cứu/capture, đừng trỏ vào tài khoản thật: miếng vá (2) nằm trong RAM, về lý
thuyết XIGNCODE có memory check.

### (5) `kgcdev patchlib` — vá một lib nằm trong split APK

Guest linker map thẳng file APK (lib ở dạng STORED, không giải nén), nên `/proc/<pid>/maps` hiện
**tên APK** và cột offset = **vị trí trong file APK**, không phải offset của lib. Ví dụ v174.0.00
`lib/arm64-v8a/libunity.so` có data offset `0xfe8000` trong `config.arm64_v8a.apk`.

```
pos  = zip_data_offset + elf_file_offset(vaddr)      # elf_file_offset lấy từ program headers
addr = mapping.start + (pos - mapping.off)           # mapping chứa pos
kgcdev patchlib <pkg> split_config.arm64_v8a.apk <pos_hex> <expect_hex> [repl_hex] [revert_s]
```

Ba cái bẫy: (a) phải lọc theo **tên APK**, không lọc theo tên lib (maps không nhắc tên lib);
(b) cùng một offset có thể có **hai** mapping (map cả file + map từng segment) — chọn cái chứa `pos`;
(c) đừng quên `repl` (mặc định là `ret`) — xem bẫy `cbz` ở (3).

### (6) Watchdog — vì instability là của môi trường, không phải của patch

`scripts/stock-redroid/watchdog.sh` (chạy `setsid`, sống ngoài adb): 5 s/lần kiểm tra `pidof`, thấy
chết thì `am start` lại; daemon `kgcdev` tự vá process mới. Tài khoản là guest trên server thật nên
lần launch sau vẫn vào đúng nhân vật. Dừng: `pkill -f watchdog.sh`.

Thử thêm (kết quả: **không cải thiện**): stub `AdManager.Init` (RVA `0x2C4B660`) và
`AdmobManager.Init` (RVA `0x2C4B9E8`) bằng `ret` — vẫn chết y nguyên, và WebView Chromium **vẫn** được
tạo (từ SDK consent/UMP + Airbridge chứ không chỉ AdMob). Nên đừng đi đường "tắt ads để hết crash".

### (7) Kẹt "Loading resources…" = `UnityCache` hỏng (do chính `am force-stop`)

Triệu chứng: vào scene login, `Utility::LoadResource() Failed to load Datas/Strings/…`, màn hình
"Loading resources…" đứng im, không có kết nối TCP nào tới CDN (kiểm tra bằng cách đối chiếu inode
socket trong `/proc/<pid>/fd` với `/proc/net/tcp{,6}`), rồi ~60 s sau SIGSEGV.

Nguyên nhân: cache Addressables (`/sdcard/Android/data/<pkg>/files/UnityCache`) bị **force-stop giữa
lúc đang tải** ⇒ catalog còn, bundle thiếu/hỏng ⇒ client không tải lại, cũng không bỏ qua.

Fix (đã kiểm chứng): `rm -rf /sdcard/Android/data/com.awesomepiece.castle/files/UnityCache` rồi
relaunch ⇒ log ra `Ready to go! Starting the game now!` + progress **31/31** rồi mới vào game. Đừng
`pm clear` (mất `Guest_…` trong playerprefs = mất luôn tài khoản guest).
`up.sh` có `KGC_CLEAR_CACHE=1` cho việc này.

Ghi chú: server/CDN thật vẫn sống — `https://kgc-k8s-1.awesomepiece.com/auth/xcdSeed?version=174.0.00`
trả **200** (danh sách domain ở `docs`/patch_hosts), còn listing bucket CDN đã bị khoá
(`AccessDenied`) nên đừng dùng listing để kiểm tra version còn được phục vụ hay không.

### Bài học chung

- XIGNCODE NEO trên emulator **không** phải bất khả thi: chỉ cần đúng *một* path (`/system/bin/linker64`)
  đúng nội dung trong đúng namespace. Đừng patch cả `/system/bin` (sẽ giết mọi binary x86_64).
- Mọi thứ "app tự văng" trước đây có **hai** nguyên nhân khác nhau: packer `exit(1)` (bytehook) và
  crash ad-SDK; đừng gộp.
- Địa chỉ mutex trong log chỉ dùng được nếu đã chụp `/proc/<pid>/maps` **trong lúc process còn sống**
  (ASLR đổi mỗi lần chạy).
- Trước khi quy tội cho miếng vá của mình: **chạy đối chứng không vá**. Cả một buổi đi tìm
  "XIGNCODE phát hiện byte trong RAM" chỉ vì thiếu lần đo đó.
