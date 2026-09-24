# 3.12 et non 3.13 : Kokoro (la voix de la cabine) ne s'installe pas encore
# sous 3.13.
FROM python:3.12-slim

WORKDIR /app

# eSpeak : la phonetisation francaise de Kokoro. PyTorch en version CPU, avant
# le reste : sinon pip tirerait la version CUDA (plusieurs Go de plus), inutile
# sur une tour sans carte graphique.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends espeak-ng \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt requirements-voix.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-voix.txt

# Voix de la cabine (voir app/services/synthese.py) : Kokoro-82M et la voix
# ff_siwis, telecharges ici, au build ; ensuite plus aucun acces au reseau.
ENV HF_HOME=/app/modeles/hf
RUN python -c "from kokoro import KPipeline; p = KPipeline(lang_code='f', repo_id='hexgrad/Kokoro-82M'); list(p('Bonjour.', voice='ff_siwis'))"
ENV MOTEUR_VOIX=kokoro VOIX_KOKORO=ff_siwis

# Modele Whisper du dialogue, telecharge ici, au build, et jamais a la requete :
# la cabine doit pouvoir converser hors ligne (voir app/services/dialogue.py).
# Voix de la cabine (voir app/services/synthese.py) : modele fr_FR-upmc-medium,
# locuteur "pierre", telecharge au build comme Whisper.
ENV DOSSIER_VOIX=/app/modeles/piper VOIX_PIPER=fr_FR-upmc-medium LOCUTEUR_PIPER=pierre
ADD https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx /app/modeles/piper/
ADD https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/upmc/medium/fr_FR-upmc-medium.onnx.json /app/modeles/piper/

ENV MODELE_WHISPER=small DOSSIER_WHISPER=/app/modeles/whisper
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8', download_root='/app/modeles/whisper')"

# Tous les modeles sont telecharges (Kokoro, Piper, Whisper) : a partir d'ici,
# plus aucun acces au reseau, ni au build ni a l'execution. Cette ligne doit
# rester APRES le dernier telechargement - placee plus haut, elle empechait
# Whisper de telecharger son modele.
ENV HF_HUB_OFFLINE=1

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