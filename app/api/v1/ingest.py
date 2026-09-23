from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session as DbSession

from app.deps import get_db
from app.models.tables import Astronaute, Mesure, Session as SessionModel
from app.schemas.ingest import IngestMessage

router = APIRouter()


def get_or_create_session(db: DbSession) -> SessionModel:
    session = (
        db.query(SessionModel)
        .filter(SessionModel.fin.is_(None))
        .order_by(SessionModel.id.desc())
        .first()
    )
    if session:
        return session

    astronaute = db.query(Astronaute).first()
    if not astronaute:
        astronaute = Astronaute(nom="Astronaute de test")
        db.add(astronaute)
        db.flush()

    session = SessionModel(
        astronaute_id=astronaute.id,
        debut=datetime.now(timezone.utc),
        mode="normal",
    )
    db.add(session)
    db.flush()
    return session


@router.post("/ingest", status_code=status.HTTP_202_ACCEPTED)
def ingest(message: IngestMessage, db: DbSession = Depends(get_db)):
    session = get_or_create_session(db)

    if message.ppg_raw:
        db.add(
            Mesure(
                session_id=session.id,
                device_id=message.device_id,
                capteur="ppg",
                seq=message.seq,
                ts=message.ts,
                valeurs={"ppg_raw": message.ppg_raw},
                qualite={"cardiaque": message.qualite.cardiaque},
            )
        )

    if message.ibi_ms:
        db.add(
            Mesure(
                session_id=session.id,
                device_id=message.device_id,
                capteur="cardiaque",
                seq=message.seq,
                ts=message.ts,
                valeurs={"ibi_ms": message.ibi_ms},
                qualite={"cardiaque": message.qualite.cardiaque},
            )
        )

    if message.eda_us:
        db.add(
            Mesure(
                session_id=session.id,
                device_id=message.device_id,
                capteur="sudation",
                seq=message.seq,
                ts=message.ts,
                valeurs={"eda_us": message.eda_us},
                qualite={"eda": message.qualite.eda},
            )
        )

    db.commit()

    return {"recu": True, "seq": message.seq, "session_id": session.id}