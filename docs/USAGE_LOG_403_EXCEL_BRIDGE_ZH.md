# TestData 使用日志上传 HTTP 403 —— 根因分析与已验证修复方案（Excel 桥）

> 提交给：Test-Data-Consolidation-Tool 维护者
> 日期：2026-09-17
> 结论先行：**403 的根因已实验定位，修复方案已在本机实测跑通（4 条积压日志全部成功上传 ToolUseLogs），建议植入主程序。** 参考实现代码见文末，可直接改编。

---

## 1. 问题现象

- 工具的使用记录上传持续失败，队列（`%LOCALAPPDATA%\FORVIA\TestDataConsolidation\usage\queue.sqlite3`）中错误均为：
  ```
  AI Portal：读取列表元数据返回 HTTP 403
  ```
- 积压 4 条（2026-09-10 ~ 09-15，SUCCESS 事件），设计上不丢（SQLite 持久队列），但一直发不出去。
- 直接用 PowerShell 手工发同样的请求同样 403，说明**不是偶发网络问题，是通道本身的问题**。

## 2. 根因（已实验实锤）

当前上传通道 `powershell_request()`（`src/testdata_tool/usage_logging.py` + `sharepoint_request.ps1`）：

- 每次请求 spawn 一个 PowerShell 子进程，用 `MSXML2.XMLHTTP.6.0` 发 REST；
- `MSXML2.XMLHTTP` 走 **WinINET** 登录上下文；
- **Win11 的 Edge/Chromium 登录 Cookie 不进 WinINET 库**，所以 WinINET 会话里没有 SharePoint Online 的 FedAuth Cookie；
- 请求确实到达了 SPO（返回体是 `System.UnauthorizedAccessException`），**是认证问题，不是代理拦截**。

### 2.1 关键机制（2026-09-11 五点探针实验确认）

**同一个 Excel 进程内，先 `Workbooks.Open(SP 工作簿, 只读)` → 等几秒 → `Close`，之后该进程的 WinINET 会话就持有 FedAuth，同进程内用 `MSXML2.XMLHTTP.6.0` 发 REST 返回 200。**

要点（全部实测验证过）：

| 现象 | 结论 |
|---|---|
| 工作簿开着的时候 probe 是 403，Close 之后才是 200 | Cookie 在关闭时落地（会话级） |
| open → 立即 close → probe 可能仍 403；open → 间隔数秒 → close → probe 稳定 200 | 有时序竞态，需要等待（我用 7s，实测充足） |
| 跨进程（PowerShell / 另一个 Excel）probe 始终 403 | **纯进程内会话 Cookie，不落盘**（磁盘 INetCookies 始终为空） |
| 种子文件在 ES-Asia_RandD2 站点，日志列表在 AIPortal 站点，仍然 200 | Cookie 按 host（faurecia.sharepoint.com）作用域，**跨站点生效** |

前提：该 Excel 进程的 Office 已登录公司账号（SSO）。用 `DispatchEx` 从 Python 拉起的自动化隐藏 Excel 同样有效（已实测）。

### 2.2 为什么安全软件不挡这条路

本机公司安全软件对"自动化方式拉起的 Office"有限制（实测：所有工作簿 ReadOnly=True、Save/SaveAs 静默丢弃）。**本方案只需要 Open（只读）+ Close + MSXML，不保存任何工作簿**，2026-09-17 实测完全不受影响。

## 3. 2026-09-17 实测验证结果

用「隐藏 Excel 进程内播种 + 进程内 MSXML 直发」的桥方案补传积压，**一次通过**：

```
START   excel=16.0
SEED    ok
PROBE   1   200          ← 播种后第一次探针就 200
ENTITY  SP.Data.ToolUseLogsListItem
DIGEST  200
EVENT   0e3fde70-…   OK   ← 2026-09-10 T13 SUCCESS
EVENT   bf55ad84-…   OK   ← 2026-09-10 T13 SUCCESS
EVENT   bb08c9d4-…   OK   ← 2026-09-11 T13 SUCCESS
EVENT   7e32efb6-…   OK   ← 2026-09-15 FAKT LTI-498254-E0V-003 SUCCESS
DONE
```

