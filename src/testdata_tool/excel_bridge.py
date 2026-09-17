"""Bounded, process-isolated Excel transport. All Excel COM calls share one thread."""
from __future__ import annotations

import atexit
import hashlib
import json
import multiprocessing
import os
import re
import tempfile
import threading
import time
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit
from uuid import uuid4

START_TIMEOUT = 90
REQUEST_TIMEOUT = 15
IDLE_TIMEOUT = 120
DISCOVERY_TIMEOUT = 30
SEED_SITE = "https://faurecia.sharepoint.com/sites/ES-Asia_RandD2"
SEED_FOLDER = "/sites/ES-Asia_RandD2/Released Documents"
DEFAULT_SEED_URL = SEED_SITE + "/Released Documents/CHD-F-DSE-1018 BOM Conversion Tool.xlsm"
NUMBER = re.compile(r"(?<![A-Z0-9])CHD-F-DSE-(100[1-9]|101[0-9]|1020)(?![A-Z0-9])", re.I)


class BridgeError(Exception):
    pass


def valid_seed_url(url, site_url):
    parsed, site = urlsplit(url), urlsplit(site_url)
    return (
        parsed.scheme == "https" and parsed.hostname == site.hostname
        and parsed.port in (None, 443) and not parsed.username and not parsed.password
        and not parsed.query and not parsed.fragment
        and Path(unquote(parsed.path)).suffix.lower() in {".xlsx", ".xlsm"}
    )


def bridge_root():
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "FORVIA/TestDataConsolidation/bridge"


def verified_workbook():
    folder = Path(__file__).with_name("bridge")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    workbook = folder / "excel_bridge.xlsm"
    for path, key in ((workbook, "workbook_sha256"), (folder / "Bridge.bas", "source_sha256")):
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[key]:
            raise BridgeError("Excel 桥文件校验失败，请重新安装工具")
    return workbook


