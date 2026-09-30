from pydantic import BaseModel


class AddressBookOut(BaseModel):
    id: str
    name: str
    type: str
    model_config = {"from_attributes": True}


class EntryIn(BaseModel):
    rustdesk_id: str
    alias: str = ""
    note: str = ""
    customer_id: str | None = None
    tags: list[str] = []
    password: str = ""


class EntryOut(BaseModel):
    id: str
    rustdesk_id: str
    alias: str = ""
    note: str = ""
    customer_id: str | None = None
    tags: list[str] = []
    model_config = {"from_attributes": True}


class TagIn(BaseModel):
    name: str
    color: int = 0


class TagOut(BaseModel):
    id: str
    name: str
    color: int = 0
    devices: int = 0
    model_config = {"from_attributes": True}


class CustomerIn(BaseModel):
    name: str
    note: str = ""


class CustomerOut(BaseModel):
    id: str
    name: str
    note: str = ""
    model_config = {"from_attributes": True}


class UserIn(BaseModel):
    username: str
    password: str
    is_admin: bool = False


class UserOut(BaseModel):
    id: str
    username: str
    is_admin: bool = False
    is_disabled: bool = False
    model_config = {"from_attributes": True}
