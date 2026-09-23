import pytest
from datetime import datetime, timezone
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DbSession, sessionmaker

from app.models.tables import Base, Astronaute, Session as SessionModel, Mesure
from app.schemas.ingest import IngestMessage

BASE = {
    "v": 1,
    "device_id": "cabine-01",
    "ts": "2026-09-23T10:00:00Z",
    "seq": 0,
    "qualite": {"cardiaque": 0.9, "eda": 0.9},
}


def test_accepte_le_ppg_brut_et_le_courant():
    m = IngestMessage(**BASE, ppg_raw=[120000, 120500], ma=212.0)
    assert m.ppg_raw == [120000, 120500]
    assert m.ma == 212.0


def test_reste_compatible_avec_le_simulateur():
    """Le simulateur existant n'envoie ni ppg_raw ni ma : il doit continuer."""
    m = IngestMessage(**BASE, ibi_ms=[857], eda_us=[4.0])
    assert m.ppg_raw == []
    assert m.ma is None


def test_rejette_un_intervalle_hors_bornes():
    with pytest.raises(ValidationError):
        IngestMessage(**BASE, ibi_ms=[120])


def test_stocke_le_courant_en_base():
    """Verifie qu'un message avec ma produit une ligne capteur=courant."""
    # Setup SQLite in-memory
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    # Create astronaute and session
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

    # Ingest a message with ma
    message = IngestMessage(**BASE, ma=212.0)
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

    # Verify the courant mesure was stored
    mesure = db.query(Mesure).filter(Mesure.capteur == "courant").first()
    assert mesure is not None
    assert mesure.valeurs["ma"] == 212.0
    assert mesure.session_id == session.id
