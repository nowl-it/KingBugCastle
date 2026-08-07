import xml.etree.ElementTree as ET

def _build_gacha_ceil(st, xml_dir):
    """Build BuyResponseModel.gachaCeil dict: {ceilKey: current_stack} for ALL gachas."""
    gss = st.get("gachaStacks", {})
    ceil_dict = {str(k): int(v) for k, v in gss.items() if str(k).isdigit()}
    
    import pathlib
    tree = ET.parse(pathlib.Path(xml_dir) / "Gachas.xml")
    for g in tree.findall(".//GachaCeil"):
        key = g.get("Key")
        if key:
            pool_id = g.get("PoolID") or g.findtext("../ID") # Fallback to parent Gacha ID
            # Wait, parent Gacha is g.find("..").get("ID")
            # In ElementTree, find("..") isn't always reliable unless using specific paths, but we can do it directly.
            pass
            
    # Better to iterate over Gacha elements
    for g in tree.findall("Gacha"):
        gid = g.get("ID")
        for ce in g.findall("GachaCeil"):
            key = ce.get("Key")
            if key:
                pool_id = ce.get("PoolID") or gid
                if pool_id:
                    ceil_dict[key] = gss.get(str(pool_id), 0)
                    
    return ceil_dict

