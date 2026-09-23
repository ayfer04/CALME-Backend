#!/bin/sh
# Point d'entree du conteneur de l'API C.A.L.M.E.
#
# Les migrations tournent AVANT le serveur, a chaque demarrage. Alembic est
# idempotent : sur une base deja a jour, c'est une commande qui ne fait rien.
# Sans cette etape, un deploiement sur une base neuve laisse une base vide et
# chaque appel de l'API echoue avec une erreur qui ne dit pas pourquoi.
#
# La boucle existe parce que Coolify demarre l'API et PostgreSQL en parallele :
# au premier deploiement, la base n'ecoute pas encore quand l'API se lance.
set -e

ESSAIS="${ATTENTE_BASE_ESSAIS:-30}"
n=0
until alembic upgrade head; do
    n=$((n + 1))
    if [ "$n" -ge "$ESSAIS" ]; then
        echo "ECHEC : base injoignable apres $ESSAIS tentatives." >&2
        echo "Verifiez DATABASE_URL (jamais 127.0.0.1 depuis un conteneur) et que" >&2
        echo "PostgreSQL et l'API partagent le meme reseau Docker : la case" >&2
        echo "'Connect To Predefined Network' doit etre active sur les deux." >&2
        exit 1
    fi
    echo "Base pas encore prete (tentative $n/$ESSAIS), nouvel essai dans 2 s..."
    sleep 2
done

echo "Migrations appliquees. Demarrage du serveur."
exec fastapi run app/main.py --host 0.0.0.0 --port 8000
