"""Les interventions de la cabine. Toutes non medicamenteuses, toutes
realisables avec le son, la lumiere et la voix de la cabine.

Chaque exercice declare les signaux qu'il vise (`signals`) : c'est ce qui
permet de proposer d'abord ce qui repond a ce que la mesure a vraiment vu -
un coeur qui s'emballe n'appelle pas la meme chose qu'un visage crispe ou
qu'une voix eteinte. Le modele de langage choisit toujours DANS cette liste
ordonnee (voir app/services/consigne.py) ; sans lui, c'est le premier qui
l'emporte.

Les signaux possibles sont ceux de l'indice de charge (app/services/indice.py)
plus deux etats deduits : "fatigue" (activation basse, voix eteinte) et
"diffus" (aucun signal ne se detache).
"""

RANG = {"green": 0, "amber": 1, "red": 2}

# Musique libre de droits embarquee dans le front (Frontend/public/audio) :
# "Box Breathing & Binaural Beats", Breathwork Beats by Touek, licence
# Creative Commons BY - l'attribution est affichee pendant l'exercice.
PISTE_CARRE = "/audio/respiration-carree-80bpm.ogg"
# "Winter Aurora" (SleepTube) : pas libre de droits, donc jamais copiee - lue
# par le lecteur integre de YouTube, que l'auteur autorise (voir
# Frontend/src/features/cabin/audio/lecteur.ts, avec la piste libre en secours).
PISTE_RELAXATION = "youtube:RzYIQMYjao4"

CATALOGUE: list[dict] = [
    {"id": "cc365", "name": "Cohérence cardiaque 365", "duration": 5,
     "indication": "Activation forte, variabilité cardiaque basse",
     "minLevel": "green", "kind": "breathing", "music": None,
     "signals": ["fc_moyenne", "hrv_rmssd", "diffus"]},
    {"id": "soupir", "name": "Soupir physiologique", "duration": 2,
     "indication": "Pic de stress aigu : cœur rapide et sudation en pics",
     "minLevel": "green", "kind": "breathing", "music": None,
     "signals": ["fc_moyenne", "eda_reponses"]},
    {"id": "carre", "name": "Respiration au carré", "duration": 4,
     "indication": "Anxiété avant une tâche, sudation de fond élevée",
     "minLevel": "green", "kind": "breathing", "music": PISTE_CARRE,
     "signals": ["eda_fond", "hrv_rmssd", "voix"]},
    {"id": "478", "name": "Respiration 4-7-8", "duration": 3,
     "indication": "Agitation en fin de journée, difficulté d'endormissement",
     "minLevel": "green", "kind": "breathing", "music": None,
     "signals": ["fc_moyenne", "visage"]},
    {"id": "visage", "name": "Relâchement du visage", "duration": 3,
     "indication": "Visage crispé : sourcils froncés, mâchoire serrée",
     "minLevel": "green", "kind": "relaxation", "music": PISTE_RELAXATION,
     "signals": ["visage"]},
    {"id": "jacobson", "name": "Relaxation musculaire progressive", "duration": 8,
     "indication": "Corps tendu, sudation de fond et visage crispés",
     "minLevel": "amber", "kind": "relaxation", "music": PISTE_RELAXATION,
     "signals": ["eda_fond", "visage"]},
    {"id": "scan", "name": "Scan corporel", "duration": 7,
     "indication": "Charge modérée, sans signal dominant",
     "minLevel": "green", "kind": "relaxation", "music": PISTE_RELAXATION,
     "signals": ["diffus"]},
    {"id": "ancrage5432", "name": "Ancrage sensoriel 5-4-3-2-1", "duration": 5,
     "indication": "Rumination, pensées qui tournent en boucle",
     "minLevel": "amber", "kind": "grounding", "music": None,
     "signals": ["eda_reponses", "voix"]},
    {"id": "recul", "name": "Prendre du recul", "duration": 5,
     "indication": "Voix tendue après une journée difficile",
     "minLevel": "green", "kind": "reflection", "music": None,
     "signals": ["voix", "eda_reponses"]},
    {"id": "visualisation", "name": "La Terre vue du hublot", "duration": 6,
     "indication": "Lassitude, voix éteinte, besoin d'évasion",
     "minLevel": "green", "kind": "relaxation", "music": PISTE_RELAXATION,
     "signals": ["fatigue", "diffus"]},
    {"id": "playlist", "name": "Playlist à tempo décroissant", "duration": 10,
     "indication": "Charge modérée, descente progressive",
     "minLevel": "green", "kind": "audio", "music": PISTE_RELAXATION,
     "signals": ["diffus"]},
    {"id": "circadien", "name": "Séquence lumineuse circadienne", "duration": 15,
     "indication": "Désynchronisation, baisse de vigilance",
     "minLevel": "green", "kind": "light", "music": PISTE_RELAXATION,
     "signals": ["fatigue"]},
    {"id": "sieste", "name": "Micro-sieste guidée", "duration": 20,
     "indication": "Fatigue accumulée",
     "minLevel": "amber", "kind": "nap", "music": PISTE_RELAXATION,
     "signals": ["fatigue"]},
    {"id": "journal", "name": "Journal vocal différé", "duration": 8,
     "indication": "Repli, isolement social",
     "minLevel": "green", "kind": "journal", "music": None,
     "signals": ["voix", "fatigue"]},
]

