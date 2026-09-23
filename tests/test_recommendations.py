from datetime import datetime, timezone

from app.models.tables import Astronaute, Decision, Session as SessionModel


def _decision(db_session, niveau="green", indice=25.0, assessment_id="44444444-4444-4444-4444-444444444444"):
    astro = Astronaute(nom="Test")
    db_session.add(astro)
    db_session.flush()
    session = SessionModel(astronaute_id=astro.id, debut=datetime.now(timezone.utc), mode="measuring")
    db_session.add(session)
    db_session.flush()
    decision = Decision(
        session_id=session.id, ts=datetime.now(timezone.utc),
        indice_charge=indice, niveau=niveau, exercice_declenche=False,
        consigne_ia=None, source="rules", confiance=0.9,
        assessment_id=assessment_id,
    )
    db_session.add(decision)
    db_session.commit()
    db_session.refresh(decision)
    return decision


def test_recommander_persiste_lexercice_et_la_consigne(client, db_session, monkeypatch):
    # Pas d'appel reseau reel a Ollama dans les tests : on force le repli
    # deterministe sur les regles, comme tests/test_consigne.py le fait deja.
    monkeypatch.setattr("app.services.consigne.interroger_modele", lambda *a, **k: None)
    decision = _decision(db_session)

    reponse = client.post(f"/api/v1/assessments/{decision.assessment_id}/recommend")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["id"] == f"reco-{decision.assessment_id}"
    assert corps["assessmentId"] == decision.assessment_id
    assert corps["source"] == "rules"
    assert corps["exercise"]["minLevel"] == "green"
    assert corps["modelName"] is None

    db_session.refresh(decision)
    assert decision.exercice_id == corps["exercise"]["id"]
    assert decision.consigne_ia == corps["message"]
    assert decision.exercice_declenche is True


def test_recommander_sur_une_evaluation_inconnue_est_refuse(client):
    reponse = client.post("/api/v1/assessments/inconnu/recommend")
    assert reponse.status_code == 404


def test_recommander_sans_exercice_autorise_ne_fabrique_rien(client, db_session, monkeypatch):
    """Niveau 'unreliable' : exercices_autorises() renvoie une liste vide, et
    rediger() renvoie alors exercice=None. Le contrat TS attend un Exercise
    non-nul (Frontend/src/api/types.ts, Recommendation.exercise) : plutot que
    d'y placer un exercise=None qui violerait ce contrat, la route renvoie
    null - il n'y a pas de recommandation a faire, et pretendre le contraire
    serait plus malhonnete qu'un null.
    """
    monkeypatch.setattr("app.services.consigne.interroger_modele", lambda *a, **k: None)
    decision = _decision(db_session, niveau="unreliable",
                         assessment_id="66666666-6666-6666-6666-666666666666")

    reponse = client.post(f"/api/v1/assessments/{decision.assessment_id}/recommend")
    assert reponse.status_code == 200
    assert reponse.json() is None

    # La decision garde neanmoins la trace : pas d'exercice declenche, mais
    # le message de maintenance persiste (pour /sessions/{id}/assessment).
    db_session.refresh(decision)
    assert decision.exercice_id is None
    assert decision.exercice_declenche is False


def test_feedback_est_persiste_et_relie_a_la_bonne_decision(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.consigne.interroger_modele", lambda *a, **k: None)
    decision = _decision(db_session)
    recommandation = client.post(f"/api/v1/assessments/{decision.assessment_id}/recommend").json()

    reponse = client.post(
        f"/api/v1/recommendations/{recommandation['id']}/feedback",
        json={"feedback": "helped"},
    )
    assert reponse.status_code == 204

    db_session.refresh(decision)
    assert decision.feedback == "helped"


def test_feedback_sur_un_id_malforme_est_refuse(client):
    reponse = client.post(
        "/api/v1/recommendations/pas-le-bon-format/feedback",
        json={"feedback": "helped"},
    )
    assert reponse.status_code == 404


def test_feedback_sur_une_recommandation_inconnue_est_refuse(client):
    reponse = client.post(
        "/api/v1/recommendations/reco-inconnu/feedback",
        json={"feedback": "not-really"},
    )
    assert reponse.status_code == 404


def test_feedback_refuse_une_valeur_hors_contrat(client, db_session, monkeypatch):
    monkeypatch.setattr("app.services.consigne.interroger_modele", lambda *a, **k: None)
    decision = _decision(db_session, assessment_id="77777777-7777-7777-7777-777777777777")
    reponse = client.post(
        f"/api/v1/recommendations/reco-{decision.assessment_id}/feedback",
        json={"feedback": "bof"},
    )
    assert reponse.status_code == 422
