#!/usr/bin/env python3
"""Clear hbbs's per-IP registration limiter (ERR-022, SEC-029).

hbbs accepts RegisterPk only if the source IP has made <= 30 of them since its
last accepted one less than 60 s ago, and has registered <= 300 distinct IDs
within 24 h of its last accepted one (check_ip_blocker, same in 1.1.16 and
master). Many devices behind one address exhaust it, and new devices get
"ID doesn't exist" until hbbs restarts. hbbs's admin command `ib <ip> -` drops
one IP's counters.

hbbs takes admin commands only from loopback on its NAT-test port (21115), so
this must run inside the hbbs network namespace:
as the RustDesk Manager agent: a compose service with
`network_mode: "service:hbbs"` (WORKFLOW §7.1). One pass now:
  docker compose run --rm rustdesk-manager-agent --interval 0

Env (each has a matching flag, the flag wins):
  HBBS_UNBLOCK_INTERVAL  how often to clear: 0 = once and exit (default),
                         otherwise at least 60 s; seconds or with a unit:
                         3600, 90s, 30m, 1h, 12h
  HBBS_ADMIN_PORT        hbbs NAT-test/admin port (default 21115)
  CLEAR_ALL=1            clear every tracked IP, not only blocked ones
  DRY_RUN=1              only print, clear nothing

Standard library only, so it runs in any image with python3.
"""
import argparse
import os
import re
import socket
import sys
import time
from datetime import datetime, timezone

# Thresholds from hbbs check_ip_blocker: blocked when count > 30 / distinct > 300.
PER_MIN, PER_DAY = 30, 300
MIN_INTERVAL = 60  # hbbs releases the "in a row" counter after 60 s by itself
UNITS = {"": 1, "s": 1, "m": 60, "h": 3600}
LINE = re.compile(r"^(?P<ip>.+): (?P<n>\d+)/(?P<ns>\d+)s (?P<d>\d+)/(?P<ds>\d+)s$")


def log(msg: str, err: bool = False) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} hbbs-unblock: {msg}", file=sys.stderr if err else sys.stdout, flush=True)


def parse_interval(text: str) -> int:
    m = re.fullmatch(r"\s*(\d+)\s*([smh]?)\s*", text.lower())
    if not m:
        raise argparse.ArgumentTypeError(f"{text!r}: expected 0, 3600, 90s, 30m or 1h")
    sec = int(m[1]) * UNITS[m[2]]
    if 0 < sec < MIN_INTERVAL:
        raise argparse.ArgumentTypeError(f"{text!r}: 0 (once) or at least {MIN_INTERVAL}s")
    return sec


def cmd(port: int, text: str) -> str:
    # hbbs reads one chunk per connection, answers and closes.
    with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
        s.sendall(text.encode())
        out = b""
        while chunk := s.recv(65536):
            out += chunk
    return out.decode(errors="replace")


def run_once(port: int, clear_all: bool, dry_run: bool) -> None:
    """One pass. Raises OSError/ValueError if hbbs does not answer properly."""
    total = int(cmd(port, "ib").splitlines()[0])
    # `ib <n>` lists 10 entries starting at n (the first line is the total).
    entries = {}
    for start in range(0, total, 10):
        for line in cmd(port, f"ib {start}").splitlines()[1:]:
            m = LINE.match(line.strip())
            if m:
                entries[m["ip"]] = (int(m["n"]), int(m["ns"]), int(m["d"]), int(m["ds"]))
    if len(entries) < total:
        # The map can change between pages; what was missed is caught next pass.
        log(f"listed {len(entries)} of {total} tracked IPs", err=True)

    cleared = 0
    for ip, (n, ns, d, ds) in sorted(entries.items()):
        blocked = n > PER_MIN or d > PER_DAY
        if not (blocked or clear_all):
            continue
        log(f"{'blocked' if blocked else 'tracked'} {ip} registrations={n} (last {ns}s ago) "
            f"distinct_ids={d} (last {ds}s ago){' [dry-run]' if dry_run else ''}")
        if not dry_run:
            cmd(port, f"ib {ip} -")
            cleared += 1
    log(f"tracked={len(entries)} cleared={cleared}")


def main() -> int:
    env = os.environ.get
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=int(env("HBBS_ADMIN_PORT", "21115")),
                    help="hbbs NAT-test/admin port (default 21115)")
    ap.add_argument("--interval", type=parse_interval, default=env("HBBS_UNBLOCK_INTERVAL", "0"),
                    help="0 = run once (default); else >= 60s: 3600, 90s, 30m, 1h")
    ap.add_argument("--clear-all", action="store_true", default=env("CLEAR_ALL") == "1",
                    help="clear every tracked IP, not only blocked ones")
    ap.add_argument("--dry-run", action="store_true", default=env("DRY_RUN") == "1",
                    help="only print, clear nothing")
    a = ap.parse_args()

    if a.interval:
        log(f"started: every {a.interval}s, port {a.port}"
            f"{', clear-all' if a.clear_all else ''}{', dry-run' if a.dry_run else ''}")
    while True:
        try:
            run_once(a.port, a.clear_all, a.dry_run)
        except (OSError, ValueError, IndexError) as e:
            # Exit instead of retrying: with `restart: unless-stopped` Docker
            # restarts the agent, which then rejoins the namespace of a
            # restarted hbbs (a stale namespace has nothing on the port).
            log(f"hbbs admin port {a.port} did not answer: {e!r}", err=True)
            return 1
        if not a.interval:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
