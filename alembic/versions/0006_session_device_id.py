"""Remember the RustDesk device id of a client session.

Additive migration: one nullable-free column with an empty-string default plus
an index. Existing sessions keep working and simply have `device_id = ''`;
nothing is rewritten. The column lets the audit log attribute a rendezvous
connection request to the last user who authenticated from that device.

Revision 0006 follows 0005, the current head at the time of writing.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("device_id", sa.String(64), nullable=False, server_default=""),
    )
    op.create_index("ix_sessions_device_id", "sessions", ["device_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_device_id", table_name="sessions")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("device_id")
