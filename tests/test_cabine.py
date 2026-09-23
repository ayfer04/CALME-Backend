from datetime import datetime, timezone

import neurokit2 as nk

from app.models.tables import Astronaute, Mesure, Session as SessionModel


def test_occupant_cree_lastronaute_de_test_si_la_table_est_vide(client):
    """Meme simplification assumee que get_or_create_session dans ingest.py."""
    reponse = client.get("/api/v1/cabins/cabine-01/occupant")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["displayName"] == "Astronaute de test"
    assert corps["id"] == "1"


def test_occupant_renvoie_le_premier_astronaute_de_la_table(client, db_session):
    a1 = Astronaute(nom="Mei Tanaka", role="Ingenieure systemes", initiales="MT",
                     sol_embarquement=3)
    db_session.add(a1)
    db_session.commit()

    reponse = client.get("/api/v1/cabins/cabine-01/occupant")
    corps = reponse.json()
    assert corps["displayName"] == "Mei Tanaka"
    assert corps["role"] == "Ingenieure systemes"
    assert corps["initials"] == "MT"
    assert corps["joinedSol"] == 3


def test_derniere_seance_absente_renvoie_null(client, db_session):
    a1 = Astronaute(nom="Mei")
    db_session.add(a1)
    db_session.commit()

    reponse = client.get(f"/api/v1/crew/{a1.id}/last-session")
    assert reponse.status_code == 200
    # Le contrat reel est {lastSessionAt: string | null}, pas une chaine nue
    # (voir Frontend/src/api/live.ts, getLastSessionAt).
    assert reponse.json() == {"lastSessionAt": None}


def test_derniere_seance_avec_un_identifiant_non_numerique_renvoie_null(client):
    assert client.get("/api/v1/crew/mei/last-session").json() == {"lastSessionAt": None}


def test_derniere_seance_renvoie_la_plus_recente(client, db_session):
    a1 = Astronaute(nom="Mei")
    db_session.add(a1)
    db_session.flush()
    ancienne = SessionModel(astronaute_id=a1.id, debut=datetime(2026, 1, 1, tzinfo=timezone.utc),
                             mode="measuring")
    recente = SessionModel(astronaute_id=a1.id, debut=datetime(2026, 9, 1, tzinfo=timezone.utc),
                            mode="measuring")
    db_session.add_all([ancienne, recente])
    db_session.commit()

    reponse = client.get(f"/api/v1/crew/{a1.id}/last-session")
    assert reponse.json()["lastSessionAt"] == recente.debut.isoformat()


def test_consentement_par_defaut_est_actif(client):
    reponse = client.get("/api/v1/cabins/cabine-01/consent")
    assert reponse.status_code == 200
    assert reponse.json() == {"camera": True, "microphone": True}


def test_capteurs_renvoie_les_quatre_avec_les_vraies_references_de_composant(client):
    """model/sampleRate doivent porter la reference reelle du composant,
    pas un espace reserve de maquette (voir tache-19-brief.md).
    """
    reponse = client.get("/api/v1/cabins/cabine-01/sensors")
    assert reponse.status_code == 200
    corps = reponse.json()
    par_cle = {c["key"]: c for c in corps}
    assert set(par_cle) == {"hr", "eda", "face", "voice"}
    assert par_cle["hr"]["model"] == "MAX30102"
    assert par_cle["hr"]["sampleRate"] == "100 Hz"
    assert par_cle["eda"]["model"] == "Grove GSR"
    assert par_cle["eda"]["sampleRate"] == "10 Hz"
    assert par_cle["face"]["model"] == "Logitech C270"
    assert par_cle["voice"]["model"] == "Logitech C270"


def test_capteurs_sans_aucune_seance_sont_tous_non_fiables_et_sans_valeur(client):
    corps = client.get("/api/v1/cabins/cabine-01/sensors").json()
    for capteur in corps:
        assert capteur["level"] == "unreliable"
        assert capteur["value"] is None
        assert capteur["window"] == []


def test_capteur_face_signale_le_consentement_coupe(client, db_session):
    a1 = Astronaute(nom="Mei")
    db_session.add(a1)
    db_session.flush()
    session = SessionModel(astronaute_id=a1.id, debut=datetime.now(timezone.utc), mode="measuring")
    db_session.add(session)
    db_session.commit()

    client.post(f"/api/v1/sessions/{session.id}/consent",
                json={"camera": False, "microphone": True})

    corps = client.get("/api/v1/cabins/cabine-01/sensors").json()
    par_cle = {c["key"]: c for c in corps}
    assert par_cle["face"]["note"] == "Coupe par consentement"
    assert par_cle["voice"]["note"] != "Coupe par consentement"


def test_capteur_eda_relit_une_vraie_mesure_stockee(client, db_session):
    a1 = Astronaute(nom="Mei")
    db_session.add(a1)
    db_session.flush()
    session = SessionModel(astronaute_id=a1.id, debut=datetime.now(timezone.utc), mode="measuring")
    db_session.add(session)
    db_session.flush()

    eda = nk.eda_simulate(duration=15, sampling_rate=10, scr_number=2, random_state=1).tolist()
    db_session.add(Mesure(
        session_id=session.id, device_id="cabine-01", capteur="sudation",
        seq=0, ts=datetime.now(timezone.utc), valeurs={"eda_us": eda}, qualite={"eda": 0.9},
    ))
    db_session.commit()

    corps = client.get("/api/v1/cabins/cabine-01/sensors").json()
    par_cle = {c["key"]: c for c in corps}
    assert par_cle["eda"]["value"] is not None
    assert par_cle["eda"]["level"] == "green"
    assert par_cle["eda"]["window"] == eda[-30:]
