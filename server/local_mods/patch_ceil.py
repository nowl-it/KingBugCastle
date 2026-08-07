def _build_gacha_ceil(gacha_el, st):
    gss = st.get("gachaStacks", {})
    ceil_dict = {str(k): int(v) for k, v in gss.items() if str(k).isdigit()}
    if gacha_el is not None:
        for ce in gacha_el.findall("GachaCeil"):
            if ce.get("Key"):
                pool_id = ce.get("PoolID") or gacha_el.get("ID")
                if pool_id:
                    ceil_dict[ce.get("Key")] = gss.get(str(pool_id), 0)
    return ceil_dict
