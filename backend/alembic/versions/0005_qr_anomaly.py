"""qr codes and anomaly detection columns on stock_txns

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("stock_txns", sa.Column("department", sa.String(100), nullable=True))
    op.add_column("stock_txns", sa.Column("anomaly_status", sa.String(20), nullable=True))
    op.add_column("stock_txns", sa.Column("anomaly_message", sa.Text(), nullable=True))
    op.add_column("stock_txns", sa.Column("dispense_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_txns", "dispense_reason")
    op.drop_column("stock_txns", "anomaly_message")
    op.drop_column("stock_txns", "anomaly_status")
    op.drop_column("stock_txns", "department")
