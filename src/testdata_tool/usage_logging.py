"""Success-only usage events and a durable, asynchronous SharePoint outbox."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from uuid import UUID, uuid4

DEFAULT_SITE = "https://faurecia.sharepoint.com/sites/AIPortal"
DEFAULT_LIST = "Test Data Consolidation Logs"
REQUEST_TIMEOUT = 15
LEASE_SECONDS = 300


@dataclass(frozen=True)
class Settings:
    mode: str = "cache_only"
    site_url: str = DEFAULT_SITE
    list_name: str = DEFAULT_LIST

    @classmethod
    def from_mapping(cls, values):
        result = cls(**values)
        if result.mode not in {"cache_only", "online", "off"}:
            raise ValueError("usage_logging.mode 必须是 cache_only、online 或 off")
        url = urlsplit(result.site_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("usage_logging.site_url 必须是无凭据、查询参数的 HTTPS 站点地址")
        if not result.list_name.strip():
            raise ValueError("usage_logging.list_name 不能为空")
        return result


def queue_path():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "FORVIA" / "TestDataConsolidation" / "usage" / "queue.sqlite3"


@lru_cache(maxsize=1)
def user_identity():
    email = ""
    if os.name == "nt":
        try:
            whoami = Path(os.environ["SystemRoot"]) / "System32" / "whoami.exe"
            response = subprocess.run(
                [str(whoami), "/upn"], capture_output=True, timeout=2,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            value = response.stdout.decode(errors="replace").strip()
            if response.returncode == 0 and "@" in value and not any(c.isspace() for c in value):
                email = value
        except (OSError, subprocess.SubprocessError):
            pass
    return {"UserName": os.environ.get("USERNAME", ""), "UserEmail": email,
            "ComputerName": os.environ.get("COMPUTERNAME", "")}


def create_success_event(event_id, result, precheck, config, duration, identity=None):
    """Create one event only after a usable merge result has been saved."""
    rows = sum(result.type_rows.values())
    if rows <= 0 or not result.output_path.is_file() or result.output_path.stat().st_size <= 0:
        raise ValueError("没有可用合并结果，不能记录成功")
    selected = set(result.source_index["Source_ID"])
    formats = sorted({item.path.suffix.lstrip(".").lower() for item in precheck.files if item.source_id in selected})
    failures = int(result.source_index["状态"].eq("合并失败").sum())
    event = {
        "EventId": str(UUID(str(event_id))), "Title": "SUCCESS",
        "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "InputFormat": ";".join(formats), "OutputFormat": "XLSX",
        "RowCount": int(rows), "Duration": round(max(0.0, duration), 2),
        "ProjectName": precheck.input_folder.name,
        "ErrorMessage": f"{failures} 个文件合并失败；详情见本地验证信息" if failures else "",
        "FileCount": len(selected), "FailedFileCount": failures,
        "TestTypes": ";".join(sorted(result.datasets)),
        "ConfigVersion": config.config_version, "TemplateVersion": config.template_version,
    }
    from . import __version__
    event["AppVersion"] = __version__
    event.update(user_identity() if identity is None else identity)
    return {key: value[:255] if isinstance(value, str) and key != "ErrorMessage" else value
            for key, value in event.items()}


class Outbox:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0,
                lease TEXT, lease_until REAL NOT NULL DEFAULT 0,
                next_try REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '')""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def enqueue(self, event):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO events(id,payload) VALUES (?,?)",
                       (event["EventId"], json.dumps(event, ensure_ascii=False, allow_nan=False)))

    def claim(self, excluded):
        now, token = time.time(), str(uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,payload FROM events WHERE sent=0 AND lease_until<=? AND next_try<=? ORDER BY rowid", (now, now))
            row = next((row for row in rows if row[0] not in excluded), None)
            if row is None:
                return None
            db.execute("UPDATE events SET lease=?,lease_until=? WHERE id=?", (token, now + LEASE_SECONDS, row[0]))
            return row[0], json.loads(row[1]), token

    def finish(self, event_id, token, success, error="", delay=0):
        with self.connect() as db:
            db.execute("UPDATE events SET sent=?,error=?,lease=NULL,lease_until=0,next_try=? WHERE id=? AND lease=?",
                       (int(success), error, time.time() + delay, event_id, token))

    def status(self):
        with self.connect() as db:
            pending = db.execute("SELECT COUNT(*) FROM events WHERE sent=0").fetchone()[0]
            error = db.execute("SELECT error FROM events WHERE sent=0 AND error<>'' ORDER BY rowid DESC LIMIT 1").fetchone()
            return pending, error[0] if error else ""


class UploadError(Exception):
    def __init__(self, message, retryable=False, retry_after=2):
        super().__init__(message)
        self.retryable, self.retry_after = retryable, retry_after


def powershell_request(method, url, headers, body=None):
    """Use the same COM HTTP client as ebom, with a process-level hard timeout."""
    if os.name != "nt":
        raise UploadError("使用记录上传需要 Windows")
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    helper = Path(__file__).with_name("sharepoint_request.ps1")
    try:
        result = subprocess.run(
            [str(executable), "-NoProfile", "-NonInteractive", "-File", str(helper)],
            input=json.dumps({"method": method, "url": url, "headers": headers, "body": body}, ensure_ascii=True).encode(),
            capture_output=True, timeout=REQUEST_TIMEOUT, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise UploadError("Windows 请求组件未能完成请求", retryable=True)
        response = json.loads(result.stdout.decode("utf-8-sig"))
        if response.get("transport_error"):
            raise UploadError("网络请求失败", retryable=True)
        return response
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise UploadError("网络请求失败或超过 15 秒", retryable=True) from exc


class SharePointClient:
    def __init__(self, settings, request=powershell_request):
        self.settings, self.request = settings, request
        self.site = settings.site_url.rstrip("/")
        self.list_url = self.site + "/_api/web/lists/getbytitle('" + quote(settings.list_name.replace("'", "''"), safe="") + "')"

    def call(self, method, url, body=None, digest=None, operation="请求 AI Portal"):
        headers = {"Accept": "application/json;odata=verbose", "Content-Type": "application/json;odata=verbose"}
        if digest:
            headers["X-RequestDigest"] = digest
        response = self.request(method, url, headers, body)
        status = int(response["status"])
        if status not in {200, 201}:
            delay = 2
            retry_after = response.get("retry_after", "")
            if retry_after:
                try:
                    delay = max(2, int(retry_after))
                except ValueError:
                    try:
                        delay = max(2, (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds())
                    except (TypeError, ValueError):
                        pass
            raise UploadError(
                f"AI Portal：{operation}返回 HTTP {status}",
                status in {0, 408, 429} or status >= 500,
                delay,
            )
        try:
            data = json.loads(response["body"])
            return data["d"]
        except (ValueError, KeyError, TypeError) as exc:
            raise UploadError(f"AI Portal：{operation}返回登录页面或非预期响应") from exc

    def exists(self, event_id):
        query = urlencode({"$filter": f"EventId eq '{UUID(event_id)}'", "$select": "Id,EventId", "$top": "1"})
        data = self.call("GET", self.list_url + "/items?" + query, operation="查询已有 EventId")
        return any(item.get("EventId") == event_id for item in data.get("results", []))

    def send(self, event):
        if self.exists(event["EventId"]):
            return
        entity = self.call(
            "GET", self.list_url + "?$select=ListItemEntityTypeFullName", operation="读取列表元数据"
        )["ListItemEntityTypeFullName"]
        digest = self.call(
            "POST", self.site + "/_api/contextinfo", operation="获取写入令牌"
        )["GetContextWebInformation"]["FormDigestValue"]
        try:
            saved = self.call(
                "POST", self.list_url + "/items", {"__metadata": {"type": entity}, **event}, digest,
                operation="新增使用记录",
            )
            if saved.get("EventId") == event["EventId"] and saved.get("Id"):
                return
            if not self.exists(event["EventId"]):
                raise UploadError("提交后尚未确认记录", retryable=True)
        except UploadError as original:
            try:
                if self.exists(event["EventId"]):
                    return
            except UploadError:
                pass
            raise original


class UsageService:
    def __init__(self, path, settings, client_factory=SharePointClient):
        self.outbox = Outbox(path)
        self.settings, self.client_factory = settings, client_factory
        self.lock = threading.Lock()
        self.running = False
        self.requested = False

    def configure(self, settings):
        with self.lock:
            self.settings = settings

    def enqueue(self, event):
        if self.settings.mode != "off":
            self.outbox.enqueue(event)
            self.wake()

    def wake(self):
        with self.lock:
            if self.settings.mode != "online":
                return
            self.requested = True
            if not self.running:
                self.running = True
                threading.Thread(target=self._run, name="usage-upload", daemon=True).start()

    def sync_once(self):
        visited = set()
        while self.settings.mode == "online":
            claimed = self.outbox.claim(visited)
            if claimed is None:
                break
            event_id, event, token = claimed
            visited.add(event_id)
            settings = self.settings
            success, error, delay = False, "", 0
            try:
                for attempt in range(3):
                    if self.settings != settings:
                        break
                    try:
                        self.client_factory(settings).send(event)
                        success = True
                        break
                    except UploadError as exc:
                        error, delay = str(exc), max(2, exc.retry_after)
                        if not exc.retryable or attempt == 2 or delay > 2:
                            break
                        time.sleep(delay)
                # A failed entry waits for a later wake, not a tight retry loop.
            except Exception:
                error, delay = "使用记录同步异常，等待下次重试", 2
            finally:
                self.outbox.finish(event_id, token, success, error, delay if not success else 0)

    def _run(self):
        try:
            while True:
                with self.lock:
                    if not self.requested:
                        self.running = False
                        return
                    self.requested = False
                self.sync_once()
        except Exception:
            with self.lock:
                self.running = False


_services = {}
_services_lock = threading.Lock()


def get_service(values):
    settings = Settings.from_mapping(values)
    path = queue_path()
    with _services_lock:
        service = _services.get(path)
        if service is None:
            service = _services[path] = UsageService(path, settings)
        service.configure(settings)
        return service
