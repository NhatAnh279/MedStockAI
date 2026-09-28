from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Item
from app.services.forecast import forecast


def run_reorder(db: Session, horizon_days: int = 30) -> list[dict]:
    items = db.execute(select(Item)).scalars().all()
    results = []
    for item in items:
        result = forecast(db, item.id, horizon_days)
        result["needs_order"] = result["order_qty"] > 0
        results.append(result)
    results.sort(
        key=lambda r: (
            r["days_until_stockout"] if r["days_until_stockout"] is not None else float("inf")
        )
    )
    return results
