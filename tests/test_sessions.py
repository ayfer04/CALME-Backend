from datetime import datetime, timezone

from app.models.tables import Astronaute, Decision, Session as SessionModel


def _astronaute(db_session, **kwargs):
    valeurs = {"nom": "Mei Tanaka", "role": "Ingenieure systemes", "initiales": "MT",
               "sol_embarquement": 0}
    valeurs.update(kwargs)
    a = Astronaute(**valeurs)
    db_session.add(a)
    db_session.commit()
    db_session.refresh(a)
    return a


def _session_ouverte(db_session, astronaute):
    s = SessionModel(astronaute_id=astronaute.id, debut=datetime.now(timezone.utc), mode="measuring")
    db_session.add(s)
    db_session.commit()
    db_session.refresh(s)
    return s


def test_ouvrir_une_session_renvoie_le_contrat_attendu(client, db_session):
    astro = _astronaute(db_session)
    reponse = client.post("/api/v1/sessions", json={"crewId": str(astro.id), "cabinId": "cabine-01"})
    assert reponse.status_code == 200
    corps = reponse.json()
    assert set(corps) == {"id", "crewId", "startedAt", "closedAt", "mode", "exerciseId"}
    assert corps["crewId"] == str(astro.id)
    assert corps["closedAt"] is None
    assert corps["mode"] == "measuring"
    assert corps["exerciseId"] is None


def test_ouvrir_une_session_pour_un_crew_inconnu_est_refuse(client):
    reponse = client.post("/api/v1/sessions", json={"crewId": "999", "cabinId": "cabine-01"})
    assert reponse.status_code == 404


def test_lire_une_session(client, db_session):
    astro = _astronaute(db_session)
    ouverte = client.post(
        "/api/v1/sessions", json={"crewId": str(astro.id), "cabinId": "cabine-01"}
    ).json()

    reponse = client.get(f"/api/v1/sessions/{ouverte['id']}")
    assert reponse.status_code == 200
    assert reponse.json()["id"] == ouverte["id"]


def test_lire_une_session_absente_renvoie_404(client):
    assert client.get("/api/v1/sessions/999").status_code == 404


def test_lire_une_session_expose_lexercice_retenu(client, db_session):
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    db_session.add(Decision(
        session_id=session.id, ts=datetime.now(timezone.utc),
        indice_charge=50.0, niveau="green", exercice_declenche=True,
        consigne_ia="Ok", source="model", confiance=0.9,
        assessment_id="33333333-3333-3333-3333-333333333333", exercice_id="carre",
    ))
    db_session.commit()

    reponse = client.get(f"/api/v1/sessions/{session.id}")
    assert reponse.json()["exerciseId"] == "carre"


def test_lire_lassessment_sans_decision_renvoie_404(client, db_session):
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    reponse = client.get(f"/api/v1/sessions/{session.id}/assessment")
    assert reponse.status_code == 404


def test_lire_lassessment_relit_la_decision_persistee_sans_recalculer(client, db_session):
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    db_session.add(Decision(
        session_id=session.id, ts=datetime.now(timezone.utc),
        indice_charge=58.3, niveau="amber", exercice_declenche=False,
        consigne_ia=None, source="rules", confiance=0.75,
        assessment_id="11111111-1111-1111-1111-111111111111",
    ))
    db_session.commit()

    reponse = client.get(f"/api/v1/sessions/{session.id}/assessment")
    assert reponse.status_code == 200
    corps = reponse.json()
    # L'id, l'indice, le niveau et la confiance viennent de la ligne
    # persistee : deux appels doivent renvoyer exactement le meme id, pas un
    # uuid4() neuf a chaque fois.
    assert corps["id"] == "11111111-1111-1111-1111-111111111111"
    assert corps["index"] == 58.3
    assert corps["level"] == "amber"
    assert corps["confidence"] == 0.75
    assert corps["sessionId"] == str(session.id)
    # Aucune mesure en base pour cette seance : tous les signaux manquent,
    # aucun n'est invente.
    assert {m["signal"] for m in corps["missingSignals"]} == {"hr", "eda", "voice", "face"}
    assert corps["indicators"]["heartRateMean"] is None

    reponse2 = client.get(f"/api/v1/sessions/{session.id}/assessment")
    assert reponse2.json()["id"] == corps["id"]


def test_cloturer_sans_evaluation_est_refuse(client, db_session):
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    reponse = client.post(f"/api/v1/sessions/{session.id}/close")
    assert reponse.status_code == 409


