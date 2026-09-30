"""All SQLAlchemy models. UUIDs stored as 36-char strings (sqlite+postgres portable)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
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


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(128), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    entries: Mapped[list[AddressBookEntry]] = relationship(back_populates="customer")


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
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id", ondelete="SET NULL"), nullable=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    book: Mapped[AddressBook] = relationship(back_populates="entries")
    customer: Mapped[Customer | None] = relationship(back_populates="entries")
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
