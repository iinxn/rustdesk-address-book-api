from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str = ""
    password: str = ""
    id: str = ""
    uuid: str = ""
    autoLogin: bool = False
    type: str = "account"
    deviceInfo: dict = {}
    verificationCode: str = ""
    tfaCode: str = ""
    secret: str = ""


class UserOut(BaseModel):
    name: str
    display_name: str = ""
    avatar: str = ""
    email: str = ""
    note: str = ""
    status: int = 1
    is_admin: bool = False


class LoginOut(BaseModel):
    access_token: str
    type: str = "access_token"
    user: UserOut


class PeerOut(BaseModel):
    id: str
    username: str = ""
    hostname: str = ""
    platform: str = ""
    alias: str = ""
    tags: list[str] = []
    hash: str = ""
    password: str = ""
    note: str = ""


class PeersPage(BaseModel):
    total: int
    data: list[PeerOut]


class TagOut(BaseModel):
    name: str
    color: int = 0


class SharedProfileOut(BaseModel):
    guid: str
    name: str
    owner: str = ""
    note: str = ""
    info: dict | None = None
    rule: int = 1


class SharedProfilesPage(BaseModel):
    total: int
    data: list[SharedProfileOut]


class ErrorOut(BaseModel):
    error: str
