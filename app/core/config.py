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

    app_name: str = "RustDesk Manager"
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
    # Temporary diagnostics: log decrypted message types + target IDs
    # (never tokens/keys). Off by default.
    shim_diag_msgtypes: str = "0"
    # Request hardening.
    max_body_bytes: int = 5 * 1024 * 1024
    login_per_minute_per_ip: int = 20
    heartbeat_per_minute_per_ip: int = 300
    # Comma-separated IPs of reverse proxies whose `X-Forwarded-For` may be
    # trusted for per-IP rate-limit keying (e.g. "127.0.0.1" for Caddy on
    # loopback). Empty (default) = never trust XFF: the direct peer address is
    # always the key, so a spoofed header cannot dodge or poison the buckets.
    trusted_proxies: str = ""
    # Expose FastAPI's /docs, /redoc and /openapi.json. Off by default
    # (production); DEV_MODE=1 turns them on automatically for local work.
    expose_docs: str = "0"

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
