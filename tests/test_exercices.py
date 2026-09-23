from app.services.exercices import CATALOGUE, exercices_autorises


def test_le_catalogue_a_huit_exercices():
    assert len(CATALOGUE) == 8


def test_chaque_exercice_a_la_forme_du_contrat_front():
    for exercice in CATALOGUE:
        assert set(exercice) == {"id", "name", "duration", "indication", "minLevel", "kind"}
        assert exercice["minLevel"] in {"green", "amber", "red"}
        assert exercice["kind"] in {"breathing", "grounding", "audio", "light", "nap", "journal"}


def test_en_vert_les_exercices_sont_courts_et_legers():
    ids = {e["id"] for e in exercices_autorises("green")}
    assert "journal" in ids
    assert "playlist" in ids


def test_en_rouge_la_coherence_cardiaque_est_disponible():
    assert "cc365" in {e["id"] for e in exercices_autorises("red")}


def test_une_mesure_inexploitable_ne_propose_rien():
    assert exercices_autorises("unreliable") == []
