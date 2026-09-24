from app.services.consigne import CONSIGNES_GENERIQUES, MODELE, MODELE_DEGRADE, rediger
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
                                         "message": "On respire ensemble, tranquillement."})
    autorises = exercices_autorises("red")
    exercice, message, source, modele = rediger(
        {"level": "red", "index": 78.0}, autorises, historique=[])
    assert exercice["id"] == "cc365"
    # L'accroche du modele, puis le deroule exact du catalogue.
    assert message.startswith("On respire ensemble, tranquillement. ")
    assert message.endswith(CONSIGNES_GENERIQUES["cc365"])
    assert source == "model"
    assert modele is not None


def test_aucun_exercice_autorise_ne_fait_pas_planter():
    exercice, message, source, _ = rediger(
        {"level": "unreliable", "index": 0.0}, [], historique=[])
    assert exercice is None
    assert source == "rules"
    assert "maintenance" in message.lower()


def test_le_modele_degrade_prend_le_relais_si_le_nominal_echoue(monkeypatch):
    """Le nominal echoue, le degrade repond : le nom renvoye doit etre celui
    qui a vraiment redige, pas le nominal - sinon la tracabilite affichee
    au front (modelName) est mensongere."""
    def faux_interroger(evaluation, autorises, historique, modele=None):
        if modele == MODELE_DEGRADE:
            return {"exercice_id": "cc365", "message": "Consigne du modele degrade."}
        return None

    monkeypatch.setattr("app.services.consigne.interroger_modele", faux_interroger)
    autorises = exercices_autorises("red")
    exercice, message, source, modele = rediger(
        {"level": "red", "index": 78.0}, autorises, historique=[])
    assert exercice["id"] == "cc365"
    assert message.startswith("Consigne du modele degrade. ")
    assert source == "model"
    assert modele == MODELE_DEGRADE


def test_les_deux_modeles_indisponibles_retombe_sur_les_regles(monkeypatch):
    """Nominal et degrade echouent tous les deux, une seule fois chacun :
    le systeme retombe sur les regles sans boucler indefiniment."""
    appels = []

    def faux_interroger(evaluation, autorises, historique, modele=None):
        appels.append(modele)
        return None

    monkeypatch.setattr("app.services.consigne.interroger_modele", faux_interroger)
    autorises = exercices_autorises("amber")
    exercice, message, source, modele = rediger(
        {"level": "amber", "index": 55.0}, autorises, historique=[])
    assert source == "rules"
    assert modele is None
    assert exercice in autorises
    assert message == CONSIGNES_GENERIQUES[exercice["id"]]
    assert appels == [MODELE, MODELE_DEGRADE]


def test_une_accroche_qui_deborde_est_ecartee():
    """Chiffres, durees ou pave de consignes : l'accroche disparait, il ne
    reste que le deroule exact (le 3b melangeait les rythmes)."""
    from app.services.consigne import nettoyer_accroche

    assert nettoyer_accroche("Inspire sur quatre temps, retiens sur sept.") == ""
    assert nettoyer_accroche("Respire 4 secondes.") == ""
    assert nettoyer_accroche("Alors que la nuit tombe, laisse-toi aller. Puis blabla.") == \
        "Alors que la nuit tombe, laisse-toi aller."
    assert nettoyer_accroche("C&#39;est le moment de souffler.") == "C'est le moment de souffler."
