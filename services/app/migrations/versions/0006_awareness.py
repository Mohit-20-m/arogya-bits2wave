"""Awareness film: when the patient first watched it (the film is required once, before the first result).

Revision ID: 0006_awareness
Revises: 0005_care
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_awareness"
down_revision = "0005_care"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("awareness_watched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("patients", "awareness_watched_at")
