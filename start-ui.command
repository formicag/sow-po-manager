#!/bin/bash
#
# SOW/PO Manager - Desktop Launcher for macOS
# Double-click this file to start the Flask UI
#

# Get the directory where this script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

# Clear the terminal
clear

echo "=========================================="
echo "  SOW/PO Document Management System"
echo "=========================================="
echo ""
echo "Starting Flask UI..."
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found. Running setup..."
    make setup
fi

# Activate virtual environment and start UI
source .venv/bin/activate
python3 ui/app.py

# Keep terminal open after exit
echo ""
echo "Flask UI has stopped."
echo "Press any key to close this window..."
read -n 1
