"""Le modele redige, il ne decide pas.

Il choisit un exercice DANS la liste qu'on lui donne et ecrit la consigne. Il
n'a acces a aucun autre levier. Sa reponse est contrainte en JSON au decodage
et verifiee avant affichage : si l'exercice n'est pas dans la liste, ou si le
format ne tient pas, le serveur prend un choix par defaut.

Consequence : si le modele est indisponible, trop lent, ou coupe pour
economiser l'energie, le systeme continue. Il perd sa capacite a personnaliser,
pas sa fonction.
"""

import os

import httpx

from app.services.exercices import LIBELLES_SIGNAUX

MODELE = os.environ.get("MODELE_OLLAMA", "llama3.2:3b")
# Palier intermediaire de la chaine de repli : un modele plus petit, tente
# une seule fois si le modele nominal echoue ou repond hors-liste, avant de
# retomber sur les regles. C'est lui qui explique le nom de modele affiche
# quand le nominal est indisponible mais qu'une consigne personnalisee
# reste possible.
MODELE_DEGRADE = os.environ.get("MODELE_OLLAMA_DEGRADE", "llama3.2:1b")
HOTE_OLLAMA = os.environ.get("HOTE_OLLAMA", "http://localhost:11434")

# Delai de connexion : tres court, expres. Detecter qu'Ollama ne repond pas
# ne doit pas couter le meme prix qu'une vraie generation. Sur un budget total
# de 30 s entre la fin de la mesure et l'affichage de la consigne, un hote
# injoignable (service gele, paquets perdus, pas de refus explicite) ne doit
# pas immobiliser tout le systeme le temps d'un DELAI_MAX_S complet, et ce
# pour chacune des deux tentatives (nominal puis degrade).
DELAI_CONNEXION_S = 2.0
# Delai de lecture : le temps qu'on tolere pour une vraie generation, une
# fois la connexion etablie.
DELAI_MAX_S = 12.0

CONSIGNES_GENERIQUES: dict[str, str] = {
    "cc365": "Cinq minutes de respiration guidee. Suivez le cercle : il se dilate a l'inspiration, il se contracte a l'expiration.",
    "carre": "Quatre minutes. Inspirez sur quatre temps, retenez quatre, expirez quatre, attendez quatre.",
    "478": "Trois minutes. Inspirez sur quatre temps, retenez sept, expirez sur huit.",
    "ancrage5432": "Cinq minutes. Nommez cinq choses que vous voyez, quatre que vous entendez, trois que vous touchez.",
    "playlist": "Dix minutes de son, dont le tempo descendra progressivement. Vous n'avez rien a faire.",
    "circadien": "Quinze minutes de lumiere descendante, calee sur l'heure de bord.",
    "sieste": "Vingt minutes. Fermez les yeux, la cabine vous reveillera.",
    "journal": "Huit minutes. Racontez votre journee a voix haute. Personne ne l'ecoutera.",
    "soupir": "Deux minutes. Deux inspirations par le nez, puis une longue expiration par la bouche.",
    "visage": "Trois minutes. Contractez puis relachez le front, les yeux et la machoire.",
    "jacobson": "Huit minutes. Contractez chaque partie du corps cinq secondes, puis relachez.",
    "scan": "Sept minutes. Laissez votre attention parcourir le corps, des pieds a la tete.",
    "recul": "Cinq minutes. Trois questions pour remettre la journee a sa juste place.",
    "visualisation": "Six minutes. Laissez-vous guider jusqu'au hublot, face a la Terre.",
}

MESSAGE_MAINTENANCE = (
    "Les mesures ne sont pas exploitables pour l'instant. "
    "Aucun exercice n'est propose. Signalez-le en maintenance."
)

SYSTEME = (
    "Tu es l'assistant d'une cabine de recuperation a bord d'un vaisseau. "
    "Tu choisis UN exercice dans la liste fournie et tu rediges une consigne "
    "de deux phrases maximum, calme, tutoiement exclu, sans emoji, sans "
    "diagnostic medical. Tu ne proposes rien qui ne soit pas dans la liste."
)


def interroger_modele(evaluation: dict, autorises: list[dict], historique: list[dict],
                       modele: str = MODELE) -> dict | None:
    """Renvoie None en cas d'indisponibilite : l'appelant gere le repli."""
    try:
        import ollama

        delai = httpx.Timeout(DELAI_MAX_S, connect=DELAI_CONNEXION_S)
        client = ollama.Client(host=HOTE_OLLAMA, timeout=delai)
        liste = "\n".join(f"- {e['id']} : {e['name']} ({e['duration']} min, {e['indication']})"
                          for e in autorises)
        dominant = evaluation.get("dominantSignal")
        # La liste arrive deja triee (les plus adaptes au signal dominant
        # d'abord) : le modele sait pourquoi, et peut s'y tenir.
        oriente = (f"\nCe que la mesure a vu d'abord : {LIBELLES_SIGNAUX[dominant]}. "
                   f"Les premiers exercices de la liste y repondent le mieux."
                   if dominant in LIBELLES_SIGNAUX else "")
        schema = {
            "type": "object",
            "properties": {
                "exercice_id": {"type": "string", "enum": [e["id"] for e in autorises]},
                "message": {"type": "string"},
            },
            "required": ["exercice_id", "message"],
        }
        reponse = client.chat(
            model=modele,
            messages=[
                {"role": "system", "content": SYSTEME},
                {"role": "user", "content":
                    f"Indice de charge : {evaluation['index']} sur 100, palier "
                    f"{evaluation['level']}.{oriente}\nExercices disponibles :\n{liste}"},
            ],
            format=schema,   # contrainte appliquee au decodage, pas verifiee apres coup
        )
        import json
        return json.loads(reponse["message"]["content"])
    except Exception:
        return None


def rediger(evaluation: dict, autorises: list[dict],
            historique: list[dict]) -> tuple[dict | None, str, str, str | None]:
    if not autorises:
        return None, MESSAGE_MAINTENANCE, "rules", None

    defaut = autorises[0]

    # Une seule tentative de repli vers le modele degrade, pas une boucle :
    # le budget est de 30 secondes au total, pas l'eternite. Deux etages
    # suffisent a montrer la degradation progressive (nominal, puis plus
    # petit, puis regles) sans faire attendre l'utilisateur indefiniment.
    for candidat in (MODELE, MODELE_DEGRADE):
        propose = interroger_modele(evaluation, autorises, historique, modele=candidat)
        if propose:
            choisi = next((e for e in autorises if e["id"] == propose.get("exercice_id")), None)
            message = (propose.get("message") or "").strip()
            if choisi and message:
                return choisi, message, "model", candidat

    return defaut, CONSIGNES_GENERIQUES[defaut["id"]], "rules", None
