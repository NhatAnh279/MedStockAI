"""Natural-language inventory assistant: Claude answers questions by calling read-only tools.

Every figure comes from the tools (which wrap the forecast engine and the DB); the model
only phrases the answer. Tools are plain Python functions taking (db, **args); TOOLS holds
their JSON schemas and _DISPATCH maps names to functions.
"""
import calendar
import json
import logging
import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import (
    AuditLog,
    Batch,
    Item,
    Patient,
    PlanStatus,
    POLine,
    POStatus,
    Protocol,
    ProtocolItem,
    PurchaseOrder,
    Supplier,
    SupplierPrice,
    StockTxn,
    TreatmentPlan,
)
from app.routers.inventory import expiring_batches
from app.services.forecast import forecast
from app.services.llm import get_client
from app.services.reorder import run_reorder

log = logging.getLogger(__name__)

HORIZON_DAYS = 30
MAX_TOOL_ROUNDS = 6
MAX_HISTORY = 10


class ChatUnavailable(Exception):
    """No API key configured, or the Claude API could not be reached."""


# ── Shared helpers ────────────────────────────────────────────────────────────


def _find_items(db: Session, name: str) -> list[Item]:
    items = db.execute(select(Item).order_by(Item.name)).scalars().all()
    key = name.strip().lower()
    hits = [i for i in items if key in i.name.lower()]
    if not hits:  # every word must appear
        words = [w.rstrip("s") for w in re.findall(r"[a-z0-9]+", key)]
        hits = [i for i in items if words and all(w in i.name.lower() for w in words)]
    return hits


def _find_protocols(db: Session, name: str) -> list[Protocol]:
    key = name.strip().lower()
    protocols = db.execute(select(Protocol)).scalars().all()
    return [p for p in protocols if key in p.name.lower() or key in p.icd_code.lower()]


_CONDITION_ALIASES = {
    "tuberculosis": "tb",
    "chemo": "cancer",
    "chemotherapy": "cancer",
    "oncology": "cancer",
    "breast": "cancer",
    "kidney": "dialysis",
    "renal": "dialysis",
    "ckd": "dialysis",
    "diabetes": "t2dm",
    "diabetic": "t2dm",
}


def _protocol_matches(protocol: Protocol, needles: set[str]) -> bool:
    name = protocol.name.lower()
    for n in needles:
        if protocol.icd_code.lower().startswith(n):
            return True
        if len(n) <= 3:
            if re.search(rf"\b{re.escape(n)}\b", name):
                return True
        elif n in name:
            return True
    return False


def _needles_for(condition: str) -> set[str]:
    key = condition.strip().lower()
    return {key} | {alias for word, alias in _CONDITION_ALIASES.items() if word in key}


# ── Inventory & Stock tools ───────────────────────────────────────────────────


def get_low_stock(db: Session, days: int) -> dict[str, Any]:
    rows = [
        r
        for r in run_reorder(db, horizon_days=HORIZON_DAYS)
        if r["days_until_stockout"] is not None and r["days_until_stockout"] < days
    ]
    return {
        "threshold_days": days,
        "count": len(rows),
        "items": [
            {
                "item_name": r["item_name"],
                "days_until_stockout": r["days_until_stockout"],
                "usable_stock": r["usable_stock"],
                "qty_on_order": r["qty_on_order"],
                "needs_order": r["needs_order"],
                "suggested_order_qty": r["order_qty"],
            }
            for r in rows
        ],
    }


def get_supplier_prices(db: Session, item_name: str | None = None) -> dict[str, Any]:
    today = date.today()
    stmt = (
        select(SupplierPrice)
        .options(selectinload(SupplierPrice.supplier), selectinload(SupplierPrice.item))
        .where((SupplierPrice.valid_to == None) | (SupplierPrice.valid_to >= today))  # noqa: E711
        .order_by(SupplierPrice.unit_price)
    )
    rows = db.execute(stmt).scalars().all()
    if item_name:
        matched_ids = {i.id for i in _find_items(db, item_name)}
        if not matched_ids:
            return {"error": f"No item matching '{item_name}'."}
        rows = [r for r in rows if r.item_id in matched_ids]
    return {
        "count": len(rows),
        "prices": [
            {
                "item_name": r.item.name,
                "unit": r.item.unit,
                "supplier_name": r.supplier.name,
                "unit_price_aud": float(r.unit_price),
                "pack_size": r.item.pack_size,
                "min_order_qty": r.min_order_qty,
                "valid_from": r.valid_from.isoformat(),
                "valid_to": r.valid_to.isoformat() if r.valid_to else None,
            }
            for r in rows
        ],
    }


