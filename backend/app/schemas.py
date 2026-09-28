from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.models import ItemType, POCreator, POStatus, TxnReason


class BatchOut(BaseModel):
    id: int
    lot_no: str
    qty_on_hand: int
    expiry_date: date
    received_at: datetime

    model_config = {"from_attributes": True}


class ItemListOut(BaseModel):
    id: int
    name: str
    type: ItemType
    unit: str
    total_stock: int
    status: str  # adequate | low | critical
    days_until_stockout: Optional[float]
    default_supplier_name: Optional[str]


class ItemDetailOut(BaseModel):
    id: int
    name: str
    type: ItemType
    unit: str
    unit_cost: float
    total_stock: int
    avg_daily_consumption: float
    batches: list[BatchOut]


class StockTxnCreate(BaseModel):
    item_id: int
    qty: int
    reason: TxnReason
    batch_id: Optional[int] = None


class StockTxnOut(BaseModel):
    id: int
    item_id: int
    batch_id: Optional[int]
    qty_delta: int
    reason: TxnReason
    created_at: datetime

    model_config = {"from_attributes": True}


class TxnPage(BaseModel):
    items: list[StockTxnOut]
    total: int
    page: int
    page_size: int


class ExpiringBatchOut(BaseModel):
    id: int
    item_id: int
    item_name: str
    lot_no: str
    qty_on_hand: int
    expiry_date: date
    days_until_expiry: int


class DispenseSummaryLine(BaseModel):
    item_id: int
    item_name: str
    qty_dispensed: int
    patient_id: int
    patient_name: str


class SimulateResult(BaseModel):
    date_processed: date
    plans_processed: int
    lines_dispensed: list[DispenseSummaryLine]
    total_qty_dispensed: int


class SupplierBrief(BaseModel):
    id: int
    name: str
    email: Optional[str]
    phone: Optional[str]
    contact_person: Optional[str]
    lead_time_days: int
    payment_terms: Optional[str]

    model_config = {"from_attributes": True}


class POLineOut(BaseModel):
    id: int
    item_id: int
    item_name: str
    qty: int
    unit_price: float
    line_total: float
    rationale: Optional[str]


class POOut(BaseModel):
    id: int
    supplier: SupplierBrief
    status: POStatus
    created_by: POCreator
    total: float
    line_count: int
    created_at: datetime
    lines: list[POLineOut]
    supplier_reply: Optional[str]
    reply_parsed: Optional[dict]
    backup_of_po_id: Optional[int]
    backup_po_id: Optional[int]  # PO auto-created for a partial/short delivery


class POListItem(BaseModel):
    id: int
    supplier_id: int
    supplier_name: str
    status: POStatus
    created_by: POCreator
    total: float
    line_count: int
    created_at: datetime
    backup_of_po_id: Optional[int]


class GenerateResult(BaseModel):
    created: int
    po_ids: list[int]
    skipped_items: list[str]  # already on an open PO, or no supplier
    pos: list[POListItem]


class ReceiveResult(BaseModel):
    po: POOut
    units_received: int


# ── Forecast ──────────────────────────────────────────────────────────────────


class DemandBreakdown(BaseModel):
    A_scheduled: float
    B_baseline: float
    C_new_intake: float
    total: float


class ForecastItemOut(BaseModel):
    item_id: int
    item_name: str
    horizon_days: int
    demand: DemandBreakdown
    usable_stock: float
    qty_on_order: float
    ROP: float
    order_qty: int
    days_until_stockout: Optional[float]
    needs_order: bool
    rationale_data: dict  # contributing_patients, baseline_figure, new_intake_rate, expiring_batches_excluded
