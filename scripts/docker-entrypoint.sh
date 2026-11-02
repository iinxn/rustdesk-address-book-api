#!/usr/bin/env bash
# Docker entrypoint: fills missing secrets once, persists them in the data
# volume (/app/data/.secrets.env) so restarts reuse the SAME values, then
# execs the command (default: python -m app).
#
# Rotating DEVICE_SECRET would orphan encrypted device passwords and rotating
# WEB_SECRET would log out panel users - hence persistence, not regeneration.
# Explicitly provided values always win; only empty or CHANGEME* placeholders
# trigger auto-generation. Never prints secret values (only which key + source).
set -euo pipefail

DATA_DIR="/app/data"
SECRETS_FILE="$DATA_DIR/.secrets.env"
# Files created here (secrets, and the SQLite DB created later by the app)
# are private to the service user.
umask 077

if [ ! -d "$DATA_DIR" ] || [ ! -w "$DATA_DIR" ]; then
  echo "entrypoint: ERROR: $DATA_DIR is not writable by uid $(id -u) gid $(id -g)." >&2
  echo "entrypoint: fix the mounted directory on the host: chown -R $(id -u):$(id -g) <data-dir>," >&2
  echo "entrypoint: or run the container as the owner of that directory (compose: user: \"UID:GID\")." >&2
  exit 1
fi

need_gen() {  # need_gen VAR -> 0/1 ; true when empty or CHANGEME placeholder
  local v="${!1:-}"
  [ -z "$v" ] && return 0
  case "$v" in CHANGEME*) return 0 ;; *) return 1 ;; esac
}

if need_gen DEVICE_SECRET || need_gen WEB_SECRET; then
  # Adopt previously generated values WITHOUT clobbering explicitly provided
  # ones (explicit env always wins over the saved file).
  if [ -f "$SECRETS_FILE" ]; then
    # An older file may be group/world readable (SEC-002); tighten it if ours.
    chmod 600 "$SECRETS_FILE" 2>/dev/null || true
    # NB: parse with expansion, NOT `IFS='=' read` - read strips a trailing
    # "=" (Fernet keys end with padding) and would corrupt the value.
    while IFS= read -r line || [ -n "$line" ]; do
      k="${line%%=*}"; v="${line#*=}"
      if [ "$k" = "DEVICE_SECRET" ] && need_gen DEVICE_SECRET && [ -n "$v" ]; then
        DEVICE_SECRET="$v"
      fi
      if [ "$k" = "WEB_SECRET" ] && need_gen WEB_SECRET && [ -n "$v" ]; then
        WEB_SECRET="$v"
      fi
    done < "$SECRETS_FILE"
    export DEVICE_SECRET WEB_SECRET
    echo "entrypoint: using secrets saved in $SECRETS_FILE"
  fi
  NEW_FILE=0
  if need_gen DEVICE_SECRET; then
    DEVICE_SECRET="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    export DEVICE_SECRET
    echo "entrypoint: generated DEVICE_SECRET (persisting)"
    NEW_FILE=1
  fi
  if need_gen WEB_SECRET; then
    WEB_SECRET="$(python -c 'import secrets; print(secrets.token_hex(32))')"
    export WEB_SECRET
    echo "entrypoint: generated WEB_SECRET (persisting)"
    NEW_FILE=1
  fi
  if [ "$NEW_FILE" = 1 ]; then
    # Written to a temp file and renamed: a crash cannot leave a half file.
    tmp="$SECRETS_FILE.tmp.$$"
    if printf 'DEVICE_SECRET=%s\nWEB_SECRET=%s\n' "$DEVICE_SECRET" "$WEB_SECRET" > "$tmp" \
       && chmod 600 "$tmp" && mv -f "$tmp" "$SECRETS_FILE"; then
      echo "entrypoint: secrets saved to $SECRETS_FILE (mode 600)"
    else
      rm -f "$tmp"
      echo "entrypoint: ERROR: cannot write $SECRETS_FILE; refusing to start with secrets that would be lost on restart" >&2
      exit 1
    fi
  fi
fi

exec "$@"