def get_stock_transactions(db: Session, item_name: str, days: int = 30) -> dict[str, Any]:
    matches = _find_items(db, item_name)
    if not matches:
        return {"error": f"No item matching '{item_name}'."}
    cutoff = datetime.utcnow() - timedelta(days=days)
    results = []
    for item in matches[:3]:
        txns = (
            db.execute(
                select(StockTxn)
                .where(StockTxn.item_id == item.id, StockTxn.created_at >= cutoff)
                .order_by(StockTxn.created_at.desc())
            )
            .scalars()
            .all()
        )
        summary: dict[str, int] = {}
        for t in txns:
            reason = t.reason.value
            summary[reason] = summary.get(reason, 0) + abs(t.qty_delta)
        results.append({
            "item_name": item.name,
            "unit": item.unit,
            "window_days": days,
            "transaction_count": len(txns),
            "summary_by_reason": summary,
            "transactions": [
                {
                    "date": t.created_at.date().isoformat(),
                    "reason": t.reason.value,
                    "qty_delta": t.qty_delta,
                }
                for t in txns[:50]
            ],
        })
    return {"items": results}


def get_batch_details(db: Session, item_name: str) -> dict[str, Any]:
    matches = _find_items(db, item_name)
    if not matches:
        return {"error": f"No item matching '{item_name}'."}
    today = date.today()
    results = []
    for item in matches[:3]:
        batches = (
            db.execute(
                select(Batch)
                .where(Batch.item_id == item.id)
                .order_by(Batch.expiry_date)
            )
            .scalars()
            .all()
        )
        results.append({
            "item_name": item.name,
            "unit": item.unit,
            "batch_count": len(batches),
            "total_qty_on_hand": sum(b.qty_on_hand for b in batches),
            "batches": [
                {
                    "lot_no": b.lot_no,
                    "qty_on_hand": b.qty_on_hand,
                    "expiry_date": b.expiry_date.isoformat(),
                    "days_until_expiry": (b.expiry_date - today).days,
                    "received_at": b.received_at.date().isoformat(),
                }
                for b in batches
            ],
        })
    return {"items": results}


def get_inventory_value(db: Session) -> dict[str, Any]:
    rows = db.execute(
        select(
            Item.id,
            Item.name,
            Item.type,
            Item.unit,
            Item.unit_cost,
            func.coalesce(func.sum(Batch.qty_on_hand), 0).label("total_qty"),
        )
        .outerjoin(Batch, Batch.item_id == Item.id)
        .group_by(Item.id)
        .order_by(Item.name)
    ).all()

    by_type: dict[str, float] = {}
    total = 0.0
    items_detail = []
    for row in rows:
        value = float(row.total_qty) * float(row.unit_cost)
        total += value
        cat = row.type.value if hasattr(row.type, "value") else str(row.type)
        by_type[cat] = by_type.get(cat, 0.0) + value
        if value > 0:
            items_detail.append({
                "item_name": row.name,
                "type": cat,
                "unit": row.unit,
                "qty_on_hand": int(row.total_qty),
                "unit_cost_aud": round(float(row.unit_cost), 4),
                "total_value_aud": round(value, 2),
            })
    items_detail.sort(key=lambda x: x["total_value_aud"], reverse=True)
    return {
        "total_inventory_value_aud": round(total, 2),
        "by_category": {k: round(v, 2) for k, v in by_type.items()},
        "top_items": items_detail[:20],
    }


# ── Forecast & Procurement tools ──────────────────────────────────────────────


def get_forecast(db: Session, item_name: str) -> dict[str, Any]:
    matches = _find_items(db, item_name)
    if not matches:
        return {"error": f"No item matching '{item_name}'."}
    out = []
    for item in matches[:3]:
        f = forecast(db, item.id, HORIZON_DAYS)
        rd = f["rationale_data"]
        out.append({
            "item_name": f["item_name"],
            "horizon_days": f["horizon_days"],
            "demand": f["demand"],
            "usable_stock": f["usable_stock"],
            "qty_on_order": f["qty_on_order"],
            "reorder_point": f["ROP"],
            "order_qty": f["order_qty"],
            "days_until_stockout": f["days_until_stockout"],
            "patients_on_active_plans": len(rd["contributing_patients"]),
            "expiring_batches_excluded": rd["expiring_batches_excluded"],
        })
    result: dict[str, Any] = {"forecasts": out}
    if len(matches) > 3:
        result["other_matches"] = [i.name for i in matches[3:]]
    return result


