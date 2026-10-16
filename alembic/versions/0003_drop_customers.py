"""Remove customers feature: drop address_book_entries.customer_id, drop customers table."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("address_book_entries") as batch:
        batch.drop_column("customer_id")
    op.drop_table("customers")


def downgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, index=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("address_book_entries") as batch:
        batch.add_column(sa.Column("customer_id", sa.String(36),
                                   sa.ForeignKey("customers.id", ondelete="SET NULL"),
                                   nullable=True))
