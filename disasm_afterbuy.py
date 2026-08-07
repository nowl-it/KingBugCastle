from capstone import *
with open("il2cpp/v171.1.00/libil2cpp_v17110_ssl.so", "rb") as f:
    data = f.read()
# AfterBuy RVA 0x3277174, offset = 0x3273174
offset = 0x3273174
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
count = 0
for i in md.disasm(data[offset:offset+0x600], 0x3277174):
    print("0x%x:\t%s\t%s" %(i.address, i.mnemonic, i.op_str))
    count += 1
    if count > 300 or i.mnemonic == 'ret':
        break
