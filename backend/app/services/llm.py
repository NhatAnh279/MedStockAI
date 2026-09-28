"""LLM helpers: PO line rationale and supplier-reply parsing.

Both entry points degrade gracefully: with no ANTHROPIC_API_KEY (or on any API/parse
error) they fall back to a deterministic path, so the PO workflow never depends on the
network. The forecast numbers are always computed by the forecast engine; the LLM only
words them and never supplies figures.
"""
import json
import logging
import re
from typing import Any

from app.config import settings

log = logging.getLogger(__name__)

_client = None


def get_client():
    """Shared Anthropic client, or None when no API key is configured."""
    global _client
    if not settings.anthropic_api_key:
        return None
    if _client is None:
        import anthropic  # lazy: optional dependency

        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=90.0)
    return _client


def _complete(prompt: str, max_tokens: int = 300) -> str | None:
    """Single-turn completion. Returns None when no key is set or the call fails."""
    try:
        client = get_client()
        if client is None:
            return None
        msg = client.messages.create(
            model=settings.llm_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        return text or None
    except Exception:  # noqa: BLE001 — any failure means "use the fallback"
        log.warning("LLM call failed; using fallback", exc_info=True)
        return None


# ── Rationale ────────────────────────────────────────────────────────────────


def _fmt(n: float) -> str:
    return f"{n:,.0f}" if float(n).is_integer() or abs(n) >= 100 else f"{n:,.1f}"


def template_rationale(item_name: str, supplier_name: str, qty: int, fc: dict[str, Any]) -> str:
    d = fc["demand"]
    rd = fc["rationale_data"]
    patients = rd["contributing_patients"]
    excluded = rd["expiring_batches_excluded"]

    parts = [
        f"Order {qty:,} units of {item_name} from {supplier_name}: "
        f"forecast {fc['horizon_days']}-day demand is {_fmt(d['total'])} units "
        f"against {_fmt(fc['usable_stock'])} usable in stock"
    ]
    if fc["qty_on_order"]:
        parts[0] += f" and {_fmt(fc['qty_on_order'])} already on order"
    parts[0] += f", with a reorder point of {_fmt(fc['ROP'])}."

    breakdown = []
    if patients:
        breakdown.append(
            f"{_fmt(d['A_scheduled'])} scheduled for {len(patients)} patient"
            f"{'s' if len(patients) != 1 else ''} on active treatment plans"
        )
    if d["B_baseline"]:
        breakdown.append(f"{_fmt(d['B_baseline'])} from the recent dispensing baseline")
    if d["C_new_intake"]:
        breakdown.append(f"{_fmt(d['C_new_intake'])} from expected new patient intake")
    if breakdown:
        parts.append("Demand is " + ", ".join(breakdown) + ".")

    if excluded:
        lots = ", ".join(b["lot_no"] for b in excluded)
        parts.append(f"{len(excluded)} batch{'es' if len(excluded) != 1 else ''} ({lots}) will expire before use and are excluded from usable stock.")

    if fc["days_until_stockout"] is not None and fc["days_until_stockout"] < 30:
        parts.append(f"Projected stockout in {_fmt(fc['days_until_stockout'])} days.")
    return " ".join(parts)


def _round_fc(fc: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of a forecast dict with key numeric fields rounded to integers."""
    d = dict(fc)
    demand = dict(d.get("demand", {}))
    for k in ("A_scheduled", "B_baseline", "C_new_intake", "total"):
        if k in demand:
            demand[k] = round(demand[k])
    d["demand"] = demand
    for k in ("usable_stock", "ROP", "order_qty", "qty_on_order"):
        if k in d and d[k] is not None:
            d[k] = round(d[k])
    if d.get("days_until_stockout") is not None:
        d["days_until_stockout"] = round(d["days_until_stockout"])
    return d


def generate_rationale(item_name: str, supplier_name: str, qty: int, fc: dict[str, Any]) -> str:
    """Short human-readable justification for one PO line."""
    fallback = template_rationale(item_name, supplier_name, qty, fc)
    prompt = (
        "You are a hospital pharmacy purchasing assistant. Write a 2-3 sentence rationale "
        "for a pharmacist reviewing this purchase order line. Use ONLY the figures below, "
        "do not invent or recompute numbers, and do not use markdown.\n\n"
        f"Item: {item_name}\nSupplier: {supplier_name}\nOrder quantity: {qty}\n"
        f"Forecast data (JSON): {json.dumps(_round_fc(fc), default=str)}"
    )
    return _complete(prompt, max_tokens=220) or fallback


# ── Supplier reply parsing ───────────────────────────────────────────────────

# Matches the simulator's format, and most "<name>: confirmed X of Y" style replies.
_LINE_RE = re.compile(
    r"^\s*[-*•]?\s*(?P<name>.+?)\s*[:\-–]\s*(?:can\s+)?confirm(?:ed)?\s+(?P<c>[\d,]+)\s+of\s+(?P<o>[\d,]+)",
    re.IGNORECASE | re.MULTILINE,
)


def _to_int(s: str) -> int:
    return int(s.replace(",", ""))


def _classify(lines: list[dict]) -> str:
    if not lines:
        return "unparsed"
    if all(l["confirmed_qty"] >= l["ordered_qty"] for l in lines):
        return "full"
    if all(l["confirmed_qty"] == 0 for l in lines):
        return "rejected"
    return "partial"


def _match_item(name: str, po_lines: list[dict]) -> dict | None:
    key = name.strip().lower()
    for l in po_lines:
        if l["item_name"].lower() == key:
            return l
    for l in po_lines:  # tolerate "Rifampicin" vs "Rifampicin 300mg"
        n = l["item_name"].lower()
        if key in n or n in key:
            return l
    return None


def _build(po_lines: list[dict], confirmed: dict[int, int], notes: str | None, parser: str) -> dict:
    lines = [
        {
            "item_id": l["item_id"],
            "item_name": l["item_name"],
            "ordered_qty": l["qty"],
            "confirmed_qty": max(0, min(confirmed.get(l["item_id"], 0), l["qty"])),
        }
        for l in po_lines
        if l["item_id"] in confirmed
    ]
    return {"status": _classify(lines), "lines": lines, "notes": notes, "parser": parser}


def _regex_parse(reply: str, po_lines: list[dict]) -> dict:
    confirmed: dict[int, int] = {}
    for m in _LINE_RE.finditer(reply):
        line = _match_item(m.group("name"), po_lines)
        if line is not None:
            confirmed[line["item_id"]] = _to_int(m.group("c"))
    note = re.search(r"^\s*(?:note|backorder|eta)s?\s*:\s*(.+)$", reply, re.IGNORECASE | re.MULTILINE)
    return _build(po_lines, confirmed, note.group(1).strip() if note else None, "regex")


def _llm_parse(reply: str, po_lines: list[dict]) -> dict | None:
    prompt = (
        "Extract the supplier's confirmed quantities from this reply to a purchase order. "
        "Respond with JSON only, no prose: "
        '{"lines": [{"item_id": <int>, "confirmed_qty": <int>}], "notes": <string or null>}. '
        "Use confirmed_qty 0 for items the supplier cannot supply.\n\n"
        f"Ordered lines: {json.dumps([{'item_id': l['item_id'], 'item_name': l['item_name'], 'qty': l['qty']} for l in po_lines])}\n\n"
        f"Supplier reply:\n{reply}"
    )
    raw = _complete(prompt, max_tokens=400)
    if not raw:
        return None
    try:
        data = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
        valid_ids = {l["item_id"] for l in po_lines}
        confirmed = {
            int(x["item_id"]): int(x["confirmed_qty"])
            for x in data["lines"]
            if int(x["item_id"]) in valid_ids
        }
        if not confirmed:
            return None
        return _build(po_lines, confirmed, data.get("notes"), "llm")
    except (ValueError, KeyError, TypeError):
        log.warning("Could not parse LLM JSON for supplier reply; using regex", exc_info=True)
        return None


def parse_supplier_reply(reply: str, po_lines: list[dict]) -> dict:
    """Turn a free-text supplier reply into a structured confirmation.

    po_lines: [{"item_id", "item_name", "qty"}]. Returns
    {"status": full|partial|rejected|unparsed, "lines": [...], "notes", "parser"}.
    The status is always derived from the quantities, never taken from the LLM.
    """
    return _llm_parse(reply, po_lines) or _regex_parse(reply, po_lines)
