#!/usr/bin/env python3
"""
In-place patch libil2cpp.so inside split_config.armeabi_v7a.apk.
Finds the stored (uncompressed) lib inside the ZIP and patches specific offsets.
No APK repack or resign needed - modifies the file directly.

Usage: python3 patch_apk_inplace.py <apk_path>
"""
import sys, struct, pathlib, zipfile, zlib

APK = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("split_config.armeabi_v7a.apk")

# Each patch: (offset_in_libil2cpp, old_bytes, new_bytes, description)
PATCHES = [
    # SSL certificate bypass: ValidateCertificate always returns true
    (0x017CC300,
     bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),  # original (placeholder)
     bytes([0x01, 0x00, 0xA0, 0xE3, 0x1E, 0xFF, 0x2F, 0xE1]),  # MOV R0,#1; BX LR
     "PinnedCertHandler$$ValidateCertificate"),
    (0x04C23B28,
     bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
     bytes([0x01, 0x00, 0xA0, 0xE3, 0x1E, 0xFF, 0x2F, 0xE1]),
     "UnityTlsProvider$$ValidateCertificate"),
    (0x04C0A568,
     bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
     bytes([0x01, 0x00, 0xA0, 0xE3, 0x1E, 0xFF, 0x2F, 0xE1]),
     "MobileTlsContext$$ValidateCertificate"),
    # CDN bypass patch 1 removed: UpdatePatchSetList failure flag -> let it actually try CDN
    # CDN bypass patch 2 removed: LoadAssetsAfterOk asset-not-in-remoteHashes -> let it download
    # Patch 6: BadwordFilter.CheckWord - stub out profanity check (Init NullRef: asset bundles not loaded)
    # Return false immediately = no bad word = name valid; allows OnClickRegister to proceed to server call
    (0x024E7BFC,
     bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),  # placeholder: always apply
     bytes([0x00, 0x00, 0xA0, 0xE3, 0x1E, 0xFF, 0x2F, 0xE1]),  # MOV R0,#0; BX LR (return false)
     "BadwordFilter$$CheckWord(stub,8b)"),
    # CDN bypass patch 3 removed: LoadAssets_MoveNext -> let CDN loading proceed.
    # Patch 7: Scene_Login.GetGoogleUserId - guest registration (AutoRegister) calls this
    # to get a Google Play Games user id. Instead of returning null (which triggers GPGS
    # auth dialog in AutoRegisterImpl), call GenerateRandomName and return its result as a
    # synthetic "id". AutoRegisterImpl sees a non-null, non-empty string and skips the
    # GPGS sign-in entirely, proceeding directly to RestAPI.Register(name). The server
    # accepts any id and returns a valid AuthResponse.
    (0x02265470,
     bytes([0x10, 0x40, 0x2D, 0xE9, 0x00, 0x00, 0xA0, 0xE3]),  # PUSH {r4,lr}; MOV R0,#0
     bytes([0xCA, 0x0E, 0x00, 0xEB, 0x1E, 0xFF, 0x2F, 0xE1]),  # BL GenerateRandomName(0x2268fa0); BX LR
     "Scene_Login$$GetGoogleUserId->GenerateRandomName(8b)"),
    # Patch 8: <OnClickGuestLogin>b__102_0(yes) - force AUTHENTIC random-name guest register.
    # Stock b__102_0(yes) for a fresh guest (no stored credential) branches three ways:
    #   - 0x2268ea0: tail-call AutoRegister  (GenerateRandomName -> RestAPI.Register -> Auth)
    #   - 0x2268eac: tail-call Auth(cred)    (returning user with a stored credential)
    #   - 0x2268ec4: tail-call ShowRegister  (manual name-entry panel; taken only when an
    #                ObscuredBool build flag is false AND a localized-string compare fails)
    # The authentic in-game behavior is "Guest Login -> random name account -> tutorial ->
    # main", i.e. AutoRegister. AutoRegister is clean (no Google): it generates a random
    # name, runs BadwordFilter.CheckWord (stubbed by patch 6), POSTs RestAPI.Register, then
    # on success calls Auth -> GetCookie(RestAPI.GetXigncodeSeed) -> RestAPI.Auth, all of
    # which hit the private server. To make this deterministic regardless of the build flag,
    # retarget the rare ShowRegister tail-call (0x2268ec4) to AutoRegister (0x22664ec). The
    # returning-user Auth(cred) tail-call (0x2268eac) is left untouched. Single 4-byte B.
    (0x02268EC4,
     bytes([0xFE, 0xF5, 0xFF, 0xEA]),  # B ShowRegister (0x22666c4)
     bytes([0x88, 0xF5, 0xFF, 0xEA]),  # B AutoRegister (0x22664ec)
     "Scene_Login$$GuestFresh_ShowRegister->AutoRegister(4b)"),
    # NOTE: a "patch 9a" (force b__102_0 BEQ->B at 0x2268E30 = always Auth-direct) was tried
    # 2026-06-26 and REVERTED: Auth(this, cred) with a NULL cred (FUN_024e5c58 returns null for a
    # fresh guest) faults client-side before any /auth request. Guest needs a non-null id.
    #
    # Patch 9: (REVERTED 2026-06-26) GuestLogin->TestLogin redirect broke the login dialog.
    # OnClickTestLogin preconditions fail when the test panel was never shown; Auth("")
    # is rejected client-side. The correct path is AutoRegister (via b__102_0 Yes handler)
    # with proper server responses. Keeping the entry as a comment for reference.
    #(0x02264D1C,
    # bytes([0xF0, 0x41, 0x2D, 0xE9]),  # PUSH {r4-r8,lr}  (OnClickGuestLogin prologue)
    # bytes([0x18, 0xFD, 0xFF, 0xEA]),  # B 0x2264184      (-> OnClickTestLogin(this))
    # "Scene_Login$$GuestLogin->TestLogin(4b)"),
    # Patch 10: (REVERTED 2026-06-26) GoogleInit + SocialInit stubs killed login UI.
    #(0x02263558, bytes([0x00, 0x48, 0x2D, 0xE9]), bytes([0x1E, 0xFF, 0x2F, 0xE1]), "Scene_Login$$GoogleInit(stub,4b)"),
    #(0x02263454, bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]), bytes([0x1E, 0xFF, 0x2F, 0xE1]), "Scene_Login$$SocialInit(stub,4b)"),
]

