import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from testdata_tool.excel_bridge import (
    DEFAULT_SEED_URL, SEED_FOLDER, SEED_SITE, ExcelBridge, discover_seeds,
    read_seed_cache, save_seed_cache, seed_candidates, verified_workbook,
)
from testdata_tool.managed_config import _validate_local_operations, _validate_operations
from testdata_tool.usage_logging import Settings, SharePointClient, UploadError, UsageService


def add_events(service, count):
    for _ in range(count):
        service.outbox.enqueue({
            "EventId": str(uuid4()), "Title": "SUCCESS", "ErrorMessage": "old local summary",
            "Timestamp": "2026-09-05T08:30:00Z", "Toolname": "Testing Data Consolidation Tool",
            "InputFormat": "csv", "OutputFormat": "XLSX", "RowCount": 1, "Duration": 1.5,
        })


class FakeBridge:
    def __init__(self, settings):
        self.posts = []
        self.closed = False
        self.discovered = 0

    def request(self, method, url, headers, body=None):
        if method == "GET":
            data = {"ListItemEntityTypeFullName": "SP.Data.ToolUseLogsListItem"}
        elif url.endswith("/contextinfo"):
            data = {"GetContextWebInformation": {"FormDigestValue": "digest"}}
        else:
            self.posts.append(body)
            data = {"Id": len(self.posts)}
        return {"status": 201 if url.endswith("/items") else 200, "body": json.dumps({"d": data})}

    def discover(self):
        self.discovered += 1

    def close(self):
        self.closed = True


def test_403_fallback_once_reuses_bridge_and_projects_old_events(tmp_path):
    direct, bridges = [], []
    class Direct:
        def send(self, event):
            direct.append(event)
            raise UploadError("forbidden", http_status=403)
    def factory(settings):
        bridge = FakeBridge(settings)
        bridges.append(bridge)
        return bridge
    service = UsageService(tmp_path / "queue.db", Settings(), lambda _: Direct(), factory)
    add_events(service, 6)
    service.sync_once()
    assert len(direct) == len(bridges) == 1
    assert len(bridges[0].posts) == 6
    assert all(post["ErrorMessage"] == "" and "EventId" not in post for post in bridges[0].posts)
    assert service.outbox.status() == (0, "")
    assert service.snapshot()["sent"] == 6
    assert bridges[0].discovered == 1
    service._close_bridge()


@pytest.mark.parametrize("status", [None, 401, 400, 404, 500])
def test_other_failures_never_start_bridge(tmp_path, status):
    class Direct:
        def send(self, event):
            raise UploadError("request failed", http_status=status)
    def forbidden(settings):
        pytest.fail("bridge should not start")
    service = UsageService(tmp_path / "q.db", Settings(), lambda _: Direct(), forbidden)
    add_events(service, 1)
    service.sync_once()
    assert service.outbox.status()[0] == 1


def test_direct_success_and_disabled_bridge(tmp_path):
    called = []
    def forbidden(settings):
        pytest.fail("bridge should not start")
    service = UsageService(tmp_path / "q.db", Settings(), lambda _: SimpleNamespace(send=lambda event: called.append(event)), forbidden)
    add_events(service, 1)
    service.sync_once()
    assert len(called) == 1 and service.outbox.status()[0] == 0
    service.settings = replace(service.settings, excel_bridge_enabled=False)
    def fail(event):
        raise UploadError("403", http_status=403)
    service.client_factory = lambda _: SimpleNamespace(send=fail)
    add_events(service, 1)
    service.sync_once()
    assert service.outbox.status()[0] == 1


@pytest.mark.parametrize("failure", ["fatal", "permission"])
def test_bridge_failure_stops_batch_without_losing_queue(tmp_path, failure):
    class Broken(FakeBridge):
        def request(self, *args, **kwargs):
            raise UploadError("Excel bridge unavailable", bridge_fatal=failure == "fatal",
                              http_status=403 if failure == "permission" else None)
    bridges = []
    def factory(settings):
        bridges.append(Broken(settings))
        return bridges[-1]
    def direct(event):
        raise UploadError("403", http_status=403)
    service = UsageService(tmp_path / "q.db", Settings(), lambda _: SimpleNamespace(send=direct), factory)
    add_events(service, 6)
    service.sync_once()
    assert service.outbox.status()[0] == 6
    assert len(bridges) == 1 and bridges[0].closed
    assert service.snapshot()["failed"] == 1


