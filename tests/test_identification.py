"""Identification faciale et enrolement de l'equipage.

Les empreintes de test ne sont jamais des vecteurs L2-normalises reels (face-
api.js s'en charge cote navigateur, jamais ici) : ce sont des vecteurs
fabriques ou seule une coordonnee varie, pour que la distance euclidienne
entre deux empreintes soit exactement connue sans calcul de norme.
"""

from app.models.tables import Astronaute
from app.services.visage import SEUIL_RECONNAISSANCE


def vecteur(decalage: float = 0.0) -> list[float]:
    """128 flottants a zero, sauf la premiere coordonnee : la distance
    euclidienne a `vecteur()` est alors exactement `abs(decalage)`.
    """
    v = [0.0] * 128
    v[0] = decalage
    return v


def enroler(client, nom: str, empreinte: list[float]) -> dict:
    reponse = client.post(
        "/api/v1/crew/enroll", json={"displayName": nom, "empreinte": empreinte}
    )
    assert reponse.status_code == 200
    return reponse.json()


def identifier(client, empreinte: list[float]):
    reponse = client.post(
        "/api/v1/cabins/cabine-01/identify", json={"empreinte": empreinte}
    )
    assert reponse.status_code == 200
    return reponse.json()


def test_deux_empreintes_identiques_sont_reconnues(client):
    cree = enroler(client, "Mei Tanaka", vecteur())
    reconnu = identifier(client, vecteur())
    assert reconnu is not None
    assert reconnu["id"] == cree["id"]
    assert reconnu["displayName"] == "Mei Tanaka"


def test_enrolement_puis_identification_renvoie_le_crew_member_complet(client):
    cree = enroler(client, "Mei Tanaka", vecteur())
    reconnu = identifier(client, vecteur())
    # Le contrat CrewMember au caractere pres (Frontend/src/api/types.ts).
    assert set(reconnu.keys()) == {"id", "displayName", "role", "initials", "joinedSol"}
    assert reconnu == cree


def test_une_empreinte_eloignee_renvoie_null_jamais_le_plus_proche_voisin(client):
    """Meme si un seul astronaute est enrole (donc mecaniquement "le plus
    proche"), une distance trop grande doit renvoyer null plutot que ce
    candidat par defaut.
    """
    enroler(client, "Mei Tanaka", vecteur())
    assert identifier(client, vecteur(decalage=10.0)) is None


def test_juste_en_dessous_du_seuil_est_reconnu(client):
    enroler(client, "Mei Tanaka", vecteur())
    assert identifier(client, vecteur(decalage=SEUIL_RECONNAISSANCE - 0.01)) is not None


def test_juste_au_dessus_du_seuil_renvoie_null(client):
    enroler(client, "Mei Tanaka", vecteur())
    assert identifier(client, vecteur(decalage=SEUIL_RECONNAISSANCE + 0.01)) is None


def test_un_vecteur_trop_court_renvoie_422_a_lidentification(client):
    reponse = client.post(
        "/api/v1/cabins/cabine-01/identify", json={"empreinte": [0.1] * 50}
    )
    assert reponse.status_code == 422


def test_un_vecteur_trop_long_renvoie_422_a_lenrolement(client):
    reponse = client.post(
        "/api/v1/crew/enroll",
        json={"displayName": "Mei Tanaka", "empreinte": [0.1] * 200},
    )
    assert reponse.status_code == 422


def test_astronaute_sans_empreinte_nest_jamais_renvoye_et_ne_casse_pas_la_comparaison(
    client, db_session
):
    db_session.add(Astronaute(nom="Jamais enrole"))
    db_session.commit()

    enroler(client, "Mei Tanaka", vecteur())

    # Une identification sur un vecteur proche de l'enrole reconnu doit
    # fonctionner sans que l'astronaute sans empreinte n'y participe.
    reconnu = identifier(client, vecteur(decalage=0.01))
    assert reconnu is not None
    assert reconnu["displayName"] == "Mei Tanaka"

    # Une identification qui ne matche personne ne doit pas planter non plus.
    assert identifier(client, vecteur(decalage=10.0)) is None


def test_liste_equipage_inclut_les_astronautes_sans_empreinte(client, db_session):
    db_session.add(Astronaute(nom="Jamais enrole"))
    db_session.commit()
    enroler(client, "Mei Tanaka", vecteur())

    reponse = client.get("/api/v1/crew")
    assert reponse.status_code == 200
    noms = {membre["displayName"] for membre in reponse.json()}
    assert noms == {"Jamais enrole", "Mei Tanaka"}
