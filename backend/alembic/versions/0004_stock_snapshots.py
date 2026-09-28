"""stock snapshots table for simulate history chart

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stock_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sim_date", sa.Date(), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=False),
        sa.Column("qty_on_hand", sa.Integer(), nullable=False),
    )
    op.create_index("ix_stock_snapshots_sim_date", "stock_snapshots", ["sim_date"])
    op.create_index("ix_stock_snapshots_item_id", "stock_snapshots", ["item_id"])
    op.create_unique_constraint(
        "uq_stock_snapshots_date_item", "stock_snapshots", ["sim_date", "item_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_stock_snapshots_date_item", "stock_snapshots", type_="unique")
    op.drop_index("ix_stock_snapshots_item_id", table_name="stock_snapshots")
    op.drop_index("ix_stock_snapshots_sim_date", table_name="stock_snapshots")
    op.drop_table("stock_snapshots")
