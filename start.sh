#!/usr/bin/env bash
# Linux / Termux entrypoint. Use SGS_PYTHON to select a specific interpreter.
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"
python_bin="${SGS_PYTHON:-python3}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
    printf 'Python executable not found: %s\n' "$python_bin" >&2
    exit 1
fi
export PYTHONIOENCODING=utf-8
if [[ "${1:-}" == "--check" ]]; then
    "$python_bin" -c 'import httpx, websockets; print("DEPENDENCIES_OK")'
    exit 0
fi
if [[ "$#" -ne 0 ]]; then
    printf 'Usage: %s [--check]\n' "$0" >&2
    exit 2
fi
exec "$python_bin" -u game_server.py
