import sys
from capstone import *
with open("il2cpp/v171.1.00/libil2cpp_v17110_ssl.so", "rb") as f:
    data = f.read()
# HandleSkinGachaResult RVA 0x32785AC, offset = 0x32745AC
offset = 0x32745AC
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
for i in md.disasm(data[offset:offset+0x100], 0x32785AC):
    print("0x%x:\t%s\t%s" %(i.address, i.mnemonic, i.op_str))
    if i.mnemonic == 'ret' or (i.mnemonic == 'b' and not i.op_str.startswith('#0x3278')):
        if i.mnemonic == 'ret': break
