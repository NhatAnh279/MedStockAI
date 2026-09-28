"""purchase orders: supplier reply, parsed confirmation, backup PO link

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("supplier_reply", sa.Text(), nullable=True))
    op.add_column("purchase_orders", sa.Column("reply_parsed", sa.JSON(), nullable=True))
    op.add_column("purchase_orders", sa.Column("backup_of_po_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_purchase_orders_backup_of_po_id",
        "purchase_orders",
        "purchase_orders",
        ["backup_of_po_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_purchase_orders_backup_of_po_id", "purchase_orders", type_="foreignkey")
    op.drop_column("purchase_orders", "backup_of_po_id")
    op.drop_column("purchase_orders", "reply_parsed")
    op.drop_column("purchase_orders", "supplier_reply")
