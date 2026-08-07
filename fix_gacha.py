with open("server/gacha.py", "r") as f:
    content = f.read()

content = content.replace('"type": "InventoryItem", "unitId": 390', '"type": "SkinToken", "unitId": 390')

with open("server/gacha.py", "w") as f:
    f.write(content)
