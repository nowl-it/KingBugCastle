from capstone import *
with open("il2cpp/v171.1.00/libil2cpp_v17110_ssl.so", "rb") as f:
    data = f.read()
# GachaResult.get_type_() RVA 0x2CC28E8, offset = 0x2CBE8E8
offset = 0x2CBE8E8
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
count = 0
for i in md.disasm(data[offset:offset+0x100], 0x2CC28E8):
    print("0x%x:\t%s\t%s" %(i.address, i.mnemonic, i.op_str))
    count += 1
    if i.mnemonic == 'ret' or count > 50:
        break
