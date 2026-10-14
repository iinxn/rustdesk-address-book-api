#!/usr/bin/env bash
# Single-command startup: ./scripts/start.sh
# Foreground process; Ctrl+C / SIGTERM stops everything gracefully.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
  echo "ERROR: .venv missing. Create it and install deps first (see README.md)." >&2
  exit 1
fi
echo $$ > data/app.pid
trap 'rm -f data/app.pid' EXIT
exec .venv/bin/python -m app "$@"
