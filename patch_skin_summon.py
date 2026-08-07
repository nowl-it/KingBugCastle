import re

with open('server/gacha.py', 'r') as f:
    gacha_py = f.read()

# Replace SkinToken and Skin_Grade handlers
gacha_py = re.sub(
    r'elif type_str in \("SkinToken",\):\s+pull_res = \{"type": "Item", "unitId": _SKIN_TOKEN_ID, "count": count, "isNew": True\}\s+elif type_str == "Skin_Grade":[\s\S]*?(?=\s+elif type_str == "MapSkin_Grade":)',
    '''elif type_str in ("SkinToken",):
                pull_res = {"type": "SkinToken", "unitId": 0, "count": count, "isNew": True}
            elif type_str == "Skin_Grade":
                grade = chosen.get("id", "0")
                import xml.etree.ElementTree as ET
                import pathlib
                cache = getattr(gacha, "_SKIN_GRADE_CACHE", None)
                if cache is None:
                    cache = {}
                    try:
                        tree = ET.parse(pathlib.Path(xml_dir) / "Skins.xml")
                        for skin in tree.findall("Skin"):
                            g = skin.findtext("Grade")
                            if g is not None:
                                cache.setdefault(g, []).append(int(skin.get("ID")))
                        gacha._SKIN_GRADE_CACHE = cache
                    except:
                        pass
                pool = cache.get(str(grade))
                if pool:
                    import random
                    sid = random.choice(pool)
                    is_new = sid not in st.get("skins", [])
                    pull_res = {"type": "Skin", "unitId": sid, "count": 1, "isNew": is_new}
                else:
                    pull_res = {"type": "SkinToken", "unitId": 0, "count": 5, "isNew": True}''',
    gacha_py
)

# Replace reward_gacha_list append logic
gacha_py = re.sub(
    r'reward_gacha_list\.append\(\{\s+"originReward": \{\s+"type": pull_res\["type"\],\s+"id": pull_res\["unitId"\],\s+"count": pull_res\.get\("count", 1\)\s+\}\s+\}\)',
    '''reward = {
                        "originReward": {
                            "type": pull_res["type"],
                            "id": pull_res["unitId"],
                            "count": pull_res.get("count", 1)
                        },
                        "replaceTo": None
                    }
                    if pull_res.get("type") == "Skin" and not pull_res.get("isNew"):
                        reward["replaceTo"] = {
                            "type": "SkinToken",
                            "id": 0,
                            "count": 5
                        }
                    reward_gacha_list.append(reward)''',
    gacha_py
)

with open('server/gacha.py', 'w') as f:
    f.write(gacha_py)

print("Patched gacha.py successfully.")
