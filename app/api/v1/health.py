from fastapi import APIRouter
from sqlalchemy import text

from app.db import engine

router = APIRouter()


@router.get("/health")
def health():
    try:
        with engine.connect() as connexion:
            connexion.execute(text("SELECT 1"))
        base = "ok"
    except Exception:
        base = "indisponible"
    return {"api": "ok", "base": base}