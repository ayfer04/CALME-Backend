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

# Phrases prononcees par la cabine : elles gardent leurs accents, que Piper
# lit (sans eux, "guidee" se prononce comme il est ecrit).
CONSIGNES_GENERIQUES: dict[str, str] = {
    "cc365": "Cinq minutes de respiration guidée. Suis le cercle : il se remplit quand tu inspires, il se vide quand tu expires.",
    "carre": "Quatre minutes de respiration au carré, au rythme de la musique : inspire, retiens, expire, attends.",
    "478": "Trois minutes. Inspire sur quatre temps, retiens sur sept, expire sur huit.",
    "ancrage5432": "Cinq minutes. Nomme cinq choses que tu vois, quatre que tu entends, trois que tu touches.",
    "playlist": "Dix minutes de musique, dont le tempo va ralentir peu à peu. Tu n'as rien à faire.",
    "circadien": "Quinze minutes de lumière descendante, calée sur l'heure de bord.",
    "sieste": "Vingt minutes. Ferme les yeux, la cabine te réveillera.",
    "journal": "Huit minutes. Raconte ta journée à voix haute. Personne ne l'écoutera.",
    "soupir": "Deux minutes. Deux inspirations par le nez, puis une longue expiration par la bouche.",
    "visage": "Trois minutes pour détendre ton visage : le front, les yeux, la mâchoire.",
    "jacobson": "Huit minutes. Contracte chaque partie du corps cinq secondes, puis relâche.",
    "scan": "Sept minutes. Laisse ton attention parcourir le corps, des pieds à la tête.",
    "recul": "Cinq minutes. Trois questions pour remettre la journée à sa juste place.",
    "visualisation": "Six minutes. Laisse-toi guider jusqu'au hublot, face à la Terre.",
}

# Mesure incomplete : on le dit avant de proposer, sans alarmer ni conclure.
PREFIXE_MESURE_PARTIELLE = (
    "Ma mesure est incomplète aujourd'hui, alors je te propose quelque chose de doux. "
)

MESSAGE_MAINTENANCE = (
    "Les mesures ne sont pas exploitables pour l'instant. "
    "Aucun exercice n'est proposé. Signale-le en maintenance."
)

SYSTEME = (
    "Tu es l'assistant d'une cabine de recuperation a bord d'un vaisseau. "
    "Tu choisis UN exercice dans la liste fournie et tu rediges une consigne "
    "de deux phrases maximum, calme, en tutoyant, sans emoji, sans "
    "diagnostic medical. Tu ne proposes rien qui ne soit pas dans la liste."
)


def contexte_mesure(evaluation: dict) -> str:
    if evaluation.get("level") == "unreliable":
        # Pas d'indice a citer : il ne repose que sur une partie des capteurs.
        return ("Mesure incomplete : peu de capteurs ont repondu, le niveau de "
                "charge n'est pas fiable. Dis-le simplement en une courte phrase, "
                "sans alarmer, puis propose l'exercice choisi.")
    return f"Indice de charge : {evaluation['index']} sur 100, palier {evaluation['level']}."


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
                    f"{contexte_mesure(evaluation)}{oriente}\nExercices disponibles :\n{liste}"},
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

    message = CONSIGNES_GENERIQUES[defaut["id"]]
    if evaluation.get("level") == "unreliable":
        message = PREFIXE_MESURE_PARTIELLE + message
    return defaut, message, "rules", None
