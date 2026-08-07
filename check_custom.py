import xml.etree.ElementTree as ET

tree = ET.parse('server/xml_live/Gachas.xml')
for gacha in tree.findall('Gacha'):
    if gacha.findtext('Type') == 'CustomUnitGacha':
        end_date = gacha.findtext('EndDate')
        print(f"Gacha {gacha.get('ID')}: EndDate {end_date}")
