from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Actor, AuditLog, Batch, Item, StockTxn, TxnReason
from app.schemas import (
    BatchOut,
    ExpiringBatchOut,
    ItemDetailOut,
    ItemListOut,
    StockTxnCreate,
    StockTxnOut,
    TxnPage,
)

router = APIRouter()


def avg_daily_consumption(db: Session, item_id: int) -> float:
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    total_out = (
        db.execute(
            select(func.sum(func.abs(StockTxn.qty_delta))).where(
                StockTxn.item_id == item_id,
                StockTxn.reason.in_([TxnReason.dispense, TxnReason.waste]),
                StockTxn.created_at >= thirty_days_ago,
            )
        ).scalar()
        or 0
    )
    return float(total_out) / 30.0


def _stockout_status(days: Optional[float]) -> str:
    if days is None:
        return "adequate"
    if days < 7:
        return "critical"
    if days < 30:
        return "low"
    return "adequate"


def fefo_dispense(db: Session, item_id: int, qty: int) -> list[StockTxn]:
    """Deduct qty from batches using FEFO; returns unsaved StockTxn rows."""
    batches = (
        db.execute(
            select(Batch)
            .where(
                Batch.item_id == item_id,
                Batch.expiry_date > date.today(),
                Batch.qty_on_hand > 0,
            )
            .order_by(Batch.expiry_date)
        )
        .scalars()
        .all()
    )

    remaining = qty
    txns: list[StockTxn] = []
    for batch in batches:
        if remaining <= 0:
            break
        take = min(remaining, batch.qty_on_hand)
        batch.qty_on_hand -= take
        remaining -= take
        txn = StockTxn(
            item_id=item_id,
            batch_id=batch.id,
            qty_delta=-take,
            reason=TxnReason.dispense,
        )
        db.add(txn)
        txns.append(txn)

    if remaining > 0:
        raise HTTPException(400, f"Insufficient stock: short by {remaining} units")
    return txns


def _write_audit(db: Session, action: str, entity: str, entity_id: int, after: dict) -> None:
    db.add(
        AuditLog(
            actor=Actor.user,
            action=action,
            entity=entity,
            entity_id=entity_id,
            after=after,
        )
    )


@router.get("/items", response_model=list[ItemListOut])
def list_items(db: Session = Depends(get_db)):
    items = (
        db.execute(select(Item).options(selectinload(Item.supplier)))
        .scalars()
        .all()
    )
    result = []
    for item in items:
        total_stock = (
            db.execute(
                select(func.sum(Batch.qty_on_hand)).where(Batch.item_id == item.id)
            ).scalar()
            or 0
        )
        avg = avg_daily_consumption(db, item.id)
        days = (float(total_stock) / avg) if avg > 0 else None
        result.append(
            ItemListOut(
                id=item.id,
                name=item.name,
                type=item.type,
                unit=item.unit,
                total_stock=int(total_stock),
                status=_stockout_status(days),
                days_until_stockout=round(days, 1) if days is not None else None,
                default_supplier_name=item.supplier.name if item.supplier else None,
            )
        )
    return result


@router.get("/items/{item_id}", response_model=ItemDetailOut)
def get_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")
    batches = (
        db.execute(
            select(Batch).where(Batch.item_id == item_id).order_by(Batch.expiry_date)
        )
        .scalars()
        .all()
    )
    total_stock = sum(b.qty_on_hand for b in batches)
    avg = avg_daily_consumption(db, item_id)
    return ItemDetailOut(
        id=item.id,
        name=item.name,
        type=item.type,
        unit=item.unit,
        unit_cost=float(item.unit_cost),
        total_stock=total_stock,
        avg_daily_consumption=round(avg, 3),
        batches=[BatchOut.model_validate(b) for b in batches],
    )


@router.post("/stock-txns", response_model=list[StockTxnOut], status_code=201)
def create_stock_txn(body: StockTxnCreate, db: Session = Depends(get_db)):
    item = db.get(Item, body.item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    txns: list[StockTxn] = []

    if body.reason == TxnReason.dispense:
        txns = fefo_dispense(db, body.item_id, body.qty)

    elif body.reason == TxnReason.receive:
        if body.batch_id:
            batch = db.get(Batch, body.batch_id)
            if not batch or batch.item_id != body.item_id:
                raise HTTPException(404, "Batch not found for this item")
            batch.qty_on_hand += body.qty
        else:
            expiry = date.today() + timedelta(days=item.shelf_life_days or 365)
            batch = Batch(
                item_id=body.item_id,
                lot_no=f"AUTO-{date.today().isoformat()}",
                qty_on_hand=body.qty,
                expiry_date=expiry,
                received_at=datetime.utcnow(),
            )
            db.add(batch)
            db.flush()
        txn = StockTxn(
            item_id=body.item_id,
            batch_id=batch.id,
            qty_delta=body.qty,
            reason=TxnReason.receive,
        )
        db.add(txn)
        txns = [txn]

    else:  # waste | adjust
        if body.batch_id:
            batch = db.get(Batch, body.batch_id)
            if not batch or batch.item_id != body.item_id:
                raise HTTPException(404, "Batch not found for this item")
        else:
            batch = (
                db.execute(
                    select(Batch)
                    .where(Batch.item_id == body.item_id, Batch.qty_on_hand > 0)
                    .order_by(Batch.expiry_date)
                )
                .scalars()
                .first()
            )
            if not batch:
                raise HTTPException(400, "No stock available")
        # waste always removes; adjust passes qty directly (negative = reduction)
        delta = -body.qty if body.reason == TxnReason.waste else body.qty
        batch.qty_on_hand += delta
        txn = StockTxn(
            item_id=body.item_id,
            batch_id=batch.id,
            qty_delta=delta,
            reason=body.reason,
        )
        db.add(txn)
        txns = [txn]

    db.flush()
    for txn in txns:
        _write_audit(
            db,
            "stock_txn",
            "stock_txns",
            txn.id,
            {
                "qty_delta": txn.qty_delta,
                "reason": txn.reason.value,
                "batch_id": txn.batch_id,
            },
        )

    db.commit()
    for txn in txns:
        db.refresh(txn)
    return txns


@router.get("/items/{item_id}/txns", response_model=TxnPage)
def item_txns(
    item_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if not db.get(Item, item_id):
        raise HTTPException(404, "Item not found")
    total = (
        db.execute(
            select(func.count()).select_from(StockTxn).where(StockTxn.item_id == item_id)
        ).scalar()
        or 0
    )
    txns = (
        db.execute(
            select(StockTxn)
            .where(StockTxn.item_id == item_id)
            .order_by(StockTxn.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return TxnPage(items=list(txns), total=int(total), page=page, page_size=page_size)


@router.get("/batches/expiring", response_model=list[ExpiringBatchOut])
def expiring_batches(days: int = Query(14, ge=1), db: Session = Depends(get_db)):
    today = date.today()
    cutoff = today + timedelta(days=days)
    rows = (
        db.execute(
            select(Batch, Item.name)
            .join(Item, Batch.item_id == Item.id)
            .where(
                Batch.expiry_date <= cutoff,
                Batch.expiry_date >= today,
                Batch.qty_on_hand > 0,
            )
            .order_by(Batch.expiry_date)
        )
        .all()
    )
    return [
        ExpiringBatchOut(
            id=b.id,
            item_id=b.item_id,
            item_name=name,
            lot_no=b.lot_no,
            qty_on_hand=b.qty_on_hand,
            expiry_date=b.expiry_date,
            days_until_expiry=(b.expiry_date - today).days,
        )
        for b, name in rows
    ]
