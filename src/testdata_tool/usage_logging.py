"""Conversion usage events and a durable, asynchronous SharePoint outbox."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid4
from .excel_bridge import DEFAULT_SEED_URL, ExcelBridge, valid_seed_url

DEFAULT_SITE = "https://faurecia.sharepoint.com/sites/AIPortal"
DEFAULT_LIST = "ToolUseLogs"
DEFAULT_TOOL_NAME = "Testing Data Consolidation Tool"
REQUEST_TIMEOUT = 15
LEASE_SECONDS = 300
LEGACY_LIST_NAMES = {"EBOM Conversion Logs", "AI Portal Tool Usage Logs"}
SHAREPOINT_FIELDS = (
    "Title", "InputFormat", "OutputFormat", "RowCount", "Duration", "ErrorMessage",
    "Timestamp", "UserName", "UserEmail", "ComputerName", "ProjectCode", "ProjectName",
    "Toolname",
)


@dataclass(frozen=True)
class Settings:
    mode: str = "online"
    site_url: str = DEFAULT_SITE
    list_name: str = DEFAULT_LIST
    tool_name: str = DEFAULT_TOOL_NAME
    excel_bridge_enabled: bool = True
    seed_url: str = DEFAULT_SEED_URL

    @classmethod
    def from_mapping(cls, values):
        # `logging` is the shared eBOM-compatible schema.  Keep accepting the
        # earlier `usage_logging` field names so existing local pilots retain
        # their explicit configuration during the migration.
        values = dict(values or {})
        if "sharepoint_site_url" in values:
            values = {
                "mode": values.get("mode", "online"),
                "site_url": values.get("sharepoint_site_url", DEFAULT_SITE),
                "list_name": values.get("list_name", DEFAULT_LIST),
                "tool_name": values.get("tool_name", DEFAULT_TOOL_NAME),
                "excel_bridge_enabled": values.get("excel_bridge_enabled", True),
                "seed_url": values.get("seed_url", DEFAULT_SEED_URL),
            }
        # Earlier releases pointed at shared or eBOM lists. Keep their other
        # settings, but never send this tool's records back to an old list.
        if values.get("list_name", "").strip() in LEGACY_LIST_NAMES:
            values["list_name"] = DEFAULT_LIST
        result = cls(**values)
        if result.mode not in {"cache_only", "online", "off"}:
            raise ValueError("logging.mode 必须是 cache_only、online 或 off")
        url = urlsplit(result.site_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("logging.sharepoint_site_url 必须是无凭据、查询参数的 HTTPS 站点地址")
        if not result.list_name.strip():
            raise ValueError("logging.list_name 不能为空")
        if not result.tool_name.strip():
            raise ValueError("logging.tool_name 不能为空")
        if not isinstance(result.excel_bridge_enabled, bool):
            raise ValueError("logging.excel_bridge_enabled 必须是布尔值")
        if not valid_seed_url(result.seed_url, result.site_url):
            raise ValueError("logging.seed_url 必须是同一 SharePoint 主机上的 HTTPS Excel 文件地址")
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


def _event_formats(precheck, selected_source_ids):
    return ";".join(sorted({
        item.path.suffix.lstrip(".").lower()
        for item in precheck.files if item.source_id in selected_source_ids and item.path.suffix
    }))


def _event_base(event_id, precheck, duration, identity, tool_name, title, error_message=""):
    event = {
        "EventId": str(UUID(str(event_id))), "Title": title, "Toolname": tool_name,
        "Timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "InputFormat": "", "OutputFormat": "XLSX", "RowCount": 0,
        "Duration": round(max(0.0, duration), 2), "ProjectCode": "",
        "ProjectName": precheck.input_folder.name, "ErrorMessage": error_message,
    }
    event.update(user_identity() if identity is None else identity)
    return event


def create_success_event(event_id, result, precheck, config, duration, identity=None, tool_name=DEFAULT_TOOL_NAME):
    """Create one event only after a usable merge result has been saved."""
    rows = sum(result.type_rows.values())
    if rows <= 0 or not result.output_path.is_file() or result.output_path.stat().st_size <= 0:
        raise ValueError("没有可用合并结果，不能记录成功")
    selected = set(result.source_index["Source_ID"])
    formats = _event_formats(precheck, selected)
    failures = int(result.source_index["状态"].eq("合并失败").sum())
    event = _event_base(event_id, precheck, duration, identity, tool_name, "SUCCESS")
    event.update({
        "InputFormat": formats, "RowCount": int(rows),
        "FileCount": len(selected), "FailedFileCount": failures,
        "TestTypes": ";".join(sorted(result.datasets)),
        "ConfigVersion": config.config_version, "TemplateVersion": config.template_version,
    })
    from . import __version__
    event["AppVersion"] = __version__
    event.update(user_identity() if identity is None else identity)
    return {key: value[:255] if isinstance(value, str) and key != "ErrorMessage" else value
            for key, value in event.items()}


def _safe_error_message(error):
    """Keep the list useful without exposing local file paths or a traceback."""
    text = re.sub(r"(?:[A-Za-z]:[\\/]|/)[^\s;，；:：]+", "[本地路径]", str(error))
    return (" ".join(text.splitlines()[:1]).strip() or "转换失败")[:4000]


def create_failure_event(event_id, precheck, selected_source_ids, duration, error, identity=None, tool_name=DEFAULT_TOOL_NAME):
    event = _event_base(
        event_id, precheck, duration, identity, tool_name, "FAILED", _safe_error_message(error)
    )
    event["InputFormat"] = _event_formats(precheck, selected_source_ids)
    return {key: value[:255] if isinstance(value, str) and key != "ErrorMessage" else value
            for key, value in event.items()}


def sharepoint_payload(event):
    """Return exactly the columns provisioned in ToolUseLogs for an event."""
    defaults = {"ProjectCode": "", "ErrorMessage": "", "OutputFormat": "XLSX"}
    payload = {field: event.get(field, defaults.get(field, "")) for field in SHAREPOINT_FIELDS}
    if payload["Title"] == "SUCCESS":
        payload["ErrorMessage"] = ""
    return payload


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

    def pending_ids(self):
        with self.connect() as db:
            return {row[0] for row in db.execute("SELECT id FROM events WHERE sent=0")}

    def claim(self, excluded, allowed=None):
        now, token = time.time(), str(uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,payload FROM events WHERE sent=0 AND lease_until<=? AND next_try<=? ORDER BY rowid", (now, now))
            row = next((row for row in rows if row[0] not in excluded
                        and (allowed is None or row[0] in allowed)), None)
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
    def __init__(self, message, retryable=False, retry_after=2, http_status=None, operation="", bridge_fatal=False):
        super().__init__(message)
        self.retryable, self.retry_after = retryable, retry_after
        self.http_status, self.operation, self.bridge_fatal = http_status, operation, bridge_fatal


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
                http_status=status, operation=operation,
            )
        try:
            data = json.loads(response["body"])
            return data["d"]
        except (ValueError, KeyError, TypeError) as exc:
            raise UploadError(f"AI Portal：{operation}返回登录页面或非预期响应") from exc

    def send(self, event):
        # Match the established eBOM flow: acquire the list metadata and form
        # digest, then submit directly. ToolUseLogs has no EventId column, so
        # confirmation is the successful item response.
        entity = self.call(
            "GET", self.list_url + "?$select=ListItemEntityTypeFullName", operation="读取列表元数据"
        )["ListItemEntityTypeFullName"]
        digest = self.call(
            "POST", self.site + "/_api/contextinfo", operation="获取写入令牌"
        )["GetContextWebInformation"]["FormDigestValue"]
        saved = self.call(
            "POST", self.list_url + "/items",
            {"__metadata": {"type": entity}, **sharepoint_payload(event)}, digest,
            operation="新增使用记录",
        )
        if not isinstance(saved, dict) or type(saved.get("Id")) is not int or saved["Id"] <= 0:
            raise UploadError("提交后未收到列表项标识", retryable=True)


class UsageService:
    def __init__(self, path, settings, client_factory=SharePointClient, bridge_factory=ExcelBridge):
        self.outbox = Outbox(path)
        self.settings, self.client_factory = settings, client_factory
        self.lock = threading.Lock()
        self.running = False
        self.requested = False
        self.sync_lock = threading.Lock()
        self.bridge_factory = bridge_factory
        self._bridge = None
        self._bridge_settings = None
        self._manual_ids = None
        self._progress = {"active": False, "completed": False, "sent": 0, "failed": 0, "error": ""}

    def configure(self, settings):
        with self.lock:
            changed = self.settings != settings
            self.settings = settings
        if changed:
            # Dispose on the worker, not the UI/COM caller.
            with self.lock:
                if self._bridge is not None:
                    self.requested = True
                    if not self.running:
                        self.running = True
                        threading.Thread(target=self._run, name="usage-upload", daemon=True).start()

    def snapshot(self):
        pending, error = self.outbox.status()
        with self.lock:
            return {**self._progress, "pending": pending, "mode": self.settings.mode,
                    "running": self.running or self._progress["active"], "queue_error": error}

    def request_manual_sync(self):
        with self.lock:
            if self.settings.mode != "online" or self.running or self._progress["active"]:
                return False
            ids = self.outbox.pending_ids()
            if len(ids) <= 5:
                return False
            self._manual_ids = ids
            self.requested = self.running = True
            threading.Thread(target=self._run, name="usage-upload", daemon=True).start()
            return True

    def _close_bridge(self):
        bridge, self._bridge = self._bridge, None
        self._bridge_settings = None
        if bridge is not None:
            try:
                bridge.close()
            except Exception:
                pass

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

    def sync_once(self, batch_ids=None):
        if not self.sync_lock.acquire(blocking=False):
            return
        try:
            self._sync_batch(batch_ids)
        finally:
            self.sync_lock.release()

    def _sync_batch(self, batch_ids):
        with self.lock:
            self._progress = {"active": True, "completed": False, "sent": 0, "failed": 0, "error": ""}
        try:
            self._send_batch(batch_ids)
        finally:
            with self.lock:
                self._progress.update(active=False, completed=True)

    def _send_batch(self, batch_ids):
        visited = set()
        settings = self.settings
        batch_ids = self.outbox.pending_ids() if batch_ids is None else batch_ids
        if self._bridge_settings != self.settings:
            self._close_bridge()
        use_bridge = False
        while self.settings.mode == "online" and self.settings == settings:
            claimed = self.outbox.claim(visited, allowed=batch_ids)
            if claimed is None:
                break
            event_id, event, token = claimed
            visited.add(event_id)
            success, error, delay = False, "", 0
            stop_batch = False
            try:
                for attempt in range(3):
                    if self.settings != settings:
                        break
                    try:
                        if use_bridge:
                            if self._bridge is None:
                                self._bridge = self.bridge_factory(settings)
                                self._bridge_settings = settings
                            client = SharePointClient(settings, request=self._bridge.request)
                        else:
                            client = self.client_factory(settings)
                        if isinstance(client, SharePointClient):
                            request = client.request
                            def guarded_request(*args, **kwargs):
                                if self.settings != settings:
                                    raise UploadError("日志配置已变更，等待下次补传")
                                return request(*args, **kwargs)
                            client.request = guarded_request
                        client.send(event)
                        success = True
                        break
                    except UploadError as exc:
                        error, delay = str(exc), max(2, exc.retry_after)
                        if (exc.http_status == 403 and not use_bridge and settings.excel_bridge_enabled
                                and self.bridge_factory is not None and attempt < 2):
                            use_bridge = True
                            continue
                        if use_bridge and (exc.bridge_fatal or exc.http_status in {401, 403}):
                            stop_batch = True
                            self._close_bridge()
                            break
                        if not exc.retryable or attempt == 2 or delay > 2:
                            break
                        time.sleep(delay)
                # A failed entry waits for a later wake, not a tight retry loop.
            except Exception:
                error, delay = "使用记录同步异常，等待下次重试", 2
                if use_bridge:
                    stop_batch = True
                    self._close_bridge()
            finally:
                self.outbox.finish(event_id, token, success, "" if success else error, delay if not success else 0)
                with self.lock:
                    self._progress["sent" if success else "failed"] += 1
                    if not success:
                        self._progress["error"] = error
            if stop_batch:
                break
        if use_bridge and self._bridge and self.settings == self._bridge_settings:
            try:
                self._bridge.discover()
            except Exception:
                self._close_bridge()
        if self._bridge_settings != self.settings or self.settings.mode != "online":
            self._close_bridge()

    def _run(self):
        try:
            while True:
                with self.lock:
                    if not self.requested:
                        self.running = False
                        return
                    self.requested = False
                    batch_ids, self._manual_ids = self._manual_ids, None
                self.sync_once(batch_ids)
        except Exception:
            self._close_bridge()
            with self.lock:
                self.running = False
                self._progress.update(active=False, completed=True, error="使用记录同步异常，日志已保留")


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