- 4/4 上传成功，队列标记 sent，剩余待发 0；
- REST 调用序列与主程序 `SharePointClient.send()` 完全一致（GET 实体类型 → contextinfo → POST items），只是换了传输通道；
- 播种 + 探针 + digest + 4 条上传全程 **16 秒**（含 9 秒等待）。

## 4. 建议植入主程序的方案

### 4.1 架构：Excel 桥作为 403 回退通道

`powershell_request` 保持现状作为主通道（零新依赖）；**在 sync 收到 403 类错误时，启动 Excel 桥重发**，桥在进程内常驻直到空闲超时。这样：

- 无 SPO 认证问题的环境行为完全不变；
- 有问题的环境自动切换，无需用户干预；
- 桥启动一次（~10s），之后每次 REST 调用比 spawn PowerShell 更快（进程内 ~0.3–1s vs 每次 ~1–2s）。

```
UsageService.sync_once
   └─ SharePointClient.send(event) ──403──▶ 启动 ExcelBridge（懒加载，一次）
              │                                   │
           200/201 成功                    桥内重发同一 event
                                                     │
                                        隐藏 Excel [种子已播种]
                                          └─ VBA DoRequest ←→ request/response 文件
```

### 4.2 发布物：预构建的桥工作簿（重要）

不要在运行时往空工作簿里注入 VBA——那需要终端用户开启"信任对 VBA 工程对象模型的访问"（默认关闭）。**随 exe 打包一个预构建的 `excel_bridge.xlsm`**（只有一个标准模块，代码见 §5.2），打开顺序：

1. `DispatchEx` 拉起隐藏 Excel；
2. `AutomationSecurity = 1`（msoAutomationSecurityLow）→ `Workbooks.Open(本地 excel_bridge.xlsm)`，宏可用；
3. `AutomationSecurity = 3`（ForceDisable）→ 之后再开种子工作簿，防止其 `Workbook_Open` 执行；
4. 种子 Open（只读）→ 等 7s → Close → 等 2s；
5. 之后每次请求：写请求文件 → `Application.Run("…!DoRequest")` → 读响应文件。

（我 9-17 的原型用的是运行时注入 + 本机恰好开着 VBE 信任，产品化请用预构建 xlsm 的路线，对终端用户零配置要求。）

### 4.3 集成点（现有代码几乎不用改）

`SharePointClient` 的传输已经是可注入的（`request=powershell_request`），桥只要实现同签名：

```python
# usage_logging.py 内的示意补丁
class UsageService:
    def __init__(self, path, settings, client_factory=SharePointClient,
                 bridge_factory=None):          # ← 新增，默认 None 保持旧行为
        ...
        self._bridge = None
        self._bridge_factory = bridge_factory

    def sync_once(self):
        ...
        try:
            self.client_factory(settings).send(event)
        except UploadError as exc:
            if "HTTP 403" in str(exc) and self._bridge_factory is not None:
                if self._bridge is None:
                    self._bridge = self._bridge_factory()   # 懒启动 Excel 桥
                SharePointClient(settings, request=self._bridge.request).send(event)
            else:
                raise
```

桥的 `request(method, url, headers, body)` 返回 `{"status": int, "body": str}`，与 `powershell_request` 契约一致（`SharePointClient.call` 只读这两个键 + 可选 `retry_after`）。

### 4.4 部署与工程细节

