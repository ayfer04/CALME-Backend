from app.services.voix import FEATURES, indice_vocal

BASELINE = {cle: (10.0, 2.0) for cle in FEATURES}


def test_les_poids_somment_a_un():
    assert abs(sum(FEATURES.values()) - 1.0) < 1e-9


def test_ni_jitter_ni_shimmer():
    """Trop sensibles au micro d'une webcam pour porter un indice."""
    noms = " ".join(FEATURES).lower()
    assert "jitter" not in noms
    assert "shimmer" not in noms


def test_a_la_baseline_lindice_vaut_un_demi():
    features = {cle: 10.0 for cle in FEATURES}
    assert abs(indice_vocal(features, BASELINE) - 0.5) < 0.01


def test_tout_au_dessus_de_la_baseline_monte_lindice():
    features = {cle: 16.0 for cle in FEATURES}   # +3 sigma
    assert indice_vocal(features, BASELINE) > 0.8


def test_lindice_reste_borne():
    enorme = {cle: 1e6 for cle in FEATURES}
    minuscule = {cle: -1e6 for cle in FEATURES}
    assert 0.0 <= indice_vocal(enorme, BASELINE) <= 1.0
    assert 0.0 <= indice_vocal(minuscule, BASELINE) <= 1.0


def test_une_feature_absente_ne_fait_pas_planter():
    partiel = {cle: 10.0 for cle in list(FEATURES)[:2]}
    assert 0.0 <= indice_vocal(partiel, BASELINE) <= 1.0