def test_manual_batch_does_not_duplicate_or_take_new_events(tmp_path):
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    sent = []
    def send(event):
        entered.set()
        assert release.wait(3)
        sent.append(event["EventId"])
    service = UsageService(tmp_path / "q.db", Settings(), lambda _: SimpleNamespace(send=send))
    add_events(service, 6)
    original = service._run
    def run():
        try:
            original()
        finally:
            done.set()
    service._run = run
    assert service.request_manual_sync()
    assert entered.wait(3)
    assert not service.request_manual_sync()
    service.sync_once()  # competing sync is rejected by the same lock
    add_events(service, 1)
    release.set()
    assert done.wait(5)
    assert len(sent) == len(set(sent)) == 6
    assert service.outbox.status()[0] == 1


@pytest.mark.parametrize("mode,count", [("online", 0), ("online", 5), ("off", 6), ("cache_only", 6)])
def test_manual_threshold_and_modes(tmp_path, mode, count):
    service = UsageService(tmp_path / "q.db", Settings(mode))
    add_events(service, count)
    assert not service.request_manual_sync()


def test_batch_preserves_leases_and_retry_after(tmp_path):
    sent = []
    service = UsageService(tmp_path / "q.db", Settings(), lambda _: SimpleNamespace(send=lambda event: sent.append(event)))
    add_events(service, 6)
    held, _, _ = service.outbox.claim(set())
    with service.outbox.connect() as db:
        db.execute("UPDATE events SET next_try=? WHERE id<>?", (time.time() + 120, held))
    service.sync_once()
    assert not sent and service.outbox.status()[0] == 6


def test_mode_change_stops_following_events(tmp_path):
    sent = []
    def send(event):
        sent.append(event)
        service.configure(replace(service.settings, mode="off"))
    service = UsageService(tmp_path / "q.db", Settings(), lambda _: SimpleNamespace(send=send))
    add_events(service, 6)
    service.sync_once()
    assert len(sent) == 1 and service.outbox.status()[0] == 5


@pytest.mark.parametrize("validate", [_validate_operations, _validate_local_operations])
def test_bridge_settings_roundtrip(validate):
    data = validate({"schema_version": 1, "logging": {"excel_bridge_enabled": False, "seed_url": DEFAULT_SEED_URL}})
    settings = Settings.from_mapping(data["logging"])
    assert not settings.excel_bridge_enabled
    assert Settings.from_mapping({"sharepoint_site_url": Settings().site_url, **data["logging"]}) == settings
    for bad in ("true", 1, None):
        with pytest.raises((ValueError, TypeError)):
            Settings.from_mapping({"excel_bridge_enabled": bad})
    for url in ("http://faurecia.sharepoint.com/a.xlsx", "https://other.test/a.xlsx", DEFAULT_SEED_URL + "?token=secret"):
        with pytest.raises(ValueError):
            Settings.from_mapping({"seed_url": url})


def test_seed_candidates_limit_validate_and_prefer_success(tmp_path):
    urls = [SEED_SITE + f"/Released Documents/CHD-F-DSE-{n} Tool.xlsx" for n in (1001, 1002, 1019)]
    path = tmp_path / "seeds.json"
    save_seed_cache(path, {"last_success": urls[-1], "urls": [*urls, "https://wrong.test/a.xlsx"]})
    assert seed_candidates(Settings(), read_seed_cache(path)) == [DEFAULT_SEED_URL, urls[-1], urls[0]]


