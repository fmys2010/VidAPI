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

# Run the unified app (backend + GUI)
echo "Starting vidapi (backend + GUI)..."
echo "API server: http://0.0.0.0:8000"
echo "API docs: http://0.0.0.0:8000/docs"
echo "Web UI: http://0.0.0.0:8000/ui"
echo ""
echo "Press Ctrl+C to stop"
echo ""

python run.py