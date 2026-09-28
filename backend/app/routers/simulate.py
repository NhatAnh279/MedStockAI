import math
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Actor,
    AuditLog,
    Item,
    Patient,
    PlanStatus,
    Protocol,
    ProtocolItem,
    TreatmentPlan,
)
from app.routers.inventory import fefo_dispense
from app.schemas import DispenseSummaryLine, SimulateResult

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

    return SimulateResult(
        date_processed=today,
        plans_processed=len(plans),
        lines_dispensed=lines_dispensed,
        total_qty_dispensed=sum(l.qty_dispensed for l in lines_dispensed),
    )
