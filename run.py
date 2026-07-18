#!/usr/bin/env python3
"""Unified entry point: starts FastAPI backend + Tkinter GUI in a single process.

The FastAPI server runs in a background thread, GUI runs in the main thread.
"""

import sys
import os
import signal
import threading
import time
import logging
from typing import Any

# Add vidapi to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from vidapi.main import create_app
from vidapi.gui.app import main as gui_main


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("vidapi.unified")


def run_server(server: uvicorn.Server):
    """Run uvicorn server in a background thread."""
    server.run()


def wait_for_server(url: str = "http://localhost:8000/health", timeout: float = 10.0) -> bool:
    """Wait for the FastAPI server to be ready."""
    import urllib.request
    import urllib.error
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionRefusedError, TimeoutError):
            time.sleep(0.3)
    return False


def main():
    print("Starting vidapi (backend + GUI)...")

    # ponytail: Ctrl+C cross-platform handling. The naive approach — install
    # a signal.signal(SIGINT, handler) that calls root.quit() — fails on
    # Windows because (1) the Tk Tcl/Tk mainloop is a blocking WaitEvent
    # call that never returns to the Python interpreter, so the queued
    # Python signal handler never runs, and (2) on Windows SIGINT fires on
    # a separate console-control thread, where calling any Tk API is
    # undefined (Tk is single-threaded by contract).
    # The Tk project's own workaround (Guido van Rossum, cpython mailing
    # list, 2001) is to install a `root.after(ms, poll)` heartbeat so the
    # mainloop periodically re-enters Python and can act on a flag set by
    # the signal handler. We do that here against a threading.Event so the
    # signal handler only touches thread-safe primitives.
    shutdown_event = threading.Event()
    server_holder: dict[str, uvicorn.Server | None] = {"server": None}
    tk_root_holder: dict[str, Any | None] = {"root": None}

    def _on_sigint(signum, frame):
        logger.info("Received SIGINT, shutting down...")
        shutdown_event.set()
        server = server_holder.get("server")
        if server is not None:
            server.should_exit = True

    signal.signal(signal.SIGINT, _on_sigint)

    app = create_app()
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
    )
    server = uvicorn.Server(config)
    server_holder["server"] = server

    # Start FastAPI server in background thread (non-daemon)
    server_thread = threading.Thread(target=run_server, args=(server,), name="FastAPI-Server")
    server_thread.start()

    # Wait for server to be ready
    print("Waiting for FastAPI server to start on http://localhost:8000 ...")
    if not wait_for_server():
        print("ERROR: FastAPI server failed to start within timeout")
        server.should_exit = True
        server_thread.join(timeout=5)
        sys.exit(1)

    print("FastAPI server ready. Starting GUI...")
    print()

    # Run GUI in main thread (blocking) — pass the root back to the SIGINT handler.
    # Install a 200ms heartbeat so the mainloop periodically re-enters Python
    # and can observe shutdown_event being set by the signal handler.
    import tkinter as tk
    root = tk.Tk()
    tk_root_holder["root"] = root

    def _sigint_heartbeat():
        if shutdown_event.is_set():
            try:
                root.quit()
            except RuntimeError:
                pass
            return
        root.after(200, _sigint_heartbeat)

    root.after(200, _sigint_heartbeat)

    try:
        gui_main(root=root)
    finally:
        tk_root_holder["root"] = None

    # GUI exited — gracefully stop FastAPI server and wait for thread
    print("GUI exited. Shutting down FastAPI server...")
    server.should_exit = True
    server_thread.join(timeout=10)
    if server_thread.is_alive():
        print("WARNING: FastAPI server thread did not exit cleanly within timeout")
        sys.exit(1)
    print("FastAPI server shut down gracefully.")


if __name__ == "__main__":
    main()