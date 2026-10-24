#!/usr/bin/env python3
"""Phan loai stub rong trong port theo hinh dang ma may (v174).

Y tuong: stub `{ }` trong port thuong la method ma than ham that rat ngan
(getter/setter/forward/const). Script nay doc dump.cs de lay RVA + field offset,
disassemble vai lenh dau, roi xep loai:

  ret         : than rong  (void)
  get_field   : ldr w0,[x0,#off]; ret          -> return this.<field>
  set_field   : str w1/x1,[x0,#off]; ret       -> this.<field> = value
  get_static  : adrp+ldr; ret                  -> return <static field>
  const       : mov w0,#N; ret                 -> return N
  forward     : b <target>                     -> goi lai method khac (tail-call)
  other       : con lai (can doc tay)
"""
import json, re, sys, glob
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from capstone.arm64 import ARM64_OP_IMM, ARM64_OP_MEM, ARM64_OP_REG

ROOT = '/home/nowl/Code/kgc'
IL2 = ROOT + '/il2cpp/v174.0.00'
PORT = ROOT + '/unity/kgc-rebuild/ExportedProject/Assets/Scripts/Assembly-CSharp'
data = open(IL2 + '/libil2cpp_v17400.so', 'rb').read()

# --- sections cho RVA -> file offset ---
import struct
e_phoff = struct.unpack_from('<Q', data, 0x20)[0]
e_phentsize, e_phnum = struct.unpack_from('<HH', data, 0x36)
segs = []
for i in range(e_phnum):
    o = e_phoff + i * e_phentsize
    p_type = struct.unpack_from('<I', data, o)[0]
    p_offset, p_vaddr, _, p_filesz = struct.unpack_from('<QQQQ', data, o + 8)
    if p_type == 1:
        segs.append((p_vaddr, p_offset, p_filesz))


def foff(v):
    for va, off, sz in segs:
        if va <= v < va + sz:
            return off + (v - va)
    return None


# --- dump.cs: class -> {method: rva}, class -> {offset: field} ---
cls_methods, cls_fields, cur = {}, {}, None
lines = open(IL2 + '/dump.cs', errors='replace').read().split('\n')
decl = re.compile(r'^\s*(?:public|internal|private|protected)[\w\s<>,\[\]\.]*\b(class|struct|interface)\s+(\w+)')
meth = re.compile(r'^\s*(?:public|private|protected|internal|static|virtual|override|abstract|extern|\s)+[\w<>\[\],\.\?]+\s+(\w+)\s*\(')
rvare = re.compile(r'// RVA: (0x[0-9A-Fa-f]+)')
fieldre = re.compile(r'^\s*public\s+[\w<>\[\],\.\?]+\s+(\w+);\s*//\s*(0x[0-9A-Fa-f]+)')
for i, ln in enumerate(lines):
    m = decl.match(ln)
    if m:
        cur = m.group(2)
        cls_methods.setdefault(cur, {})
        cls_fields.setdefault(cur, {})
        continue
    if cur is None:
        continue
    if i and rvare.search(lines[i - 1]):
        mm = meth.search(ln)
        if mm:
            cls_methods[cur].setdefault(mm.group(1), int(rvare.search(lines[i - 1]).group(1), 16))
            continue
    fm = fieldre.match(ln)
    if fm:
        cls_fields[cur][int(fm.group(2), 16)] = fm.group(1)

md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
md.detail = True


def classify(rva, classname):
    off = foff(rva)
    if off is None:
        return 'other'
    code = data[off:off + 64]
    ins = list(md.disasm(code, rva))[:8]
    if not ins:
        return 'other'
    m0 = ins[0]
    fields = cls_fields.get(classname, {})
    if m0.mnemonic == 'ret':
        return 'ret'
    if m0.mnemonic == 'b' and len(ins) >= 1 and m0.operands and m0.operands[0].type == ARM64_OP_IMM:
        return 'forward'
    if len(ins) >= 2 and ins[-1].mnemonic == 'ret':
        first = ins[0]
        ops = first.operands
        if first.mnemonic in ('ldr', 'ldrb', 'ldrh') and len(ops) == 2 and ops[0].type == ARM64_OP_REG and ops[1].type == ARM64_OP_MEM:
            mem = ops[1]
            base_name = first.reg_name(mem.mem.base)
            if base_name in ('x0', 'x1') and mem.mem.base != 0 and mem.mem.disp in fields:
                return 'get_field'
        if first.mnemonic in ('str', 'strb', 'strh') and len(ops) == 2 and ops[0].type == ARM64_OP_REG and ops[1].type == ARM64_OP_MEM:
            mem = ops[1]
            if first.reg_name(mem.mem.base) in ('x0',) and mem.mem.disp in fields:
                return 'set_field'
        if first.mnemonic == 'mov' and ops and ops[0].type == ARM64_OP_REG and first.reg_name(ops[0].reg) in ('w0', 'x0') and len(ops) > 1 and ops[1].type == ARM64_OP_IMM:
            return 'const'
        if first.mnemonic == 'adrp':
            return 'get_static'
    return 'other'


stub_re = re.compile(r'(?:public|private|protected|internal)[^;{}=\n]*?[\w<>\[\],\.]+\s+(\w+)\s*\([^;{}]*\)\s*\{\s*\}')
results, unknown = {}, 0
for f in glob.glob(PORT + '/**/*.cs', recursive=True):
    cls = f.rsplit('/', 1)[1][:-3]
    src = open(f, errors='replace').read()
    if 'namespace' in src and cls not in cls_methods:
        for c in cls_methods:
            if c == cls:
                break
    for m in stub_re.finditer(src):
        name = m.group(1)
        rva = cls_methods.get(cls, {}).get(name)
        if rva is None:
            unknown += 1
            continue
        k = classify(rva, cls)
        results.setdefault(k, []).append(f'{cls}.{name}')

for k in sorted(results, key=lambda x: -len(results[x])):
    print(f'{k:12s} {len(results[k]):5d}')
print('total classified', sum(len(v) for v in results.values()), '| no rva', unknown)
json.dump(results, open('/tmp/opencode/autoport_classify.json', 'w'), indent=0)
