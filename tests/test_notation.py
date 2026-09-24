"""La note de bien-etre sur 100 : 100 = le mieux, 0 = detresse."""

from app.services import notation


def test_visage_detendu_et_souriant_note_haut():
    assert notation.note_visage(0.08) == 95.0
    assert notation.note_visage(0.1, sourire=0.8) == 100.0
    assert notation.note_visage(0.45) < 30


def test_voix_posee_note_haut_tendue_ou_eteinte_plus_bas():
    assert notation.note_voix(0.5) == 85.0
    assert notation.note_voix(0.8) < notation.note_voix(0.2) < 85.0


def test_note_globale_ponderee_sur_ce_qui_existe():
    note, confiance = notation.note_globale({"visage": 90.0, "voix": None, "parole": None})
    assert note == 90.0 and abs(confiance - 0.30) < 1e-9
    note, confiance = notation.note_globale({"visage": 80.0, "voix": 80.0, "parole": 20.0})
    assert note == 53.0 and confiance == 1.0


def test_niveaux_et_couleurs():
    assert notation.niveau(82, 1.0) == "green"
    assert notation.niveau(50, 1.0) == "amber"
    assert notation.niveau(20, 1.0) == "red"
    assert notation.niveau(90, 0.1) == "unreliable"


def test_une_humeur_de_detresse_passe_au_rouge_quoi_quil_arrive():
    assert notation.niveau(75, 1.0, humeur=5) == "red"


def test_filet_de_securite_sur_les_mots_de_detresse():
    assert notation.humeur_securisee(80, "je veux en finir") == 5.0
    assert notation.humeur_securisee(80, "une journée plutôt tranquille") == 80.0


def test_le_modele_seul_ne_note_pas_la_detresse_ni_le_bruit():
    """Un 0 du modele sur une vraie phrase est ramene au plancher ; une phrase
    trop courte (souvent du bruit mal transcrit) n'est pas notee."""
    assert notation.humeur_securisee(0, "je ne sais pas trop quoi dire") == 16.0
    assert notation.humeur_securisee(0, "euh bon") is None


def test_verdict():
    assert notation.verdict(82.4, "green") == "Tout va bien : 82 sur 100."
    assert notation.verdict(28, "red").startswith("Je te sens en difficulté : 28 sur 100.")


def test_signal_dominant_est_la_note_la_plus_basse():
    assert notation.signal_dominant({"visage": 40.0, "voix": 55.0, "parole": 70.0}) == "visage"
    assert notation.signal_dominant({"visage": 80.0, "voix": 75.0, "parole": None}) == "diffus"