| 事项 | 建议 |
|---|---|
| **种子文件** | 不要依赖 ES-Asia_RandD2 的 1018 工具文件（跨团队依赖）。建议在 AIPortal 站点传一个专用的极小 xlsx（如 `Shared Documents/bridge-seed.xlsx`），URL 放进 `local-config.yaml` 的 `logging.seed_url`，不要硬编码 |
| **pywin32** | 新增依赖：`pip install pywin32`；spec 里 hiddenimports 加 `win32com`、`win32com.client`、`pythoncom`、`pywintypes`（EBOM 工具的 spec 有现成先例）；`excel_bridge.xlsm` 加进 `datas` |
| **线程** | 桥必须跑在现有的 usage-upload 后台线程，不要碰 UI 线程；COM 记得 `pythoncom.CoInitialize()` |
| **超时看门狗** | `Application.Run` 卡死无法中断，加一个看门狗线程（如 90s 未返回就 `xl.Quit()` 强杀） |
| **失败提示** | Office 未登录公司账号时：种子 `Workbooks.Open` 会直接失败 → 给出可理解的错误文案（"请先在 Excel 中登录公司账号"），并回退原通道/入队等下次 |
| **Excel 不存在** | `DispatchEx` 抛异常 → 按无桥处理，走旧路径 |
| **幂等** | 沿用现状：ToolUseLogs 无 EventId 列，以 `201 + 响应含 "Id":` 为成功确认，成功后才标 sent |
| **body 编码** | Python 序列化 body 用 `ensure_ascii=True`（`\uXXXX` 转义，线上传输纯 ASCII），彻底绕开 VBA/MSXML 的字符串编码问题——服务端 JSON 解析后完全等价 |
| **生命周期** | 空闲 2 分钟或进程退出时 `wb.Close(False)` + `xl.Quit()`；一定放 `finally` |

## 5. 参考实现

### 5.1 Python 侧：ExcelBridge 传输类（产品形态骨架，可直接改编）

```python
# excel_bridge.py —— 403 回退通道：隐藏 Excel 进程内播种 + MSXML 直发
import json
import os
import time
from pathlib import Path

import pythoncom
import win32com.client

_BRIDGE_DIR = Path(os.environ["LOCALAPPDATA"]) / "FORVIA" / "TestDataConsolidation" / "bridge"
REQ = _BRIDGE_DIR / "request.txt"
RES = _BRIDGE_DIR / "response.txt"
SEED_WAIT, CLOSE_WAIT = 7, 2


class ExcelBridge:
    """request() 签名与 powershell_request 兼容，可直接注入 SharePointClient。"""

    def __init__(self, bridge_xlsm, seed_url, site_url):
        self.bridge_xlsm, self.seed_url = bridge_xlsm, seed_url
        self.site_url = site_url.rstrip("/")
        self._xl = self._wb = None

    # -- 生命周期 ------------------------------------------------------------
    def start(self):
        _BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
        pythoncom.CoInitialize()
        self._xl = win32com.client.DispatchEx("Excel.Application")
        self._xl.Visible = False
        self._xl.DisplayAlerts = False
        self._xl.AutomationSecurity = 1            # 允许桥工作簿的宏
        self._wb = self._xl.Workbooks.Open(str(self.bridge_xlsm))
        self._xl.AutomationSecurity = 3            # 之后（种子）禁宏，防 Workbook_Open
        self._seed()
        resp = self.request("POST", self.site_url + "/_api/contextinfo")   # 探针
        if resp["status"] != 200:
            raise RuntimeError(f"Excel 桥播种失败: HTTP {resp['status']}")

    def _seed(self):
        swb = self._xl.Workbooks.Open(self.seed_url, ReadOnly=True)
        time.sleep(SEED_WAIT)
        swb.Close(SaveChanges=False)
        time.sleep(CLOSE_WAIT)

    def close(self):
        try:
            self._wb.Close(SaveChanges=False)
            self._xl.Quit()
        except Exception:
            pass

    # -- request 契约 ---------------------------------------------------------
    def request(self, method, url, headers=None, body=None):
        headers = headers or {}
        digest = headers.get("X-RequestDigest", "")
        payload = body if body is None else json.dumps(
            body, ensure_ascii=True, separators=(",", ":"))
        REQ.write_text(f"{method}\n{url}\n{digest or '-'}\n{payload or '-'}",
                       encoding="ascii")
        self._wb.Worksheets(1).Range("A1").Value = str(REQ)
        self._wb.Worksheets(1).Range("A2").Value = str(RES)
        RES.unlink(missing_ok=True)
        self._xl.Run("'" + self._wb.Name + "'!DoRequest")
        status, _, text = RES.read_text(encoding="utf-8-sig").partition("\n")
        return {"status": int(status), "body": text, "retry_after": ""}
```

