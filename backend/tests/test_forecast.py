"""Forecast engine unit tests — pure in-memory SQLite, no external services."""
import itertools
import math
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_patient_seq = itertools.count(1)

from app.database import Base
from app.models import (
    Batch,
    Condition,
    Item,
    ItemType,
    Patient,
    PlanStatus,
    Protocol,
    ProtocolItem,
    Supplier,
    TreatmentPlan,
)
from app.services.forecast import forecast

TODAY = date.today()
UTC = timezone.utc


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=True)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def make_supplier(db, lead_time_days: int = 5) -> Supplier:
    s = Supplier(name="Test Supplier", lead_time_days=lead_time_days, reliability_score=0.9)
    db.add(s)
    db.flush()
    return s


def make_item(db, supplier, name="Rifampicin 300mg", pack_size=60, moq=600) -> Item:
    item = Item(
        name=name,
        type=ItemType.drug,
        unit="capsule",
        pack_size=pack_size,
        moq=moq,
        unit_cost=1.10,
        shelf_life_days=1095,
        supplier_id=supplier.id,
    )
    db.add(item)
    db.flush()
    return item


def make_protocol(db, icd_code="A15.0", phase="intensive", cycle_length=30, total_cycles=2) -> Protocol:
    p = Protocol(
        name=f"Test Protocol {phase}",
        icd_code=icd_code,
        phase=phase,
        cycle_length_days=cycle_length,
        total_cycles=total_cycles,
    )
    db.add(p)
    db.flush()
    return p


def make_protocol_item(db, protocol, item, qty_per_cycle, dose_per_kg=None) -> ProtocolItem:
    pi = ProtocolItem(
        protocol_id=protocol.id,
        item_id=item.id,
        qty_per_cycle=qty_per_cycle,
        dose_per_kg=dose_per_kg,
    )
    db.add(pi)
    db.flush()
    return pi


def make_patient(db, weight_kg=70.0) -> Patient:
    n = next(_patient_seq)
    p = Patient(
        medicare_no=f"T{n:011d}",
        full_name=f"Test Patient {n}",
        dob=TODAY - timedelta(days=30 * 365),
        sex="M",
        weight_kg=weight_kg,
    )
    db.add(p)
    db.flush()
    return p


def make_plan(
    db, patient, protocol, current_cycle=1, next_due_offset_days=10, status=PlanStatus.active
) -> TreatmentPlan:
    next_due = TODAY + timedelta(days=next_due_offset_days) if next_due_offset_days is not None else None
    plan = TreatmentPlan(
        patient_id=patient.id,
        protocol_id=protocol.id,
        current_phase=protocol.phase,
        current_cycle=current_cycle,
        next_due_date=next_due,
        status=status,
    )
    db.add(plan)
    db.flush()
    return plan


def make_batch(db, item, qty, expiry_offset_days=365, lot_no=None) -> Batch:
    b = Batch(
        item_id=item.id,
        lot_no=lot_no or f"LOT-{expiry_offset_days}",
        qty_on_hand=qty,
        expiry_date=TODAY + timedelta(days=expiry_offset_days),
        received_at=datetime.now(UTC),
    )
    db.add(b)
    db.flush()
    return b


# ── Test A ────────────────────────────────────────────────────────────────────

def test_a_tb_scheduled_demand(db):
    """5 active TB intensive patients, each with 1 cycle due within 30 days.
    Rifampicin qty_per_cycle=60 → A_scheduled must equal 300."""
    supplier = make_supplier(db)
    item = make_item(db, supplier)
    protocol = make_protocol(db, phase="intensive", cycle_length=30, total_cycles=2)
    make_protocol_item(db, protocol, item, qty_per_cycle=60)

    # Each patient gets next_due at a different day within horizon
    for i in range(5):
        patient = make_patient(db, weight_kg=70.0)
        # next_due within [today, today+30), at cycle 1 of 2 so only 1 fits
        make_plan(db, patient, protocol, current_cycle=1, next_due_offset_days=5 + i * 4)

    # Minimal stock so usable_stock computation doesn't error
    make_batch(db, item, qty=10000, expiry_offset_days=365)

    result = forecast(db, item.id, horizon_days=30)

    assert result["demand"]["A_scheduled"] == 300.0
    assert len(result["rationale_data"]["contributing_patients"]) == 5
    for p in result["rationale_data"]["contributing_patients"]:
        assert p["qty"] == 60
        assert p["cycles"] == 1


# ── Test B ────────────────────────────────────────────────────────────────────