def get_po_cost_summary(db: Session) -> dict[str, Any]:
    rows = db.execute(
        select(
            PurchaseOrder.status,
            func.count(PurchaseOrder.id).label("po_count"),
            func.coalesce(func.sum(PurchaseOrder.total), 0).label("total_aud"),
        ).group_by(PurchaseOrder.status)
    ).all()
    by_status = {
        r.status.value: {"po_count": r.po_count, "total_aud": round(float(r.total_aud), 2)}
        for r in rows
    }
    grand_total = sum(v["total_aud"] for v in by_status.values())
    return {
        "grand_total_aud": round(grand_total, 2),
        "by_status": by_status,
    }


def get_budget_estimate(db: Session, horizon_days: int = 30) -> dict[str, Any]:
    reorder_rows = run_reorder(db, horizon_days=horizon_days)
    items_map = {
        i.id: i
        for i in db.execute(select(Item).options(selectinload(Item.supplier))).scalars().all()
    }
    today = date.today()
    # Best current price per item from SupplierPrice; fall back to item.unit_cost
    prices = (
        db.execute(
            select(SupplierPrice)
            .options(selectinload(SupplierPrice.supplier))
            .where((SupplierPrice.valid_to == None) | (SupplierPrice.valid_to >= today))  # noqa: E711
        )
        .scalars()
        .all()
    )
    best_price: dict[int, tuple[float, str]] = {}  # item_id -> (unit_price, supplier_name)
    for sp in prices:
        existing = best_price.get(sp.item_id)
        if existing is None or sp.unit_price < existing[0]:
            best_price[sp.item_id] = (float(sp.unit_price), sp.supplier.name)

    by_supplier: dict[str, float] = {}
    line_items = []
    for r in reorder_rows:
        if not r["needs_order"] or r["order_qty"] <= 0:
            continue
        item = items_map.get(r["item_id"])
        if not item:
            continue
        if r["item_id"] in best_price:
            unit_price, supplier_name = best_price[r["item_id"]]
        else:
            unit_price = float(item.unit_cost)
            supplier_name = item.supplier.name if item.supplier else "unknown"
        est_cost = round(r["order_qty"] * unit_price, 2)
        by_supplier[supplier_name] = by_supplier.get(supplier_name, 0.0) + est_cost
        line_items.append({
            "item_name": r["item_name"],
            "order_qty": r["order_qty"],
            "unit_price_aud": unit_price,
            "estimated_cost_aud": est_cost,
            "supplier": supplier_name,
            "days_until_stockout": r["days_until_stockout"],
        })
    line_items.sort(key=lambda x: x["estimated_cost_aud"], reverse=True)
    total = sum(by_supplier.values())
    return {
        "horizon_days": horizon_days,
        "estimated_total_aud": round(total, 2),
        "by_supplier": {k: round(v, 2) for k, v in sorted(by_supplier.items(), key=lambda x: -x[1])},
        "line_items": line_items,
    }


def get_forecast_detail(db: Session, item_name: str) -> dict[str, Any]:
    matches = _find_items(db, item_name)
    if not matches:
        return {"error": f"No item matching '{item_name}'."}
    item = matches[0]
    f = forecast(db, item.id, HORIZON_DAYS)
    rd = f["rationale_data"]
    return {
        "item_name": f["item_name"],
        "horizon_days": f["horizon_days"],
        "demand_breakdown": {
            "A_scheduled_treatments": round(f["demand"]["A_scheduled"]),
            "B_dispensing_baseline": round(f["demand"]["B_baseline"]),
            "C_new_patient_intake": round(f["demand"]["C_new_intake"]),
            "total": round(f["demand"]["total"]),
        },
        "usable_stock": round(f["usable_stock"]),
        "qty_on_order": round(f["qty_on_order"]),
        "reorder_point": round(f["ROP"]),
        "suggested_order_qty": round(f["order_qty"]),
        "days_until_stockout": (
            round(f["days_until_stockout"]) if f["days_until_stockout"] is not None else None
        ),
        "contributing_patients": len(rd["contributing_patients"]),
        "contributing_patient_names": [p["name"] for p in rd["contributing_patients"][:10]],
        "expiring_batches_excluded": rd["expiring_batches_excluded"],
    }