### 5.2 VBA 侧：桥工作簿唯一模块（预构建进 excel_bridge.xlsm）

请求文件 4 行：`METHOD` / `URL` / `digest 或 -` / `body(ASCII JSON) 或 -`；
响应文件：首行 HTTP 状态码，其后为 body。

```vba
' modBridge —— excel_bridge.xlsm 的唯一标准模块
Option Explicit

Public Sub DoRequest()
    On Error GoTo Fail
    Dim reqPath As String, resPath As String
    reqPath = ThisWorkbook.Worksheets(1).Range("A1").Value
    resPath = ThisWorkbook.Worksheets(1).Range("A2").Value

    Dim f As Integer, method As String, urlv As String, dig As String, body As String
    f = FreeFile: Open reqPath For Input As #f
    Line Input #f, method
    Line Input #f, urlv
    Line Input #f, dig
    Line Input #f, body
    Close #f
    If dig = "-" Then dig = ""
    If body = "-" Then body = ""

    Dim x As Object
    Set x = CreateObject("MSXML2.XMLHTTP.6.0")
    x.Open method, urlv, False
    x.SetRequestHeader "Accept", "application/json;odata=verbose"
    x.SetRequestHeader "Content-Type", "application/json;odata=verbose"
    If Len(dig) > 0 Then x.SetRequestHeader "X-RequestDigest", dig
    If Len(body) = 0 Then x.Send Else x.Send body

    WriteUtf8 resPath, CStr(x.Status) & vbCrLf & x.ResponseText
    Exit Sub
Fail:
    WriteUtf8 resPath, "-1" & vbCrLf & "bridge_error:" & Err.Number & " " & Err.Description
End Sub

Private Sub WriteUtf8(ByVal p As String, ByVal s As String)
    Dim st As Object
    Set st = CreateObject("ADODB.Stream")
    st.Type = 2: st.Charset = "utf-8": st.Open
    st.WriteText s
    st.SaveToFile p, 2   ' adSaveCreateOverWrite
End Sub
```

（播种本身不需要 VBA——由 Python 侧 COM 直接 `Workbooks.Open`/`Close` 驱动，见 §5.1 `_seed()`。）

### 5.3 9-17 实测原型（现场验证版，含完整 VBA）

已包含在本仓库 `scripts/flush_usage_queue.py`（批处理形态：导出队列 → 隐藏 Excel 一次跑完 → 标 sent），其内嵌 VBA 与上面等价但把所有请求串在一个宏里跑。**该原型用的是运行时注入 VBA（要求 VBE 信任开启），产品化请用 §4.2 的预构建 xlsm 路线。** 需要完整文件可以再发。

## 6. 上线后验证清单

1. 正常网络 + Office 已登录：跑一次真实转换，确认 ToolUseLogs 出现新行（对照 Timestamp/ProjectName）；
2. 事先杀掉所有 Excel 进程再跑（确认桥不依赖用户已开的 Excel）；
3. 模拟 Office 未登录（或断开账号）：确认种子 Open 失败走可理解提示，事件留在队列不丢；
4. PyInstaller 打包后（桥 xlsm 已 bundle、pywin32 hiddenimports）重复 1–3；
5. 确认无 Excel 残留进程（看门狗 + finally Quit）。

## 7. 附注

- 同样的根因与修法适用于任何「PowerShell/MSXML 直连 SPO REST 403」的场景（包括 EBOM 工具若日后回到 SP List 方案），桥代码可直接复用；
- 播种等待 7s 是保守值（实测探针一次即 200），上线前可实测压到 3–5s；
- 本次补传的 4 条记录已在 ToolUseLogs 列表，Timestamp 为原始事件时间（非补传时间），无需去重处理。
