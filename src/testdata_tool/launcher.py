from __future__ import annotations

import socket
import os
import sys
import threading
import time
from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _ui_path() -> Path:
    candidate = Path(__file__).with_name("ui.py")
    if candidate.exists():
        return candidate
    root = Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return root / "testdata_tool" / "ui.py"


def _start_idle_monitor(grace_seconds: int = 120, idle_seconds: int = 30) -> None:
    def monitor() -> None:
        time.sleep(grace_seconds)
        seen_session = False
        idle_started: float | None = None
        while True:
            time.sleep(2)
            try:
                from streamlit.runtime import Runtime

                runtime = Runtime.instance()
                sessions = runtime._session_mgr.list_active_sessions()  # noqa: SLF001
            except Exception:
                continue
            if sessions:
                seen_session = True
                idle_started = None
            elif seen_session:
                idle_started = idle_started or time.monotonic()
                if time.monotonic() - idle_started >= idle_seconds:
                    os._exit(0)

    threading.Thread(target=monitor, name="idle-shutdown", daemon=True).start()


def _apply_bootstrap_arguments(arguments: list[str]) -> None:
    for index, argument in enumerate(arguments):
        if argument.startswith("--config-root="):
            os.environ["TESTDATA_TOOL_CONFIG_ROOT"] = argument.split("=", 1)[1]
            return
        if argument == "--config-root" and index + 1 < len(arguments):
            os.environ["TESTDATA_TOOL_CONFIG_ROOT"] = arguments[index + 1]
            return


def main() -> None:
    from multiprocessing import freeze_support
    freeze_support()
    from streamlit.web import cli as streamlit_cli
    from testdata_tool.config import load_config

    _apply_bootstrap_arguments(sys.argv[1:])
    port = _free_port()
    lifecycle = load_config(managed=False).app.get("lifecycle", {})
    if lifecycle.get("auto_shutdown_on_idle", True):
        _start_idle_monitor(
            int(lifecycle.get("idle_shutdown_startup_grace_seconds", 120)),
            int(lifecycle.get("idle_shutdown_seconds", 30)),
        )
    sys.argv = [
        "streamlit",
        "run",
        str(_ui_path()),
        "--server.address=127.0.0.1",
        f"--server.port={port}",
        "--server.headless=false",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
        "--global.developmentMode=false",
        "--client.toolbarMode=minimal",
        "--client.showErrorDetails=none",
        "--client.showErrorLinks=false",
    ]
    raise SystemExit(streamlit_cli.main())


if __name__ == "__main__":
    main()