def test_discovery_pagination_subfolders_and_exact_number():
    calls = []
    def request(method, url, headers):
        calls.append(url)
        if "page=2" in url:
            data = {"results": [{"Name": "CHD-F-DSE-1020 Z.xlsm", "ServerRelativeUrl": SEED_FOLDER + "/CHD-F-DSE-1020 Z.xlsm"}]}
        elif "/Folders?" in url:
            data = {"results": [] if "/Sub" in url else [{"Name": "Sub", "ServerRelativeUrl": SEED_FOLDER + "/Sub"}]}
        elif "/Sub" in url:
            data = {"results": [{"Name": "CHD-F-DSE-1002 X.xlsx", "ServerRelativeUrl": SEED_FOLDER + "/Sub/CHD-F-DSE-1002 X.xlsx"}]}
        else:
            data = {"__next": SEED_SITE + "/page=2", "results": [
                {"Name": name, "ServerRelativeUrl": SEED_FOLDER + "/" + name}
                for name in ("CHD-F-DSE-1001 X.xlsx", "CHD-F-DSE-10010 X.xlsx",
                             "CHD-F-DSE-1021 X.xlsx", "CHD-F-DSE-1004 X.pdf")
            ]}
        return {"status": 200, "body": json.dumps({"d": data})}
    found = discover_seeds(request, Settings().site_url, time.monotonic() + 5)
    assert len(found) == 3 and any("1002" in u for u in found)
    assert len(calls) == 5
    assert discover_seeds(request, Settings().site_url, time.monotonic() - 1) == []


@pytest.mark.parametrize("item_id", [None, "", "1", 0, -1, True])
def test_upload_requires_positive_integer_id(item_id):
    bridge = FakeBridge(Settings())
    request = bridge.request
    def transport(method, url, headers, body):
        if url.endswith("/items"):
            return {"status": 201, "body": json.dumps({"d": {"Id": item_id}})}
        return request(method, url, headers, body)
    with pytest.raises(UploadError):
        SharePointClient(Settings(), transport).send({"Title": "SUCCESS"})


def test_bridge_asset_is_real_and_matches_source():
    import zipfile
    with zipfile.ZipFile(verified_workbook()) as archive:
        assert len(archive.read("xl/vbaProject.bin")) > 1000


def test_helper_timeout_returns_failure_and_closes(monkeypatch):
    bridge = ExcelBridge(Settings())
    bridge._conn = SimpleNamespace(send=lambda message: None, poll=lambda timeout: False, close=lambda: None)
    closed = []
    monkeypatch.setattr(bridge, "close", lambda: closed.append(True))
    with pytest.raises(UploadError, match="超时") as exc:
        bridge._exchange({}, 0)
    assert exc.value.bridge_fatal and closed


def test_auto_wake_delivers_new_events_without_parallel_workers(tmp_path, monkeypatch, isolated_usage_network):
    monkeypatch.setattr(UsageService, "wake", isolated_usage_network)
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    sent = []
    def send(event):
        entered.set()
        assert release.wait(3)
        sent.append(event["EventId"])
    service = UsageService(tmp_path / "q.db", Settings(), lambda _: SimpleNamespace(send=send))
    run = service._run
    def observed_run():
        try:
            run()
        finally:
            done.set()
    service._run = observed_run
    service.enqueue({"EventId": str(uuid4())})
    assert entered.wait(3)
    service.enqueue({"EventId": str(uuid4())})
    assert not service.request_manual_sync()
    release.set()
    assert done.wait(5)
    assert len(set(sent)) == 2 and service.outbox.status()[0] == 0


def test_configuration_switch_between_rest_calls_cancels_remaining_requests(tmp_path):
    requests = []
    service = None
    def transport(method, url, headers, body=None):
        requests.append(url)
        service.configure(replace(service.settings, mode="off"))
        return {"status": 200, "body": json.dumps({"d": {"ListItemEntityTypeFullName": "SP.Data.ToolUseLogsListItem"}})}
    service = UsageService(tmp_path / "q.db", Settings(), lambda settings: SharePointClient(settings, transport))
    add_events(service, 2)
    service.sync_once()
    assert len(requests) == 1 and service.outbox.status()[0] == 2


def test_mode_change_releases_cached_bridge(tmp_path):
    service = UsageService(tmp_path / "q.db", Settings())
    bridge = FakeBridge(service.settings)
    service._bridge, service._bridge_settings = bridge, service.settings
    done = threading.Event()
    run = service._run
    def observed():
        try:
            run()
        finally:
            done.set()
    service._run = observed
    service.configure(replace(service.settings, mode="off"))
    assert done.wait(5)
    assert bridge.closed and service._bridge is None
