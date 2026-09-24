"""La passerelle du Pi doit produire des messages que le serveur accepte tels
quels : on les fait passer par le vrai schema et la vraie verification de
signature, pas par une copie de leur logique.
"""

import collections

import httpx

from app.api.v1.ingest import verifier_signature
from app.schemas.ingest import IngestMessage
from cabine import passerelle

CLE = "cle-de-test"


def _message(ppg=None, gsr=None, ma=245.3):
    ppg = ppg if ppg is not None else [120_000] * 100
    gsr = gsr if gsr is not None else [430] * 100
    return passerelle.construire(3, ppg, gsr, ma, device_id="cabine-01", cle=CLE, calibration=512)


def test_le_serveur_accepte_la_signature_de_la_passerelle():
    message = IngestMessage(**_message())
    assert verifier_signature(message, CLE) is True


def test_une_autre_cle_est_refusee():
    message = IngestMessage(**_message())
    assert verifier_signature(message, "autre-cle") is False


def test_une_seconde_de_mesures_donne_100_ppg_et_10_eda():
    message = IngestMessage(**_message())
    assert len(message.ppg_raw) == 100
    assert len(message.eda_us) == 10
    assert all(v > 0 for v in message.eda_us)
    assert message.ma == 245.3


def test_qualite_nulle_sans_doigt_sur_le_capteur():
    message = _message(ppg=[800] * 100)
    assert message["qualite"]["cardiaque"] == 0.0
    assert message["ppg_raw"] == []          # pas de signal plat envoye au serveur


def test_courant_absent_quand_le_firmware_ecrit_moins_un():
    assert _message(ma=-1.0)["ma"] is None


def test_sudation_saturee_vaut_zero_et_qualite_basse():
    message = _message(gsr=[511] * 100)
    assert message["eda_us"] == [0.0] * 10
    assert message["qualite"]["eda"] == 0.1


def test_lecture_des_lignes_du_firmware():
    assert passerelle.lire_ligne("D,118532,431,245.3") == (118532, 431, 245.3)
    assert passerelle.lire_ligne("#ERR MAX30102 absent") is None
    assert passerelle.lire_ligne("D,1185") is None          # ligne tronquee
    assert passerelle.lire_ligne("D,abc,431,1.0") is None


def test_un_refus_definitif_ne_bloque_pas_le_tampon(monkeypatch):
    """Un 401 ne doit pas etre rejoue a l'infini : sinon un seul message mal
    signe immobiliserait tout ce qui le suit dans le tampon."""
    envois = []

    class ClientFactice:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def post(self, url, json):
            envois.append(json["seq"])
            if len(envois) >= 2:
                raise SystemExit  # arrete la boucle infinie du fil d'envoi
            return httpx.Response(401, text="signature invalide")

    monkeypatch.setattr(passerelle.httpx, "Client", ClientFactice)
    tampon = collections.deque([_message(), {**_message(), "seq": 4}])
    try:
        passerelle.envoyer_en_continu(tampon, url="http://tour")
    except SystemExit:
        pass
    assert envois == [3, 4]
