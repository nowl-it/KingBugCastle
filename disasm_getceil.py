import sys
from capstone import *
with open("il2cpp/v171.1.00/libil2cpp_v17110_ssl.so", "rb") as f:
    data = f.read()
# GetSelectedTreasureGachaCeilId RVA 0x3050468? No, let's grep for it