def test_cloturer_une_session_absente_renvoie_404(client):
    assert client.post("/api/v1/sessions/999/close").status_code == 404


def test_cloturer_renvoie_lindex_avant_et_null_apres_sans_nouvelle_mesure(client, db_session):
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    db_session.add(Decision(
        session_id=session.id, ts=datetime.now(timezone.utc),
        indice_charge=61.0, niveau="amber", exercice_declenche=True,
        consigne_ia="Cinq minutes.", source="rules", confiance=0.8,
        assessment_id="22222222-2222-2222-2222-222222222222", exercice_id="cc365",
    ))
    db_session.commit()

    reponse = client.post(f"/api/v1/sessions/{session.id}/close")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["sessionId"] == str(session.id)
    assert corps["indexBefore"] == 61.0
    # Rien n'a ete mesure depuis l'ouverture : pas de chiffre "apres"
    # invente, un null honnete.
    assert corps["indexAfter"] is None
    assert corps["heartRateBefore"] is None
    assert corps["heartRateAfter"] is None
    assert corps["breathingRateBefore"] is None
    assert corps["breathingRateAfter"] is None
    assert corps["alertRaised"] is False

    # La cloture marque bien la seance comme terminee.
    relue = client.get(f"/api/v1/sessions/{session.id}").json()
    assert relue["closedAt"] is not None
    assert relue["mode"] == "standby"


def test_cloturer_un_niveau_rouge_declenche_lalerte(client, db_session):
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    db_session.add(Decision(
        session_id=session.id, ts=datetime.now(timezone.utc),
        indice_charge=82.0, niveau="red", exercice_declenche=True,
        consigne_ia="On respire.", source="rules", confiance=0.9,
        assessment_id="55555555-5555-5555-5555-555555555555", exercice_id="cc365",
    ))
    db_session.commit()

    corps = client.post(f"/api/v1/sessions/{session.id}/close").json()
    assert corps["alertRaised"] is True


def test_consentement_pose_par_une_session_est_relu_cabine_wide(client, db_session):
    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)

    reponse = client.post(
        f"/api/v1/sessions/{session.id}/consent", json={"camera": False, "microphone": True}
    )
    assert reponse.status_code == 200
    assert reponse.json() == {"camera": False, "microphone": True}

    # Relu depuis la route cabine (pas la meme URL) : bien persiste en base,
    # pas seulement tenu par la requete qui vient de le poser.
    relu = client.get("/api/v1/cabins/cabine-01/consent")
    assert relu.json() == {"camera": False, "microphone": True}


def test_consentement_sur_une_session_absente_est_refuse(client):
    reponse = client.post(
        "/api/v1/sessions/999/consent", json={"camera": False, "microphone": False}
    )
    assert reponse.status_code == 404


def test_la_note_de_fin_se_calcule_sur_lexercice_meme_sans_coeur(client, db_session):
    """Capteur cardiaque absent : la note de fin vient du visage mesure
    pendant l'exercice, et les mesures d'avant la decision n'y comptent pas."""
    from datetime import timedelta

    from app.models.tables import Mesure

    astro = _astronaute(db_session)
    session = _session_ouverte(db_session, astro)
    decision_ts = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.add(Decision(
        session_id=session.id, ts=decision_ts,
        indice_charge=62.0, niveau="amber", exercice_declenche=True,
        consigne_ia="Trois minutes.", source="rules", confiance=0.5,
        assessment_id="77777777-7777-7777-7777-777777777777", exercice_id="visage",
    ))
    # Avant la decision : visage tres crispe (ne doit pas compter).
    db_session.add(Mesure(session_id=session.id, device_id="cabine-front", capteur="visage",
                          seq=0, ts=decision_ts - timedelta(minutes=1),
                          valeurs={"tension": 0.95}, qualite={}))
    # Pendant l'exercice : visage detendu.
    for i in range(5):
        db_session.add(Mesure(session_id=session.id, device_id="cabine-front", capteur="visage",
                              seq=0, ts=decision_ts + timedelta(seconds=30 + i),
                              valeurs={"tension": 0.2}, qualite={}))
    db_session.commit()

    corps = client.post(f"/api/v1/sessions/{session.id}/close").json()
    assert corps["indexBefore"] == 62.0
    assert corps["indexAfter"] is not None
    # Visage detendu (0,2 pour une normale a 0,5) : l'indice passe sous 30.
    assert corps["indexAfter"] < 30.0
