#!/bin/bash
# vidapi run script

set -e

echo "=== vidapi startup ==="

# Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Run the server
echo "Starting vidapi server on http://0.0.0.0:8000"
echo "Web UI: http://0.0.0.0:8000 or http://0.0.0.0:8000/ui"
echo "Desktop GUI: python run_gui.py (requires FastAPI server running)"
echo "API docs: http://0.0.0.0:8000/docs"
echo "ReDoc: http://0.0.0.0:8000/redoc"
echo "Health: http://0.0.0.0:8000/health"
echo ""
echo "Press Ctrl+C to stop"
echo ""

uvicorn vidapi.main:app --host 0.0.0.0 --port 8000 --reload