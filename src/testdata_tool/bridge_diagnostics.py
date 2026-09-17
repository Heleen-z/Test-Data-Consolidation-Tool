"""Explicit loopback-only release check, callable from the frozen executable."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from .excel_bridge import ExcelBridge
from .usage_logging import Settings


def self_test():
    import win32api
    import win32event
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(201)
            self.send_header("Retry-After", "17")
            self.end_headers()
            self.wfile.write(json.dumps({"d": {"Id": 7, "ProjectName": "中文项目"}}, ensure_ascii=False).encode())
        def log_message(self, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    bridge = ExcelBridge(Settings())
    handle = None
    try:
        bridge.start(local_diagnostic=True)
        handle = win32api.OpenProcess(0x100000, False, bridge.identity["excel_pid"])
        body = {"ProjectName": "中文项目", "ErrorMessage": "quote \" and newline\n"}
        response = bridge.request("POST", f"http://127.0.0.1:{server.server_port}/items", {}, body)
        assert response["status"] == 201 and response["retry_after"] == "17"
        assert json.loads(response["body"])["d"]["ProjectName"] == "中文项目"
        assert received == [body]
        bridge.close()
        assert win32event.WaitForSingleObject(handle, 5000) == 0, "Owned Excel did not exit"
        return {"passed": True, "excel_pid": bridge.identity["excel_pid"],
                "checks": ["spawn", "prebuilt_macro", "loopback_http", "unicode", "retry_after", "owned_excel_exit"]}
    finally:
        bridge.close()
        if handle:
            handle.Close()
        server.shutdown()
        server.server_close()


def write_self_test(path):
    from pathlib import Path
    try:
        result = self_test()
    except Exception as exc:
        # This file is an explicit developer verification artifact, never a
        # usage event.  Keep the exception chain so a frozen-only start-up
        # failure remains diagnosable without weakening the user-facing error.
        result = {
            "passed": False,
            "error": str(exc),
            "exception_type": type(exc).__name__,
            "cause": repr(exc.__cause__) if exc.__cause__ else "",
        }
    Path(path).write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    return 0 if result["passed"] else 1