def get_reorder_summary(db: Session) -> dict[str, Any]:
    reorder_rows = run_reorder(db, horizon_days=HORIZON_DAYS)
    items_map = {
        i.id: i
        for i in db.execute(select(Item).options(selectinload(Item.supplier))).scalars().all()
    }
    needs_order = [r for r in reorder_rows if r["needs_order"]]
    summary = []
    for r in needs_order:
        item = items_map.get(r["item_id"])
        unit_cost = float(item.unit_cost) if item else 0.0
        supplier_name = item.supplier.name if item and item.supplier else None
        summary.append({
            "item_name": r["item_name"],
            "order_qty": r["order_qty"],
            "estimated_cost_aud": round(r["order_qty"] * unit_cost, 2),
            "days_until_stockout": r["days_until_stockout"],
            "usable_stock": round(r["usable_stock"]),
            "recommended_supplier": supplier_name,
        })
    total_est = sum(s["estimated_cost_aud"] for s in summary)
    return {
        "items_needing_order": len(summary),
        "estimated_total_cost_aud": round(total_est, 2),
        "items": summary,
    }


# ── Patient & Protocol tools ──────────────────────────────────────────────────


def get_patient_summary(db: Session, condition: str) -> dict[str, Any]:
    needles = _needles_for(condition)
    protocols = db.execute(select(Protocol)).scalars().all()
    matched = [p for p in protocols if _protocol_matches(p, needles)]
    if not matched:
        return {
            "error": f"No treatment protocol matches '{condition}'.",
            "available_protocols": sorted({p.name for p in protocols}),
        }
    rows = db.execute(
        select(
            Protocol.name,
            TreatmentPlan.current_phase,
            TreatmentPlan.status,
            func.count(func.distinct(Patient.id)),
        )
        .join(TreatmentPlan, TreatmentPlan.protocol_id == Protocol.id)
        .join(Patient, Patient.id == TreatmentPlan.patient_id)
        .where(Protocol.id.in_([p.id for p in matched]))
        .group_by(Protocol.name, TreatmentPlan.current_phase, TreatmentPlan.status)
    ).all()

    by_phase: dict[str, dict[str, int]] = {}
    by_status: dict[str, int] = {}
    for _, phase, status, n in rows:
        by_phase.setdefault(phase, {})[status.value] = n
        by_status[status.value] = by_status.get(status.value, 0) + n
    return {
        "condition": condition,
        "matched_protocols": [p.name for p in matched],
        "patients_in_treatment": by_status.get("active", 0),
        "patients_by_plan_status": by_status,
        "by_phase": by_phase,
    }


def get_patient_list(db: Session, condition: str | None = None, phase: str | None = None) -> dict[str, Any]:
    plans = (
        db.execute(
            select(TreatmentPlan)
            .options(selectinload(TreatmentPlan.patient), selectinload(TreatmentPlan.protocol))
            .where(TreatmentPlan.status == PlanStatus.active)
            .order_by(TreatmentPlan.next_due_date)
        )
        .scalars()
        .all()
    )
    if condition:
        needles = _needles_for(condition)
        plans = [p for p in plans if _protocol_matches(p.protocol, needles)]
    if phase:
        phase_key = phase.strip().lower()
        plans = [p for p in plans if phase_key in p.current_phase.lower()]
    return {
        "count": len(plans),
        "patients": [
            {
                "patient_name": p.patient.full_name,
                "patient_id": p.patient_id,
                "protocol_name": p.protocol.name,
                "current_phase": p.current_phase,
                "current_cycle": p.current_cycle,
                "next_due_date": p.next_due_date.isoformat() if p.next_due_date else None,
                "weight_kg": p.patient.weight_kg,
            }
            for p in plans[:50]
        ],
    }


def get_protocol_details(db: Session, protocol_name: str) -> dict[str, Any]:
    matches = _find_protocols(db, protocol_name)
    if not matches:
        all_names = db.execute(select(Protocol.name).distinct()).scalars().all()
        return {"error": f"No protocol matching '{protocol_name}'.", "available": sorted(all_names)}
    results = []
    for proto in matches[:5]:
        proto_items = (
            db.execute(
                select(ProtocolItem)
                .options(selectinload(ProtocolItem.item))
                .where(ProtocolItem.protocol_id == proto.id)
            )
            .scalars()
            .all()
        )
        results.append({
            "name": proto.name,
            "icd_code": proto.icd_code,
            "phase": proto.phase,
            "cycle_length_days": proto.cycle_length_days,
            "total_cycles": proto.total_cycles,
            "items": [
                {
                    "item_name": pi.item.name,
                    "item_type": pi.item.type.value,
                    "unit": pi.item.unit,
                    "qty_per_cycle": pi.qty_per_cycle,
                    "dose_per_kg": pi.dose_per_kg,
                }
                for pi in proto_items
            ],
        })
    return {"protocols": results}


