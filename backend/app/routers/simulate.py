import math
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    Actor,
    AuditLog,
    Batch,
    Item,
    Patient,
    PlanStatus,
    Protocol,
    ProtocolItem,
    StockSnapshot,
    TreatmentPlan,
)
from app.routers.inventory import fefo_dispense
from app.schemas import DispenseSummaryLine, SimulateResult, StockHistoryOut, StockSnapshotPoint

router = APIRouter(prefix="/simulate")

# Simulated date advances by 1 each time /advance-day is called.
# Starts at None; first call sets it to date.today() + 1.
_sim_date: date | None = None


def current_sim_date() -> date:
    """Current simulated date; equals today() until advance-day has been called."""
    return _sim_date if _sim_date is not None else date.today()


@router.post("/advance-day", response_model=SimulateResult)
def advance_day(db: Session = Depends(get_db)):
    global _sim_date
    _sim_date = (date.today() + timedelta(days=1)) if _sim_date is None else (_sim_date + timedelta(days=1))
    today = _sim_date

    plans = (
        db.execute(
            select(TreatmentPlan).where(
                TreatmentPlan.status == PlanStatus.active,
                TreatmentPlan.next_due_date <= today,
            )
        )
        .scalars()
        .all()
    )

    lines_dispensed: list[DispenseSummaryLine] = []

    for plan in plans:
        protocol = db.get(Protocol, plan.protocol_id)
        patient = db.get(Patient, plan.patient_id)
        protocol_items = (
            db.execute(
                select(ProtocolItem).where(ProtocolItem.protocol_id == plan.protocol_id)
            )
            .scalars()
            .all()
        )

        for pi in protocol_items:
            item = db.get(Item, pi.item_id)
            qty = (
                math.ceil(pi.dose_per_kg * patient.weight_kg)
                if pi.dose_per_kg
                else pi.qty_per_cycle
            )

            try:
                txns = fefo_dispense(db, pi.item_id, qty)
                dispensed = sum(abs(t.qty_delta) for t in txns)
                lines_dispensed.append(
                    DispenseSummaryLine(
                        item_id=pi.item_id,
                        item_name=item.name,
                        qty_dispensed=dispensed,
                        patient_id=plan.patient_id,
                        patient_name=patient.full_name,
                    )
                )
            except Exception:
                # insufficient stock — log and continue
                pass

        plan.current_cycle += 1
        due = plan.next_due_date or today
        plan.next_due_date = due + timedelta(days=protocol.cycle_length_days)

        if protocol.total_cycles and plan.current_cycle > protocol.total_cycles:
            plan.status = PlanStatus.completed

        db.add(
            AuditLog(
                actor=Actor.ai,
                action="advance_cycle",
                entity="treatment_plans",
                entity_id=plan.id,
                after={
                    "cycle": plan.current_cycle,
                    "next_due_date": str(plan.next_due_date),
                    "status": plan.status.value,
                    "sim_date": today.isoformat(),
                },
            )
        )

    db.commit()

    # Save stock snapshot for every item at this simulated date
    stock_rows = db.execute(
        select(Item.id, func.coalesce(func.sum(Batch.qty_on_hand), 0).label("total"))
        .outerjoin(Batch, Batch.item_id == Item.id)
        .group_by(Item.id)
    ).all()
    for row in stock_rows:
        existing = db.execute(
            select(StockSnapshot).where(
                StockSnapshot.sim_date == today, StockSnapshot.item_id == row.id
            )
        ).scalar_one_or_none()
        if existing:
            existing.qty_on_hand = row.total
        else:
            db.add(StockSnapshot(sim_date=today, item_id=row.id, qty_on_hand=row.total))
    db.commit()

    return SimulateResult(
        date_processed=today,
        plans_processed=len(plans),
        lines_dispensed=lines_dispensed,
        total_qty_dispensed=sum(l.qty_dispensed for l in lines_dispensed),
    )


@router.get("/history", response_model=StockHistoryOut)
def stock_history(db: Session = Depends(get_db)):
    """Last 30 simulated-date snapshots for every tracked item."""
    dates = (
        db.execute(
            select(StockSnapshot.sim_date)
            .distinct()
            .order_by(StockSnapshot.sim_date.desc())
            .limit(30)
        )
        .scalars()
        .all()
    )
    if not dates:
        return StockHistoryOut(snapshots=[])

    snapshots = (
        db.execute(
            select(StockSnapshot)
            .options(selectinload(StockSnapshot.item))
            .where(StockSnapshot.sim_date.in_(dates))
            .order_by(StockSnapshot.sim_date, StockSnapshot.item_id)
        )
        .scalars()
        .all()
    )
    return StockHistoryOut(
        snapshots=[
            StockSnapshotPoint(
                sim_date=s.sim_date,
                item_id=s.item_id,
                item_name=s.item.name,
                qty_on_hand=s.qty_on_hand,
            )
            for s in snapshots
        ]
    )
