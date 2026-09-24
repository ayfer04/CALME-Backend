import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

from app.api.v1 import assess, cabine, health, ingest, recommendations, sessions, stream, tts

logger = logging.getLogger("calme")

app = FastAPI(title="C.A.L.M.E. - API serveur de bord")

# --- CORS --------------------------------------------------------------
#
# Le front n'est jamais servi depuis la meme origine que l'API des qu'on
# sort du Raspberry Pi de la cabine : poste de developpement (Vite sur
# :5173), et desormais Coolify ou l'API et le front sont deux applications
# separees, chacune sur son propre domaine, issues de deux depots GitHub
# distincts. La liste d'origines est donc lue depuis l'environnement plutot
# que codee en dur - elle change selon qu'on tourne en local, sur Coolify ou
# sur le Pi - et jamais un joker "*" : le dossier du projet parle de vie
# privee a chaque page, un joker qui trainerait jusqu'en demonstration
# serait exactement le genre de detail qu'un jury releve.
ORIGINES_PAR_DEFAUT = "http://localhost:5173,http://127.0.0.1:5173"
origines_autorisees = [
    origine.strip()
    for origine in os.environ.get("ORIGINES_AUTORISEES", ORIGINES_PAR_DEFAUT).split(",")
    if origine.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origines_autorisees,
    allow_credentials=True,
    # Seules les methodes et l'en-tete reellement utilises par le front
    # (voir Frontend/src/api/http.ts) : pas de joker ici non plus.
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(ingest.router, prefix="/api/v1", tags=["ingest"])
app.include_router(stream.router, prefix="/api/v1", tags=["stream"])
app.include_router(assess.router, prefix="/api/v1", tags=["assess"])
app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
app.include_router(recommendations.router, prefix="/api/v1", tags=["recommendations"])
app.include_router(cabine.router, prefix="/api/v1", tags=["cabine"])
app.include_router(tts.router, prefix="/api/v1", tags=["tts"])


# --- Fichiers statiques du front -----------------------------------------
#
# "L'interface est une application React servie par le serveur de bord sous
# forme de fichiers statiques" (dossier du projet). Deux situations
# coexistent et doivent toutes les deux fonctionner :
#  - Sur le Raspberry Pi de la cabine, ce serveur sert reellement le front :
#    c'est ce chemin-la qui est monte ci-dessous.
#  - Sur Coolify, l'API et le front sont deux applications separees (deux
#    depots GitHub distincts, sous deux comptes differents) : le dossier
#    statique n'existe alors pas ici, et ce n'est pas une panne, c'est la
#    configuration normale de ce deploiement-la.
# Le chemin est configurable par variable d'environnement pour ces deux cas
# (et le poste de developpement, ou Frontend/ est un depot voisin de
# Backend/) ; par defaut on suppose ce voisinage de developpement.
DEFAUT_DOSSIER_STATIQUE = Path(__file__).resolve().parent.parent.parent / "Frontend" / "dist"
dossier_statique = Path(os.environ.get("DOSSIER_STATIQUE", str(DEFAUT_DOSSIER_STATIQUE)))

if dossier_statique.is_dir():
    # Monte APRES les routeurs /api/v1 : un mount a "/" capte toute requete
    # qui n'a pas deja trouve de route, donc le placer avant masquerait les
    # routes API derriere les fichiers statiques.
    app.mount("/", StaticFiles(directory=dossier_statique, html=True), name="front")
    logger.info("front statique servi depuis %s", dossier_statique)
else:
    # Volontairement une info, pas un avertissement : c'est la situation
    # normale d'un deploiement Coolify "API seule", pas une panne. Un
    # developpeur qui n'a pas encore construit le front (ou le Pi avant sa
    # premiere livraison) doit pouvoir demarrer le serveur quand meme.
    logger.info(
        "aucun dossier statique a %s : l'API demarre seule, sans front integre",
        dossier_statique,
    )


@app.exception_handler(StarletteHTTPException)
async def page_inconnue_retombe_sur_lindex(request: Request, exc: StarletteHTTPException):
    """Le front est une application une seule page : une URL inconnue (par
    exemple /medecin apres un rechargement) doit renvoyer index.html, pas un
    404, sinon la navigation cote client casse au premier F5. Une route
    /api/v1/... inconnue doit en revanche rester un vrai 404 JSON : le
    fallback SPA ne concerne que les routes clientside du front, jamais le
    contrat de l'API.
    """
    index_html = dossier_statique / "index.html"
    if (
        exc.status_code == 404
        and index_html.is_file()
        and not request.url.path.startswith("/api/")
    ):
        return FileResponse(index_html)
    return await http_exception_handler(request, exc)