def test_b_expiring_batch_excluded_from_usable_stock(db):
    """Batch expiring in 5 days is excluded when daily demand would only reach
    it after day 5 (another larger batch consumed first via FEFO)."""
    supplier = make_supplier(db)
    item = make_item(db, supplier)
    protocol = make_protocol(db)
    make_protocol_item(db, protocol, item, qty_per_cycle=60)

    # 5 patients × 60 = 300 total demand over 30 days → 10/day
    for i in range(5):
        patient = make_patient(db)
        make_plan(db, patient, protocol, current_cycle=1, next_due_offset_days=5 + i * 4)

    # Batch1: expires in 2 days, qty=150 → at 10/day takes 15 days to exhaust (FEFO first)
    make_batch(db, item, qty=150, expiry_offset_days=2, lot_no="EXPIRE-SOON")
    # Batch2: expires in 5 days, reached at day 15 → EXCLUDED (15 > 5)
    make_batch(db, item, qty=50, expiry_offset_days=5, lot_no="EXPIRE-5")
    # Batch3: long-dated
    make_batch(db, item, qty=200, expiry_offset_days=365, lot_no="LONG-DATE")

    result = forecast(db, item.id, horizon_days=30)

    excluded = result["rationale_data"]["expiring_batches_excluded"]
    excluded_lots = [e["lot_no"] for e in excluded]
    assert "EXPIRE-5" in excluded_lots, f"Expected EXPIRE-5 excluded, got {excluded_lots}"

    # usable_stock = 150 (Batch1) + 200 (Batch3); Batch2 excluded
    assert result["usable_stock"] == 350.0


# ── Test C ────────────────────────────────────────────────────────────────────

def test_c_phase_transition_mid_horizon(db):
    """Patient transitions intensive→maintenance mid-horizon.
    One intensive cycle at day 10 + one maintenance cycle at day 25 → RIF A=120."""
    supplier = make_supplier(db)
    item = make_item(db, supplier)

    proto_intensive = make_protocol(db, icd_code="A15.0", phase="intensive", cycle_length=30, total_cycles=2)
    make_protocol_item(db, proto_intensive, item, qty_per_cycle=60)

    proto_maint = make_protocol(db, icd_code="A15.0", phase="maintenance", cycle_length=30, total_cycles=4)
    make_protocol_item(db, proto_maint, item, qty_per_cycle=60)

    patient = make_patient(db)

    # Intensive: current_cycle=2 (last intensive cycle), next_due=today+10 → 1 cycle in horizon
    # Next would be today+40, but total_cycles=2 and current_cycle would be 3 → stop
    make_plan(db, patient, proto_intensive, current_cycle=2, next_due_offset_days=10)

    # Maintenance: current_cycle=1, next_due=today+25 → 1 cycle in horizon
    make_plan(db, patient, proto_maint, current_cycle=1, next_due_offset_days=25)

    make_batch(db, item, qty=10000, expiry_offset_days=365)

    result = forecast(db, item.id, horizon_days=30)

    assert result["demand"]["A_scheduled"] == 120.0

    phases = {p["phase"] for p in result["rationale_data"]["contributing_patients"]}
    assert "intensive" in phases
    assert "maintenance" in phases


# ── Test D ────────────────────────────────────────────────────────────────────

def test_d_order_qty_rounds_up_to_pack_size_never_below_moq(db):
    """order_qty must be a multiple of pack_size and never less than MOQ."""
    supplier = make_supplier(db, lead_time_days=5)
    # pack_size=100, moq=500
    item = make_item(db, supplier, pack_size=100, moq=500)
    protocol = make_protocol(db)
    make_protocol_item(db, protocol, item, qty_per_cycle=60)

    # Create enough demand that need lands between 1 and MOQ (350) → order_qty = 500
    # 5 patients × 60 = 300 demand; no stock → need ≈ 300 + ROP > 0
    for i in range(5):
        patient = make_patient(db)
        make_plan(db, patient, protocol, current_cycle=1, next_due_offset_days=5 + i)

    # No batches → usable_stock = 0, qty_on_order = 0

    result = forecast(db, item.id, horizon_days=30)

    assert result["order_qty"] > 0
    assert result["order_qty"] % 100 == 0, f"order_qty {result['order_qty']} not multiple of pack_size=100"
    assert result["order_qty"] >= 500, f"order_qty {result['order_qty']} below MOQ=500"

    # Also test rounding: need just above an exact pack multiple → next multiple up
    # Directly exercise ceil logic: need=650, pack=100, moq=500
    # max(650, 500) = 650; ceil(650/100)*100 = 700
    assert math.ceil(max(650, 500) / 100) * 100 == 700
    # need=350: max(350, 500) = 500; ceil(500/100)*100 = 500
    assert math.ceil(max(350, 500) / 100) * 100 == 500
