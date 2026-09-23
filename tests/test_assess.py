from datetime import datetime, timezone

import neurokit2 as nk

from app.api.v1.assess import baseline_ou_generique, construire_assessment
from app.models.tables import Astronaute, Indicateur, Mesure, Session as SessionModel

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


# ---------------------------------------------------------------------------
# Tests de la route POST /sessions/{id}/assess : la baseline personnelle doit
# s'activer depuis l'historique reel de l'astronaute, pas depuis une liste
# vide codee en dur. C'est justement l'absence de test de route qui avait
# laisse passer ce defaut (voir tache-24).
# ---------------------------------------------------------------------------

def _astronaute(db_session, nom="Test"):
    astro = Astronaute(nom=nom)
    db_session.add(astro)
    db_session.flush()
    return astro


def _session_ouverte(db_session, astronaute):
    session = SessionModel(
        astronaute_id=astronaute.id, debut=datetime.now(timezone.utc), mode="measuring"
    )
    db_session.add(session)
    db_session.flush()
    return session


def _ajouter_mesure_cardiaque(db_session, session):
    """Un vrai signal PPG simule : sans lui, hrv_rmssd et fc_moyenne restent
    None et la confiance calculee est nulle quel que soit le facteur de
    baseline, ce qui ne testerait rien.
    """
    ppg = nk.ppg_simulate(duration=30, sampling_rate=100, heart_rate=70, random_state=1)
    db_session.add(Mesure(
        session_id=session.id, device_id="cabine-01", capteur="ppg", seq=0,
        ts=datetime.now(timezone.utc),
        valeurs={"ppg_raw": [int(v * 10000) for v in ppg]}, qualite={"cardiaque": 0.9},
    ))
    db_session.commit()


def _historique_de_douze_seances(db_session, astronaute):
    """Douze seances passees, avec un hrv_rmssd connu, pour que la baseline
    personnelle calculee soit verifiable au chiffre pres (moyenne 55.5, comme
    le test pur test_au_dela_de_dix_seances_la_baseline_est_personnelle).
    """
    for i in range(12):
        s = SessionModel(
            astronaute_id=astronaute.id, debut=datetime.now(timezone.utc),
            fin=datetime.now(timezone.utc), mode="standby",
        )
        db_session.add(s)
        db_session.flush()
        db_session.add(Indicateur(
            session_id=s.id, astronaute_id=astronaute.id, ts=datetime.now(timezone.utc),
            fc_moyenne=None, hrv_rmssd=50.0 + i, eda_fond=None, eda_reponses=None,
            frequence_respiratoire=None,
        ))
    db_session.commit()


def test_assess_sans_historique_la_confiance_porte_le_facteur_generique(client, db_session):
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    _ajouter_mesure_cardiaque(db_session, session)

    reponse = client.post(f"/api/v1/sessions/{session.id}/assess")
    assert reponse.status_code == 200
    corps = reponse.json()

    # Seuls hrv_rmssd (0,30) et fc_moyenne (0,10) sont disponibles : la
    # confiance de base est 0,40, multipliee par le facteur generique 0,6.
    assert abs(corps["confidence"] - 0.24) < 0.01
    # Aucun historique : la baseline reste la generique (42.0), jamais 42.0
    # invente pour une autre raison — ici c'est bien la valeur de repli.
    assert corps["personalBaseline"] == 42.0


def test_assess_avec_douze_seances_la_baseline_est_personnelle_et_la_confiance_pleine(
    client, db_session
):
    astro = _astronaute(db_session)
    _historique_de_douze_seances(db_session, astro)
    session = _session_ouverte(db_session, astro)
    _ajouter_mesure_cardiaque(db_session, session)

    reponse = client.post(f"/api/v1/sessions/{session.id}/assess")
    assert reponse.status_code == 200
    corps = reponse.json()

    # Douze seances passees (>= SEANCES_POUR_BASELINE) : facteur 1.0, donc la
    # confiance de base (0,40) n'est plus rabotee.
    assert abs(corps["confidence"] - 0.40) < 0.01
    # La baseline vient des 12 seances precedentes (moyenne 55.5), pas de la
    # constante generique 42.0.
    assert corps["personalBaseline"] == 55.5


def test_assess_dune_autre_seance_du_meme_astronaute_nest_jamais_dans_son_propre_historique(
    client, db_session
):
    """Rejouer /assess sur la seance en cours ne doit jamais faire grossir son
    propre historique : sinon on finirait par comparer l'astronaute a
    lui-meme quelques secondes plus tot.
    """
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    _ajouter_mesure_cardiaque(db_session, session)

    premiere = client.post(f"/api/v1/sessions/{session.id}/assess").json()
    seconde = client.post(f"/api/v1/sessions/{session.id}/assess").json()

    assert premiere["personalBaseline"] == seconde["personalBaseline"] == 42.0


# ---------------------------------------------------------------------------
# Palier 'unreliable' : rediger() renvoie exercice=None, et ni l'evenement
# WebSocket ni la reponse HTTP ne doivent alors prétendre a une recommandation
# (voir tache-24, correction 2 : Frontend/src/api/types.ts declare
# Recommendation.exercise non-nullable).
# ---------------------------------------------------------------------------

def test_assess_niveau_unreliable_pousse_un_notice_jamais_une_recommandation_a_null(
    client, db_session, monkeypatch
):
    monkeypatch.setattr("app.services.consigne.interroger_modele", lambda *a, **k: None)
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    db_session.commit()
    # Aucune mesure : tous les signaux manquent, la confiance calculee est
    # nulle, donc le niveau est 'unreliable' et exercices_autorises() est vide.

    with client.websocket_connect(f"/api/v1/sessions/{session.id}/stream") as ws:
        reponse = client.post(f"/api/v1/sessions/{session.id}/assess")
        assert reponse.status_code == 200
        evaluation = reponse.json()
        assert evaluation["level"] == "unreliable"

        evenement_assessment = ws.receive_json()
        assert evenement_assessment["type"] == "assessment"

        # Jamais d'evenement 'recommendation' avec exercise=None : un 'notice'
        # a la place, avec le message de maintenance.
        evenement_suivant = ws.receive_json()
        assert evenement_suivant["type"] == "notice"
        assert evenement_suivant["payload"]["level"] == "warning"
        assert "exploitable" in evenement_suivant["payload"]["message"].lower()

    # Le endpoint HTTP direct suit le meme principe : pas de Recommendation
    # avec exercise=None, un null honnete a la place.
    reco = client.post(f"/api/v1/assessments/{evaluation['id']}/recommend")
    assert reco.status_code == 200
    assert reco.json() is None
