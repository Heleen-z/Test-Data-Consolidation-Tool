import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest

from testdata_tool.managed_config import _validate_operations, _validate_local_operations, ManagedConfigError
from testdata_tool.usage_logging import (
    Outbox, Settings, SharePointClient, UploadError, UsageService, create_success_event,
    powershell_request,
)


def test_event_uses_actual_merge_counts_and_directory(tmp_path):
    output = tmp_path / "result.xlsx"
    output.write_bytes(b"saved workbook")
    result = SimpleNamespace(
        output_path=output, type_rows={"T09": 12, "T12": 3}, datasets={"T09": None, "T12": None},
        source_index=pd.DataFrame({"Source_ID": ["a", "b"], "状态": ["有效", "合并失败"]}),
    )
    precheck = SimpleNamespace(input_folder=tmp_path / "项目甲", files=[
        SimpleNamespace(source_id="a", path=tmp_path / "1.CSV"),
        SimpleNamespace(source_id="b", path=tmp_path / "2.txt"),
        SimpleNamespace(source_id="excluded", path=tmp_path / "3.xls"),
    ])
    config = SimpleNamespace(config_version="local-test", template_version="built-in")
    event = create_success_event(uuid4(), result, precheck, config, 1.234,
                                 {"UserName": "tester", "UserEmail": "", "ComputerName": "PC"})
    assert event["Title"] == "SUCCESS"
    assert (event["FileCount"], event["RowCount"], event["FailedFileCount"]) == (2, 15, 1)
    assert event["InputFormat"] == "csv;txt"
    assert event["TestTypes"] == "T09;T12"
    assert event["ProjectName"] == "项目甲"
    assert event["UserEmail"] == ""
    assert "ProjectCode" not in event
    assert event["Timestamp"].endswith("Z") and event["Duration"] == 1.23
    assert "1 个文件" in event["ErrorMessage"]
    result.type_rows = {}
    with pytest.raises(ValueError):
        create_success_event(uuid4(), result, precheck, config, 1, {})
    result.type_rows = {"T09": 1}
    output.unlink()
    with pytest.raises(ValueError):
        create_success_event(uuid4(), result, precheck, config, 1, {})


def test_outbox_restart_lease_recovery_and_deduplication(tmp_path):
    path = tmp_path / "queue.sqlite3"
    box = Outbox(path)
    event = {"EventId": str(uuid4()), "Timestamp": "2026-09-05T00:00:00Z"}
    box.enqueue(event)
    box.enqueue(event)
    event_id, payload, token = box.claim(set())
    other = Outbox(path)
    assert other.claim(set()) is None
    assert other.status()[0] == 1
    with box.connect() as db:
        db.execute("UPDATE events SET lease_until=0")
    _, restored, new_token = other.claim(set())
    assert restored == payload == event
    box.finish(event_id, token, True)  # Old worker cannot acknowledge a renewed lease.
    assert box.status()[0] == 1
    other.finish(event_id, new_token, True)
    box.enqueue(event)  # Even after acknowledgement, same event stays deduplicated.
    assert box.status() == (0, "")


@pytest.mark.parametrize("mode", ["off", "cache_only"])
def test_modes_never_start_network(tmp_path, mode):
    def forbidden(_):
        pytest.fail("network must not start")
    service = UsageService(tmp_path / "queue.sqlite3", Settings(mode), forbidden)
    service.enqueue({"EventId": str(uuid4())})
    service.sync_once()
    assert service.outbox.status()[0] == (1 if mode == "cache_only" else 0)


def test_retry_limits_and_authentication_failures(tmp_path, monkeypatch):
    calls = []
    class Offline:
        def send(self, event):
            calls.append(event)
            raise UploadError("offline", retryable=True)
    monkeypatch.setattr("testdata_tool.usage_logging.time.sleep", lambda _: None)
    service = UsageService(tmp_path / "queue.sqlite3", Settings("online"), lambda _: Offline())
    service.outbox.enqueue({"EventId": str(uuid4())})
    service.sync_once()
    assert len(calls) == 3 and service.outbox.status() == (1, "offline")
    with service.outbox.connect() as db:
        db.execute("UPDATE events SET next_try=0")
    class Unauthenticated:
        def send(self, event):
            calls.append(event)
            raise UploadError("HTTP 403")
    service.client_factory = lambda _: Unauthenticated()
    service.sync_once()
    assert len(calls) == 4 and service.outbox.status() == (1, "HTTP 403")