# Ce que chaque signal veut dire, pour le prompt du modele et pour l'ecran.
LIBELLES_SIGNAUX = {
    "fc_moyenne": "fréquence cardiaque élevée",
    "hrv_rmssd": "variabilité cardiaque basse",
    "eda_reponses": "pics de sudation",
    "eda_fond": "sudation de fond élevée",
    "visage": "visage crispé",
    "voix": "voix tendue",
    "fatigue": "fatigue, activation basse",
    "diffus": "charge diffuse, aucun signal ne domine",
}

# En dessous de cet ecart (en sigmas, dans le sens du stress), aucun signal ne
# se detache vraiment : on parle de charge diffuse.
SEUIL_DOMINANT = 0.5
# Voix ou coeur nettement sous l'habitude de la personne, sans autre signal de
# stress : c'est de la fatigue, pas de la detente.
SEUIL_FATIGUE = -1.0


def signal_dominant(zs: dict[str, float], inverses: set[str]) -> str:
    """Le signal qui s'ecarte le plus de l'habitude, dans le sens du stress.

    `zs` sont les ecarts bornes de app/services/indice.py ; `inverses` les
    signaux pour lesquels une baisse signe le stress (la variabilite
    cardiaque). Deterministe, comme l'indice : meme mesure, meme choix.
    """
    contributions = {cle: (-z if cle in inverses else z)
                     for cle, z in zs.items() if z is not None}
    if not contributions:
        return "diffus"
    cle, valeur = max(contributions.items(), key=lambda kv: kv[1])
    if valeur >= SEUIL_DOMINANT:
        return cle
    bas = [zs.get(k) for k in ("voix", "fc_moyenne") if zs.get(k) is not None]
    if bas and min(bas) <= SEUIL_FATIGUE:
        return "fatigue"
    return "diffus"


def exercices_autorises(niveau: str, dominant: str | None = None) -> list[dict]:
    """Les exercices permis par le palier, les plus pertinents d'abord.

    En rouge, c'est toujours de la respiration. Une mesure incomplete (peu de
    capteurs, confiance basse) ne tranche pas sur le niveau, mais ne laisse
    pas la personne repartir les mains vides : elle recoit les exercices les
    plus doux, ceux du palier vert, que l'on peut faire sans risque quelle que
    soit la charge reelle. L'ecran dit que la mesure est partielle.
    """
    if niveau == "unreliable":
        niveau = "green"
    if niveau == "red":
        permis = [e for e in CATALOGUE if e["kind"] == "breathing"]
    else:
        plafond = RANG[niveau]
        permis = [e for e in CATALOGUE if RANG[e["minLevel"]] <= plafond]
    if dominant:
        # Un exercice dont c'est la cible principale (premier signal liste)
        # passe devant celui dont c'est une cible secondaire, puis tous les
        # autres. Tri stable : a pertinence egale, l'ordre du catalogue reste.
        def rang(e: dict) -> int:
            return e["signals"].index(dominant) if dominant in e["signals"] else len(e["signals"]) + 9
        permis = sorted(permis, key=rang)
    return permis
