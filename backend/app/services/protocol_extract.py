"""Extract treatment-protocol definitions from an uploaded PDF using Claude's PDF input.

The model is given the inventory catalogue so it can map each drug/consumable in the PDF to
an existing item and express quantities in that item's base unit. Output is constrained to a
JSON schema; anything unmatched comes back with item_id null for the user to fix in the preview.
"""
import base64
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Item
from app.schemas import ExtractedProtocol, ExtractedProtocolItem
from app.services.chat import ChatUnavailable
from app.services.llm import get_client

log = logging.getLogger(__name__)

_NULLABLE_INT = {"type": ["integer", "null"]}

_SCHEMA = {
    "type": "object",
    "properties": {
        "protocols": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "icd_code": {"type": "string"},
                    "phase": {"type": "string"},
                    "cycle_length_days": {"type": "integer"},
                    "total_cycles": _NULLABLE_INT,
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_id": _NULLABLE_INT,
                                "item_name": {"type": "string"},
                                "dosage": {"type": "string"},
                                "qty_per_cycle": {"type": "integer"},
                                "dose_per_kg": {"type": ["number", "null"]},
                            },
                            "required": ["item_id", "item_name", "dosage", "qty_per_cycle", "dose_per_kg"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["name", "icd_code", "phase", "cycle_length_days", "total_cycles", "items"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["protocols"],
    "additionalProperties": False,
}


class ExtractionError(Exception):
    """The PDF could not be turned into protocol items."""


def _prompt(catalogue: list[dict[str, Any]]) -> str:
    return (
        "Extract treatment protocol details: drug names, dosages, phases, cycle length, items needed per "
        "cycle. Return as JSON.\n\n"
        "Rules:\n"
        "- Return one protocol per treatment phase (e.g. an intensive phase and a continuation phase are two "
        "protocols). 'name' is the protocol title including the phase; 'phase' is a short lowercase label such "
        "as 'intensive' or 'maintenance'.\n"
        "- 'icd_code' is the ICD-10 code if the document gives one, otherwise the best-matching ICD-10 code for "
        "the condition.\n"
        "- 'cycle_length_days' is the length of one dispensing/treatment cycle in days; 'total_cycles' is how "
        "many cycles the phase runs, or null if it is ongoing.\n"
        "- 'items' lists every drug and consumable a patient needs per cycle. 'dosage' is copied from the "
        "document (e.g. '600 mg once daily'). 'qty_per_cycle' is the total units of the inventory item needed "
        "per patient per cycle, in that item's unit (count tablets/capsules/vials etc., not mg), worked out from "
        "the dosage and cycle length. If the dose depends on body weight, set 'dose_per_kg' to the units of the "
        "inventory item per kg per cycle and 'qty_per_cycle' to the amount for a 70 kg adult; otherwise null.\n"
        "- Set 'item_id' to the id of the matching inventory item below (same drug and strength/form), or null if "
        "there is no match — never invent an id.\n"
        "- Only include what the document states; do not add items it does not mention.\n\n"
        f"Inventory catalogue (id, name, unit):\n{json.dumps(catalogue)}"
    )


def extract_protocols(db: Session, pdf_bytes: bytes) -> list[ExtractedProtocol]:
    import anthropic

    client = get_client()
    if client is None:
        raise ChatUnavailable("ANTHROPIC_API_KEY is not configured on the server.")

    items = db.execute(select(Item).order_by(Item.id)).scalars().all()
    catalogue = [{"id": i.id, "name": i.name, "unit": i.unit} for i in items]
    valid_ids = {i.id for i in items}

    try:
        resp = client.messages.create(
            model=settings.chat_model,
            max_tokens=8000,
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": base64.standard_b64encode(pdf_bytes).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": _prompt(catalogue)},
                    ],
                }
            ],
        )
    except anthropic.BadRequestError as e:  # e.g. not a readable PDF, too many pages
        log.warning("Claude rejected the PDF", exc_info=True)
        raise ExtractionError(f"The PDF could not be processed: {e.message}") from e
    except anthropic.APIStatusError as e:
        log.warning("Claude API error %s", e.status_code, exc_info=True)
        raise ChatUnavailable(f"Claude API error ({e.status_code}).") from e
    except anthropic.APIConnectionError as e:
        log.warning("Claude API unreachable", exc_info=True)
        raise ChatUnavailable("Could not reach the Claude API.") from e

    if resp.stop_reason == "max_tokens":
        raise ExtractionError("The protocol document is too large to extract in one pass.")
    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        data = json.loads(text)
        protocols = []
        for p in data["protocols"]:
            protocols.append(
                ExtractedProtocol(
                    **{k: p[k] for k in ("name", "icd_code", "phase", "cycle_length_days", "total_cycles")},
                    items=[
                        ExtractedProtocolItem(**{**it, "item_id": it["item_id"] if it["item_id"] in valid_ids else None})
                        for it in p["items"]
                    ],
                )
            )
    except (ValueError, KeyError, TypeError) as e:
        log.warning("Unparseable extraction output: %.500s", text)
        raise ExtractionError("Could not read protocol details from the document.") from e
    if not protocols:
        raise ExtractionError("No treatment protocol was found in the document.")
    return protocols
