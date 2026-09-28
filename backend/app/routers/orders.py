"""Purchase-order workflow: generate (AI) -> approve & send -> supplier reply -> receive."""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    Actor,
    AuditLog,
    Batch,
    ForecastRun,
    Item,
    POCreator,
    POLine,
    POStatus,
    PurchaseOrder,
    StockTxn,
    Supplier,
    SupplierPrice,
    TxnReason,
)
from app.schemas import (
    GenerateResult,
    POLineOut,
    POListItem,
    POOut,
    ReceiveResult,
    SupplierBrief,
)
from app.services.llm import generate_rationale, parse_supplier_reply
from app.services.reorder import run_reorder
from app.services.simulator import simulate_supplier_reply

router = APIRouter(prefix="/purchase-orders")

HORIZON_DAYS = 30
OPEN_STATUSES = [POStatus.draft, POStatus.pending_approval, POStatus.sent]


# ── helpers ──────────────────────────────────────────────────────────────────


def _audit(db: Session, actor: Actor, action: str, po: PurchaseOrder, before=None, after=None) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            entity="purchase_orders",
            entity_id=po.id,
            before=before,
            after=after,
        )
    )


def _unit_price(db: Session, supplier_id: int, item: Item) -> float:
    """Current supplier price-list price, falling back to the item's standard cost."""
    today = date.today()
    price = db.execute(
        select(SupplierPrice.unit_price)
        .where(
            SupplierPrice.supplier_id == supplier_id,
            SupplierPrice.item_id == item.id,
            SupplierPrice.valid_from <= today,
            or_(SupplierPrice.valid_to.is_(None), SupplierPrice.valid_to >= today),
        )
        .order_by(SupplierPrice.valid_from.desc())
        .limit(1)
    ).scalar()
    return float(price if price is not None else item.unit_cost)


def _get_po(db: Session, po_id: int) -> PurchaseOrder:
    po = db.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id)
        .options(selectinload(PurchaseOrder.lines).selectinload(POLine.item))
    ).scalar_one_or_none()
    if po is None:
        raise HTTPException(404, "Purchase order not found")
    return po


def _line_dicts(po: PurchaseOrder) -> list[dict]:
    return [{"item_id": l.item_id, "item_name": l.item.name, "qty": l.qty} for l in po.lines]


def _po_out(db: Session, po: PurchaseOrder) -> POOut:
    backup_id = db.execute(
        select(PurchaseOrder.id).where(PurchaseOrder.backup_of_po_id == po.id).limit(1)
    ).scalar()
    return POOut(
        id=po.id,
        supplier=SupplierBrief.model_validate(po.supplier),
        status=po.status,
        created_by=po.created_by,
        total=float(po.total),
        line_count=len(po.lines),
        created_at=po.created_at,
        lines=[
            POLineOut(
                id=l.id,
                item_id=l.item_id,
                item_name=l.item.name,
                qty=l.qty,
                unit_price=float(l.unit_price),
                line_total=round(l.qty * float(l.unit_price), 2),
                rationale=l.rationale,
            )
            for l in po.lines
        ],
        supplier_reply=po.supplier_reply,
        reply_parsed=po.reply_parsed,
        backup_of_po_id=po.backup_of_po_id,
        backup_po_id=backup_id,
    )


def _list_item(po: PurchaseOrder) -> POListItem:
    return POListItem(
        id=po.id,
        supplier_id=po.supplier_id,
        supplier_name=po.supplier.name,
        status=po.status,
        created_by=po.created_by,
        total=float(po.total),
        line_count=len(po.lines),
        created_at=po.created_at,
        backup_of_po_id=po.backup_of_po_id,
    )


def _confirmed_qty(po: PurchaseOrder) -> dict[int, int]:
    """item_id -> qty the supplier will actually ship (ordered qty if no usable reply)."""
    parsed = po.reply_parsed
    if parsed and parsed.get("status") in ("full", "partial", "rejected"):
        by_item = {l["item_id"]: l["confirmed_qty"] for l in parsed["lines"]}
        return {l.item_id: by_item.get(l.item_id, 0) for l in po.lines}
    return {l.item_id: l.qty for l in po.lines}


def _create_backup_po(db: Session, po: PurchaseOrder, shortfalls: dict[int, int]) -> PurchaseOrder:
    """Draft PO for whatever the supplier could not ship, routed to the backup supplier."""
    supplier = po.supplier.backup_supplier or po.supplier
    backup = PurchaseOrder(
        supplier_id=supplier.id,
        status=POStatus.draft,
        created_by=POCreator.ai,
        total=0,
        backup_of_po_id=po.id,
    )
    db.add(backup)
    db.flush()

    total = 0.0
    for line in po.lines:
        short = shortfalls.get(line.item_id, 0)
        if short <= 0:
            continue
        price = _unit_price(db, supplier.id, line.item)
        total += short * price
        db.add(
            POLine(
                po_id=backup.id,
                item_id=line.item_id,
                qty=short,
                unit_price=price,
                rationale=(
                    f"Backup order for {short:,} units of {line.item.name} that "
                    f"{po.supplier.name} could not supply on PO #{po.id}."
                ),
            )
        )
    backup.total = round(total, 2)
    _audit(db, Actor.ai, "create_backup_po", backup, after={"backup_of_po_id": po.id, "total": backup.total})
    return backup


# ── endpoints ────────────────────────────────────────────────────────────────


