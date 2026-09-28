"""Natural-language chat over inventory, forecast, patient and order data."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ChatIn, ChatOut
from app.services.chat import ChatUnavailable, answer

router = APIRouter()


@router.post("/chat", response_model=ChatOut)
def chat(body: ChatIn, db: Session = Depends(get_db)):
    try:
        response, tools_used = answer(db, body.message, [t.model_dump() for t in body.history])
    except ChatUnavailable as e:
        raise HTTPException(503, str(e))
    return ChatOut(response=response, tools_used=tools_used)
