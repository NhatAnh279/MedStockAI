import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Batch, Item
from app.utils import get_local_network_ip

router = APIRouter()


def _resolve_host() -> str:
    if settings.network_host and settings.network_host != "auto":
        return settings.network_host
    return get_local_network_ip()


def _fefo_batch(db: Session, item_id: int):
    return (
        db.execute(
            select(Batch)
            .where(
                Batch.item_id == item_id,
                Batch.qty_on_hand > 0,
                Batch.expiry_date > date.today(),
            )
            .order_by(Batch.expiry_date)
        )
        .scalars()
        .first()
    )


def _build_scan_url(host: str, item_id: int, batch) -> str:
    url = f"http://{host}:3000/scan?item_id={item_id}"
    if batch:
        url += f"&batch_id={batch.id}&lot_no={batch.lot_no}"
    return url


def _render_qr_png(url: str, size: int = 300) -> bytes:
    import qrcode
    from PIL import Image as PILImage

    _resample = getattr(PILImage, "Resampling", PILImage).LANCZOS

    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    raw = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    raw.save(buf)
    buf.seek(0)
    pil = PILImage.open(buf).convert("RGB").resize((size, size), _resample)
    out = io.BytesIO()
    pil.save(out, "PNG")
    return out.getvalue()


@router.get("/items/qr-labels")
def get_qr_labels(db: Session = Depends(get_db)):
    import qrcode
    from PIL import Image as PILImage
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdf_canvas

    host = _resolve_host()
    items = db.execute(select(Item).order_by(Item.id)).scalars().all()

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4

    cols = 4
    rows_per_page = 6
    margin = 15 * mm
    label_w = (page_w - 2 * margin) / cols
    label_h = (page_h - 2 * margin) / rows_per_page
    pad = 3 * mm

    for i, item in enumerate(items):
        if i > 0 and i % (cols * rows_per_page) == 0:
            c.showPage()

        col = i % cols
        row = (i // cols) % rows_per_page
        cell_x = margin + col * label_w
        # reportlab y=0 is bottom; cell_y is the bottom of this cell
        cell_y = page_h - margin - (row + 1) * label_h

        batch = _fefo_batch(db, item.id)
        url = _build_scan_url(host, item.id, batch)

        # Border
        c.setStrokeColorRGB(0.8, 0.8, 0.8)
        c.rect(cell_x + pad, cell_y + pad, label_w - 2 * pad, label_h - 2 * pad)

        # QR image
        qr_size_pts = min(label_w, label_h) * 0.55
        qr_png = _render_qr_png(url, 200)
        qr_x = cell_x + (label_w - qr_size_pts) / 2
        qr_y = cell_y + label_h * 0.32
        c.drawImage(ImageReader(io.BytesIO(qr_png)), qr_x, qr_y, qr_size_pts, qr_size_pts)

        # Item name
        c.setFont("Helvetica-Bold", 7)
        name_disp = item.name[:26] + "…" if len(item.name) > 27 else item.name
        c.drawCentredString(cell_x + label_w / 2, cell_y + label_h * 0.22, name_disp)

        # Lot
        c.setFont("Helvetica", 6)
        lot_disp = f"Lot: {batch.lot_no}" if batch else "Lot: —"
        c.drawCentredString(cell_x + label_w / 2, cell_y + label_h * 0.13, lot_disp)

        # Shelf placeholder
        c.drawCentredString(cell_x + label_w / 2, cell_y + label_h * 0.06, "Shelf: [TBD]")

    c.save()
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=qr-labels.pdf"},
    )


@router.get("/items/{item_id}/qr")
def get_item_qr(item_id: int, db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(404, "Item not found")

    host = _resolve_host()
    batch = _fefo_batch(db, item_id)
    url = _build_scan_url(host, item_id, batch)

    return Response(content=_render_qr_png(url, 300), media_type="image/png")
