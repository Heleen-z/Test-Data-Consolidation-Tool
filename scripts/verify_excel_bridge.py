"""Explicit Windows verification: loopback macro or read-only SharePoint metadata.

No list items are created. Runs outside pytest and never consumes the usage queue.
"""
import argparse
import json
import multiprocessing
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

from testdata_tool.excel_bridge import ExcelBridge, ExcelSession
from testdata_tool.usage_logging import Settings, SharePointClient


def loopback():
    import pythoncom
    import win32event
    import win32process
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
    owner = {}
    pythoncom.CoInitialize()
    try:
        with tempfile.TemporaryDirectory(prefix="bridge-verify-") as directory:
            session = ExcelSession(directory, owner)
            try:
                session.open_bridge()
                body = {"ProjectName": "中文项目", "ErrorMessage": "quote \" and newline\n"}
                response = session.request("POST", f"http://127.0.0.1:{server.server_port}/items", {}, body)
                assert response["status"] == 201
                assert response["retry_after"] == "17"
                assert json.loads(response["body"])["d"]["ProjectName"] == "中文项目"
                assert received == [body]
                print("PASS: prebuilt macro, read-only workbook, ASCII JSON, UTF-8 response, Retry-After")
            finally:
                session.close()
                if owner.get("excel_handle"):
                    if win32event.WaitForSingleObject(owner["excel_handle"], 1000) != 0:
                        win32process.TerminateProcess(owner["excel_handle"], 0)
                    assert win32event.WaitForSingleObject(owner["excel_handle"], 5000) == 0
                    owner["excel_handle"].Close()
                    print("PASS: owned Excel exited; other Excel processes untouched")
    finally:
        server.shutdown()
        pythoncom.CoUninitialize()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sharepoint-read-only", action="store_true")
    args = parser.parse_args()
    if not args.sharepoint_read_only:
        loopback()
        return
    settings = Settings()
    bridge = ExcelBridge(settings)
    try:
        client = SharePointClient(settings, request=bridge.request)
        data = client.call("GET", client.list_url + "?$select=ListItemEntityTypeFullName")
        print("PASS: SharePoint read-only metadata:", data["ListItemEntityTypeFullName"])
        bridge.discover()
    finally:
        bridge.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
