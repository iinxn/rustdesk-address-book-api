from pydantic import BaseModel, Field


class AddressBookOut(BaseModel):
    id: str
    name: str
    type: str
    model_config = {"from_attributes": True}


class EntryIn(BaseModel):
    rustdesk_id: str
    alias: str = ""
    note: str = ""
    tags: list[str] = []
    password: str = ""


class EntryOut(BaseModel):
    id: str
    rustdesk_id: str
    alias: str = ""
    note: str = ""
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


class UserIn(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    display_name: str = ""


class MeIn(BaseModel):
    display_name: str = ""


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str = ""
    is_admin: bool = False
    is_disabled: bool = False
    model_config = {"from_attributes": True}


class BulkIdsIn(BaseModel):
    ids: list[str] = Field(default_factory=list)


class BulkTagsIn(BaseModel):
    ids: list[str] = Field(default_factory=list)
    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class DiscoveredAddIn(BaseModel):
    book_id: str
    alias: str = ""
    note: str = ""
    tags: list[str] = Field(default_factory=list)
