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

MODELE = os.environ.get("MODELE_OLLAMA", "llama3.2:3b")
HOTE_OLLAMA = os.environ.get("HOTE_OLLAMA", "http://localhost:11434")
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


def interroger_modele(evaluation: dict, autorises: list[dict], historique: list[dict]) -> dict | None:
    """Renvoie None en cas d'indisponibilite : l'appelant gere le repli."""
    try:
        import ollama

        client = ollama.Client(host=HOTE_OLLAMA, timeout=DELAI_MAX_S)
        liste = "\n".join(f"- {e['id']} : {e['name']} ({e['duration']} min, {e['indication']})"
                          for e in autorises)
        schema = {
            "type": "object",
            "properties": {
                "exercice_id": {"type": "string", "enum": [e["id"] for e in autorises]},
                "message": {"type": "string"},
            },
            "required": ["exercice_id", "message"],
        }
        reponse = client.chat(
            model=MODELE,
            messages=[
                {"role": "system", "content": SYSTEME},
                {"role": "user", "content":
                    f"Indice de charge : {evaluation['index']} sur 100, palier "
                    f"{evaluation['level']}.\nExercices disponibles :\n{liste}"},
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
    propose = interroger_modele(evaluation, autorises, historique)

    if propose:
        choisi = next((e for e in autorises if e["id"] == propose.get("exercice_id")), None)
        message = (propose.get("message") or "").strip()
        if choisi and message:
            return choisi, message, "model", MODELE

    return defaut, CONSIGNES_GENERIQUES[defaut["id"]], "rules", None