# Find lib offset within APK (ZIP)
with zipfile.ZipFile(APK, 'r') as z:
    info = z.getinfo("lib/armeabi-v7a/libil2cpp.so")
    # ZipInfo.header_offset = offset of local file header
    # Actual data offset = header_offset + 30 + len(filename) + len(extra)
    print(f"[*] ZipEntry compress_type={info.compress_type} (0=stored, 8=deflate)")
    if info.compress_type != 0:
        print("[!] lib is compressed - cannot in-place patch!")
        sys.exit(1)
    print(f"[*] ZipEntry header_offset=0x{info.header_offset:x}")
    print(f"[*] lib file_size={info.file_size} compress_size={info.compress_size}")

# Calculate exact data offset by reading local header
apk_data = bytearray(APK.read_bytes())
hdr_off = info.header_offset

# Local file header: PK\x03\x04, then at +26: fname_len(2), extra_len(2)
assert apk_data[hdr_off:hdr_off+4] == b'PK\x03\x04', "Not a ZIP local header!"
fname_len = struct.unpack_from('<H', apk_data, hdr_off + 26)[0]
extra_len = struct.unpack_from('<H', apk_data, hdr_off + 28)[0]
lib_start = hdr_off + 30 + fname_len + extra_len
print(f"[*] libil2cpp.so starts at APK offset 0x{lib_start:x}")

# Verify ELF magic
assert apk_data[lib_start:lib_start+4] == b'\x7fELF', "ELF magic mismatch!"
print("[*] ELF magic OK")

# Apply patches
for lib_offset, old_bytes, new_bytes, name in PATCHES:
    apk_offset = lib_start + lib_offset
    before = bytes(apk_data[apk_offset:apk_offset+len(new_bytes)])
    if before != old_bytes and old_bytes != bytes(len(old_bytes)):  # skip placeholder check for SSL patches
        print(f"[!] {name}: expected {old_bytes.hex()} got {before.hex()} - skipping")
        continue
    apk_data[apk_offset:apk_offset+len(new_bytes)] = new_bytes
    print(f"[+] {name}")
    print(f"    lib=0x{lib_offset:08x}  apk=0x{apk_offset:x}  {before.hex()} -> {new_bytes.hex()}")

# Recompute CRC-32 for the lib and update in local file header + central directory
lib_end = lib_start + info.file_size
lib_data = bytes(apk_data[lib_start:lib_end])
new_crc = zlib.crc32(lib_data) & 0xFFFFFFFF
struct.pack_into('<I', apk_data, hdr_off + 14, new_crc)  # local header CRC at +14
# Also update central directory (scan for this entry's cd record)
cd_sig = b'PK\x01\x02'
search_start = lib_end
cd_pos = bytes(apk_data).find(cd_sig, search_start)
while cd_pos >= 0:
    fname_len_cd = struct.unpack_from('<H', apk_data, cd_pos + 28)[0]
    fname = bytes(apk_data[cd_pos + 46: cd_pos + 46 + fname_len_cd])
    if fname == b'lib/armeabi-v7a/libil2cpp.so':
        struct.pack_into('<I', apk_data, cd_pos + 16, new_crc)
        print(f"[+] Updated CRC-32 in central directory: 0x{new_crc:08x}")
        break
    cd_pos = bytes(apk_data).find(cd_sig, cd_pos + 1)

# Write back
APK.write_bytes(apk_data)
print(f"\n[+] Patched APK written: {APK}")
