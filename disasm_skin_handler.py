from capstone import *
with open("il2cpp/v171.1.00/libil2cpp_v17110_ssl.so", "rb") as f:
    data = f.read()
# HandleSkinGachaResult RVA 0x32785AC, offset = 0x32745AC
offset = 0x32745AC
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
md.detail = True
count = 0
for i in md.disasm(data[offset:offset+0x400], 0x32785AC):
    print("0x%x:\t%s\t%s" %(i.address, i.mnemonic, i.op_str))
    count += 1
    if count > 200 or i.mnemonic == 'ret':
        break
