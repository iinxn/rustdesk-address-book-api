#!/usr/bin/env bash
# Stop a background-started app (./scripts/start.sh &). Foreground Ctrl+C needs nothing.
#
# SEC-010: the old fallback pattern ("rustdesk-manager/.venv/...") never
# matched this repo, and a stale data/app.pid made the script report success
# without stopping anything. Now we (1) trust the pidfile only if the pid is
# alive AND still looks like this project's `python -m app`, (2) fall back to
# matching our process by working directory, and (3) verify it is really gone.
set -euo pipefail
cd "$(dirname "$0")/.."

PIDFILE=data/app.pid

alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

# True only if `pid` runs `python -m app` from THIS project root.
is_our_pid() {
  local pid="$1" cwd cmd
  cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  [ "$cwd" = "$PWD" ] || return 1
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  case "$cmd" in
    *python*"-m app "* | *python*"-m app") return 0 ;;
    *) return 1 ;;
  esac
}

# PIDs of `python -m app` started from THIS project root.
app_pids() {
  local pid
  for pid in $(pgrep -f 'python -m app( |$)' 2>/dev/null || true); do
    is_our_pid "$pid" && echo "$pid"
  done
}

stop_pid() {
  local pid="$1"
  kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 15); do
    alive "$pid" || return 0
    sleep 1
  done
  echo "timeout, SIGKILL pid $pid"
  kill -KILL "$pid" 2>/dev/null || true
}

stopped=0

# 1) Pidfile path (preferred): use it only if the pid is really ours.
if [ -f "$PIDFILE" ]; then
  pid="$(cat "$PIDFILE" 2>/dev/null || true)"
  if [ -n "$pid" ] && alive "$pid" && is_our_pid "$pid"; then
    stop_pid "$pid"
    stopped=1
  else
    echo "stale/foreign $PIDFILE (pid ${pid:-?}); ignoring"
  fi
  rm -f "$PIDFILE"
fi

# 2) Fallback: find our own process by cwd, for starts without the pidfile.
if [ "$stopped" -eq 0 ]; then
  for pid in $(app_pids); do
    stop_pid "$pid"
    stopped=1
  done
fi

# 3) Verify nothing of ours is left.
left="$(app_pids || true)"
if [ -n "$left" ]; then
  echo "still running after TERM, SIGKILL: $left"
  for pid in $left; do
    kill -KILL "$pid" 2>/dev/null || true
  done
fi

if [ -n "$(app_pids || true)" ]; then
  echo "ERROR: app process still running" >&2
  exit 1
fi

if [ "$stopped" -eq 0 ]; then
  echo "nothing running"
else
  echo stopped
fi
