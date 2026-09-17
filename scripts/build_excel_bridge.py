"""Developer-only builder. End users load the resulting workbook without VBProject access."""
from pathlib import Path
import hashlib
import json
import zipfile

import pythoncom
import win32com.client


def main():
    root = Path(__file__).resolve().parents[1] / "src/testdata_tool/bridge"
    target = root / "excel_bridge.xlsm"
    source = root / "Bridge.bas"
    pythoncom.CoInitialize()
    xl = wb = None
    try:
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        xl.EnableEvents = False
        xl.AutomationSecurity = 3
        wb = xl.Workbooks.Add()
        wb.VBProject.VBComponents.Import(str(source))
        wb.SaveAs(str(target), FileFormat=52)
        wb.Close(False)
        wb = None
        if not target.is_file():
            raise RuntimeError("Excel did not save the bridge workbook; build blocked")
        with zipfile.ZipFile(target) as archive:
            if not archive.read("xl/vbaProject.bin"):
                raise RuntimeError("Bridge workbook has no VBA project")
        # Only this locally built, reviewed workbook is loaded with macros enabled.
        xl.AutomationSecurity = 1
        wb = xl.Workbooks.Open(str(target), UpdateLinks=0, ReadOnly=True)
        xl.AutomationSecurity = 3
        assert xl.Run(f"'{wb.Name}'!Bridge.BridgeVersion") == "1"
        manifest = {
            "version": "1",
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "workbook_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Built and reopened verified bridge: {target}")
    finally:
        if wb is not None:
            wb.Close(False)
        if xl is not None:
            xl.Quit()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
