"""Forecast router: exposes run_reorder() results over HTTP."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ForecastItemOut
from app.services.reorder import run_reorder

router = APIRouter(prefix="/forecast")


@router.get("", response_model=list[ForecastItemOut])
def get_forecast(
    horizon_days: int = Query(30, ge=1, le=365, description="Demand horizon in days"),
    db: Session = Depends(get_db),
):
    """Run the A+B+C forecast for every item and return results sorted by urgency
    (fewest days until stockout first; items with no stockout risk at the end)."""
    return run_reorder(db, horizon_days=horizon_days)
