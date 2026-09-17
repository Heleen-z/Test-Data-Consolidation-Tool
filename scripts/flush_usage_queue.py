# -*- coding: utf-8 -*-
"""TestData 使用日志补传：隐藏 Excel 进程内播种 + MSXML REST 直传 ToolUseLogs。

机制（2026-09-11 五点探针实验实锤）：
- MSXML2.XMLHTTP.6.0 走 WinINET，跨进程无 SPO FedAuth Cookie 必 403；
- 同一 Excel 进程内 Workbooks.Open(SP 工作簿, 只读) -> 等数秒 -> Close 之后，
  该进程 WinINET 会话获得 FedAuth，同进程 MSXML 返回 200；
- Cookie 按 host faurecia.sharepoint.com 作用域，ES-Asia_RandD2 的种子对 AIPortal 生效。

阶段：1) sqlite 导出待发事件为 ASCII JSON 体  2) COM 隐藏 Excel 执行 VBA
      3) 按结果文件把成功条目标 sent=1
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

BASE = Path(os.environ.get("TEMP", Path.home() / "AppData" / "Local" / "Temp")) / "tdc_flush"
DB = Path(os.environ["LOCALAPPDATA"]) / "FORVIA" / "TestDataConsolidation" / "usage" / "queue.sqlite3"
SITE = "https://faurecia.sharepoint.com/sites/AIPortal"
LIST_NAME = "ToolUseLogs"
SEED_URL = ("https://faurecia.sharepoint.com/sites/ES-Asia_RandD2/"
            "Released Documents/CHD-F-DSE-1018 BOM Conversion Tool.xlsm")
SHAREPOINT_FIELDS = (
    "Title", "InputFormat", "OutputFormat", "RowCount", "Duration", "ErrorMessage",
    "Timestamp", "UserName", "UserEmail", "ComputerName", "ProjectCode", "ProjectName",
    "Toolname",
)


def sharepoint_payload(event):
    defaults = {"ProjectCode": "", "ErrorMessage": "", "OutputFormat": "XLSX"}
    return {f: event.get(f, defaults.get(f, "")) for f in SHAREPOINT_FIELDS}


def phase1_export():
    manifest = []
    db = sqlite3.connect(DB)
    rows = db.execute("SELECT id, payload FROM events WHERE sent=0 ORDER BY rowid").fetchall()
    db.close()
    for n, (eid, payload) in enumerate(rows, 1):
        event = json.loads(payload)
        body = {"__metadata": {"type": "__ENTITY__"}, **sharepoint_payload(event)}
        fn = f"body_{n}.json"
        (BASE / fn).write_text(
            json.dumps(body, ensure_ascii=True, separators=(",", ":")), encoding="ascii")
        manifest.append(f"{eid}\t{fn}")
    (BASE / "manifest.txt").write_text("\n".join(manifest), encoding="ascii")
    print(f"[阶段1] 导出 {len(rows)} 条待发事件")
    return len(rows)


VBA = r'''
Option Explicit

Private Declare PtrSafe Sub Sleep Lib "kernel32" (ByVal ms As Long)

Private Sub AppendResult(ByVal s As String)
    Dim f As Integer: f = FreeFile
    Open "__RESULTS__" For Append As #f
    Print #f, s
    Close #f
End Sub

Private Function Sanitize(ByVal s As String) As String
    Dim i As Long, c As Long, out As String
    For i = 1 To Len(s)
        c = AscW(Mid$(s, i, 1))
        If c >= 32 And c <= 126 Then out = out & Chr$(c)
    Next i
    If Len(out) > 100 Then out = Left$(out, 100)
    Sanitize = out
End Function

Private Sub HttpGet(ByVal url As String, ByRef st As Long, ByRef resp As String)
    Dim x As Object: Set x = CreateObject("MSXML2.XMLHTTP.6.0")
    x.Open "GET", url, False
    x.SetRequestHeader "Accept", "application/json;odata=verbose"
    x.Send
    st = x.Status: resp = x.ResponseText
End Sub

Private Sub HttpPost(ByVal url As String, ByVal body As String, ByVal digest As String, _
                     ByRef st As Long, ByRef resp As String)
    Dim x As Object: Set x = CreateObject("MSXML2.XMLHTTP.6.0")
    x.Open "POST", url, False
    x.SetRequestHeader "Accept", "application/json;odata=verbose"
    x.SetRequestHeader "Content-Type", "application/json;odata=verbose"
    If Len(digest) > 0 Then x.SetRequestHeader "X-RequestDigest", digest
    If Len(body) = 0 Then x.Send Else x.Send body
    st = x.Status: resp = x.ResponseText
End Sub

Private Function ExtractJsonValue(ByVal txt As String, ByVal key As String) As String
    Dim p As Long, q As Long
    p = InStr(txt, """" & key & """:""")
    If p = 0 Then Exit Function
    p = p + Len(key) + 4
    q = InStr(p, txt, """")
    If q > p Then ExtractJsonValue = Mid$(txt, p, q - p)
