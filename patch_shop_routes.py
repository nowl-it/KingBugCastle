import re

with open('server/shop_routes.py', 'r') as f:
    shop_routes_py = f.read()

shop_routes_py = re.sub(
    r'gacha_stack_single = \{"gachaId": gacha_id, "stack": gss\.get\(str\(gacha_id\), 0\)\} if gacha_id > 0 else None',
    '''actual_gacha_id = gacha_id
        if gacha_id == 103:
            actual_gacha_id = 7000
        gacha_stack_single = {"gachaId": actual_gacha_id, "stack": gss.get(str(actual_gacha_id), 0)} if actual_gacha_id > 0 else None''',
    shop_routes_py
)

with open('server/shop_routes.py', 'w') as f:
    f.write(shop_routes_py)

print("Patched shop_routes.py successfully.")
