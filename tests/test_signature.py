import hashlib
import hmac

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1.ingest import ingest, verifier_signature
from app.models.tables import Base
from app.schemas.ingest import IngestMessage

CLE = "cle-de-test"
BASE = {
    "v": 1, "device_id": "cabine-01", "ts": "2026-09-23T10:00:00+00:00",
    "seq": 7, "qualite": {"cardiaque": 0.9, "eda": 0.9},
}


def signer(device_id: str, seq: int, ts: str, cle: str) -> str:
    return hmac.new(cle.encode(), f"{device_id}|{seq}|{ts}".encode(), hashlib.sha256).hexdigest()


def test_accepte_une_signature_valide():
    m = IngestMessage(**BASE, sig=signer("cabine-01", 7, BASE["ts"], CLE))
    assert verifier_signature(m, CLE) is True


def test_refuse_une_cle_inconnue():
    m = IngestMessage(**BASE, sig=signer("cabine-01", 7, BASE["ts"], "autre-cle"))
    assert verifier_signature(m, CLE) is False


def test_refuse_un_message_non_signe():
    m = IngestMessage(**BASE)
    assert verifier_signature(m, CLE) is False


def test_refuse_un_message_rejoue_avec_un_autre_seq():
    """La signature couvre le numero de sequence : on ne peut pas rejouer."""
    m = IngestMessage(**{**BASE, "seq": 8}, sig=signer("cabine-01", 7, BASE["ts"], CLE))
    assert verifier_signature(m, CLE) is False


def test_refuse_un_appareil_inconnu():
    """Ronde de correction 1 : un device_id absent de `appareils` est rejete

    au meme titre qu'une signature invalide - la porte ouverte precedente
    (laisser passer tout appareil non declare) rendait le controle
    contournable par sa propre entree.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    # BASE porte device_id="cabine-01", volontairement absent de cette base
    # en memoire : aucun appareil n'y est jamais enregistre.
    m = IngestMessage(**BASE, sig=signer("cabine-01", 7, BASE["ts"], CLE))

    with pytest.raises(HTTPException) as exc_info:
        ingest(m, db)
    assert exc_info.value.status_code == 401
