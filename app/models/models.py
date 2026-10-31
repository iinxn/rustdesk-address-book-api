"""All SQLAlchemy models. UUIDs stored as 36-char strings (sqlite+postgres portable)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    sessions: Mapped[list[Session]] = relationship(back_populates="user", cascade="all, delete-orphan")
    books: Mapped[list[AddressBook]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # RustDesk device id reported by the client in `/api/login` (`id`). It is
    # the same id the client registers on rendezvous, so a connection event can
    # be attributed to the last user who authenticated from that device.
    # Empty for browser/panel sessions and for rows created before 0006.
    device_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class AddressBook(Base):
    __tablename__ = "address_books"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128))
    type: Mapped[str] = mapped_column(String(16), default="personal")  # personal|shared
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    owner: Mapped[User] = relationship(back_populates="books")
    entries: Mapped[list[AddressBookEntry]] = relationship(back_populates="book", cascade="all, delete-orphan")
    tags: Mapped[list[Tag]] = relationship(back_populates="book", cascade="all, delete-orphan")
    permissions: Mapped[list[AddressBookPermission]] = relationship(back_populates="book", cascade="all, delete-orphan")


class AddressBookEntry(Base):
    __tablename__ = "address_book_entries"
    __table_args__ = (UniqueConstraint("address_book_id", "rustdesk_id", name="uq_book_rustdesk"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    address_book_id: Mapped[str] = mapped_column(ForeignKey("address_books.id", ondelete="CASCADE"), index=True)
    rustdesk_id: Mapped[str] = mapped_column(String(64), index=True)
    alias: Mapped[str] = mapped_column(String(128), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    username: Mapped[str] = mapped_column(String(128), default="")
    hostname: Mapped[str] = mapped_column(String(128), default="")
    platform: Mapped[str] = mapped_column(String(32), default="")
    hash_value: Mapped[str] = mapped_column(String(255), default="")
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    book: Mapped[AddressBook] = relationship(back_populates="entries")
    entry_tags: Mapped[list[EntryTag]] = relationship(back_populates="entry", cascade="all, delete-orphan")


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("address_book_id", "name", name="uq_book_tag"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    address_book_id: Mapped[str] = mapped_column(ForeignKey("address_books.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    color: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    book: Mapped[AddressBook] = relationship(back_populates="tags")
    entry_tags: Mapped[list[EntryTag]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class EntryTag(Base):
    __tablename__ = "entry_tags"

    entry_id: Mapped[str] = mapped_column(ForeignKey("address_book_entries.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    entry: Mapped[AddressBookEntry] = relationship(back_populates="entry_tags")
    tag: Mapped[Tag] = relationship(back_populates="entry_tags")


class AddressBookPermission(Base):
    __tablename__ = "address_book_permissions"
    __table_args__ = (UniqueConstraint("address_book_id", "user_id", name="uq_book_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    address_book_id: Mapped[str] = mapped_column(ForeignKey("address_books.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    rule: Mapped[int] = mapped_column(Integer, default=1)  # 1=read 2=readWrite 3=fullControl

    book: Mapped[AddressBook] = relationship(back_populates="permissions")


class DiscoveredDevice(Base):
    """Rendezvous evidence seen by the KX shim (independent from address books).

    A row means "this RustDesk ID connected to our shim at least once". It is
    NOT proof of identity and it is NOT a system-inventory record. Rows are
    kept after disconnect; `online` is maintained by the shim's connection
    lifecycle plus a staleness sweep.
    """
    __tablename__ = "discovered_devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    rustdesk_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    last_connected: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_disconnected: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_ip: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(16), default="")  # "tcp", "udp" or "tcp,udp"
    seen_count: Mapped[int] = mapped_column(Integer, default=0)
    online: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class DeviceInfo(Base):
    """System facts uploaded by the stock RustDesk client to /api/sysinfo.

    Only whitelisted, non-secret fields are persisted (never uuid, preset
    passwords or other option payloads). The raw client string is kept next to
    conservatively parsed values so the UI never invents data.
    """
    __tablename__ = "device_info"

    rustdesk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    hostname: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str] = mapped_column(String(128), default="")
    os: Mapped[str] = mapped_column(String(255), default="")
    os_name: Mapped[str] = mapped_column(String(128), default="")
    os_version: Mapped[str] = mapped_column(String(255), default="")
    cpu: Mapped[str] = mapped_column(String(255), default="")
    cpu_model: Mapped[str] = mapped_column(String(255), default="")
    cpu_freq_ghz: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_logical: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpu_physical: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory: Mapped[str] = mapped_column(String(64), default="")
    memory_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    version: Mapped[str] = mapped_column(String(32), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    collected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditEvent(Base):
    """Append-only audit/access history (see services/audit.py).

    Every field is deliberately bounded at write time: SQLite does not enforce
    `String(n)`, and the log must not become a place where a large request body
    or a secret accidentally survives. `details` is redacted JSON, capped at
    4 KiB. Rows are deleted only by the retention job; normal API code never
    updates or removes them.
    """
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_target", "target_type", "target_id"),
        Index("ix_audit_events_category_time", "category", "timestamp"),
        Index("ix_audit_events_type_time", "event_type", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    category: Mapped[str] = mapped_column(String(16), index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    actor_type: Mapped[str] = mapped_column(String(16), index=True)
    actor_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    actor_name: Mapped[str] = mapped_column(String(128), default="")
    source_ip: Mapped[str] = mapped_column(String(64), default="", index=True)
    destination: Mapped[str] = mapped_column(String(32), default="")
    http_method: Mapped[str] = mapped_column(String(8), default="")
    route: Mapped[str] = mapped_column(String(255), default="")
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[str] = mapped_column(String(128), default="")
    outcome: Mapped[str] = mapped_column(String(16), default="success", index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str] = mapped_column(String(36), default="", index=True)
    details: Mapped[str] = mapped_column(Text, default="{}")
