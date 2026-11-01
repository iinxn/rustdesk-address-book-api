"""Request bodies of the internal panel API (`/api/v1`)."""
from pydantic import BaseModel, Field

TAG_COLOR_MAX = 0xFFFFFFFF  # ARGB, unsigned 32-bit (same bound as services.ab)


class EntryIn(BaseModel):
    rustdesk_id: str
    alias: str = ""
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    password: str = ""


class TagIn(BaseModel):
    name: str
    color: int = Field(default=0, ge=0, le=TAG_COLOR_MAX)


class UserIn(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    display_name: str = ""


class MeIn(BaseModel):
    display_name: str = ""


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
