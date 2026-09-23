from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Astronaute(Base):
    __tablename__ = "astronautes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(80), default="")
    initiales: Mapped[str] = mapped_column(String(4), default="")
    sol_embarquement: Mapped[int] = mapped_column(Integer, default=0)


class Appareil(Base):
    __tablename__ = "appareils"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(String(100), unique=True)
    cle_signature: Mapped[str] = mapped_column(String(200))


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    astronaute_id: Mapped[int] = mapped_column(ForeignKey("astronautes.id"))
    debut: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mode: Mapped[str] = mapped_column(String(20), default="normal")


class Mesure(Base):
    __tablename__ = "mesures"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    device_id: Mapped[str] = mapped_column(String(100))
    capteur: Mapped[str] = mapped_column(String(30))
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valeurs: Mapped[dict] = mapped_column(JSON)
    qualite: Mapped[dict] = mapped_column(JSON)


class Indicateur(Base):
    __tablename__ = "indicateurs"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    astronaute_id: Mapped[int] = mapped_column(ForeignKey("astronautes.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fc_moyenne: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv_rmssd: Mapped[float | None] = mapped_column(Float, nullable=True)
    eda_fond: Mapped[float | None] = mapped_column(Float, nullable=True)
    eda_reponses: Mapped[float | None] = mapped_column(Float, nullable=True)
    frequence_respiratoire: Mapped[float | None] = mapped_column(Float, nullable=True)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    indice_charge: Mapped[float] = mapped_column(Float)
    niveau: Mapped[str] = mapped_column(String(20))
    exercice_declenche: Mapped[bool] = mapped_column(Boolean, default=False)
    consigne_ia: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    confiance: Mapped[float] = mapped_column(Float)

    # Identifiant public de l'evaluation (celui deja diffuse au front et
    # renvoye par POST /sessions/{id}/assess). Sans lui, GET /assessment,
    # POST /recommend et POST /feedback n'ont aucun moyen de retrouver la
    # ligne qui correspond a l'uuid4() que le front a deja en main.
    assessment_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    # L'exercice retenu par la redaction (l'id du catalogue, ex. "cc365"),
    # pas seulement le booleen "un exercice a-t-il ete declenche" : c'est ce
    # que GET /sessions/{id} doit pouvoir exposer comme exerciseId, et ce que
    # la recommandation doit pouvoir rejouer sans recalculer.
    exercice_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Le retour de l'astronaute sur la consigne ('helped' / 'not-really').
    # Nulle tant que POST /recommendations/{id}/feedback n'a pas ete appele.
    feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)


class ConsentementCabine(Base):
    """Consentement camera/micro de la cabine, persiste pour survivre a un
    redemarrage du serveur (systemd redemarre seul apres une coupure).

    Une seule cabine aujourd'hui : une seule ligne suffit. La colonne
    cabine_id existe pour ne pas avoir a remigrer le jour ou une deuxieme
    cabine sera cablee.
    """

    __tablename__ = "consentements_cabine"

    id: Mapped[int] = mapped_column(primary_key=True)
    cabine_id: Mapped[str] = mapped_column(String(50), unique=True)
    camera: Mapped[bool] = mapped_column(Boolean, default=True)
    microphone: Mapped[bool] = mapped_column(Boolean, default=True)
    maj: Mapped[datetime] = mapped_column(DateTime(timezone=True))