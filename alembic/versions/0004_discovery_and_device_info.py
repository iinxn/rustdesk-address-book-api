"""Add shim discovery registry and client-uploaded device info.

Safe, additive migration: no existing table/column is touched. Both tables are
optional caches; dropping them loses discovery history and the last uploaded
system report, but never address books, peers, tags or users.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "discovered_devices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rustdesk_id", sa.String(64), nullable=False),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("last_connected", sa.DateTime(), nullable=True),
        sa.Column("last_disconnected", sa.DateTime(), nullable=True),
        sa.Column("last_ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("source", sa.String(16), nullable=False, server_default=""),
        sa.Column("seen_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("online", sa.Boolean(), nullable=False, server_default="0"),
        sa.UniqueConstraint("rustdesk_id", name="uq_discovered_rustdesk"),
    )
    op.create_index("ix_discovered_devices_last_seen", "discovered_devices", ["last_seen"])
    op.create_index("ix_discovered_devices_online", "discovered_devices", ["online"])

    op.create_table(
        "device_info",
        sa.Column("rustdesk_id", sa.String(64), primary_key=True),
        sa.Column("hostname", sa.String(128), nullable=False, server_default=""),
        sa.Column("username", sa.String(128), nullable=False, server_default=""),
        sa.Column("os", sa.String(255), nullable=False, server_default=""),
        sa.Column("os_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("os_version", sa.String(255), nullable=False, server_default=""),
        sa.Column("cpu", sa.String(255), nullable=False, server_default=""),
        sa.Column("cpu_model", sa.String(255), nullable=False, server_default=""),
        sa.Column("cpu_freq_ghz", sa.Float(), nullable=True),
        sa.Column("cpu_logical", sa.Integer(), nullable=True),
        sa.Column("cpu_physical", sa.Integer(), nullable=True),
        sa.Column("memory", sa.String(64), nullable=False, server_default=""),
        sa.Column("memory_gb", sa.Float(), nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default=""),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("collected_at", sa.DateTime(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("device_info")
    op.drop_index("ix_discovered_devices_online", table_name="discovered_devices")
    op.drop_index("ix_discovered_devices_last_seen", table_name="discovered_devices")
    op.drop_table("discovered_devices")
