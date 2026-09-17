# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules
from testdata_tool.excel_bridge import verified_workbook

verified_workbook()  # Missing, stale, or modified bridge assets block release.

streamlit_data, streamlit_bins, streamlit_hidden = collect_all("streamlit")
plotly_data, plotly_bins, plotly_hidden = collect_all("plotly")
streamlit_hidden = [
    name for name in streamlit_hidden
    if not name.startswith(("streamlit.testing", "streamlit.hello"))
]
plotly_hidden = [
    name for name in plotly_hidden if not name.startswith("plotly.matplotlylib")
]

datas = sorted(streamlit_data + plotly_data + [
    ("config", "config"),
    ("Raw data standard Title", "Raw data standard Title"),
    ("src/testdata_tool/ui.py", "testdata_tool"),
    ("src/testdata_tool/sharepoint_request.ps1", "testdata_tool"),
    ("src/testdata_tool/bridge", "testdata_tool/bridge"),
])
binaries = sorted(streamlit_bins + plotly_bins)
hiddenimports = sorted(set(streamlit_hidden + plotly_hidden + collect_submodules("testdata_tool") + [
    "pyarrow",
    "pyarrow.parquet",
    "openpyxl",
    "xlsxwriter",
    "yaml",
    "win32com.client",
    "pythoncom",
    "pywintypes",
    "win32process",
    "win32event",
    "win32api",
    "win32timezone",
]))

a = Analysis(
    ["run_tool.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "pytest", "scipy", "sklearn", "streamlit.testing"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Testing Data Consolidation Tool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