@router.post("/generate", response_model=GenerateResult, status_code=201)
def generate_pos(db: Session = Depends(get_db)):
    """Run the forecast for every item and draft one PO per supplier for items that need stock."""
    results = run_reorder(db, HORIZON_DAYS)
    db.add(ForecastRun(horizon_days=HORIZON_DAYS, snapshot={"results": results}))

    on_open_po = set(
        db.execute(
            select(POLine.item_id)
            .join(PurchaseOrder, POLine.po_id == PurchaseOrder.id)
            .where(PurchaseOrder.status.in_(OPEN_STATUSES))
        ).scalars()
    )

    by_supplier: dict[int, list[tuple[Item, dict]]] = {}
    skipped: list[str] = []
    for r in results:
        if not r["needs_order"]:
            continue
        item = db.get(Item, r["item_id"])
        if item.supplier_id is None or item.id in on_open_po:
            skipped.append(item.name)
            continue
        by_supplier.setdefault(item.supplier_id, []).append((item, r))

    pos: list[PurchaseOrder] = []
    for supplier_id, entries in by_supplier.items():
        supplier = db.get(Supplier, supplier_id)
        po = PurchaseOrder(supplier_id=supplier_id, status=POStatus.draft, created_by=POCreator.ai, total=0)
        db.add(po)
        db.flush()

        total = 0.0
        for item, r in entries:
            price = _unit_price(db, supplier_id, item)
            total += r["order_qty"] * price
            db.add(
                POLine(
                    po_id=po.id,
                    item_id=item.id,
                    qty=r["order_qty"],
                    unit_price=price,
                    rationale=generate_rationale(item.name, supplier.name, r["order_qty"], r),
                )
            )
        po.total = round(total, 2)
        _audit(db, Actor.ai, "generate_po", po, after={"total": po.total, "lines": len(entries)})
        pos.append(po)

    db.commit()
    for po in pos:
        db.refresh(po)
    return GenerateResult(
        created=len(pos),
        po_ids=[po.id for po in pos],
        skipped_items=skipped,
        pos=[_list_item(po) for po in pos],
    )


@router.get("", response_model=list[POListItem])
def list_pos(db: Session = Depends(get_db)):
    pos = (
        db.execute(
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.lines), selectinload(PurchaseOrder.supplier))
            .order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
        )
        .scalars()
        .all()
    )
    return [_list_item(po) for po in pos]


@router.get("/{po_id}", response_model=POOut)
def get_po(po_id: int, db: Session = Depends(get_db)):
    return _po_out(db, _get_po(db, po_id))


@router.patch("/{po_id}/approve", response_model=POOut)
def approve_po(po_id: int, db: Session = Depends(get_db)):
    """Approve and send. The simulated supplier replies immediately; the reply is parsed,
    and any shortfall is drafted as a backup PO."""
    po = _get_po(db, po_id)
    if po.status not in (POStatus.draft, POStatus.pending_approval):
        raise HTTPException(409, f"Cannot approve a PO that is already {po.status.value}")

    before = {"status": po.status.value}
    po.status = POStatus.sent

    reply = simulate_supplier_reply(
        po_id=po.id,
        supplier_name=po.supplier.name,
        contact_person=po.supplier.contact_person,
        reliability_score=po.supplier.reliability_score,
        lead_time_days=po.supplier.lead_time_days,
        lines=[
            {"item_name": l.item.name, "qty": l.qty, "pack_size": l.item.pack_size} for l in po.lines
        ],
    )
    parsed = parse_supplier_reply(reply, _line_dicts(po))
    po.supplier_reply = reply
    po.reply_parsed = parsed

    if parsed["status"] in ("full", "partial"):
        po.status = POStatus.confirmed
    if parsed["status"] in ("partial", "rejected"):
        confirmed = {l["item_id"]: l["confirmed_qty"] for l in parsed["lines"]}
        shortfalls = {l.item_id: l.qty - confirmed.get(l.item_id, 0) for l in po.lines}
        _create_backup_po(db, po, shortfalls)

    _audit(
        db, Actor.user, "approve_po", po, before=before,
        after={"status": po.status.value, "reply_status": parsed["status"]},
    )
    db.commit()
    return _po_out(db, _get_po(db, po_id))


@router.post("/{po_id}/receive", response_model=ReceiveResult)
def receive_po(po_id: int, db: Session = Depends(get_db)):
    """Book the delivery into stock as new batches (confirmed quantities only)."""
    po = _get_po(db, po_id)
    if po.status not in (POStatus.sent, POStatus.confirmed):
        raise HTTPException(409, f"Cannot receive a PO that is {po.status.value}")
    if po.reply_parsed and po.reply_parsed.get("status") == "rejected":
        raise HTTPException(409, "Supplier rejected this PO; nothing to receive")

    now = datetime.now(timezone.utc)
    units = 0
    confirmed = _confirmed_qty(po)
    for line in po.lines:
        qty = confirmed[line.item_id]
        if qty <= 0:
            continue
        batch = Batch(
            item_id=line.item_id,
            lot_no=f"PO{po.id}-{line.item_id}",
            qty_on_hand=qty,
            expiry_date=date.today() + timedelta(days=line.item.shelf_life_days or 365),
            received_at=now,
        )
        db.add(batch)
        db.flush()
        db.add(StockTxn(item_id=line.item_id, batch_id=batch.id, qty_delta=qty, reason=TxnReason.receive))
        units += qty

    before = {"status": po.status.value}
    po.status = POStatus.received
    _audit(db, Actor.user, "receive_po", po, before=before, after={"status": "received", "units": units})
    db.commit()
    return ReceiveResult(po=_po_out(db, _get_po(db, po_id)), units_received=units)