def get_treatment_summary(db: Session) -> dict[str, Any]:
    rows = db.execute(
        select(
            Protocol.name,
            TreatmentPlan.current_phase,
            TreatmentPlan.status,
            func.count(func.distinct(TreatmentPlan.patient_id)).label("n"),
            func.min(TreatmentPlan.next_due_date).label("earliest_due"),
        )
        .join(TreatmentPlan, TreatmentPlan.protocol_id == Protocol.id)
        .group_by(Protocol.name, TreatmentPlan.current_phase, TreatmentPlan.status)
        .order_by(Protocol.name, TreatmentPlan.current_phase)
    ).all()

    breakdown = []
    for row in rows:
        breakdown.append({
            "protocol": row.name,
            "phase": row.current_phase,
            "status": row.status.value if hasattr(row.status, "value") else str(row.status),
            "patient_count": row.n,
            "earliest_next_due": row.earliest_due.isoformat() if row.earliest_due else None,
        })
    active_total = sum(r["patient_count"] for r in breakdown if r["status"] == "active")
    return {
        "total_active_patients": active_total,
        "breakdown": breakdown,
    }


def get_patients_due_soon(db: Session, days: int = 7) -> dict[str, Any]:
    cutoff = date.today() + timedelta(days=days)
    plans = (
        db.execute(
            select(TreatmentPlan)
            .options(
                selectinload(TreatmentPlan.patient),
                selectinload(TreatmentPlan.protocol)
                .selectinload(Protocol.items)
                .selectinload(ProtocolItem.item),
            )
            .where(
                TreatmentPlan.status == PlanStatus.active,
                TreatmentPlan.next_due_date <= cutoff,
            )
            .order_by(TreatmentPlan.next_due_date)
        )
        .scalars()
        .all()
    )
    results = []
    today = date.today()
    for plan in plans:
        items_needed = []
        for pi in plan.protocol.items:
            qty = (
                math.ceil(pi.dose_per_kg * plan.patient.weight_kg)
                if pi.dose_per_kg
                else pi.qty_per_cycle
            )
            items_needed.append({
                "item_name": pi.item.name,
                "unit": pi.item.unit,
                "qty_needed": qty,
            })
        results.append({
            "patient_name": plan.patient.full_name,
            "patient_id": plan.patient_id,
            "protocol_name": plan.protocol.name,
            "phase": plan.current_phase,
            "next_due_date": plan.next_due_date.isoformat() if plan.next_due_date else None,
            "days_until_due": (plan.next_due_date - today).days if plan.next_due_date else None,
            "items_needed": items_needed,
        })
    return {
        "window_days": days,
        "patients_due": len(results),
        "patients": results,
    }


# ── Supplier tools ────────────────────────────────────────────────────────────


def get_supplier_info(db: Session, supplier_name: str | None = None) -> dict[str, Any]:
    suppliers = db.execute(
        select(Supplier).options(selectinload(Supplier.backup_supplier))
    ).scalars().all()
    if supplier_name:
        key = supplier_name.strip().lower()
        suppliers = [s for s in suppliers if key in s.name.lower()]
        if not suppliers:
            all_names = sorted(s.name for s in db.execute(select(Supplier)).scalars().all())
            return {"error": f"No supplier matching '{supplier_name}'.", "available": all_names}
    return {
        "count": len(suppliers),
        "suppliers": [
            {
                "name": s.name,
                "contact_person": s.contact_person,
                "email": s.email,
                "phone": s.phone,
                "address": s.address,
                "lead_time_days": s.lead_time_days,
                "payment_terms": s.payment_terms,
                "reliability_score": round(s.reliability_score, 3),
                "backup_supplier": s.backup_supplier.name if s.backup_supplier else None,
            }
            for s in suppliers
        ],
    }


def get_supplier_performance(db: Session) -> dict[str, Any]:
    suppliers = db.execute(select(Supplier)).scalars().all()
    # Tally partial/rejected replies from parsed POs
    partial_counts: dict[int, int] = {}
    po_counts: dict[int, int] = {}
    pos = db.execute(
        select(PurchaseOrder).where(PurchaseOrder.reply_parsed != None)  # noqa: E711
    ).scalars().all()
    for po in pos:
        sid = po.supplier_id
        po_counts[sid] = po_counts.get(sid, 0) + 1
        if po.reply_parsed and po.reply_parsed.get("status") in ("partial", "rejected"):
            partial_counts[sid] = partial_counts.get(sid, 0) + 1
    return {
        "suppliers": [
            {
                "name": s.name,
                "reliability_score": round(s.reliability_score, 3),
                "lead_time_days": s.lead_time_days,
                "payment_terms": s.payment_terms,
                "parsed_replies": po_counts.get(s.id, 0),
                "partial_or_rejected": partial_counts.get(s.id, 0),
                "fulfillment_rate": round(
                    1.0 - partial_counts.get(s.id, 0) / max(po_counts.get(s.id, 1), 1), 3
                ),
            }
            for s in sorted(suppliers, key=lambda x: -x.reliability_score)
        ]
    }


