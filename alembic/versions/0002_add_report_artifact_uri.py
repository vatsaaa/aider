"""add artifact_uri to reports

Revision ID: 0002_add_report_artifact_uri
Revises: 0001_create_alerts_and_dlq_retries
Create Date: 2026-06-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_add_report_artifact_uri"
down_revision = "0001_create_alerts_and_dlq_retries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("artifact_uri", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "artifact_uri")
