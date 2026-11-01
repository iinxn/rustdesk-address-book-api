"""Request bodies of the RustDesk client API (`/api/*`).

Only `/api/login` has a typed body; the address-book routes accept the
client's free-form JSON and validate it field by field (see api/rustdesk.py).
"""
from typing import Any

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str = ""
    password: str = ""
    id: str = ""
    uuid: str = ""
    autoLogin: bool = False
    type: str = "account"
    deviceInfo: dict[str, Any] = Field(default_factory=dict)
    verificationCode: str = ""
    tfaCode: str = ""
    secret: str = ""
