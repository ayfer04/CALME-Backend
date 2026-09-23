import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.deps import get_db
from app.models.tables import Appareil, Astronaute, Mesure, Session as SessionModel
from app.schemas.ingest import IngestMessage

router = APIRouter()


def verifier_signature(message: IngestMessage, cle: str) -> bool:
    """HMAC-SHA256 sur device_id | seq | ts.

    Le numero de sequence est dans la signature : sans lui, un message capture
    pourrait etre rejoue indefiniment avec la meme signature valide.
    """
    if not message.sig:
        return False
    ts = message.ts.isoformat()
    attendu = hmac.new(
        cle.encode(), f"{message.device_id}|{message.seq}|{ts}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(attendu, message.sig)


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
    appareil = db.query(Appareil).filter(Appareil.device_id == message.device_id).first()
    if appareil and not verifier_signature(message, appareil.cle_signature):
        # Journalise et rejette. Un capteur qui parle mal n'est pas une urgence
        # medicale, c'est un capteur qui deconne - ou quelqu'un d'autre.
        print(f"signature refusee: {message.device_id} seq={message.seq}", flush=True)
        raise HTTPException(status_code=401, detail="signature invalide")
    # Un appareil inconnu de la table `appareils` reste accepte sans verification :
    # c'est une porte ouverte assumee pour la demonstration (elle laisse tourner
    # simulator/send_measures.py sans cle), pas un oubli. A durcir en refusant
    # aussi les appareils non declares, si le temps le permet.

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

    if message.ma is not None:
        db.add(
            Mesure(
                session_id=session.id,
                device_id=message.device_id,
                capteur="courant",
                seq=message.seq,
                ts=message.ts,
                valeurs={"ma": message.ma},
                qualite={},
            )
        )

    db.commit()

    return {"recu": True, "seq": message.seq, "session_id": session.id}