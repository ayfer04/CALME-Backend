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


# ---------------------------------------------------------------------------
# Palier 'unreliable' : rediger() renvoie exercice=None, et ni l'evenement
# WebSocket ni la reponse HTTP ne doivent alors prétendre a une recommandation
# (voir tache-24, correction 2 : Frontend/src/api/types.ts declare
# Recommendation.exercise non-nullable).
# ---------------------------------------------------------------------------

def test_assess_mesure_incomplete_propose_quand_meme_un_exercice_doux(
    client, db_session, monkeypatch
):
    """Aucun capteur n'a repondu : le niveau reste 'unreliable' (on ne tranche
    pas sur la charge), mais la personne repart avec un exercice doux, et la
    consigne dit que la mesure est partielle."""
    monkeypatch.setattr("app.services.consigne.interroger_modele", lambda *a, **k: None)
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    db_session.commit()

    with client.websocket_connect(f"/api/v1/sessions/{session.id}/stream") as ws:
        reponse = client.post(f"/api/v1/sessions/{session.id}/assess")
        assert reponse.status_code == 200
        evaluation = reponse.json()
        assert evaluation["level"] == "unreliable"

        assert ws.receive_json()["type"] == "assessment"
        recommandation = ws.receive_json()
        assert recommandation["type"] == "recommendation"
        exercice = recommandation["payload"]["exercise"]
        assert exercice["minLevel"] == "green"
        assert "incomplète" in recommandation["payload"]["message"].lower()

    reco = client.post(f"/api/v1/assessments/{evaluation['id']}/recommend")
    assert reco.status_code == 200
    assert reco.json()["exercise"]["minLevel"] == "green"


def test_la_decision_retient_le_signal_dominant(client, db_session):
    from app.models.tables import Decision

    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    _ajouter_mesure_cardiaque(db_session, session)

    corps = client.post(f"/api/v1/sessions/{session.id}/assess").json()
    decision = db_session.query(Decision).filter_by(assessment_id=corps["id"]).one()
    assert decision.signal_dominant == corps["dominantSignal"]


def test_le_visage_et_la_voix_comptent_dans_la_mesure(client, db_session):
    """Diffuses a l'ecran, ils n'etaient jamais ranges : l'indice les
    ignorait. Ils sont maintenant gardes (des nombres, jamais une image)."""
    from app.api.v1.calcul import mesures_de_la_seance

    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    db_session.commit()
    for tension in (0.4, 0.6):
        r = client.post(f"/api/v1/sessions/{session.id}/face",
                        json={"at": "2026-09-24T10:00:00Z", "tension": tension,
                              "blinkRate": 12, "stillness": 0.8})
        assert r.status_code == 202

    mesures = mesures_de_la_seance(db_session, session.id)
    assert abs(mesures["visage"] - 0.5) < 1e-9


def test_lassessment_a_la_forme_attendue_par_le_front():
    """Note de bien-etre sur 100 : visage detendu, voix posee, humeur bonne."""
    a = construire_assessment(session_id=1, mesures={"visage": 0.1, "voix": 0.5, "parole": 80.0})
    assert set(a) >= {"id", "sessionId", "index", "level", "confidence", "missingSignals",
                      "indicators", "scores", "verdict", "dominantSignal", "computedAt"}
    assert a["level"] == "green"
    assert a["index"] >= 80
    assert a["verdict"].startswith("Tout va bien")
    assert abs(a["confidence"] - 1.0) < 1e-9
    assert a["missingSignals"] == []


def test_lassessment_nomme_la_note_la_plus_basse():
    a = construire_assessment(session_id=1, mesures={"visage": 0.45, "voix": 0.5, "parole": 70.0})
    assert a["scores"]["face"] < 60
    assert a["dominantSignal"] == "visage"


def test_sans_camera_ni_micro_on_ne_conclut_rien():
    a = construire_assessment(session_id=1, mesures={})
    assert a["level"] == "unreliable"
    assert {m["signal"] for m in a["missingSignals"]} == {"face", "voice"}
