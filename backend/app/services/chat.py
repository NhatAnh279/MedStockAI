"""Natural-language inventory assistant: Claude answers questions by calling read-only tools.

Every figure comes from the tools (which wrap the forecast engine and the DB); the model
only phrases the answer. Tools are plain Python functions taking (db, **args); TOOLS holds
their JSON schemas and _DISPATCH maps names to functions.
"""
import calendar
import json
import logging
import re
from datetime import date, timedelta
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import Item, Patient, POLine, POStatus, Protocol, PurchaseOrder, TreatmentPlan
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


# ── Tools ────────────────────────────────────────────────────────────────────


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


def _find_items(db: Session, name: str) -> list[Item]:
    items = db.execute(select(Item).order_by(Item.name)).scalars().all()
    key = name.strip().lower()
    hits = [i for i in items if key in i.name.lower()]
    if not hits:  # every word must appear, e.g. "rifampicin capsules" -> "Rifampicin 300mg ... capsule"
        words = [w.rstrip("s") for w in re.findall(r"[a-z0-9]+", key)]
        hits = [i for i in items if words and all(w in i.name.lower() for w in words)]
    return hits


def get_forecast(db: Session, item_name: str) -> dict[str, Any]:
    matches = _find_items(db, item_name)
    if not matches:
        return {"error": f"No item matching '{item_name}'."}
    out = []
    for item in matches[:3]:
        f = forecast(db, item.id, HORIZON_DAYS)
        rd = f["rationale_data"]
        out.append(
            {
                "item_name": f["item_name"],
                "horizon_days": f["horizon_days"],
                "demand": f["demand"],  # A_scheduled, B_baseline, C_new_intake, total
                "usable_stock": f["usable_stock"],
                "qty_on_order": f["qty_on_order"],
                "reorder_point": f["ROP"],
                "order_qty": f["order_qty"],
                "days_until_stockout": f["days_until_stockout"],
                "patients_on_active_plans": len(rd["contributing_patients"]),
                "expiring_batches_excluded": rd["expiring_batches_excluded"],
            }
        )
    result: dict[str, Any] = {"forecasts": out}
    if len(matches) > 3:
        result["other_matches"] = [i.name for i in matches[3:]]
    return result


# Words a user might say -> text that appears in the protocol name.
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


def get_patient_summary(db: Session, condition: str) -> dict[str, Any]:
    key = condition.strip().lower()
    needles = {key} | {alias for word, alias in _CONDITION_ALIASES.items() if word in key}
    protocols = db.execute(select(Protocol)).scalars().all()
    matched = [p for p in protocols if _protocol_matches(p, needles)]
    if not matched:
        return {
            "error": f"No treatment protocol matches '{condition}'.",
            "available_protocols": sorted({p.name for p in protocols}),
        }

    rows = db.execute(
        select(Protocol.name, TreatmentPlan.current_phase, TreatmentPlan.status, func.count(func.distinct(Patient.id)))
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
        "patients_in_treatment": by_status.get("active", 0),  # active plans only
        "patients_by_plan_status": by_status,  # active / paused / completed
        "by_phase": by_phase,  # phase -> plan status -> patients
    }


def get_expiring_batches(db: Session, days: int) -> dict[str, Any]:
    rows = expiring_batches(days=days, db=db)
    return {
        "window_days": days,
        "window_end_date": (date.today() + timedelta(days=days)).isoformat(),  # batches expire on or before this
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
                "status": po.status.value,  # draft / pending_approval / sent / confirmed
                "created_by": po.created_by.value,
                "lines": [{"item_name": l.item.name, "qty": l.qty} for l in po.lines],
                "total_aud": float(po.total),
                "created_at": po.created_at.date().isoformat(),
            }
            for po in pos
        ],
    }


def _schema(name: str, description: str, props: dict[str, Any] | None = None) -> dict[str, Any]:
    props = props or {}
    return {
        "name": name,
        "description": description,
        "input_schema": {"type": "object", "properties": props, "required": list(props)},
    }


TOOLS = [
    _schema(
        "get_low_stock",
        "Items forecast to run out within N days (30-day demand forecast: scheduled treatments + "
        "dispensing baseline + expected new patients, against usable non-expiring stock). "
        "Sorted most urgent first. Use for 'what's running low' and 'what should we prepare/order'.",
        {"days": {"type": "integer", "description": "Only include items with fewer than this many days of stock, e.g. 14 or 30."}},
    ),
    _schema(
        "get_forecast",
        "Forecast detail for one item: demand split into A (scheduled treatments), B (recent dispensing "
        "baseline) and C (new patient intake), usable stock, reorder point, suggested order quantity.",
        {"item_name": {"type": "string", "description": "Item name or part of it, e.g. 'Rifampicin' or 'insulin'."}},
    ),
    _schema(
        "get_patient_summary",
        "Count of patients on a treatment protocol for a condition, with breakdown by treatment phase "
        "and plan status. Conditions: TB, breast cancer/chemo, haemodialysis, type 2 diabetes (insulin or metformin).",
        {"condition": {"type": "string", "description": "Condition name, e.g. 'TB', 'dialysis', 'diabetes'."}},
    ),
    _schema(
        "get_expiring_batches",
        "Stock batches (lots) with units on hand that expire between today and N days from today, soonest first.",
        {"days": {"type": "integer", "description": "Look-ahead window in days from today."}},
    ),
    _schema(
        "get_order_status",
        "All open purchase orders (draft, pending approval, sent, confirmed) with supplier, status and total.",
    ),
]

_DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "get_low_stock": get_low_stock,
    "get_forecast": get_forecast,
    "get_patient_summary": get_patient_summary,
    "get_expiring_batches": get_expiring_batches,
    "get_order_status": get_order_status,
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
        f"({(eonm - today).days} days from today).\n"
        "Answer questions about stock levels, demand forecasts, treatment patients, expiring batches and "
        "purchase orders. Always call the tools for data; never guess or compute figures yourself, and only "
        "quote numbers that a tool returned. If a tool returns an error or no data, say so plainly. "
        "For 'this month' or 'next month' use the day counts above as the tool's days argument. "
        "Only report items inside the window you were asked about; if it is empty, say so plainly, then "
        "mention the next expiries or items beyond it, clearly labelled as outside the window. Do not add "
        "urgency labels or advice beyond what the data shows, and do not link an item to a purchase order "
        "unless the tool result shows it. When a result has many items, list the eight most urgent and sum up "
        "the rest in one line. Reply in English, concisely, as plain text (short hyphen lists are fine; no "
        "markdown headings, tables or bold). Give dates as day month year."
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
            except Exception as e:  # noqa: BLE001 — report tool failures to the model instead of failing the chat
                log.warning("Tool %s failed", block.name, exc_info=True)
                db.rollback()
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": f"Tool error: {e}", "is_error": True}
                )
        messages.append({"role": "user", "content": results})

    return "I couldn't finish looking that up — please try a more specific question.", tools_used
