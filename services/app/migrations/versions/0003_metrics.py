"""Real system metrics: service health checks and server resource samples recorded every minute.

Revision ID: 0003_metrics
Revises: 0002_security
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_metrics"
down_revision = "0002_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_checks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("service", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=12), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_checks_service_time", "service_checks", ["service", "checked_at"])
    op.create_table(
        "host_samples",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("sampled_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("cpu_pct", sa.Float(), nullable=True),
        sa.Column("mem_pct", sa.Float(), nullable=True),
        sa.Column("disk_pct", sa.Float(), nullable=True),
        sa.Column("load1", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_host_samples_time", "host_samples", ["sampled_at"])


def downgrade() -> None:
    op.drop_index("ix_host_samples_time", table_name="host_samples")
    op.drop_table("host_samples")
    op.drop_index("ix_service_checks_service_time", table_name="service_checks")
    op.drop_table("service_checks")
