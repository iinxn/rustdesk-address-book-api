#!/usr/bin/env bash
# Stop a background-started app (./scripts/start.sh &). Foreground Ctrl+C needs nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f data/app.pid ]; then
  echo "no data/app.pid (app not started via start.sh &?)"
  pkill -f "rustdesk-manager/.venv/bin/python -m app" && echo stopped || echo "nothing running"
  exit 0
fi
kill -TERM "$(cat data/app.pid)"
for _ in $(seq 1 15); do
  kill -0 "$(cat data/app.pid)" 2>/dev/null || break
  sleep 1
done
kill -0 "$(cat data/app.pid)" 2>/dev/null && { echo "timeout, SIGKILL"; kill -KILL "$(cat data/app.pid)"; }
rm -f data/app.pid
echo stopped