# ── Remaining original tools ──────────────────────────────────────────────────


def get_expiring_batches(db: Session, days: int) -> dict[str, Any]:
    rows = expiring_batches(days=days, db=db)
    return {
        "window_days": days,
        "window_end_date": (date.today() + timedelta(days=days)).isoformat(),
        "count": len(rows),
        "batches": [
            {
                "item_name": r.item_name,
                "lot_no": r.lot_no,
                "qty_on_hand": r.qty_on_hand,
                "expiry_date": r.expiry_date.isoformat(),
                "days_until_expiry": r.days_until_expiry,
            }
            for r in rows
        ],
    }


def get_order_status(db: Session) -> dict[str, Any]:
    pos = (
        db.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.status != POStatus.received)
            .options(
                selectinload(PurchaseOrder.supplier),
                selectinload(PurchaseOrder.lines).selectinload(POLine.item),
            )
            .order_by(PurchaseOrder.created_at.desc())
        )
        .scalars()
        .all()
    )
    return {
        "note": "Open purchase orders only (received orders are excluded).",
        "count": len(pos),
        "orders": [
            {
                "po_id": po.id,
                "supplier": po.supplier.name,
                "status": po.status.value,
                "created_by": po.created_by.value,
                "lines": [{"item_name": l.item.name, "qty": l.qty} for l in po.lines],
                "total_aud": float(po.total),
                "created_at": po.created_at.date().isoformat(),
            }
            for po in pos
        ],
    }


def get_audit_log(db: Session, entity: str | None = None, limit: int = 20) -> dict[str, Any]:
    stmt = select(AuditLog).order_by(AuditLog.ts.desc()).limit(min(limit, 100))
    if entity:
        stmt = stmt.where(AuditLog.entity.ilike(f"%{entity}%"))
    rows = db.execute(stmt).scalars().all()
    return {
        "count": len(rows),
        "entries": [
            {
                "id": r.id,
                "actor": r.actor.value,
                "action": r.action,
                "entity": r.entity,
                "entity_id": r.entity_id,
                "ts": r.ts.isoformat(),
                "after": r.after,
            }
            for r in rows
        ],
    }


def get_simulation_date(db: Session) -> dict[str, Any]:
    from app.routers.simulate import current_sim_date
    today = current_sim_date()
    return {
        "today": today.isoformat(),
        "day_of_week": today.strftime("%A"),
        "note": "Current simulated date used by the forecast and advance-day engines.",
    }


# ── Tool schemas ──────────────────────────────────────────────────────────────


def _schema(
    name: str,
    description: str,
    props: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    props = props or {}
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": required if required is not None else list(props),
        },
    }


_INT = {"type": "integer"}
_STR = {"type": "string"}
_OPT_STR = {"type": ["string", "null"]}

