#!/usr/bin/env python3
"""PATCH_libmain: injects dlopen("libxigncode.so") into JNI_OnLoad of an ARM64 libmain.so

Reads the original libmain.so, patches JNI_OnLoad at VA 0x4A74 to BL to a
newly appended trampoline, extends the R-X LOAD segment to cover the new
code+data, and writes the result.

Usage: python3 patch_libmain.py <input> <output>
"""

import struct
import sys


# ── instruction encodings (ARM64, little-endian) ──────────────────────

INSN = {
    # BL from JNI_OnLoad+4 (0x4A74) → trampoline (0x5A48)
    # imm26 = (0x5A48 - 0x4A74) / 4 = 0x3F5
    "bl_trampoline": 0x940003F5,

    # stp x29, x30, [sp, #-0x10]!
    "stp_x29_x30_sp_m16": 0xA9BF7BFD,

    # adrp x0, #0  (loads page of current PC)
    "adrp_x0_0": 0x90000000,

    # add x0, x0, #0xA60  (string at VA page+0xA60)
    "add_x0_x0_A60": 0x91298000,

    # bl dlopen@plt (0x4ED0) from BL at 0x5A54; imm26 = -0x2E1
    "bl_dlopen": 0x97FFFD1F,

    # ldp x29, x30, [sp], #0x10
    # bits 31-24 = 0xA8, addr=3 (post-index), imm7=2, Rt2=x30, Rn=sp, Rt=x29
    "ldp_x29_x30_sp_p16": 0xA8C17BFD,

    # ret
    "ret": 0xD65F03C0,
}


def va_to_file_off(va: int) -> int:
    """Map virtual address → file offset (R-X segment delta = 0x4000)."""
    return va - 0x4000


def patch_libmain(in_path: str, out_path: str) -> None:
    with open(in_path, "rb") as f:
        data = bytearray(f.read())

    file_size = len(data)

    # ── build trampoline payload ─────────────────────────────────────
    trampoline_code = b"".join(
        struct.pack("<I", INSN[insn]) for insn in (
            "stp_x29_x30_sp_m16",
            "adrp_x0_0",
            "add_x0_x0_A60",
            "bl_dlopen",
            "ldp_x29_x30_sp_p16",
            "ret",
        )
    )
    string_data = b"libxigncode.so\x00"
    payload = trampoline_code + string_data

    trampoline_va = file_size + 0x4000         # appended after current end
    string_va = trampoline_va + len(trampoline_code)
    new_file_size = file_size + len(payload)

    print(f"  Original file size: 0x{file_size:X} ({file_size})")
    print(f"  Trampoline at VA 0x{trampoline_va:X} (file 0x{file_size:X})")
    print(f"  String at VA 0x{string_va:X} (file 0x{file_size + len(trampoline_code):X})")
    print(f"  New file size: 0x{new_file_size:X} ({new_file_size})")

    # ── 1. patch JNI_OnLoad at VA 0x4A74 (file 0xA74) ──────────────
    patch_off = va_to_file_off(0x4A74)
    data[patch_off:patch_off + 4] = struct.pack("<I", INSN["bl_trampoline"])
    print(f"  Patched BL at file 0x{patch_off:X} (VA 0x4A74)")

    # ── 2. append trampoline + string ──────────────────────────────
    data.extend(payload)

    # ── 3. update R-X LOAD program header ──────────────────────────
    # ELF64 header: e_phoff at +0x20, e_phentsize at +0x36
    e_phoff = struct.unpack("<Q", data[0x20:0x28])[0]
    e_phentsize = struct.unpack("<H", data[0x36:0x38])[0]
    phnum = struct.unpack("<H", data[0x38:0x3A])[0]

    # Find the R-X LOAD segment (p_flags & 5 == 5, p_type == 1)
    rx_idx = None
    for i in range(phnum):
        ph_off = e_phoff + i * e_phentsize
        p_type = struct.unpack("<I", data[ph_off:ph_off + 4])[0]
        p_flags = struct.unpack("<I", data[ph_off + 4:ph_off + 8])[0]
        if p_type == 1 and (p_flags & 0x7) == 5:  # PT_LOAD, PF_R|PF_X
            rx_idx = i
            break

    if rx_idx is None:
        print("ERROR: could not find R-X LOAD segment", file=sys.stderr)
        sys.exit(1)

    ph_off = e_phoff + rx_idx * e_phentsize
    old_filesz = struct.unpack("<Q", data[ph_off + 32:ph_off + 40])[0]
    new_filesz = new_file_size - struct.unpack("<Q", data[ph_off + 8:ph_off + 16])[0]

    data[ph_off + 32:ph_off + 40] = struct.pack("<Q", new_filesz)
    data[ph_off + 40:ph_off + 48] = struct.pack("<Q", new_filesz)
    print(f"  PHDR[{rx_idx}] p_filesz: 0x{old_filesz:X} → 0x{new_filesz:X}")

    # ── write output ───────────────────────────────────────────────
    with open(out_path, "wb") as f:
        f.write(data)

    print(f"  Written: {out_path} ({new_file_size} bytes)")


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_libmain.so> <output_libmain.so>")
        sys.exit(1)

    in_path, out_path = sys.argv[1], sys.argv[2]
    print(f"Patching {in_path} → {out_path}")
    patch_libmain(in_path, out_path)
    print("Done.")


if __name__ == "__main__":
    main()
