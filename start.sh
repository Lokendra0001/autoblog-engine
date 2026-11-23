#!/usr/bin/env bash
set -e

PORT="${PORT:-8085}"
CLIENT="${CLIENT:-bhandari}"

# Use virtualenv python if available, else python3
if [ -f "./venv/bin/python" ]; then
    PYTHON="./venv/bin/python"
else
    PYTHON="python3"
fi

echo "=================================================="
echo " Starting AutoBlog Engine Web Dashboard"
echo " Client : $CLIENT"
echo " URL    : http://127.0.0.1:$PORT"
echo " (Press Ctrl+C to stop)"
echo "=================================================="

exec "$PYTHON" cli.py serve "$CLIENT" --port "$PORT" --reload
