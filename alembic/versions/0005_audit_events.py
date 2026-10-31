"""Add the append-only audit/access log.

Additive migration: a new table and its indexes only. Existing books, peers,
tags, users and discovery rows are untouched. The table starts empty; retention
(services/audit.cleanup_once) is the only code path that deletes rows.

Revision 0005 follows 0004, the current head at the time of writing.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("category", sa.String(16), nullable=False, server_default=""),
        sa.Column("event_type", sa.String(48), nullable=False, server_default=""),
        sa.Column("actor_type", sa.String(16), nullable=False, server_default=""),
        sa.Column("actor_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("actor_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("source_ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("destination", sa.String(32), nullable=False, server_default=""),
        sa.Column("http_method", sa.String(8), nullable=False, server_default=""),
        sa.Column("route", sa.String(255), nullable=False, server_default=""),
        sa.Column("target_type", sa.String(32), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(128), nullable=False, server_default=""),
        sa.Column("outcome", sa.String(16), nullable=False, server_default="success"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=False, server_default=""),
        sa.Column("details", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_audit_events_timestamp", "audit_events", ["timestamp"])
    op.create_index("ix_audit_events_category", "audit_events", ["category"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_actor_type", "audit_events", ["actor_type"])
    op.create_index("ix_audit_events_actor_id", "audit_events", ["actor_id"])
    op.create_index("ix_audit_events_source_ip", "audit_events", ["source_ip"])
    op.create_index("ix_audit_events_outcome", "audit_events", ["outcome"])
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])
    op.create_index("ix_audit_events_target", "audit_events", ["target_type", "target_id"])
    op.create_index(
        "ix_audit_events_category_time", "audit_events", ["category", "timestamp"]
    )
    op.create_index(
        "ix_audit_events_type_time", "audit_events", ["event_type", "timestamp"]
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_type_time", table_name="audit_events")
    op.drop_index("ix_audit_events_category_time", table_name="audit_events")
    op.drop_index("ix_audit_events_target", table_name="audit_events")
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_outcome", table_name="audit_events")
    op.drop_index("ix_audit_events_source_ip", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_id", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_type", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_category", table_name="audit_events")
    op.drop_index("ix_audit_events_timestamp", table_name="audit_events")
    op.drop_table("audit_events")
