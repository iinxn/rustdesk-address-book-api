"""Authenticated encryption for device passwords (Fernet = AES-CBC+HMAC)."""
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

log = logging.getLogger(__name__)
_fernet: Fernet | None = None


def _get() -> Fernet:
    global _fernet
    if _fernet is None:
        if settings.device_secret:
            _fernet = Fernet(settings.device_secret.encode())
        else:
            log.warning("DEVICE_SECRET empty, using ephemeral key (dev only)")
            _fernet = Fernet(Fernet.generate_key())
    return _fernet


def encrypt_password(plain: str) -> str:
    return _get().encrypt(plain.encode()).decode()


def decrypt_password(token: str) -> str:
    try:
        return _get().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


def reset_for_tests() -> None:
    global _fernet
    _fernet = None
