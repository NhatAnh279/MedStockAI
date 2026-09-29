from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.routers import chat, forecast, inventory, orders, protocols, qr, scan, simulate

app = FastAPI(title="MedStock AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_origin_regex=r"http://\d+\.\d+\.\d+\.\d+:3000",
    allow_methods=["*"],
    allow_headers=["*"],
)

# qr must come before inventory so /items/qr-labels matches before /items/{item_id}
app.include_router(qr.router, tags=["qr"])
app.include_router(scan.router, tags=["scan"])
app.include_router(inventory.router, tags=["inventory"])
app.include_router(simulate.router, tags=["simulate"])
app.include_router(forecast.router, tags=["forecast"])
app.include_router(orders.router, tags=["orders"])
app.include_router(chat.router, tags=["chat"])
app.include_router(protocols.router, tags=["protocols"])


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
