"""Migration 0002: presence support (last_seen on entries)."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("address_book_entries", sa.Column("last_seen", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("address_book_entries", "last_seen")
