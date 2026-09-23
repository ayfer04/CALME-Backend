"""Les huit interventions de la cabine. Toutes non medicamenteuses, toutes
realisables avec le son et la lumiere d'une piece.

Les trois premieres sont celles qui font le plus baisser la frequence
respiratoire : c'est sur elles que repose l'argument energetique du dossier.
"""

RANG = {"green": 0, "amber": 1, "red": 2}

CATALOGUE: list[dict] = [
    {"id": "cc365", "name": "Coherence cardiaque 365", "duration": 5,
     "indication": "Activation forte, variabilite cardiaque basse",
     "minLevel": "green", "kind": "breathing"},
    {"id": "carre", "name": "Carre de respiration", "duration": 4,
     "indication": "Anxiete ponctuelle, avant une tache delicate",
     "minLevel": "green", "kind": "breathing"},
    {"id": "478", "name": "Respiration 4-7-8", "duration": 3,
     "indication": "Difficulte d'endormissement",
     "minLevel": "green", "kind": "breathing"},
    {"id": "ancrage5432", "name": "Ancrage sensoriel 5-4-3-2-1", "duration": 5,
     "indication": "Rumination, perte de reperes",
     "minLevel": "amber", "kind": "grounding"},
    {"id": "playlist", "name": "Playlist a tempo decroissant", "duration": 10,
     "indication": "Charge moderee, descente progressive",
     "minLevel": "green", "kind": "audio"},
    {"id": "circadien", "name": "Sequence lumineuse circadienne", "duration": 15,
     "indication": "Desynchronisation, baisse de vigilance",
     "minLevel": "green", "kind": "light"},
    {"id": "sieste", "name": "Micro-sieste guidee", "duration": 20,
     "indication": "Fatigue accumulee",
     "minLevel": "amber", "kind": "nap"},
    {"id": "journal", "name": "Journal vocal differe", "duration": 8,
     "indication": "Repli, isolement social",
     "minLevel": "green", "kind": "journal"},
]


def exercices_autorises(niveau: str) -> list[dict]:
    """En rouge, c'est systematiquement une coherence cardiaque prolongee.

    Une mesure aberrante ne declenche aucun exercice : proposer une respiration
    sur un faux contact, c'est apprendre aux gens a ignorer la machine.
    """
    if niveau == "unreliable":
        return []
    if niveau == "red":
        return [e for e in CATALOGUE if e["kind"] == "breathing"]
    plafond = RANG[niveau]
    return [e for e in CATALOGUE if RANG[e["minLevel"]] <= plafond]
