FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modele Whisper du dialogue, telecharge ici, au build, et jamais a la requete :
# la cabine doit pouvoir converser hors ligne (voir app/services/dialogue.py).
ENV MODELE_WHISPER=small DOSSIER_WHISPER=/app/modeles/whisper
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='/app/modeles/whisper')"

COPY app/ ./app/

# Fichiers statiques du front (voir app/main.py) : ce dossier est vide par
# defaut dans ce depot. Frontend/ est un depot GitHub separe, sous un compte
# different - il ne peut pas etre inclus dans ce contexte de build (Docker
# interdit de sortir du contexte, et Coolify clone chaque application depuis
# son propre depot, sans acces a l'autre). Deux situations reelles :
#  - Sur Coolify, l'API et le front sont deux applications separees : ce
#    dossier reste vide, l'API demarre seule, et c'est normal (voir
#    app/main.py). Pas de front a embarquer ici.
#  - Sur le Raspberry Pi de la cabine, le serveur sert reellement le front :
#    on y copie a la main, avant de construire cette image, le resultat de
#    `cd Frontend && npm run build` (son dossier dist/) dans ce dossier
#    static/. Voir le rapport de tache pour le detail de cette contrainte.
COPY static/ ./static/
ENV DOSSIER_STATIQUE=/app/static

# Alembic a besoin de sa configuration ET de ses scripts : sans ces deux
# lignes, la commande `alembic` existe dans le conteneur mais ne trouve aucun
# fichier de configuration, et la base n'est jamais migree.
COPY alembic.ini ./
COPY migrations/ ./migrations/

# Utile pour la demonstration : injecter des mesures sans materiel.
COPY simulator/ ./simulator/

# Le point d'entree migre la base avant de lancer le serveur.
COPY docker-entrypoint.sh ./
RUN chmod +x ./docker-entrypoint.sh
CMD ["./docker-entrypoint.sh"]