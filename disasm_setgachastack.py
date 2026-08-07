from capstone import *
with open("il2cpp/v171.1.00/libil2cpp_v17110_ssl.so", "rb") as f:
    data = f.read()
# SetGachaStack RVA 0x304DF40, offset = 0x3049F40
offset = 0x3049F40
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
count = 0
for i in md.disasm(data[offset:offset+0x200], 0x304DF40):
    print("0x%x:\t%s\t%s" %(i.address, i.mnemonic, i.op_str))
    count += 1
    if i.mnemonic == 'ret' or count > 80:
        break
