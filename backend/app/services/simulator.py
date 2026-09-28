"""Supplier simulator: produces the reply a real supplier would email back for a PO.

Behaviour is deterministic per PO id (seeded RNG) so demos and tests are repeatable.
A supplier fulfils an order in full with probability `reliability_score`; otherwise it
confirms only part of one or more lines and puts the rest on backorder.
"""
import random
from typing import Any


def _floor_to_pack(qty: int, pack_size: int) -> int:
    pack = max(pack_size, 1)
    return (qty // pack) * pack


def simulate_supplier_reply(
    po_id: int,
    supplier_name: str,
    contact_person: str | None,
    reliability_score: float,
    lead_time_days: int,
    lines: list[dict[str, Any]],
) -> str:
    """lines: [{"item_name", "qty", "pack_size"}]. Returns the raw reply text.

    Line format is `- <item>: confirmed <X> of <Y> units`, which llm.parse_supplier_reply
    can read with its regex fallback as well as with the LLM.
    """
    rng = random.Random(po_id)
    fulfil_in_full = rng.random() < reliability_score

    confirmed = [l["qty"] for l in lines]
    if not fulfil_in_full and lines:
        # Always short at least one line so "partial" is actually partial.
        short_idx = {rng.randrange(len(lines))}
        short_idx |= {i for i in range(len(lines)) if rng.random() < 0.3}
        for i in short_idx:
            frac = rng.uniform(0.4, 0.8)
            confirmed[i] = _floor_to_pack(int(lines[i]["qty"] * frac), lines[i].get("pack_size", 1))

    body = "\n".join(
        f"- {l['item_name']}: confirmed {c} of {l['qty']} units" for l, c in zip(lines, confirmed)
    )
    short = any(c < l["qty"] for l, c in zip(lines, confirmed))

    out = [
        f"Subject: Re: Purchase Order #{po_id}",
        "",
        "Hi,",
        "",
        f"Thank you for PO #{po_id}. Our confirmation is below.",
        "",
        body,
        "",
    ]
    if short:
        out.append(f"Note: shortfall is on backorder due to supply constraints, ETA {lead_time_days * 2} days.")
    else:
        out.append(f"Note: full order confirmed, dispatch within {lead_time_days} days.")
    out += ["", "Kind regards,", contact_person or supplier_name, supplier_name]
    return "\n".join(out)
