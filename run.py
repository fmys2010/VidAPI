#!/usr/bin/env python3
"""Unified entry point: starts FastAPI backend + Tkinter GUI in a single process.

The FastAPI server runs in a background thread, GUI runs in the main thread.
"""

import sys
import os
import threading
import time
import logging

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


def run_server():
    """Run uvicorn server in a background thread."""
    app = create_app()
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,  # disable reload in threaded mode
    )
    server = uvicorn.Server(config)
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

    # Start FastAPI server in background thread
    server_thread = threading.Thread(target=run_server, daemon=True, name="FastAPI-Server")
    server_thread.start()

    # Wait for server to be ready
    print("Waiting for FastAPI server to start on http://localhost:8000 ...")
    if not wait_for_server():
        print("ERROR: FastAPI server failed to start within timeout")
        sys.exit(1)

    print("FastAPI server ready. Starting GUI...")
    print()

    # Run GUI in main thread (blocking)
    gui_main()


if __name__ == "__main__":
    main()