End Function

Private Function ReadFileText(ByVal p As String) As String
    Dim f As Integer, n As Long
    f = FreeFile: Open p For Binary Access Read As #f
    n = LOF(f): ReadFileText = Space$(n)
    Get #f, 1, ReadFileText
    Close #f
End Function

Public Sub FlushLogs()
    On Error GoTo HardFail
    AppendResult "START" & vbTab & "excel=" & Sanitize(Application.Version)

    ' --- 1. 播种：开种子工作簿(只读) -> 等 7s -> 关 -> 等 2s ---
    Dim seedWb As Workbook
    On Error GoTo SeedFail
    Set seedWb = Workbooks.Open(Filename:="__SEED__", ReadOnly:=True)
    Sleep 7000: DoEvents
    seedWb.Close SaveChanges:=False
    Sleep 2000: DoEvents
    On Error GoTo HardFail
    AppendResult "SEED" & vbTab & "ok"
    GoTo Seeded
SeedFail:
    AppendResult "SEED" & vbTab & "open_error:" & Err.Number & " " & Sanitize(Err.Description)
    ' 打不开也继续探针一次，留下证据
Seeded:

    ' --- 2. 探针 + 实体类型：最多 5 次，间隔 3s ---
    Dim st As Long, resp As String, i As Long, entity As String
    For i = 1 To 5
        HttpGet "__LIST__" & "?$select=ListItemEntityTypeFullName", st, resp
        AppendResult "PROBE" & vbTab & i & vbTab & st
        If st = 200 Then Exit For
        Sleep 3000: DoEvents
    Next i
    If st <> 200 Then
        AppendResult "ABORT" & vbTab & "probe_failed_" & st & " " & Sanitize(resp)
        Exit Sub
    End If
    entity = ExtractJsonValue(resp, "ListItemEntityTypeFullName")
    AppendResult "ENTITY" & vbTab & Sanitize(entity)
    If Len(entity) = 0 Then AppendResult "ABORT" & vbTab & "no_entity": Exit Sub

    ' --- 3. FormDigest ---
    HttpPost "__CONTEXTINFO__", "", "", st, resp
    AppendResult "DIGEST" & vbTab & st
    If st <> 200 Then
        AppendResult "ABORT" & vbTab & "digest_failed " & Sanitize(resp)
        Exit Sub
    End If
    Dim digest As String
    digest = ExtractJsonValue(resp, "FormDigestValue")
    If Len(digest) = 0 Then AppendResult "ABORT" & vbTab & "no_digest": Exit Sub

    ' --- 4. 逐条上传 ---
    Dim f As Integer, line As String, parts() As String
    Dim body As String, ok As Boolean
    f = FreeFile: Open "__MANIFEST__" For Input As #f
    Do While Not EOF(f)
        Line Input #f, line
        If Len(line) > 0 Then
            parts = Split(line, vbTab)
            body = ReadFileText("__EVENTS_DIR__" & "\" & parts(1))
            body = Replace(body, "__ENTITY__", entity)
            HttpPost "__LIST__/items", body, digest, st, resp
            ok = (st = 201 And InStr(resp, """Id"":") > 0)
            If ok Then
                AppendResult "EVENT" & vbTab & parts(0) & vbTab & "OK"
            Else
                AppendResult "EVENT" & vbTab & parts(0) & vbTab & "FAIL_" & st & " " & Sanitize(resp)
            End If
        End If
    Loop
    Close #f
    AppendResult "DONE"
    Exit Sub
HardFail:
    AppendResult "HARDFAIL" & vbTab & Err.Number & " " & Sanitize(Err.Description)
End Sub
'''


def phase2_excel():
    results = BASE / "results.txt"
    results.unlink(missing_ok=True)
    vba = (VBA
           .replace("__RESULTS__", str(results))
           .replace("__SEED__", SEED_URL)
           .replace("__LIST__", SITE + "/_api/web/lists/getbytitle('" + LIST_NAME + "')")
           .replace("__CONTEXTINFO__", SITE + "/_api/contextinfo")
           .replace("__MANIFEST__", str(BASE / "manifest.txt"))
           .replace("__EVENTS_DIR__", str(BASE)))

    import win32com.client
    print("[阶段2] 启动隐藏 Excel（DispatchEx 独立实例）…")
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.Visible = False
    xl.DisplayAlerts = False
    try:
        xl.AutomationSecurity = 3  # msoAutomationSecurityForceDisable，防种子 Workbook_Open
    except Exception:
        pass
    try:
        wb = xl.Workbooks.Add()
        mod = wb.VBProject.VBComponents.Add(1)  # 标准模块
        mod.Name = "modFlush"
        mod.CodeModule.AddFromString(vba)
        print("[阶段2] 注入 VBA 完成，执行 FlushLogs（播种 9s + 探针 + 上传）…")
        t0 = time.time()
        xl.Run("FlushLogs")
        print(f"[阶段2] VBA 执行完毕，耗时 {time.time()-t0:.0f}s")
        try:
            wb.Close(SaveChanges=False)
        except Exception:
            pass
    finally:
        xl.Quit()
    print("---- results.txt ----")
    print(results.read_text(encoding="ascii", errors="replace"))


def phase3_apply():
    results = BASE / "results.txt"
    if not results.exists():
        print("[阶段3] 无结果文件")
        return
    ok_ids, fail = [], []
    for line in results.read_text(encoding="ascii", errors="replace").splitlines():
        parts = line.split("\t")
        if parts[0] == "EVENT" and len(parts) >= 3:
            if parts[2] == "OK":
                ok_ids.append(parts[1])
            else:
                fail.append((parts[1], parts[2]))
    if not ok_ids:
        print(f"[阶段3] 无成功条目（失败 {len(fail)} 条），队列不动")
        return
    db = sqlite3.connect(DB)
    for eid in ok_ids:
        db.execute("UPDATE events SET sent=1, error='', lease=NULL, lease_until=0, next_try=0 "
                   "WHERE id=?", (eid,))
    db.commit()
    pending = db.execute("SELECT COUNT(*) FROM events WHERE sent=0").fetchone()[0]
    db.close()
    print(f"[阶段3] 已标记 {len(ok_ids)} 条为已发送；剩余待发 {pending}")
    for eid, why in fail:
        print(f"  失败 {eid}: {why}")


if __name__ == "__main__":
    BASE.mkdir(parents=True, exist_ok=True)
    if phase1_export() == 0:
        print("队列无待发事件，无需补传。")
        sys.exit(0)
    phase2_excel()
    phase3_apply()
