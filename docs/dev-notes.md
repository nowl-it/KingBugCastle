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
