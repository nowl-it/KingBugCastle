with open("server/shop_routes.py", "r") as f:
    content = f.read()
import re
new_code = """    gss = st.get("gachaStacks", {})
    # Sync legacy pity with Ceil pool ID for old users
    if "5052" in gss and "231052" not in gss:
        gss["231052"] = gss["5052"]
    if "3999" in gss and "131000" not in gss:
        gss["131000"] = gss["3999"]
        
    base["gachaStacks"] = [{"gachaId": int(k), "stack": v}
                           for k, v in gss.items() if str(k).isdigit()]"""
content = re.sub(r'    gss = st\.get\("gachaStacks".*?if str\(k\)\.isdigit\(\)\]', new_code, content, flags=re.DOTALL)
with open("server/shop_routes.py", "w") as f:
    f.write(content)
