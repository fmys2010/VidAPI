#!/usr/bin/env python3
"""Run vidapi GUI application.

This script starts the desktop GUI for vidapi.
Requirements: tkinter (built-in), requests

Usage:
    python run_gui.py

Note: The FastAPI server must be running at http://localhost:8000
"""

import sys
import os

# Add vidapi to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vidapi.gui.app import main

if __name__ == "__main__":
    print("Starting vidapi GUI...")
    print("Note: Make sure the FastAPI server is running at http://localhost:8000")
    print("Start server with: ./run.sh")
    print()
    main()
