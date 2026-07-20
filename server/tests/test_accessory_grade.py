"""The accessory sub-stat tier badge only renders when the server says so.

`AccessorySubStatGrade.Set(float score)` (v171 RVA 0x3361904) starts with
`GameManager.GetKeyValueInt("AccessoryRenewal")`; anything but 1 takes the
`SetActive(false)` branch and the whole grade badge disappears. The flag arrives
in PlayerData.keyValues, i.e. the /player response.

The tier itself is `Utility.LowerBound(AccessorySubStatScoreRange, score)`, and
that range comes from AccessoryConstants.xml - so a malformed range would break
tiers just as thoroughly as a missing flag.
"""
import bisect, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import server


def main():
    st = server.load_state()
    kv = {k["key"]: k["value"] for k in server.r_player({}, st)["keyValues"]}
    assert kv.get("AccessoryRenewal") == "1", \
        f"AccessoryRenewal must be 1 or the tier badge is hidden; got {kv.get('AccessoryRenewal')!r}"

    import xml.etree.ElementTree as ET
    txt = ET.parse(server.XML_DIR / "AccessoryConstants.xml").getroot().findtext(
        "AccessorySubStatScoreRange")
    assert txt, "AccessorySubStatScoreRange missing from AccessoryConstants.xml"
    rng = [float(x) for x in txt.split(",")]
    assert rng == sorted(rng), f"score range must ascend for LowerBound: {rng}"

    # Every served accessory must land on a real tier, with scores parallel to keys.
    accs = server.get_st_accessories(st)
    assert accs, "no accessories served"
    for a in accs:
        assert len(a["subStats"]) == len(a["subStatScores"]), \
            f"acc {a['id']}: subStats/subStatScores length mismatch"
        for key, score in zip(a["subStats"], a["subStatScores"]):
            tier = bisect.bisect_left(rng, score)
            assert 0 < tier <= len(rng), f"acc {a['id']} {key}: score {score} -> tier {tier} off the scale"
    print(f"ok: AccessoryRenewal=1, range={rng}, {len(accs)} accessories all on scale")


if __name__ == "__main__":
    main()