TOOLS = [
    # ── Inventory & Stock ──
    _schema(
        "get_low_stock",
        "Items forecast to run out within N days (30-day demand: scheduled treatments + dispensing "
        "baseline + new patients, against usable non-expiring stock). Sorted most urgent first. "
        "Use for 'what's running low' and 'what should we prepare/order'.",
        {"days": {**_INT, "description": "Only items with fewer than this many days of stock, e.g. 14 or 30."}},
    ),
    _schema(
        "get_supplier_prices",
        "Current unit prices, pack sizes and MOQs from the supplier price list. "
        "When item_name is omitted, returns all active prices. "
        "Always call this alongside get_forecast_detail or get_reorder_summary when the user asks about cost.",
        {"item_name": {**_OPT_STR, "description": "Item name or part of it, or null for all items."}},
        required=[],
    ),
    _schema(
        "get_stock_transactions",
        "Recent stock transaction history for an item: dispenses, receives, waste adjustments. "
        "Useful for 'how fast are we using X' or 'when did we last receive Y'.",
        {
            "item_name": {**_STR, "description": "Item name or part of it."},
            "days": {**_INT, "description": "Look-back window in days (default 30)."},
        },
        required=["item_name"],
    ),
    _schema(
        "get_batch_details",
        "All stock batches for an item: lot numbers, qty on hand, expiry dates and receipt dates. "
        "Use to inspect individual batches or find the oldest/newest stock.",
        {"item_name": {**_STR, "description": "Item name or part of it."}},
    ),
    _schema(
        "get_inventory_value",
        "Total AUD value of current stock (qty on hand × unit cost), broken down by category "
        "(drug vs consumable). Returns the top 20 most valuable items.",
    ),
    # ── Forecast & Procurement ──
    _schema(
        "get_forecast",
        "Forecast summary for up to three matching items: demand A+B+C, usable stock, reorder point, "
        "suggested order qty, days until stockout.",
        {"item_name": {**_STR, "description": "Item name or part of it, e.g. 'Rifampicin' or 'insulin'."}},
    ),
    _schema(
        "get_po_cost_summary",
        "Total AUD value of purchase orders grouped by status (draft, pending_approval, sent, "
        "confirmed, received). Use for 'how much do we have on order' questions.",
    ),
    _schema(
        "get_budget_estimate",
        "Estimated total spend to cover demand for the next N days, broken down by supplier. "
        "Uses the best current price from the supplier price list. "
        "Always call get_supplier_prices alongside this when the user asks about costs.",
        {"horizon_days": {**_INT, "description": "Forecast horizon in days (default 30)."}},
        required=[],
    ),
    _schema(
        "get_forecast_detail",
        "Full A+B+C demand breakdown for one item with contributing patient names, usable stock, "
        "reorder point, suggested order qty and days until stockout. "
        "Use when the user wants to understand why an item is forecast a certain amount.",
        {"item_name": {**_STR, "description": "Item name or part of it."}},
    ),
    _schema(
        "get_reorder_summary",
        "Items that need ordering now: name, suggested order qty, estimated cost (at unit_cost), "
        "days until stockout, and recommended supplier. "
        "Call get_supplier_prices too when the user wants accurate cost figures.",
    ),
    # ── Patient & Protocol ──
    _schema(
        "get_patient_summary",
        "Count of patients on a treatment protocol for a condition, broken down by treatment phase "
        "and plan status. Conditions: TB, breast cancer/chemo, haemodialysis, type 2 diabetes.",
        {"condition": {**_STR, "description": "Condition name, e.g. 'TB', 'dialysis', 'diabetes'."}},
    ),
    _schema(
        "get_patient_list",
        "List of active patients filtered by condition and/or treatment phase, with next due date "
        "and weight. Returns up to 50 patients.",
        {
            "condition": {**_OPT_STR, "description": "Condition keyword, or null for all conditions."},
            "phase": {**_OPT_STR, "description": "Treatment phase keyword, or null for all phases."},
        },
        required=[],
    ),
    _schema(
        "get_protocol_details",
        "Full protocol definition: ICD-10 code, phase, cycle length, total cycles, and all "
        "drugs/consumables with quantities per cycle and dose-per-kg where applicable.",
        {"protocol_name": {**_STR, "description": "Protocol name or part of it."}},
    ),
    _schema(
        "get_treatment_summary",
        "Count of all active/paused/completed patients by condition and phase, with earliest "
        "next-due dates. Use for a high-level overview of patient load.",
    ),
    _schema(
        "get_patients_due_soon",
        "Patients whose next treatment cycle is due within N days, with itemised quantities needed "
        "per patient (accounting for weight-based dosing).",
        {"days": {**_INT, "description": "Look-ahead window in days (default 7)."}},
        required=[],
    ),
    # ── Supplier ──
    _schema(
        "get_supplier_info",
        "Supplier contact details, lead time, payment terms, reliability score and backup supplier. "
        "Omit supplier_name to list all suppliers.",
        {"supplier_name": {**_OPT_STR, "description": "Supplier name or part of it, or null for all."}},
        required=[],
    ),
    _schema(
        "get_supplier_performance",
        "Reliability scores, lead times, payment terms and partial/rejected fulfilment counts "
        "for all suppliers, sorted by reliability.",
    ),
    # ── Original tools kept ──
    _schema(
        "get_expiring_batches",
        "Stock batches that expire between today and N days from today, soonest first.",
        {"days": {**_INT, "description": "Look-ahead window in days from today."}},
    ),
    _schema(
        "get_order_status",
        "All open purchase orders (draft, pending approval, sent, confirmed) with supplier, "
        "status, line items and total.",
    ),
    # ── System ──
    _schema(
        "get_audit_log",
        "Recent audit log entries showing who (ai/user) did what and when. "
        "Filter by entity type, e.g. 'protocols', 'purchase_orders', 'treatment_plans'.",
        {
            "entity": {**_OPT_STR, "description": "Entity type to filter by, or null for all entries."},
            "limit": {**_INT, "description": "Max entries to return (default 20, max 100)."},
        },
        required=[],
    ),
    _schema(
        "get_simulation_date",
        "Returns the current date used by the simulation and forecast engines. "
        "Call this when the user asks about today's date or the current simulated date.",
    ),
]

_DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "get_low_stock": get_low_stock,
    "get_supplier_prices": get_supplier_prices,
    "get_stock_transactions": get_stock_transactions,
    "get_batch_details": get_batch_details,
    "get_inventory_value": get_inventory_value,
    "get_forecast": get_forecast,
    "get_po_cost_summary": get_po_cost_summary,
    "get_budget_estimate": get_budget_estimate,
    "get_forecast_detail": get_forecast_detail,
    "get_reorder_summary": get_reorder_summary,
    "get_patient_summary": get_patient_summary,
    "get_patient_list": get_patient_list,
    "get_protocol_details": get_protocol_details,
    "get_treatment_summary": get_treatment_summary,
    "get_patients_due_soon": get_patients_due_soon,
    "get_supplier_info": get_supplier_info,
    "get_supplier_performance": get_supplier_performance,
    "get_expiring_batches": get_expiring_batches,
    "get_order_status": get_order_status,
    "get_audit_log": get_audit_log,
    "get_simulation_date": get_simulation_date,
}


# ── Chat loop ────────────────────────────────────────────────────────────────


def _system_prompt() -> str:
    today = date.today()
    eom = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    nm = eom + timedelta(days=1)
    eonm = nm.replace(day=calendar.monthrange(nm.year, nm.month)[1])
    return (
        "You are MedStock AI, an inventory assistant for a hospital pharmacy in Australia. "
        f"Today is {today:%A} {today.isoformat()}. The current month ends on {eom.isoformat()} "
        f"({(eom - today).days} days from today); next month ends on {eonm.isoformat()} "
        f"({(eonm - today).days} days from today).\n\n"
        "## Tool use rules\n"
        "- Always call the relevant tools before answering. Never guess or compute figures yourself.\n"
        "- Only quote numbers that a tool returned. If a tool returns an error or no data, say so.\n"
        "- For cost or budget questions, call BOTH the forecast/reorder tool AND get_supplier_prices "
        "so you have accurate unit costs.\n"
        "- If multiple tools are needed to fully answer the question, call them all before replying.\n"
        "- For 'this month' or 'next month' use the day counts above as the days argument.\n"
        "- Only report items inside the window asked about; if empty, say so plainly, then "
        "mention the next items beyond the window, clearly labelled as outside it.\n\n"
        "## Response format\n"
        "- Write in clear English. Use bullet points for lists of items.\n"
        "- **Bold** key numbers (quantities, costs, days) so they stand out.\n"
        "- No markdown headings or tables. Dates as day month year.\n"
        "- Be concise — summarise long lists (show the 8 most urgent, then 'and N more').\n"
        "- Do not add urgency labels or advice beyond what the data shows.\n"
        "- Do not link an item to a purchase order unless the tool result shows it."
    )


def _clean_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    msgs = [{"role": m["role"], "content": m["content"]} for m in history[-MAX_HISTORY:] if m["content"].strip()]
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


def answer(db: Session, message: str, history: list[dict[str, str]] | None = None) -> tuple[str, list[str]]:
    """Run the tool-calling loop. Returns (response_text, tools_used in first-call order)."""
    import anthropic

    client = get_client()
    if client is None:
        raise ChatUnavailable("ANTHROPIC_API_KEY is not configured on the server.")

    messages: list[dict[str, Any]] = _clean_history(history or []) + [{"role": "user", "content": message}]
    tools_used: list[str] = []
    system = _system_prompt()

    for _ in range(MAX_TOOL_ROUNDS):
        try:
            resp = client.messages.create(
                model=settings.chat_model,
                max_tokens=1500,
                system=system,
                tools=TOOLS,
                messages=messages,
            )
        except anthropic.APIStatusError as e:
            log.warning("Claude API error %s", e.status_code, exc_info=True)
            raise ChatUnavailable(f"Claude API error ({e.status_code}).") from e
        except anthropic.APIConnectionError as e:
            log.warning("Claude API unreachable", exc_info=True)
            raise ChatUnavailable("Could not reach the Claude API.") from e

        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            return text or "I couldn't produce an answer for that.", tools_used

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in (b for b in resp.content if b.type == "tool_use"):
            if block.name not in tools_used:
                tools_used.append(block.name)
            try:
                payload = _DISPATCH[block.name](db, **block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(payload, default=str)})
            except Exception as e:  # noqa: BLE001
                log.warning("Tool %s failed", block.name, exc_info=True)
                db.rollback()
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": f"Tool error: {e}", "is_error": True}
                )
        messages.append({"role": "user", "content": results})

    return "I couldn't finish looking that up — please try a more specific question.", tools_used
