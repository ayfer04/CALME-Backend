from app.api.v1.assess import baseline_ou_generique, construire_assessment

GENERIQUE = {
    "hrv_rmssd": (42.0, 15.0),
    "eda_reponses": (3.0, 2.0),
    "eda_fond": (5.0, 2.0),
    "fc_moyenne": (72.0, 9.0),
    "voix": (0.5, 0.15),
    "visage": (0.5, 0.15),
}


def test_sous_dix_seances_la_baseline_est_generique_et_la_confiance_baisse():
    base, facteur = baseline_ou_generique(historique=[], generique=GENERIQUE)
    assert base == GENERIQUE
    assert abs(facteur - 0.6) < 1e-9


def test_au_dela_de_dix_seances_la_baseline_est_personnelle():
    historique = [{"hrv_rmssd": 50.0 + i} for i in range(12)]
    base, facteur = baseline_ou_generique(historique=historique, generique=GENERIQUE)
    assert abs(facteur - 1.0) < 1e-9
    moyenne, ecart_type = base["hrv_rmssd"]
    assert abs(moyenne - 55.5) < 0.01
    assert ecart_type > 0


def test_lassessment_a_la_forme_attendue_par_le_front():
    a = construire_assessment(
        session_id=1,
        mesures={"hrv_rmssd": 30.0, "eda_reponses": 6.0, "fc_moyenne": 78.0,
                 "eda_fond": 7.0, "voix": None, "visage": None},
        baseline=GENERIQUE,
        facteur_confiance=1.0,
        indicateurs_bruts={"heartRateMean": 78.0, "heartRateVariability": 30.0,
                           "edaTonic": 7.0, "edaPhasic": 6.0,
                           "faceTension": None, "voiceIndex": None,
                           "breathingRate": 14.0},
    )
    assert set(a) >= {"id", "sessionId", "index", "level", "confidence",
                      "missingSignals", "indicators", "personalBaseline", "computedAt"}
    assert a["level"] in {"green", "amber", "red", "unreliable"}
    # Voix et visage absents : leurs poids sont retires, 1 - 0,15 - 0,10 = 0,75
    assert abs(a["confidence"] - 0.75) < 1e-9
    signaux = {m["signal"] for m in a["missingSignals"]}
    assert signaux == {"voice", "face"}
