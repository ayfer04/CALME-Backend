"""Comportement du fallback SPA de app/main.py (page_inconnue_retombe_sur_lindex).

Le montage statique lui-meme (app.mount) ne peut pas se tester ici de facon
fiable : il est fige a l'import du module, sur le vrai Frontend/dist ou qu'il
se trouve sur cette machine au moment du premier import - present ou non
selon qu'on a lance `npm run build` avant les tests. Ces tests forcent donc
`app.main.dossier_statique` vers un dossier sans index.html, pour verifier le
comportement du handler d'exception independamment de cet etat de fait. La
demonstration du montage reel se fait a la main (voir le rapport de tache
pour les curl apres un vrai `npm run build`).
"""

from app import main


def test_une_route_api_inconnue_reste_un_404_json(client):
    reponse = client.get("/api/v1/route-qui-nexiste-pas")
    assert reponse.status_code == 404
    assert reponse.headers["content-type"].startswith("application/json")


def test_une_route_hors_api_sans_front_integre_reste_un_404_json(client, monkeypatch, tmp_path):
    """Sans index.html a servir (dossier statique absent ou vide - le cas
    normal d'un deploiement Coolify 'API seule'), il n'y a rien vers quoi
    retomber : le 404 JSON par defaut de FastAPI doit rester intact, pas un
    plantage du handler d'exception.
    """
    monkeypatch.setattr(main, "dossier_statique", tmp_path)
    reponse = client.get("/une-route-quelconque")
    assert reponse.status_code == 404
    assert reponse.headers["content-type"].startswith("application/json")


def test_une_route_hors_api_avec_front_integre_retombe_sur_lindex(client, monkeypatch, tmp_path):
    """Avec un index.html present (front integre), une route inconnue du
    cote client (ex. /medecin apres un rechargement) doit renvoyer cette
    page plutot qu'un 404 : c'est le fallback SPA.
    """
    (tmp_path / "index.html").write_text("<html>front</html>")
    monkeypatch.setattr(main, "dossier_statique", tmp_path)
    reponse = client.get("/une-route-quelconque")
    assert reponse.status_code == 200
    assert reponse.headers["content-type"].startswith("text/html")
    assert "front" in reponse.text
