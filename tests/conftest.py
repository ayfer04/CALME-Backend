"""Fixtures partagees pour les tests des routes HTTP.

Une base SQLite en memoire plutot que la PostgreSQL de developpement : plus
rapide, isolee entre tests, et suffisante puisque rien ici n'exploite de
fonctionnalite specifique a Postgres.
"""

import os

# Avant tout import de l'application : pas de prechargement de Whisper en test.
os.environ.setdefault("PRECHARGER_WHISPER", "0")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.deps import get_db
from app.main import app
from app.models.tables import Base


@pytest.fixture()
def _session_factory():
    # StaticPool : une base ":memory:" ordinaire ne vit que le temps d'une
    # connexion. Le TestClient execute les routes synchrones dans un
    # threadpool (Starlette), donc sans un pool statique partage, chaque
    # requete verrait sa propre base fraiche et vide.
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False, autocommit=False)
    engine.dispose()


@pytest.fixture()
def db_session(_session_factory):
    """Un acces direct a la base du test, pour preparer des donnees
    (astronaute, decision...) sans repasser par le pipeline HTTP complet.
    """
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(_session_factory):
    def get_db_de_test():
        session = _session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = get_db_de_test
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