def read_seed_cache(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_seed_cache(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(data, ensure_ascii=True), encoding="ascii")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def seed_candidates(settings, cache):
    urls = cache.get("urls", [])
    urls = urls if isinstance(urls, list) else []
    last = cache.get("last_success", "")
    def sort_key(url):
        match = NUMBER.search(unquote(urlsplit(url).path))
        return (url != last, int(match.group(1)) if match else 9999, url)
    candidates = sorted(
        {u for u in [last, *urls] if isinstance(u, str) and valid_seed_url(u, settings.site_url)},
        key=sort_key,
    )
    return list(dict.fromkeys([settings.seed_url, *candidates]))[:3]


def discover_seeds(request, site_url, deadline):
    """Enumerate actual file URLs, following both pagination and subfolders."""
    if urlsplit(site_url).hostname != urlsplit(SEED_SITE).hostname:
        return []
    headers = {"Accept": "application/json;odata=verbose"}
    def folder_url(folder, kind):
        escaped = quote(folder.replace("'", "''"), safe="/")
        return SEED_SITE + f"/_api/web/GetFolderByServerRelativeUrl('{escaped}')/{kind}?$select=Name,ServerRelativeUrl"
    pages = [folder_url(SEED_FOLDER, "Files"), folder_url(SEED_FOLDER, "Folders")]
    visited, found = set(), set()
    origin = "https://" + urlsplit(SEED_SITE).netloc
    while pages:
        if time.monotonic() >= deadline:
            break
        url = pages.pop(0)
        parsed = urlsplit(url)
        if url in visited or parsed.scheme != "https" or parsed.netloc != urlsplit(SEED_SITE).netloc:
            continue
        visited.add(url)
        response = request("GET", url, headers)
        if response.get("status") != 200:
            continue
        data = json.loads(response["body"])["d"]
        for item in data.get("results", []):
            relative = item.get("ServerRelativeUrl", "")
            if not relative.startswith(SEED_FOLDER + "/"):
                continue
            if "/Folders?" in url:
                pages.extend([folder_url(relative, "Files"), folder_url(relative, "Folders")])
            elif NUMBER.search(item.get("Name", "")):
                file_url = origin + quote(relative, safe="/")
                if valid_seed_url(file_url, site_url):
                    found.add(file_url)
        if data.get("__next"):
            pages.append(urljoin(url, data["__next"]))
    return sorted(found)


class ExcelBridge:
    """Pipe client; the helper owns Excel and watches the parent and deadlines."""
    def __init__(self, settings):
        self.settings = settings
        self._process = self._conn = None
        self._lock = threading.RLock()

    def _exchange(self, message, timeout):
        from .usage_logging import UploadError
        try:
            self._conn.send(message)
            deadline = time.monotonic() + timeout
            stage = "正在连接 Excel"
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._conn.poll(remaining):
                    raise BridgeError(f"{stage}超时，日志已保留")
                reply = self._conn.recv()
                if "progress" in reply:
                    stage = reply["progress"]
                    continue
                break
            if reply.get("error"):
                raise BridgeError(reply["error"])
            return reply
        except (OSError, EOFError, BridgeError) as exc:
            self.close()
            reason = str(exc) if isinstance(exc, BridgeError) else f"{stage}未完成，Excel 桥已退出，日志已保留"
            raise UploadError(reason, bridge_fatal=True) from exc

    def start(self, *, local_diagnostic=False):
        with self._lock:
            if self._process and self._process.is_alive():
                return
            self.close()
            ctx = multiprocessing.get_context("spawn")
            self._conn, child = ctx.Pipe()
            self._process = ctx.Process(
                target=bridge_worker, args=(child, os.getpid()), name="excel-log-bridge", daemon=True,
            )
            self._process.start()
            atexit.unregister(self.close)
            atexit.register(self.close)
            child.close()
            self.identity = self._exchange({"action": "start", "settings": self.settings,
                                           "local_diagnostic": local_diagnostic}, START_TIMEOUT + 3)

    def request(self, method, url, headers, body=None):
        with self._lock:
            self.start()
            return self._exchange(
                {"action": "request", "method": method, "url": url, "headers": headers, "body": body},
                REQUEST_TIMEOUT + 3,
            )

    def discover(self):
        with self._lock:
            if self._process and self._process.is_alive():
                return self._exchange({"action": "discover"}, DISCOVERY_TIMEOUT + 3)

    def close(self):
        with self._lock:
            process, conn = self._process, self._conn
            self._process = self._conn = None
            if process:
                try:
                    if process.is_alive() and conn:
                        conn.send({"action": "close"})
                    process.join(timeout=3)
                    # The helper watchdog owns the Excel handle and kills only
                    # that instance on deadline or lost parent, including Quit hangs.
                    if process.is_alive():
                        if conn:
                            conn.close()
                        process.join(timeout=3)
                except (OSError, ValueError):
                    pass
            if conn:
                conn.close()
            atexit.unregister(self.close)


class ExcelSession:
    """Used only on the helper's COM-initialized main thread."""
    def __init__(self, directory, owner):
        self.directory, self.owner = Path(directory), owner
        self.xl = self.wb = None
        self.settings = None
        self.cache_path = bridge_root() / "seed-cache.json"

    def progress(self, message):
        self.owner["stage"] = message
        if self.owner.get("report"):
            self.owner["report"]({"progress": message})

    def open_bridge(self):
        import win32com.client
        import win32api
        import win32process
        started = time.time()
        self.progress("正在启动独立 Excel")
        self.xl = win32com.client.DispatchEx("Excel.Application")
        _, pid = win32process.GetWindowThreadProcessId(self.xl.Hwnd)
        handle = win32api.OpenProcess(0x100000 | 0x1000 | 1, False, pid)
        created = win32process.GetProcessTimes(handle)["CreationTime"].timestamp()
        if created < started - 2:
            handle.Close()
            self.xl = None
            raise BridgeError("无法确认独立 Excel 实例，日志已保留")
        self.owner["excel_handle"] = handle
        self.owner["excel_pid"] = pid
        self.xl.Visible = False
        self.xl.DisplayAlerts = False
        self.xl.EnableEvents = False
        self.xl.AskToUpdateLinks = False
        try:
            self.progress("正在加载 Excel 桥工作簿")
            self.xl.AutomationSecurity = 1
            self.wb = self.xl.Workbooks.Open(str(verified_workbook()), UpdateLinks=0, ReadOnly=True)
            if self.xl.Run(f"'{self.wb.Name}'!Bridge.BridgeVersion") != "1":
                raise BridgeError("Excel 桥版本不匹配")
        except Exception as exc:
            raise BridgeError("Excel 桥宏无法运行，请检查 Office 宏策略及工具完整性") from exc
        finally:
            self.xl.AutomationSecurity = 3

    def start(self, settings):
        self.settings = settings
        try:
            self.open_bridge()
        except BridgeError:
            raise
        except Exception as exc:
            raise BridgeError("无法启动独立 Excel，请检查是否已安装桌面版 Excel") from exc
        cache = read_seed_cache(self.cache_path)
        from .usage_logging import SharePointClient
        client = SharePointClient(settings, request=self.request)
        for url in seed_candidates(settings, cache):
            seed = None
            try:
                self.progress("正在只读打开 SharePoint 登录文件，请确认 Office 公司账号可用")
                seed = self.xl.Workbooks.Open(
                    quote(url, safe=":/%"), UpdateLinks=0, ReadOnly=True,
                    IgnoreReadOnlyRecommended=True, AddToMru=False,
                )
                time.sleep(7)
                seed.Close(SaveChanges=False)
                seed = None
                time.sleep(2)
                self.progress("正在验证 SharePoint 登录会话")
                client.call("GET", client.list_url + "?$select=ListItemEntityTypeFullName")
                cache["last_success"] = url
                try:
                    save_seed_cache(self.cache_path, cache)
                except OSError:
                    pass
                return
            except Exception:
                pass
            finally:
                if seed is not None:
                    seed.Close(SaveChanges=False)
        raise BridgeError("Excel 登录初始化失败，请检查 Office 公司账号、种子文件读取权限及列表权限")

    def request(self, method, url, headers, body=None):
        if self.settings:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.netloc != urlsplit(self.settings.site_url).netloc:
                raise BridgeError("Excel 桥请求地址不属于配置的 SharePoint 主机")
        digest = headers.get("X-RequestDigest", "-")
        if method not in {"GET", "POST"} or any("\n" in x or "\r" in x for x in (url, digest)):
            raise BridgeError("Excel 桥请求格式无效")
        stem = uuid4().hex
        request = self.directory / f"{stem}.txt"
        response = self.directory / f"{stem}.response"
        payload = "-" if body is None else json.dumps(body, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        try:
            request.write_text(f"{method}\n{quote(url, safe=':/%?$=&(),')}\n{digest}\n{payload}", encoding="ascii")
            self.xl.Run(f"'{self.wb.Name}'!Bridge.DoRequest", str(request), str(response))
            status, retry_after, text = response.read_text(encoding="utf-8-sig").split("\n", 2)
            return {"status": max(0, int(status)), "body": text, "retry_after": retry_after}
        finally:
            request.unlink(missing_ok=True)
            response.unlink(missing_ok=True)

    def discover(self):
        cache = read_seed_cache(self.cache_path)
        today = date.today().isoformat()
        if cache.get("last_discovery") == today:
            return
        cache["last_discovery"] = today
        # Persist before enumeration: a timeout also counts as today's attempt.
        save_seed_cache(self.cache_path, cache)
        found = discover_seeds(self.request, self.settings.site_url, time.monotonic() + DISCOVERY_TIMEOUT - 1)
        cache["urls"] = sorted(set(cache.get("urls", [])) | set(found))
        save_seed_cache(self.cache_path, cache)

    def close(self):
        try:
            if self.wb is not None:
                self.wb.Close(SaveChanges=False)
        finally:
            if self.xl is not None:
                self.xl.Quit()
            self.wb = self.xl = None


def bridge_worker(conn, parent_pid):
    """Watchdog never calls COM: it terminates only the retained owned process handle."""
    import pythoncom
    import win32api
    import win32event
    import win32process
    parent = win32api.OpenProcess(0x100000, False, parent_pid)
    owner = {"excel_handle": None, "deadline": time.monotonic() + START_TIMEOUT,
             "stage": "Excel 初始化", "report": conn.send}
    stopped = threading.Event()

    def watchdog():
        while not stopped.wait(0.25):
            if (win32event.WaitForSingleObject(parent, 0) == 0
                    or time.monotonic() > owner["deadline"]):
                handle = owner["excel_handle"]
                if handle is not None:
                    try:
                        win32process.TerminateProcess(handle, 1)
                    except Exception:
                        pass
                try:
                    conn.send({"error": owner["stage"] + "超时或主程序已退出，日志已保留"})
                except (EOFError, OSError):
                    pass
                os._exit(1)

    threading.Thread(target=watchdog, daemon=True).start()
    pythoncom.CoInitialize()
    bridge_root().mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="session-", dir=bridge_root()) as directory:
            session = ExcelSession(directory, owner)
            try:
                while conn.poll(IDLE_TIMEOUT):
                    message = conn.recv()
                    action = message["action"]
                    if action == "request":
                        owner["stage"] = "Excel 网络请求"
                    elif action == "discover":
                        owner["stage"] = "SharePoint 候选文件检索"
                    owner["deadline"] = time.monotonic() + (
                        START_TIMEOUT if action == "start" else DISCOVERY_TIMEOUT if action == "discover" else REQUEST_TIMEOUT
                    )
                    if action == "close":
                        break
                    try:
                        if action == "start":
                            owner["local_diagnostic"] = bool(message.get("local_diagnostic"))
                            if message.get("local_diagnostic"):
                                session.open_bridge()
                            else:
                                session.start(message["settings"])
                            result = {"excel_pid": owner.get("excel_pid")}
                        elif action == "discover":
                            session.discover()
                            result = {}
                        else:
                            result = session.request(
                                message["method"], message["url"], message["headers"], message.get("body")
                            )
                        conn.send(result)
                    except Exception as exc:
                        message = str(exc) if isinstance(exc, BridgeError) else "Excel 桥运行失败，日志已保留"
                        if owner.get("local_diagnostic") and not isinstance(exc, BridgeError):
                            message = f"本机桥自检异常: {exc!r}"
                        conn.send({"error": message})
                        break
                    owner["deadline"] = time.monotonic() + IDLE_TIMEOUT + 3
            finally:
                owner["deadline"] = time.monotonic() + 3
                session.close()
    except (EOFError, OSError):
        pass
    finally:
        stopped.set()
        handle = owner["excel_handle"]
        if handle is not None:
            # Quit can return while Excel still holds references.
            if win32event.WaitForSingleObject(handle, 1000) != 0:
                win32process.TerminateProcess(handle, 0)
            handle.Close()
        parent.Close()
        conn.close()
        pythoncom.CoUninitialize()
