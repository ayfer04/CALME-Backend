from app.services.exercices import CATALOGUE, LIBELLES_SIGNAUX, exercices_autorises, signal_dominant
from app.services.indice import INVERSES


def test_le_catalogue_a_quatorze_exercices_aux_id_uniques():
    assert len(CATALOGUE) == 14
    assert len({e["id"] for e in CATALOGUE}) == 14


def test_chaque_exercice_a_la_forme_du_contrat_front():
    for exercice in CATALOGUE:
        assert set(exercice) == {"id", "name", "duration", "indication", "minLevel", "kind",
                                 "music", "signals"}
        assert exercice["minLevel"] in {"green", "amber", "red"}
        assert exercice["kind"] in {"breathing", "grounding", "audio", "light", "nap", "journal",
                                    "relaxation", "reflection"}
        assert exercice["music"] is None or exercice["music"].startswith("/audio/")
        assert exercice["signals"] and set(exercice["signals"]) <= set(LIBELLES_SIGNAUX)


def test_chaque_signal_a_au_moins_un_exercice():
    for signal in LIBELLES_SIGNAUX:
        assert any(signal in e["signals"] for e in CATALOGUE), signal


def test_en_vert_les_exercices_sont_courts_et_legers():
    ids = {e["id"] for e in exercices_autorises("green")}
    assert "journal" in ids
    assert "playlist" in ids
    assert "sieste" not in ids


def test_en_rouge_la_coherence_cardiaque_est_disponible():
    assert "cc365" in {e["id"] for e in exercices_autorises("red")}


def test_en_rouge_uniquement_de_la_respiration_meme_visage_crispe():
    rouges = exercices_autorises("red", dominant="visage")
    assert rouges and all(e["kind"] == "breathing" for e in rouges)


def test_une_mesure_incomplete_propose_les_exercices_doux():
    doux = exercices_autorises("unreliable")
    assert doux and all(e["minLevel"] == "green" for e in doux)
    assert exercices_autorises("unreliable", dominant="visage")[0]["id"] == "visage"


def test_le_signal_dominant_passe_en_tete():
    assert exercices_autorises("green", dominant="visage")[0]["id"] == "visage"
    assert exercices_autorises("red", dominant="eda_reponses")[0]["id"] == "soupir"
    assert exercices_autorises("amber", dominant="fatigue")[0]["id"] in {"visualisation", "circadien", "sieste", "journal"}


def test_signal_dominant():
    assert signal_dominant({"fc_moyenne": 2.1, "visage": 0.8}, INVERSES) == "fc_moyenne"
    # Variabilite cardiaque : c'est une BAISSE qui signe le stress.
    assert signal_dominant({"hrv_rmssd": -2.5, "fc_moyenne": 0.9}, INVERSES) == "hrv_rmssd"
    assert signal_dominant({"visage": 0.3, "voix": 0.2}, INVERSES) == "diffus"
    assert signal_dominant({"voix": -1.6, "fc_moyenne": -0.4}, INVERSES) == "fatigue"
    assert signal_dominant({}, INVERSES) == "diffus"
