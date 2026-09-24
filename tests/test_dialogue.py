"""Le dialogue de la cabine : transcription et modele sont remplaces par des
doublures, on verifie la logique qui les entoure - replis, historique, et
surtout que rien n'est conserve."""

import io
import json
import wave

import pytest

from app.services import dialogue


def _wav(secondes: float = 1.0, taux: int = 16_000) -> bytes:
    tampon = io.BytesIO()
    with wave.open(tampon, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(taux)
        f.writeframes(b"\x10\x00" * int(secondes * taux))
    return tampon.getvalue()


class FauxOllama:
    def __init__(self, texte="Ca a l'air d'avoir ete une longue journee. Tu te sens comment ?",
                 echoue=False):
        self.texte, self.echoue, self.messages = texte, echoue, None

    def Client(self, **kwargs):
        return self

    def chat(self, model, messages, **kwargs):
        if self.echoue:
            raise ConnectionError("ollama coupe")
        self.messages = messages
        import json
        return {"message": {"content": json.dumps({"reponse": self.texte, "humeur": 40})}}


@pytest.fixture()
def faux_ollama(monkeypatch):
    import sys

    faux = FauxOllama()
    monkeypatch.setitem(sys.modules, "ollama", faux)
    return faux


def _poster(client, entendu="J'ai repare le panneau solaire.", **champs):
    return client.post(
        "/api/v1/sessions/1/dialogue",
        files={"fichier": ("voix.wav", _wav(), "audio/wav")},
        data=champs,
    )


def test_un_tour_complet(client, monkeypatch, faux_ollama):
    monkeypatch.setattr(dialogue, "transcrire", lambda octets: "J'ai repare le panneau solaire.")
    r = _poster(client, historique=json.dumps([
        {"role": "lila", "texte": "Qu'est-ce que tu as fait aujourd'hui ?"}]))
    assert r.status_code == 200
    corps = r.json()
    assert corps["entendu"] == "J'ai repare le panneau solaire."
    assert corps["source"] == "model"
    assert "Tu te sens comment" in corps["reponse"]
    # L'historique du navigateur est bien transmis au modele, dans l'ordre.
    roles = [m["role"] for m in faux_ollama.messages]
    assert roles == ["system", "assistant", "user"]


def test_modele_coupe_donne_une_relance_generique(client, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "ollama", FauxOllama(echoue=True))
    monkeypatch.setattr(dialogue, "transcrire", lambda octets: "Une journee chargee.")
    corps = _poster(client).json()
    assert corps["source"] == "rules"
    assert corps["reponse"] in dialogue.RELANCES_SANS_MODELE


def test_dernier_tour_sans_modele_cloture(client, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "ollama", FauxOllama(echoue=True))
    monkeypatch.setattr(dialogue, "transcrire", lambda octets: "Fatigue.")
    corps = _poster(client, dernier_tour="true").json()
    assert corps["reponse"] == dialogue.CLOTURE_SANS_MODELE


def test_silence_ne_derange_pas_le_modele(client, monkeypatch, faux_ollama):
    monkeypatch.setattr(dialogue, "transcrire", lambda octets: "")
    corps = _poster(client).json()
    assert corps == {"entendu": "", "reponse": dialogue.RELANCE_SILENCE, "source": "rules",
                     "humeur": None}
    assert faux_ollama.messages is None


def test_whisper_absent_donne_503(client, monkeypatch):
    def indisponible(octets):
        raise dialogue.DialogueIndisponible("bibliotheque faster-whisper non installee")

    monkeypatch.setattr(dialogue, "transcrire", indisponible)
    r = _poster(client)
    assert r.status_code == 503


def test_historique_illisible_refuse(client, monkeypatch):
    monkeypatch.setattr(dialogue, "transcrire", lambda octets: "bonjour")
    assert _poster(client, historique="pas du json").status_code == 422


def test_rien_n_est_ecrit_en_base(client, monkeypatch, faux_ollama, db_session):
    from app.models.tables import Base

    monkeypatch.setattr(dialogue, "transcrire", lambda octets: "J'ai dormi deux heures.")
    avant = {t.name: db_session.execute(t.select()).fetchall() for t in Base.metadata.sorted_tables}
    _poster(client)
    apres = {t.name: db_session.execute(t.select()).fetchall() for t in Base.metadata.sorted_tables}
    assert avant == apres


def test_audio_trop_court_est_un_silence(monkeypatch):
    # Pas besoin de Whisper pour savoir qu'un dixieme de seconde ne dit rien.
    monkeypatch.setattr(dialogue, "_charger_whisper", lambda: pytest.fail("Whisper charge"))
    assert dialogue.transcrire(_wav(secondes=0.1)) == ""


def test_audio_illisible(monkeypatch):
    with pytest.raises(dialogue.DialogueIndisponible):
        dialogue.transcrire(b"ceci n'est pas un wav")


def test_reechantillonnage_vers_16k():
    audio = dialogue._audio_16k(_wav(secondes=1.0, taux=48_000))
    assert abs(len(audio) - 16_000) <= 1


def test_lhumeur_est_notee_et_gardee_seule(client, monkeypatch, faux_ollama, db_session):
    """La note d'humeur (sur 100) est rangee ; les mots, jamais."""
    from app.models.tables import Astronaute, Mesure, Session as SessionModel
    from datetime import datetime, timezone

    a = Astronaute(nom="Test")
    db_session.add(a)
    db_session.flush()
    s = SessionModel(astronaute_id=a.id, debut=datetime.now(timezone.utc), mode="measuring")
    db_session.add(s)
    db_session.commit()
    monkeypatch.setattr(dialogue, "transcrire", lambda octets: "Journee difficile.")
    corps = client.post(f"/api/v1/sessions/{s.id}/dialogue",
                        files={"fichier": ("voix.wav", _wav(), "audio/wav")}).json()
    assert corps["humeur"] == 40
    lignes = db_session.query(Mesure).filter_by(session_id=s.id, capteur="parole").all()
    assert [l.valeurs for l in lignes] == [{"humeur": 40}]


def test_les_mots_de_detresse_font_tomber_lhumeur(client, monkeypatch, faux_ollama):
    monkeypatch.setattr(dialogue, "transcrire", lambda octets: "J'ai plus envie de vivre.")
    corps = _poster(client).json()
    assert corps["humeur"] <= 5
