from app.services.consigne import CONSIGNES_GENERIQUES, rediger
from app.services.exercices import exercices_autorises


def test_sans_modele_le_systeme_retombe_sur_les_regles(monkeypatch):
    monkeypatch.setattr("app.services.consigne.interroger_modele",
                        lambda *a, **k: None)
    autorises = exercices_autorises("amber")
    exercice, message, source, modele = rediger(
        {"level": "amber", "index": 55.0}, autorises, historique=[])
    assert source == "rules"
    assert modele is None
    assert exercice in autorises
    assert message == CONSIGNES_GENERIQUES[exercice["id"]]


def test_un_exercice_hors_liste_est_refuse(monkeypatch):
    """Le modele n'a acces a aucun autre levier que la liste qu'on lui donne."""
    monkeypatch.setattr("app.services.consigne.interroger_modele",
                        lambda *a, **k: {"exercice_id": "sieste", "message": "Dormez."})
    autorises = exercices_autorises("red")   # respiration uniquement
    exercice, message, source, _ = rediger(
        {"level": "red", "index": 78.0}, autorises, historique=[])
    assert exercice["id"] != "sieste"
    assert source == "rules"


def test_une_reponse_valide_du_modele_est_retenue(monkeypatch):
    monkeypatch.setattr("app.services.consigne.interroger_modele",
                        lambda *a, **k: {"exercice_id": "cc365",
                                         "message": "Cinq minutes, on respire ensemble."})
    autorises = exercices_autorises("red")
    exercice, message, source, modele = rediger(
        {"level": "red", "index": 78.0}, autorises, historique=[])
    assert exercice["id"] == "cc365"
    assert message == "Cinq minutes, on respire ensemble."
    assert source == "model"
    assert modele is not None


def test_aucun_exercice_autorise_ne_fait_pas_planter():
    exercice, message, source, _ = rediger(
        {"level": "unreliable", "index": 0.0}, [], historique=[])
    assert exercice is None
    assert source == "rules"
    assert "maintenance" in message.lower()
