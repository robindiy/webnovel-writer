#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="$REPO_ROOT/.venv"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python executable not found: $PYTHON_BIN" >&2
  exit 1
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install -r "$REPO_ROOT/requirements.txt"
