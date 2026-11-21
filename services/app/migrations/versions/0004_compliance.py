"""DPDP compliance: guardian consent for minors, erasure marker on patients, data-principal request log.

Revision ID: 0004_compliance
Revises: 0003_metrics
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_compliance"
down_revision = "0003_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("consents", sa.Column("guardian_name", sa.String(length=160), nullable=True))
    op.add_column("consents", sa.Column("guardian_relation", sa.String(length=40), nullable=True))
    op.add_column("patients", sa.Column("erased_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "data_requests",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("handled_by", sa.UUID(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"),
                  nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_requests_patient", "data_requests", ["patient_id"])


def downgrade() -> None:
    op.drop_index("ix_data_requests_patient", table_name="data_requests")
    op.drop_table("data_requests")
    op.drop_column("patients", "erased_at")
    op.drop_column("consents", "guardian_relation")
    op.drop_column("consents", "guardian_name")
