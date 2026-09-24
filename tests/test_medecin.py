"""Le poste du medecin : chaque route que le front appelle existe et a la
forme attendue (Frontend/src/api/types.ts)."""

from datetime import datetime, timedelta, timezone

from app.models.tables import Astronaute, Decision, Mesure, Session as SessionModel


def _seance(db, astro, indice, niveau, il_y_a_jours=0, apres=None):
    ts = datetime.now(timezone.utc) - timedelta(days=il_y_a_jours)
    s = SessionModel(astronaute_id=astro.id, debut=ts, mode="normal")
    db.add(s)
    db.flush()
    d = Decision(session_id=s.id, ts=ts, indice_charge=indice, niveau=niveau,
                 exercice_declenche=True, consigne_ia="…", source="rules", confiance=0.8,
                 assessment_id=f"{s.id:08d}-0000-0000-0000-000000000000", exercice_id="cc365",
                 indice_apres=apres)
    db.add(d)
    db.commit()
    return s, d


def _astro(db, nom="Maël Bourdin"):
    a = Astronaute(nom=nom)
    db.add(a)
    db.commit()
    return a


def test_vue_equipage(client, db_session):
    astro = _astro(db_session)
    _seance(db_session, astro, 60.0, "amber", il_y_a_jours=3)
    _seance(db_session, astro, 40.0, "amber")
    vue = client.get("/api/v1/crew/overview").json()
    assert len(vue) == 1
    ligne = vue[0]
    assert ligne["member"]["initials"] == "MB"
    assert ligne["meanIndex"] == 50.0
    assert len(ligne["spark"]) == 7 and ligne["spark"][-1] == 40.0
    assert ligne["lastSessionAt"] is not None


def test_historique_avec_avant_apres(client, db_session):
    astro = _astro(db_session)
    _seance(db_session, astro, 62.0, "amber", apres=41.0)
    h = client.get(f"/api/v1/crew/{astro.id}/history").json()
    assert len(h["points"]) == 30
    assert h["sessions"][0]["indexBefore"] == 62.0
    assert h["sessions"][0]["indexAfter"] == 41.0
    assert h["sessions"][0]["exerciseName"] == "Cohérence cardiaque 365"
    assert client.get("/api/v1/crew/ana/history").status_code == 404


def test_alertes_et_acquittement(client, db_session):
    astro = _astro(db_session)
    _seance(db_session, astro, 30.0, "green")
    _, rouge = _seance(db_session, astro, 78.0, "red")
    alertes = client.get("/api/v1/alerts").json()
    assert [a["id"] for a in alertes] == [f"alerte-{rouge.id}"]
    assert alertes[0]["acknowledgedAt"] is None
    acquittee = client.post(f"/api/v1/alerts/alerte-{rouge.id}/acknowledge").json()
    assert acquittee["acknowledgedAt"] is not None
    assert acquittee["acknowledgedBy"] == "Médecin de bord"


def test_tendances(client, db_session):
    astro = _astro(db_session)
    _seance(db_session, astro, 50.0, "amber")
    _seance(db_session, astro, 20.0, "green")
    t = client.get("/api/v1/trends").json()
    assert len(t["meanIndex"]) == 30
    assert t["amberShare"] == 0.5
    assert t["sessionsPerDay"] == 2.0


def test_energie_et_consigne(client):
    e = client.get("/api/v1/power").json()
    assert e["mode"] == "standby" and e["budgetWatts"] == 72.0
    assert {l["label"] for l in e["lines"]} >= {"Serveur", "Caméra"}
    e = client.post("/api/v1/power/setpoint", json={"percent": 40}).json()
    assert e["mode"] == "degraded" and e["budgetWatts"] == 28.8
    client.post("/api/v1/power/setpoint", json={"percent": 100})


def test_sante_a_la_forme_du_poste_medecin(client):
    h = client.get("/api/v1/health").json()
    assert {"api", "base", "database", "model", "sensors", "buffer"} <= set(h)
    assert h["sensors"]["total"] == 4


def test_capteurs_visage_et_voix_affichent_leurs_valeurs(client, db_session):
    astro = _astro(db_session)
    s, _ = _seance(db_session, astro, 40.0, "amber")
    for t in (0.3, 0.4):
        db_session.add(Mesure(session_id=s.id, device_id="cabine-front", capteur="visage", seq=0,
                              ts=datetime.now(timezone.utc), valeurs={"tension": t}, qualite={}))
    db_session.commit()
    capteurs = {c["key"]: c for c in client.get("/api/v1/cabins/cabine-01/sensors").json()}
    assert capteurs["face"]["value"] == 0.4
    assert capteurs["face"]["window"] == [0.3, 0.4]
    assert capteurs["voice"]["value"] is None
