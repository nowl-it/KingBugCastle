import sys
from capstone import *

# Load libil2cpp_v17110_ssl.so
with open("il2cpp/v171.1.00/libil2cpp_v17110_ssl.so", "rb") as f:
    data = f.read()

# RVA = 0x304E0A8
# File offset = RVA - 0x4000 = 0x304A0A8
offset = 0x304A0A8

md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
for i in md.disasm(data[offset:offset+0x100], 0x304E0A8):
    print("0x%x:\t%s\t%s" %(i.address, i.mnemonic, i.op_str))
    if i.mnemonic == 'ret':
        break