def test_retry_after_is_persisted_without_blocking_worker(tmp_path):
    class Limited:
        def send(self, event):
            raise UploadError("HTTP 429", True, 120)
    service = UsageService(tmp_path / "queue.sqlite3", Settings("online"), lambda _: Limited())
    service.outbox.enqueue({"EventId": str(uuid4())})
    service.sync_once()
    with service.outbox.connect() as db:
        assert db.execute("SELECT next_try FROM events").fetchone()[0] > time.time() + 110


def test_server_saved_but_response_lost_is_confirmed_without_duplicate():
    event = {"EventId": str(uuid4()), "Title": "SUCCESS", "Timestamp": "2026-09-05T00:00:00Z"}
    saved, posted = [], []
    def response(data, status=200):
        return {"status": status, "body": json.dumps({"d": data})}
    def transport(method, url, headers, body):
        if method == "GET" and "/items?" in url:
            return response({"results": saved})
        if method == "GET":
            return response({"ListItemEntityTypeFullName": "SP.Data.TestListItem"})
        if url.endswith("contextinfo"):
            return response({"GetContextWebInformation": {"FormDigestValue": "digest"}})
        assert headers["X-RequestDigest"] == "digest"
        assert body["__metadata"]["type"] == "SP.Data.TestListItem"
        if saved:
            raise UploadError("response lost", True)
        posted.append(body)
        saved.append({"Id": 1, "EventId": body["EventId"]})
        raise UploadError("response lost", True)
    client = SharePointClient(Settings("online"), transport)
    client.send(event)
    client.send(event)
    assert len(posted) == 1
    assert posted[0]["Timestamp"] == event["Timestamp"]


@pytest.mark.parametrize("status,body,retryable", [
    (401, "", False), (403, "", False), (404, "", False), (400, "bad field", False),
    (200, "<html>Login</html>", False), (500, "", True), (429, "", True),
])
def test_invalid_sharepoint_responses_are_never_acknowledged(status, body, retryable):
    client = SharePointClient(Settings("online"), lambda *args: {"status": status, "body": body, "retry_after": "30"})
    with pytest.raises(UploadError) as caught:
        client.send({"EventId": str(uuid4())})
    assert caught.value.retryable == retryable
    assert "读取列表元数据" in str(caught.value)


def test_upload_error_names_the_failed_sharepoint_operation():
    event = {"EventId": str(uuid4()), "Title": "SUCCESS", "Timestamp": "2026-09-05T00:00:00Z"}
    def response(data, status=200):
        return {"status": status, "body": json.dumps({"d": data})}
    def transport(method, url, headers, body):
        if method == "GET" and "/items?" in url:
            return response({"results": []})
        if method == "GET":
            return response({"ListItemEntityTypeFullName": "SP.Data.TestListItem"})
        if url.endswith("contextinfo"):
            return response({"GetContextWebInformation": {"FormDigestValue": "digest"}})
        return {"status": 403, "body": ""}
    with pytest.raises(UploadError, match="新增使用记录返回 HTTP 403"):
        SharePointClient(Settings("online"), transport).send(event)


@pytest.mark.parametrize("validate", [_validate_operations, _validate_local_operations])
def test_configuration_supports_both_central_and_local_overrides(validate):
    for mode in ("online", "off", "cache_only"):
        assert validate({"schema_version": 1, "usage_logging": {"mode": mode}})["usage_logging"]["mode"] == mode
    with pytest.raises(ManagedConfigError):
        validate({"schema_version": 1, "usage_logging": {"mode": "invalid"}})
    with pytest.raises(ManagedConfigError):
        validate({"schema_version": 1, "usage_logging": {"site_url": "http://example.com"}})
    assert validate({"schema_version": 1}) == {"schema_version": 1}


@pytest.mark.skipif(os.name != "nt", reason="Windows COM transport")
def test_real_windows_helper_roundtrip_uses_only_loopback():
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(201)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"d": {"Id": 1, "ProjectName": "项目测试"}}, ensure_ascii=False).encode("utf-8"))
        def log_message(self, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = {"ProjectName": "项目 ' 测试 $()", "Duration": 1.23}
        response = powershell_request("POST", f"http://127.0.0.1:{server.server_port}/items",
                                      {"Content-Type": "application/json; charset=utf-8"}, body)
        assert response["status"] == 201
        assert json.loads(response["body"])["d"]["ProjectName"] == "项目测试"
        assert received == [body]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
