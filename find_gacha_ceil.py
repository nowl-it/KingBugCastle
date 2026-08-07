import sys, re
with open("il2cpp/v171.1.00/dump.cs") as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if "GetGachaStack" in line and not "public int GetGachaStack" in line and not "public void SetGachaStack" in line:
        print(f"Line {i}: {line.strip()}")
