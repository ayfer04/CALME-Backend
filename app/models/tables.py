from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Astronaute(Base):
    __tablename__ = "astronautes"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(100))


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