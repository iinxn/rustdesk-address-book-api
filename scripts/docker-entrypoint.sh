#!/usr/bin/env bash
# Docker entrypoint: fills missing secrets once, persists them in the data
# volume (/app/data/.secrets.env) so restarts reuse the SAME values.
# Rotating DEVICE_SECRET would orphan encrypted device passwords and rotating
# WEB_SECRET would log out panel users — hence persistence, not regeneration.
# Explicitly provided values always win; only empty or CHANGEME* placeholders
# trigger auto-generation. Never prints secret values (only which key + source).
set -euo pipefail

SECRETS_FILE="/app/data/.secrets.env"
PY="$(command -v python || command -v python3)"

need_gen() {  # need_gen VAR -> 0/1 ; true when empty or CHANGEME placeholder
  local v="${!1:-}"
  [ -z "$v" ] && return 0
  case "$v" in CHANGEME*) return 0 ;; *) return 1 ;; esac
}

if need_gen DEVICE_SECRET || need_gen WEB_SECRET; then
  mkdir -p /app/data
  # Adopt previously generated values WITHOUT clobbering explicitly provided
  # ones (explicit env always wins over the saved file).
  if [ -f "$SECRETS_FILE" ]; then
    # NB: parse with expansion, NOT `IFS='=' read` — read strips a trailing
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
  fi
  NEW_FILE=0
  if need_gen DEVICE_SECRET; then
    DEVICE_SECRET="$("$PY" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
    export DEVICE_SECRET
    echo "entrypoint: generated DEVICE_SECRET (persisting)"
    NEW_FILE=1
  fi
  if need_gen WEB_SECRET; then
    WEB_SECRET="$("$PY" -c 'import secrets; print(secrets.token_hex(32))')"
    export WEB_SECRET
    echo "entrypoint: generated WEB_SECRET (persisting)"
    NEW_FILE=1
  fi
  if [ "$NEW_FILE" = 1 ]; then
    if ! { printf 'DEVICE_SECRET=%s\nWEB_SECRET=%s\n' "$DEVICE_SECRET" "$WEB_SECRET" > "$SECRETS_FILE" \
           && chmod 600 "$SECRETS_FILE"; }; then
      echo "entrypoint: WARNING: cannot persist $SECRETS_FILE secrets will be EPHEMERAL (passwords/sessions lost on restart)" >&2
    else
      echo "entrypoint: secrets saved to $SECRETS_FILE (mode 600)"
    fi
  fi
fi

# Fills for THIS process only when operator set nothing at all and no saved
# file exists are handled above; app fail-fast (DEV_MODE=0) still applies if
# generation somehow produced empty values.
exec "$@"
