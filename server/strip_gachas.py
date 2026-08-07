import xml.etree.ElementTree as ET

t = ET.parse("server/xml_live/Gachas.xml")
root = t.getroot()

to_remove = []
for g in root.findall("Gacha"):
    if g.get("Parent") == "102" and g.get("ID") not in ("3999", "5052"):
        to_remove.append(g)

for g in to_remove:
    root.remove(g)

t.write("server/xml_live/Gachas.xml", encoding="utf-8", xml_declaration=True)
print(f"Removed {len(to_remove)} gachas under 102")
