"""australian market: abn, medicare_no, patient names, 4dp unit prices

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("suppliers", "tax_code", new_column_name="abn", type_=sa.String(14))

    op.alter_column("patients", "mrn", new_column_name="medicare_no", type_=sa.String(12))
    op.execute("ALTER TABLE patients RENAME CONSTRAINT patients_mrn_key TO patients_medicare_no_key")
    op.add_column("patients", sa.Column("full_name", sa.String(120), nullable=False, server_default=""))
    op.alter_column("patients", "full_name", server_default=None)

    for table, col in [("items", "unit_cost"), ("supplier_price_list", "unit_price"), ("po_lines", "unit_price")]:
        op.alter_column(table, col, type_=sa.Numeric(14, 4))


def downgrade() -> None:
    for table, col in [("items", "unit_cost"), ("supplier_price_list", "unit_price"), ("po_lines", "unit_price")]:
        op.alter_column(table, col, type_=sa.Numeric(14, 2))

    op.drop_column("patients", "full_name")
    op.execute("ALTER TABLE patients RENAME CONSTRAINT patients_medicare_no_key TO patients_mrn_key")
    op.alter_column("patients", "medicare_no", new_column_name="mrn", type_=sa.String(20))

    op.alter_column("suppliers", "abn", new_column_name="tax_code", type_=sa.String(20))
