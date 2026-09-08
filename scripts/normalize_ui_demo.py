"""Add XLSX used-range metadata required by the app's read-only Excel reader."""
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET


def main():
    demo = Path(__file__).resolve().parents[1] / "outputs/ui-demo"
    for path in [*demo.joinpath("templates").glob("*.xlsx"), *demo.joinpath("input").glob("*.xlsx")]:
        with zipfile.ZipFile(path) as source:
            entries = [(item, source.read(item.filename)) for item in source.infolist()]
        repaired = path.with_suffix(".normalized.xlsx")
        with zipfile.ZipFile(repaired, "w", zipfile.ZIP_DEFLATED) as target:
            for item, data in entries:
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", item.filename):
                    sheet = ET.fromstring(data)
                    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
                    if sheet.find(ns + 'dimension') is None:
                        refs = [cell.attrib['r'] for cell in sheet.iter(ns + 'c')]
                        if refs:
                            sheet.insert(0, ET.Element(ns + 'dimension', {'ref': f'A1:{refs[-1]}'}))
                            data = ET.tostring(sheet, encoding='utf-8', xml_declaration=True)
                target.writestr(item, data)
        repaired.replace(path)
        print(path.name)


if __name__ == "__main__":
    main()
