"""add actor column to stock_txns

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_txns", sa.Column("actor", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_txns", "actor")
