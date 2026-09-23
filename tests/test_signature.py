import hashlib
import hmac

from app.api.v1.ingest import verifier_signature
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
