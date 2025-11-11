#!/bin/bash

# launch-ui.sh - Launch SOW/PO Manager UI
# This script activates the virtual environment and starts the Flask UI

set -e

# Get the project root directory (parent of scripts/)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "=========================================="
echo "SOW/PO Document Management System"
echo "=========================================="
echo ""
echo "Project root: $PROJECT_ROOT"
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "⚠️  Virtual environment not found. Creating it now..."
    echo ""
    make setup
    echo ""
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source .venv/bin/activate

# Check if Flask is installed
if ! python -c "import flask" 2>/dev/null; then
    echo "⚠️  Flask not installed. Installing dependencies..."
    echo ""
    pip install -r requirements.txt
    echo ""
fi

# Start the Flask UI
echo "🚀 Starting Flask UI..."
echo ""
echo "The browser will open automatically."
echo "Press Ctrl+C to stop the server."
echo ""

# Get port that will be used (Flask app finds free port)
python ui/app.py &
FLASK_PID=$!

# Wait a moment for Flask to start and find a port
sleep 3

# Try to detect the port from Flask logs and open browser
# We'll open on port 5000 by default, but the Flask app will handle port selection
# The app.py has smart port detection, so this should work
PORT=5000
while [ $PORT -lt 5100 ]; do
    if curl -s http://localhost:$PORT/health > /dev/null 2>&1; then
        echo "✅ Server is running on port $PORT"
        open "http://localhost:$PORT"
        break
    fi
    PORT=$((PORT + 1))
done

# Wait for Flask process
wait $FLASK_PID
