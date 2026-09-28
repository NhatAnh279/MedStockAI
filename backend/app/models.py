import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ItemType(str, enum.Enum):
    drug = "drug"
    consumable = "consumable"


class TxnReason(str, enum.Enum):
    dispense = "dispense"
    receive = "receive"
    waste = "waste"
    adjust = "adjust"


class PlanStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    paused = "paused"


class POStatus(str, enum.Enum):
    draft = "draft"
    pending_approval = "pending_approval"
    sent = "sent"
    confirmed = "confirmed"
    received = "received"


class Actor(str, enum.Enum):
    ai = "ai"
    user = "user"


class POCreator(str, enum.Enum):
    ai = "ai"
    human = "human"


def enum_col(e: type[enum.Enum]) -> Enum:
    return Enum(e, native_enum=False, length=32, values_callable=lambda x: [m.value for m in x])


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(50))
    contact_person: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(300))
    abn: Mapped[str | None] = mapped_column(String(14))  # "51 824 753 556"
    lead_time_days: Mapped[int] = mapped_column(Integer, default=5)
    payment_terms: Mapped[str | None] = mapped_column(String(100))
    reliability_score: Mapped[float] = mapped_column(Float, default=0.9)  # 0..1
    backup_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))

    backup_supplier: Mapped["Supplier | None"] = relationship(remote_side=[id])


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[ItemType] = mapped_column(enum_col(ItemType))
    unit: Mapped[str] = mapped_column(String(30))  # base unit; all quantities are in this unit
    pack_size: Mapped[int] = mapped_column(Integer, default=1)  # base units per pack
    moq: Mapped[int] = mapped_column(Integer, default=1)  # min order qty, base units
    unit_cost: Mapped[float] = mapped_column(Numeric(14, 4))  # AUD per base unit
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))

    supplier: Mapped[Supplier | None] = relationship()


class SupplierPrice(Base):
    __tablename__ = "supplier_price_list"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    unit_price: Mapped[float] = mapped_column(Numeric(14, 4))
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    min_order_qty: Mapped[int] = mapped_column(Integer, default=1)

    supplier: Mapped[Supplier] = relationship()
    item: Mapped[Item] = relationship()


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    lot_no: Mapped[str] = mapped_column(String(50))
    qty_on_hand: Mapped[int] = mapped_column(Integer, default=0)
    expiry_date: Mapped[date] = mapped_column(Date, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    item: Mapped[Item] = relationship()


class StockTxn(Base):
    __tablename__ = "stock_txns"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"))
    qty_delta: Mapped[int] = mapped_column(Integer)  # negative = stock out
    reason: Mapped[TxnReason] = mapped_column(enum_col(TxnReason))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    item: Mapped[Item] = relationship()
    batch: Mapped[Batch | None] = relationship()


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    medicare_no: Mapped[str] = mapped_column(String(12), unique=True)  # "2123 45670 1"
    full_name: Mapped[str] = mapped_column(String(120))
    dob: Mapped[date] = mapped_column(Date)
    sex: Mapped[str] = mapped_column(String(1))  # M / F
    weight_kg: Mapped[float] = mapped_column(Float)

    conditions: Mapped[list["Condition"]] = relationship(back_populates="patient")
    treatment_plans: Mapped[list["TreatmentPlan"]] = relationship(back_populates="patient")


class Condition(Base):
    __tablename__ = "conditions"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    icd_code: Mapped[str] = mapped_column(String(10))
    diagnosed_at: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="active")

    patient: Mapped[Patient] = relationship(back_populates="conditions")


class Protocol(Base):
    __tablename__ = "protocols"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    icd_code: Mapped[str] = mapped_column(String(10))
    phase: Mapped[str] = mapped_column(String(50))
    cycle_length_days: Mapped[int] = mapped_column(Integer)
    total_cycles: Mapped[int | None] = mapped_column(Integer)  # NULL = ongoing / chronic

    items: Mapped[list["ProtocolItem"]] = relationship(back_populates="protocol")


class ProtocolItem(Base):
    __tablename__ = "protocol_items"

    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), primary_key=True)
    qty_per_cycle: Mapped[int] = mapped_column(Integer)
    # item base units per kg body weight per cycle; when set, qty = ceil(dose_per_kg * weight_kg)
    dose_per_kg: Mapped[float | None] = mapped_column(Float)

    protocol: Mapped[Protocol] = relationship(back_populates="items")
    item: Mapped[Item] = relationship()


class TreatmentPlan(Base):
    __tablename__ = "treatment_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id"))
    current_phase: Mapped[str] = mapped_column(String(50))
    current_cycle: Mapped[int] = mapped_column(Integer, default=1)
    next_due_date: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[PlanStatus] = mapped_column(enum_col(PlanStatus), default=PlanStatus.active)

    patient: Mapped[Patient] = relationship(back_populates="treatment_plans")
    protocol: Mapped[Protocol] = relationship()


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    status: Mapped[POStatus] = mapped_column(enum_col(POStatus), default=POStatus.draft)
    created_by: Mapped[POCreator] = mapped_column(enum_col(POCreator))
    total: Mapped[float] = mapped_column(Numeric(16, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    supplier_reply: Mapped[str | None] = mapped_column(Text)  # raw supplier email text
    reply_parsed: Mapped[dict | None] = mapped_column(JSON)  # structured confirmation
    backup_of_po_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_orders.id"))

    supplier: Mapped[Supplier] = relationship()
    lines: Mapped[list["POLine"]] = relationship(back_populates="po")


class POLine(Base):
    __tablename__ = "po_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Numeric(14, 4))
    rationale: Mapped[str | None] = mapped_column(Text)

    po: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    item: Mapped[Item] = relationship()


class ForecastRun(Base):
    __tablename__ = "forecast_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    horizon_days: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[Actor] = mapped_column(enum_col(Actor))
    action: Mapped[str] = mapped_column(String(100))
    entity: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
