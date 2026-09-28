import math
from datetime import date, datetime, timedelta
from statistics import stdev
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Batch,
    Condition,
    Item,
    Patient,
    PlanStatus,
    POLine,
    POStatus,
    Protocol,
    ProtocolItem,
    PurchaseOrder,
    StockTxn,
    TreatmentPlan,
    TxnReason,
)


def _cycles_in_horizon(
    next_due: date | None,
    cycle_length: int,
    current_cycle: int,
    total_cycles: int | None,
    today: date,
    horizon_days: int,
) -> list[date]:
    if next_due is None:
        return []
    horizon_end = today + timedelta(days=horizon_days)
    dates = []
    d = next_due
    c = current_cycle
    while d < horizon_end:
        if total_cycles is not None and c > total_cycles:
            break
        if d >= today:
            dates.append(d)
        d += timedelta(days=cycle_length)
        c += 1
    return dates


def forecast(db: Session, item_id: int, horizon_days: int = 30) -> dict[str, Any]:
    today = date.today()

    item = db.get(Item, item_id)
    if item is None:
        raise ValueError(f"Item {item_id} not found")

    lead_time = item.supplier.lead_time_days if item.supplier else 7

    # ── A: Scheduled demand ───────────────────────────────────────────────────
    rows = (
        db.execute(
            select(TreatmentPlan, ProtocolItem, Patient)
            .join(Protocol, TreatmentPlan.protocol_id == Protocol.id)
            .join(ProtocolItem, ProtocolItem.protocol_id == Protocol.id)
            .join(Patient, TreatmentPlan.patient_id == Patient.id)
            .where(
                TreatmentPlan.status == PlanStatus.active,
                ProtocolItem.item_id == item_id,
            )
        )
        .all()
    )

    A_scheduled = 0.0
    contributing_patients = []
    for plan, pi, patient in rows:
        cycle_dates = _cycles_in_horizon(
            plan.next_due_date,
            plan.protocol.cycle_length_days,
            plan.current_cycle,
            plan.protocol.total_cycles,
            today,
            horizon_days,
        )
        if not cycle_dates:
            continue
        qty_per_cycle = (
            math.ceil(pi.dose_per_kg * patient.weight_kg)
            if pi.dose_per_kg
            else pi.qty_per_cycle
        )
        patient_qty = qty_per_cycle * len(cycle_dates)
        A_scheduled += patient_qty
        contributing_patients.append(
            {
                "patient_id": patient.id,
                "phase": plan.current_phase,
                "qty": patient_qty,
                "cycles": len(cycle_dates),
            }
        )

    # ── B: EWMA baseline of daily dispense (last 90 days) ────────────────────
    ninety_ago = datetime.combine(today - timedelta(days=90), datetime.min.time())
    txns = (
        db.execute(
            select(StockTxn)
            .where(
                StockTxn.item_id == item_id,
                StockTxn.reason == TxnReason.dispense,
                StockTxn.created_at >= ninety_ago,
            )
            .order_by(StockTxn.created_at)
        )
        .scalars()
        .all()
    )

    daily_dispense: dict[date, float] = {}
    for txn in txns:
        d = txn.created_at.date()
        daily_dispense[d] = daily_dispense.get(d, 0) + abs(txn.qty_delta)

    alpha = 0.3
    ewma = 0.0
    for i in range(90):
        d = today - timedelta(days=89 - i)
        qty = daily_dispense.get(d, 0.0)
        ewma = alpha * qty + (1 - alpha) * ewma

    B_baseline = ewma * horizon_days

    daily_values = [daily_dispense.get(today - timedelta(days=i), 0.0) for i in range(90)]
    std_dev_daily = stdev(daily_values) if len(set(daily_values)) > 1 else 0.0

    # ── C: New patient intake trend ───────────────────────────────────────────
    proto_icd = (
        db.execute(
            select(Protocol.icd_code)
            .join(ProtocolItem, ProtocolItem.protocol_id == Protocol.id)
            .where(ProtocolItem.item_id == item_id)
            .limit(1)
        )
        .scalar()
    )

    avg_new_patients_per_day = 0.0
    avg_qty_per_new_patient = 0.0

    if proto_icd:
        thirty_ago = today - timedelta(days=30)
        new_count = (
            db.execute(
                select(func.count(Condition.id)).where(
                    Condition.icd_code == proto_icd,
                    Condition.diagnosed_at >= thirty_ago,
                    Condition.status == "active",
                )
            ).scalar()
            or 0
        )
        avg_new_patients_per_day = new_count / 30.0

        qty_rows = (
            db.execute(
                select(ProtocolItem.qty_per_cycle)
                .join(Protocol, ProtocolItem.protocol_id == Protocol.id)
                .where(
                    Protocol.icd_code == proto_icd,
                    ProtocolItem.item_id == item_id,
                )
            )
            .scalars()
            .all()
        )
        avg_qty_per_new_patient = (
            sum(qty_rows) / len(qty_rows) if qty_rows else 0.0
        )

    C_new_intake = avg_new_patients_per_day * avg_qty_per_new_patient * horizon_days

    total_demand = A_scheduled + B_baseline + C_new_intake
    daily_demand = total_demand / horizon_days if horizon_days > 0 else 0.0

    # ── usable_stock (FEFO; exclude batches expiring before we'd reach them) ──
    batches = (
        db.execute(
            select(Batch)
            .where(Batch.item_id == item_id, Batch.qty_on_hand > 0)
            .order_by(Batch.expiry_date)
        )
        .scalars()
        .all()
    )

    usable_stock = 0.0
    excluded_batches = []
    cumulative_qty = 0.0
    for batch in batches:
        days_to_start = cumulative_qty / daily_demand if daily_demand > 0 else 0.0
        if batch.expiry_date > today + timedelta(days=days_to_start):
            usable_stock += batch.qty_on_hand
        else:
            excluded_batches.append(
                {
                    "batch_id": batch.id,
                    "lot_no": batch.lot_no,
                    "qty": batch.qty_on_hand,
                    "expiry_date": batch.expiry_date.isoformat(),
                    "days_to_start": round(days_to_start, 1),
                }
            )
        cumulative_qty += batch.qty_on_hand

    # ── qty_on_order: confirmed POs not yet received ──────────────────────────
    qty_on_order = float(
        db.execute(
            select(func.sum(POLine.qty))
            .join(PurchaseOrder, POLine.po_id == PurchaseOrder.id)
            .where(
                POLine.item_id == item_id,
                PurchaseOrder.status == POStatus.confirmed,
            )
        ).scalar()
        or 0
    )

    # ── ROP ───────────────────────────────────────────────────────────────────
    ROP = daily_demand * lead_time + 1.65 * std_dev_daily * math.sqrt(lead_time)

    # ── order_qty ─────────────────────────────────────────────────────────────
    need = total_demand + ROP - usable_stock - qty_on_order
    pack_size = item.pack_size
    moq = item.moq
    if need > 0:
        order_qty = math.ceil(max(need, moq) / pack_size) * pack_size
    else:
        order_qty = 0

    # ── days_until_stockout ───────────────────────────────────────────────────
    days_until_stockout = (
        round(usable_stock / daily_demand, 2) if daily_demand > 0 else None
    )

    return {
        "item_id": item_id,
        "item_name": item.name,
        "horizon_days": horizon_days,
        "demand": {
            "A_scheduled": round(A_scheduled, 4),
            "B_baseline": round(B_baseline, 4),
            "C_new_intake": round(C_new_intake, 4),
            "total": round(total_demand, 4),
        },
        "usable_stock": round(usable_stock, 4),
        "qty_on_order": round(qty_on_order, 4),
        "ROP": round(ROP, 4),
        "order_qty": order_qty,
        "days_until_stockout": days_until_stockout,
        "rationale_data": {
            "contributing_patients": contributing_patients,
            "baseline_figure": round(B_baseline, 4),
            "new_intake_rate": round(avg_new_patients_per_day, 4),
            "expiring_batches_excluded": excluded_batches,
        },
    }
