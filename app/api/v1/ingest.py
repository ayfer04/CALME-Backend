from fastapi import APIRouter, status

from app.schemas.ingest import IngestMessage

router = APIRouter()


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
def ingest(message: IngestMessage):
    return {"recu": True, "seq": message.seq}