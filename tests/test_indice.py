from app.services.indice import POIDS, ecart_z, indice_charge, niveau_depuis


def test_les_poids_somment_a_un():
    assert abs(sum(POIDS.values()) - 1.0) < 1e-9


def test_a_sa_propre_normale_lindice_vaut_trente():
    zs = {cle: 0.0 for cle in POIDS}
    indice, confiance = indice_charge(zs)
    assert abs(indice - 30.0) < 0.01
    assert abs(confiance - 1.0) < 1e-9


def test_reproduit_le_scenario_du_dossier():
    """Mei sort a 58, en orange, alors qu'elle est d'ordinaire autour de 30.

    Attention au signe : le stress fait BAISSER la variabilite cardiaque. Un z
    positif sur hrv_rmssd veut dire « mieux que d'habitude », pas « plus
    stressee ». C'est pour ca que le service l'inverse, et c'est pour ca que ce
    test doit le modeliser correctement sous peine de ne rien verifier.
    """
    zs = {cle: 1.4 for cle in POIDS}
    zs["hrv_rmssd"] = -1.4
    indice, _ = indice_charge(zs)
    assert abs(indice - 58.0) < 0.5
    assert niveau_depuis(indice, 1.0) == "amber"


def test_un_signal_manquant_renormalise_et_baisse_la_confiance():
    zs = {cle: 1.0 for cle in POIDS if cle != "visage"}
    zs["hrv_rmssd"] = -1.0
    indice, confiance = indice_charge(zs)
    assert abs(confiance - 0.90) < 1e-9
    # Les poids restants sont renormalises : l'indice ne bouge pas.
    assert abs(indice - 50.0) < 0.01


def test_les_seuils_sont_quarante_et_soixante_dix():
    assert niveau_depuis(39.9, 1.0) == "green"
    assert niveau_depuis(40.0, 1.0) == "amber"
    assert niveau_depuis(69.9, 1.0) == "amber"
    assert niveau_depuis(70.0, 1.0) == "red"


def test_une_confiance_trop_basse_rend_la_mesure_inexploitable():
    assert niveau_depuis(80.0, 0.3) == "unreliable"


def test_lecart_z_est_borne():
    assert ecart_z(1000.0, 0.0, 1.0) == 3.0
    assert ecart_z(-1000.0, 0.0, 1.0) == -3.0
    assert ecart_z(5.0, 5.0, 0.0) == 0.0
