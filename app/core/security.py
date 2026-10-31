"""Password hashing (bcrypt) + opaque access tokens."""
import secrets

import bcrypt

# bcrypt only uses the first 72 bytes; bcrypt>=5 raises on longer input.
PASSWORD_MAX_BYTES = 72


def password_error(password) -> str | None:
    """Policy for a password being *set*; None means acceptable."""
    if not isinstance(password, str):
        return "password must be a string"
    if not password.strip():
        return "password is required"
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        return f"password too long (max {PASSWORD_MAX_BYTES} bytes)"
    return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)
