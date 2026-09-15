#!/usr/bin/env bash
# One-command start for prototype A from Git Bash:  ./start.sh [port]
# Builds the client once (client/dist), then serves everything from FastAPI at http://127.0.0.1:8765
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8765}"
PY="$HERE/.venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then
  echo "creating project-local venv (system-site-packages) and installing fastapi/uvicorn"
  "/c/ProgramData/anaconda3/python.exe" -m venv --system-site-packages "$HERE/.venv"
  "$PY" -m pip install --quiet fastapi "uvicorn[standard]"
fi
if [ ! -d "$HERE/client/node_modules" ]; then (cd "$HERE/client" && npm install --no-audit --no-fund); fi
if [ ! -f "$HERE/client/dist/index.html" ]; then (cd "$HERE/client" && npm run build); fi
exec "$PY" "$HERE/run_server.py" --port "$PORT"
