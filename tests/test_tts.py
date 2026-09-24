import pytest

from app.services import synthese


@pytest.fixture(autouse=True)
def _reglages_neutres(monkeypatch):
    """Les fausses voix n'ont pas besoin des vrais reglages Piper."""
    monkeypatch.setattr(synthese, "_reglages_synthese", lambda voix: None)


@pytest.fixture(autouse=True)
def _cache_vide():
    """Le cache est un dictionnaire de module : on le vide avant et apres
    chaque test pour qu'aucun ne pollue le suivant.
    """
    synthese._cache.clear()
    yield
    synthese._cache.clear()


class FausseVoix:
    """Tient lieu de PiperVoice.load(...) sans toucher au vrai modele :
    compte les appels pour verifier le cache, ecrit un WAV minimal valide.
    """

    def __init__(self):
        self.appels = 0

    def synthesize_wav(self, texte, wav_file, **kwargs):
        self.appels += 1
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        wav_file.writeframes(b"\x00\x00" * 100)


def test_texte_vide_est_refuse(client):
    reponse = client.post("/api/v1/tts", json={"texte": ""})
    assert reponse.status_code == 422


def test_texte_fait_uniquement_despaces_est_refuse(client):
    reponse = client.post("/api/v1/tts", json={"texte": "   "})
    assert reponse.status_code == 422


def test_texte_trop_long_est_refuse(client):
    from app.schemas.tts import LONGUEUR_MAX_TEXTE

    reponse = client.post("/api/v1/tts", json={"texte": "a" * (LONGUEUR_MAX_TEXTE + 1)})
    assert reponse.status_code == 422


def test_piper_indisponible_renvoie_503_et_le_reste_du_serveur_repond(client, monkeypatch):
    def echoue():
        raise synthese.VoixIndisponible("bibliotheque piper non installee")

    monkeypatch.setattr(synthese, "_charger_voix", echoue)

    reponse = client.post("/api/v1/tts", json={"texte": "Bonjour."})
    assert reponse.status_code == 503
    assert "indisponible" in reponse.json()["detail"]

    # L'indisponibilite de Piper n'a fait planter ni cette requete ni le
    # reste de l'application : une autre route repond toujours normalement.
    assert client.get("/api/v1/health").status_code == 200


def test_une_erreur_de_synthese_renvoie_503_plutot_que_de_remonter(client, monkeypatch):
    class VoixCassee:
        def synthesize_wav(self, texte, wav_file, **kwargs):
            raise RuntimeError("erreur onnxruntime simulee")

    monkeypatch.setattr(synthese, "_charger_voix", lambda: VoixCassee())

    reponse = client.post("/api/v1/tts", json={"texte": "Bonjour."})
    assert reponse.status_code == 503


def test_le_cache_evite_une_deuxieme_synthese(client, monkeypatch):
    fausse_voix = FausseVoix()
    monkeypatch.setattr(synthese, "_charger_voix", lambda: fausse_voix)

    texte = "Cinq minutes de respiration guidee. Suivez le cercle."
    r1 = client.post("/api/v1/tts", json={"texte": texte})
    r2 = client.post("/api/v1/tts", json={"texte": texte})

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.content == r2.content
    assert fausse_voix.appels == 1


def test_la_reponse_est_un_wav(client, monkeypatch):
    monkeypatch.setattr(synthese, "_charger_voix", lambda: FausseVoix())

    reponse = client.post("/api/v1/tts", json={"texte": "Bonjour."})
    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "audio/wav"
    assert reponse.content[:4] == b"RIFF"
    assert reponse.content[8:12] == b"WAVE"
