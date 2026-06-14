"""create alerts_failures and dlq_retries tables

Revision ID: 0001_create_alerts_and_dlq_retries
Revises: 
Create Date: 2026-06-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '0001_create_alerts_and_dlq_retries'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'dlq_retries',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('dlq_entry_id', sa.Text, nullable=False),
        sa.Column('retried_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table(
        'alerts_failures',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('channel', sa.Text, nullable=False),
        sa.Column('payload', sa.JSON),
        sa.Column('error_message', sa.Text),
        sa.Column('failed_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()')),
    )


def downgrade():
    op.drop_table('alerts_failures')
    op.drop_table('dlq_retries')
