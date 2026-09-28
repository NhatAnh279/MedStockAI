"""Protocol PDF upload: extract with Claude -> user edits in a preview -> confirm saves to the DB."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Actor, AuditLog, Item, Protocol, ProtocolItem
from app.schemas import ProtocolConfirmIn, ProtocolConfirmOut, ProtocolPreview, SavedProtocol
from app.services.chat import ChatUnavailable
from app.services.protocol_extract import ExtractionError, extract_protocols

router = APIRouter(prefix="/protocols")

MAX_PDF_BYTES = 10 * 1024 * 1024


@router.post("/upload", response_model=ProtocolPreview)
def upload_protocol(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Extract protocol items from a PDF. Nothing is saved until /protocols/confirm."""
    name = file.filename or "upload.pdf"
    if not name.lower().endswith(".pdf") or (file.content_type or "") not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(415, "Only PDF files are accepted.")
    data = file.file.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF is larger than the 10 MB limit.")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(415, "File is not a valid PDF.")

    try:
        protocols = extract_protocols(db, data)
    except ChatUnavailable as e:
        raise HTTPException(503, str(e))
    except ExtractionError as e:
        raise HTTPException(422, str(e))
    return ProtocolPreview(filename=name, protocols=protocols)


@router.post("/confirm", response_model=ProtocolConfirmOut, status_code=201)
def confirm_protocols(body: ProtocolConfirmIn, db: Session = Depends(get_db)):
    """Save the (user-reviewed) protocols and their items in one transaction."""
    item_ids = {li.item_id for p in body.protocols for li in p.items}
    known = set(db.execute(select(Item.id).where(Item.id.in_(item_ids))).scalars())
    if missing := item_ids - known:
        raise HTTPException(422, f"Unknown inventory item id(s): {sorted(missing)}")

    seen: set[tuple[str, str]] = set()
    for p in body.protocols:
        key = (p.name.strip().lower(), p.phase.strip().lower())
        exists = db.execute(
            select(Protocol.id).where(
                Protocol.name.ilike(p.name.strip()), Protocol.phase.ilike(p.phase.strip())
            )
        ).first()
        if key in seen or exists:
            raise HTTPException(409, f"Protocol '{p.name}' ({p.phase}) already exists.")
        seen.add(key)
        if len({li.item_id for li in p.items}) != len(p.items):
            raise HTTPException(422, f"Protocol '{p.name}' lists the same item more than once.")

    saved: list[SavedProtocol] = []
    for p in body.protocols:
        proto = Protocol(
            name=p.name.strip(),
            icd_code=p.icd_code.strip(),
            phase=p.phase.strip(),
            cycle_length_days=p.cycle_length_days,
            total_cycles=p.total_cycles,
        )
        db.add(proto)
        db.flush()
        for li in p.items:
            db.add(
                ProtocolItem(
                    protocol_id=proto.id, item_id=li.item_id, qty_per_cycle=li.qty_per_cycle, dose_per_kg=li.dose_per_kg
                )
            )
        db.add(
            AuditLog(
                actor=Actor.user,
                action="protocol_create",
                entity="protocols",
                entity_id=proto.id,
                after=p.model_dump(),
            )
        )
        saved.append(SavedProtocol(id=proto.id, name=proto.name, phase=proto.phase, item_count=len(p.items)))
    db.commit()
    return ProtocolConfirmOut(saved=saved)
