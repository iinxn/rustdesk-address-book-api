"""Central settings. Env-overridable, no secrets in git.

All filesystem paths are anchored at the project root (parent of `app/`),
so the app behaves identically regardless of the current working directory.
"""
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "RustDesk API"
    # Dev escape hatch: when "1", insecure secret defaults are tolerated.
    # Production MUST run with DEV_MODE unset/0 and real secrets.
    dev_mode: str = "0"
    # Empty = default data/base.db. Absolute path, never CWD-relative.
    database_url: str = ""
    session_days: int = 30
    # REQUIRED in prod (fail fast). `python -m app.cli gen-key` to create.
    device_secret: str = ""
    # REQUIRED in prod (fail fast). Random 32+ chars.
    web_secret: str = ""
    max_peer_one_ab: int = 0  # 0 = unlimited
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000
    # Shim (KX rendezvous proxy). Disabled by default; enable explicitly.
    shim_enabled: str = "0"
    shim_listen: str = "127.0.0.1:21116"
    # Where the REAL hbbs rendezvous listens. NOT hbbr:21117 (relay speaks a
    # different protocol). Same box: move hbbs with `-p 21166`, then upstream
    # is 127.0.0.1:21166. Separate box: HBBS_IP:21116 (hbbs keeps its port).
    shim_upstream: str = "127.0.0.1:21166"
    # Absolute path to hbbs id_ed25519 (private). REQUIRED when shim enabled.
    shim_id_key: str = ""
    shim_max_conns: int = 200
    shim_per_ip_per_min: int = 30
    # UDP rendezvous has its own budget: every client socket is one relay
    # session (one upstream socket), and the stock client re-registers every
    # ~12 s, so ~800 devices need ~800 live sessions. Many of them may sit
    # behind one NAT, hence a per-IP *new session* rate far above the TCP one.
    shim_udp_max_sessions: int = 2048
    shim_udp_per_ip_per_min: int = 600
    # Temporary diagnostics: log decrypted message types + target IDs
    # (never tokens/keys). Off by default.
    shim_diag_msgtypes: str = "0"
    # Request hardening.
    max_body_bytes: int = 5 * 1024 * 1024
    # Applies to both `/api/login` and `/panel/login` (separate buckets).
    login_per_minute_per_ip: int = 20
    # bcrypt runs in a small dedicated pool, never on the event loop. Logins
    # beyond `password_hash_queue` in flight are refused with 429 instead of
    # queueing: a password-guessing burst must not starve heartbeats.
    password_hash_workers: int = 2
    password_hash_queue: int = 8
    # Panel cookie `Secure` flag: "auto" sets it when the request arrived over
    # HTTPS (directly or via a reverse proxy that sends X-Forwarded-Proto),
    # "1" always, "0" never (plain-HTTP panel over a trusted VPN only).
    session_cookie_secure: str = "auto"
    # Heartbeat: the stock client sends one every ~15s (4/min). Each device gets
    # its own bucket keyed by (id, client IP); the per-IP value is an aggregate
    # flood cap that must cover every device behind one NAT: 800 devices at
    # 15s ≈ 3200/min. Keep the aggregate well above that while remaining finite.
    heartbeat_per_minute_per_device: int = 20
    heartbeat_per_minute_per_ip: int = 6000
    # /api/sysinfo is unauthenticated by design (stock clients send no auth).
    # The client uploads at startup and after a Windows user logs in, so a
    # first boot of 800 devices behind one NAT is one burst of ≤800 requests.
    # Duplicates are acknowledged without a DB write (see
    # services/device_info.save_sysinfo), so this cap only has to absorb that
    # bootstrap burst while remaining a finite flood guard.
    sysinfo_per_minute_per_ip: int = 6000
    # Shim discovery registry (shim -> SQLite). On by default. The shim still
    # applies its own per-IP limits before publishing anything.
    discovery_enabled: str = "1"
    discovery_online_sec: int = 180
    # Comma-separated IPs of reverse proxies whose `X-Forwarded-For` may be
    # trusted for per-IP rate-limit keying (e.g. "127.0.0.1" for Caddy on
    # loopback). Empty (default) = never trust XFF: the direct peer address is
    # always the key, so a spoofed header cannot dodge or poison the buckets.
    trusted_proxies: str = ""
    # Expose FastAPI's /docs, /redoc and /openapi.json. Off by default
    # (production); DEV_MODE=1 turns them on automatically for local work.
    expose_docs: str = "0"
    # --- Audit log (persistent SQLite history, see services/audit.py) ---
    # "0" disables both access rows and explicit business events (technical
    # logs keep working). The API then returns an empty log; it never falls
    # back to in-memory history.
    audit_enabled: str = "1"
    # Kept as a string so an invalid env value is logged and clamped instead of
    # crashing the process at import time. Effective range: 30..90 days.
    audit_retention_days: str = "90"
    # Daily by default. The first run happens shortly after startup so a
    # long-running process cannot skip retention after a restart.
    audit_cleanup_interval_sec: int = 86400
    audit_cleanup_initial_delay_sec: int = 60
    # Requests slower than this are logged as a technical warning. 0 = off.
    audit_slow_request_ms: int = 2000
    # Repeated reads of the same resource (panel polling) are collapsed into
    # one access row per actor/route/target within this window.
    audit_read_dedupe_sec: int = 300

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            url = self.database_url
            # Never allow CWD-relative sqlite paths (stray DBs); anchor them.
            if url.startswith("sqlite:///") and not url.startswith("sqlite:////"):
                rel = url.split("sqlite:///", 1)[1]
                if "://" not in rel:  # not a :memory: or absolute already
                    return f"sqlite:///{DATA_DIR / Path(rel).name}"
            return url
        return f"sqlite:///{DATA_DIR / 'base.db'}"

    @property
    def is_dev(self) -> bool:
        return self.dev_mode == "1"

    @property
    def trusted_proxies_set(self) -> set[str]:
        return {p.strip() for p in self.trusted_proxies.split(",") if p.strip()}

    @property
    def docs_enabled(self) -> bool:
        return self.is_dev or self.expose_docs == "1"

    @property
    def audit_enabled_flag(self) -> bool:
        return self.audit_enabled == "1"

    def require_secret(self, name: str, value: str, hint: str) -> None:
        if value or self.is_dev:
            return
        raise SystemExit(f"FATAL: {name} is not set. {hint} "
                         f"(or set DEV_MODE=1 for local development only)")


def load_settings() -> Settings:
    s = Settings()
    s.require_secret("DEVICE_SECRET", s.device_secret,
                     "Generate one with: python -m app.cli gen-key")
    s.require_secret("WEB_SECRET", s.web_secret,
                     "Set any random 32+ char string")
    if s.shim_enabled == "1":
        if not s.shim_id_key or not os.path.isfile(s.shim_id_key):
            raise SystemExit("FATAL: SHIM_ID_KEY must point at hbbs id_ed25519 "
                             "when SHIM_ENABLED=1")
    return s


settings = load_settings()
