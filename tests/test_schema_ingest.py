import pytest
from pydantic import ValidationError

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
