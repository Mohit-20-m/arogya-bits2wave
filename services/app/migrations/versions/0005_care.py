"""Hospital map + personal roadmap: facility details shown to the ASHA, roadmap progress.

Revision ID: 0005_care
Revises: 0004_compliance
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_care"
down_revision = "0004_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("facilities", sa.Column("services", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("facilities", sa.Column("ownership", sa.String(length=20), nullable=True))
    op.add_column("facilities", sa.Column("cost", sa.String(length=20), nullable=True))
    op.add_column("facilities", sa.Column("address", sa.String(length=240), nullable=True))
    op.add_column("facilities", sa.Column("hours", sa.String(length=120), nullable=True))
    op.create_table(
        "care_progress",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("screening_id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("step_id", sa.String(length=40), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("done_by", sa.UUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("screening_id", "step_id", name="uq_care_progress_step"),
    )
    op.create_index("ix_care_progress_screening", "care_progress", ["screening_id"])


def downgrade() -> None:
    op.drop_index("ix_care_progress_screening", table_name="care_progress")
    op.drop_table("care_progress")
    for c in ("hours", "address", "cost", "ownership", "services"):
        op.drop_column("facilities", c)
