import json
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    Batch,
    Item,
    PlanStatus,
    Protocol,
    ProtocolItem,
    StockTxn,
    TreatmentPlan,
    TxnReason,
)
from app.routers.inventory import fefo_dispense
from app.schemas import AnomalyCheckIn, AnomalyCheckOut, RecentTxnOut, ScanLogIn, ScanLogOut

router = APIRouter()

_ANOMALY_SYSTEM = """You are an anomaly detection AI for a hospital pharmacy system.
Analyse the proposed transaction and return ONLY a JSON object with exactly these fields:
{
  "status": "normal" | "warning" | "alert",
  "reason_code": "normal" | "quantity_spike" | "fefo_violation" | "no_scheduled_use" | "department_unusual" | "frequency_high",
  "message": "one concise sentence for staff",
  "requires_reason": true | false
}

Rules:
- ALERT (requires_reason true): FEFO violation (bypassing an earlier-expiry batch) OR drug with no scheduled patient treatment today
- WARNING (requires_reason true): quantity > 3x department daily average OR department has no history with this item OR 3+ transactions today for this item
- NORMAL (requires_reason false): everything else

Return ONLY the raw JSON object — no markdown, no explanation."""


def _call_claude_anomaly(context: dict) -> dict:
    fallback = {"status": "normal", "reason_code": "normal", "message": "AI check unavailable", "requires_reason": False}
    if not settings.anthropic_api_key:
        return fallback
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=3.0)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=200,
            system=_ANOMALY_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(context, indent=2)}],
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)
    except Exception:
        return fallback


@router.post("/scan/check-anomaly", response_model=AnomalyCheckOut)
def check_anomaly(body: AnomalyCheckIn, db: Session = Depends(get_db)):
    item = db.get(Item, body.item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    total_dispensed = (
        db.execute(
            select(func.sum(func.abs(StockTxn.qty_delta))).where(
                StockTxn.item_id == body.item_id,
                StockTxn.reason == TxnReason.dispense,
                StockTxn.created_at >= thirty_days_ago,
            )
        ).scalar()
        or 0
    )
    avg_daily = float(total_dispensed) / 30.0

    dept_dispensed = (
        db.execute(
            select(func.sum(func.abs(StockTxn.qty_delta))).where(
                StockTxn.item_id == body.item_id,
                StockTxn.reason == TxnReason.dispense,
                StockTxn.department == body.department,
                StockTxn.created_at >= thirty_days_ago,
            )
        ).scalar()
        or 0
    )
    dept_daily_avg = float(dept_dispensed) / 30.0

    fefo_batch = (
        db.execute(
            select(Batch)
            .where(
                Batch.item_id == body.item_id,
                Batch.qty_on_hand > 0,
                Batch.expiry_date > date.today(),
            )
            .order_by(Batch.expiry_date)
        )
        .scalars()
        .first()
    )
    fefo_violation = bool(body.batch_id and fefo_batch and fefo_batch.id != body.batch_id)

    today = date.today()
    scheduled_count = (
        db.execute(
            select(func.count())
            .select_from(TreatmentPlan)
            .join(Protocol, TreatmentPlan.protocol_id == Protocol.id)
            .join(
                ProtocolItem,
                (ProtocolItem.protocol_id == Protocol.id) & (ProtocolItem.item_id == body.item_id),
            )
            .where(
                TreatmentPlan.next_due_date == today,
                TreatmentPlan.status == PlanStatus.active,
            )
        ).scalar()
        or 0
    )

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    txns_today = (
        db.execute(
            select(func.count())
            .select_from(StockTxn)
            .where(
                StockTxn.item_id == body.item_id,
                StockTxn.created_at >= today_start,
            )
        ).scalar()
        or 0
    )

    total_stock = (
        db.execute(select(func.sum(Batch.qty_on_hand)).where(Batch.item_id == body.item_id)).scalar() or 0
    )

    context = {
        "item_name": item.name,
        "item_type": item.type.value,
        "action": body.action,
        "quantity": body.qty,
        "department": body.department,
        "current_stock": int(total_stock),
        "daily_avg_all_depts": round(avg_daily, 1),
        "dept_daily_avg": round(dept_daily_avg, 1),
        "dept_has_history": dept_dispensed > 0,
        "fefo_violation": fefo_violation,
        "scheduled_treatments_today": int(scheduled_count),
        "transactions_today": int(txns_today),
    }

    result = _call_claude_anomaly(context)
    return AnomalyCheckOut(**result)


@router.post("/scan/log", response_model=list[ScanLogOut], status_code=201)
def log_scan_txn(body: ScanLogIn, db: Session = Depends(get_db)):
    item = db.get(Item, body.item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    reason_map = {
        "dispense": TxnReason.dispense,
        "receive": TxnReason.receive,
        "waste": TxnReason.waste,
    }
    reason = reason_map.get(body.action)
    if not reason:
        raise HTTPException(422, "action must be dispense, receive, or waste")

    txns: list[StockTxn] = []

    if reason == TxnReason.dispense:
        txns = fefo_dispense(db, body.item_id, body.qty)

    elif reason == TxnReason.receive:
        expiry = date.today() + timedelta(days=item.shelf_life_days or 365)
        batch = Batch(
            item_id=body.item_id,
            lot_no=f"SCAN-{date.today().isoformat()}",
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

    else:  # waste
        fefo_batch = (
            db.execute(
                select(Batch)
                .where(Batch.item_id == body.item_id, Batch.qty_on_hand > 0)
                .order_by(Batch.expiry_date)
            )
            .scalars()
            .first()
        )
        if not fefo_batch:
            raise HTTPException(400, "No stock available to waste")
        take = min(body.qty, fefo_batch.qty_on_hand)
        fefo_batch.qty_on_hand -= take
        txn = StockTxn(
            item_id=body.item_id,
            batch_id=fefo_batch.id,
            qty_delta=-take,
            reason=TxnReason.waste,
        )
        db.add(txn)
        txns = [txn]

    db.flush()
    for txn in txns:
        txn.department = body.department
        txn.anomaly_status = body.anomaly_status
        txn.anomaly_message = body.anomaly_message
        txn.dispense_reason = body.dispense_reason

    db.commit()
    for txn in txns:
        db.refresh(txn)

    return [ScanLogOut(id=txn.id, qty_delta=txn.qty_delta, created_at=txn.created_at) for txn in txns]


@router.get("/stock-txns/recent", response_model=list[RecentTxnOut])
def recent_txns(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    rows = (
        db.execute(
            select(StockTxn, Item.name.label("item_name"), Batch.lot_no.label("lot_no"))
            .join(Item, StockTxn.item_id == Item.id)
            .outerjoin(Batch, StockTxn.batch_id == Batch.id)
            .order_by(StockTxn.created_at.desc())
            .limit(limit)
        )
        .all()
    )

    return [
        RecentTxnOut(
            id=txn.id,
            created_at=txn.created_at,
            reason=txn.reason.value,
            item_id=txn.item_id,
            item_name=item_name,
            batch_id=txn.batch_id,
            lot_no=lot_no,
            qty_delta=txn.qty_delta,
            department=txn.department,
            user="Staff",
            anomaly_status=txn.anomaly_status,
            anomaly_message=txn.anomaly_message,
            dispense_reason=txn.dispense_reason,
        )
        for txn, item_name, lot_no in rows
    ]
