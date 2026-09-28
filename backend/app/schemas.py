from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.models import ItemType, TxnReason


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
