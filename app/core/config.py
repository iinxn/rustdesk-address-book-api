"""Central settings. Env-overridable, no secrets in git."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "RustDesk AB Backend (MVP)"
    # sqlite fallback for environments without postgres (this Debian box has
    # no docker/sudo); production uses postgres via docker-compose.
    database_url: str = "sqlite:///./dev.db"
    # Opaque-token sessions; expiry 0 = never.
    session_days: int = 30
    # Web panel cookie secret (dev default, override in prod).
    web_secret: str = "dev-insecure-web-secret-change-me"
    # Fernet key for device password_encrypted. Generated via `cli gen-key`.
    # If empty, an ephemeral key is used (passwords lost on restart, dev only).
    device_secret: str = ""
    max_peer_one_ab: int = 0  # 0 = unlimited


settings = Settings()
