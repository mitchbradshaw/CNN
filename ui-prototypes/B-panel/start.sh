#!/usr/bin/env bash
# One-command start for prototype B from Git Bash:  ./start.sh [port]   (serves http://127.0.0.1:8766)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "/c/ProgramData/anaconda3/python.exe" "$HERE/run_app.py" --port "${1:-8766}"
