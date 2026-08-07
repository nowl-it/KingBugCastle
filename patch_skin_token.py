import re

with open('server/gacha.py', 'r') as f:
    gacha_py = f.read()

gacha_py = re.sub(
    r'elif type_str in \("SkinToken",\):\s+pull_res = \{"type": "SkinToken", "unitId": 0, "count": count, "isNew": True\}',
    '''elif type_str in ("SkinToken",):
                pull_res = {"type": "Item", "unitId": 2001, "count": count, "isNew": True}''',
    gacha_py
)

gacha_py = re.sub(
    r'"replaceTo": \{\s+"type": "SkinToken",\s+"id": 0,\s+"count": 5\s+\}',
    '''"replaceTo": {
                            "type": "Item",
                            "id": 2001,
                            "count": 5
                        }''',
    gacha_py
)

with open('server/gacha.py', 'w') as f:
    f.write(gacha_py)

print("Patched SkinToken to Item 2001 successfully.")
