"""Initial schema: users/sessions/address_books/entries/tags/entry_tags/customers/permissions."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("is_disabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("token", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "address_books",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(16), nullable=False, server_default="personal"),
        sa.Column("owner_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "customers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, index=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "address_book_entries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("address_book_id", sa.String(36), sa.ForeignKey("address_books.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rustdesk_id", sa.String(64), nullable=False, index=True),
        sa.Column("alias", sa.String(128), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("username", sa.String(128), nullable=False, server_default=""),
        sa.Column("hostname", sa.String(128), nullable=False, server_default=""),
        sa.Column("platform", sa.String(32), nullable=False, server_default=""),
        sa.Column("hash_value", sa.String(255), nullable=False, server_default=""),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("customer_id", sa.String(36), sa.ForeignKey("customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("address_book_id", "rustdesk_id", name="uq_book_rustdesk"),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("address_book_id", sa.String(36), sa.ForeignKey("address_books.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("color", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("address_book_id", "name", name="uq_book_tag"),
    )
    op.create_table(
        "entry_tags",
        sa.Column("entry_id", sa.String(36), sa.ForeignKey("address_book_entries.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.String(36), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "address_book_permissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("address_book_id", sa.String(36), sa.ForeignKey("address_books.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rule", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("address_book_id", "user_id", name="uq_book_user"),
    )


def downgrade() -> None:
    for t in ("address_book_permissions", "entry_tags", "tags", "address_book_entries", "customers", "address_books", "sessions", "users"):
        op.drop_table(t)
