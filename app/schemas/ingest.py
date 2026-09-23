from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class Qualite(BaseModel):
    cardiaque: float = Field(ge=0, le=1)
    eda: float = Field(ge=0, le=1)


class IngestMessage(BaseModel):
    v: int = 1
    device_id: str
    ts: datetime
    seq: int = Field(ge=0)
    ibi_ms: list[int] = Field(default_factory=list)
    eda_us: list[float] = Field(default_factory=list)
    ppg_raw: list[int] = Field(default_factory=list)
    ma: float | None = None
    qualite: Qualite
    sig: str | None = None

    @field_validator("ibi_ms")
    @classmethod
    def intervalles_plausibles(cls, valeurs: list[int]) -> list[int]:
        for ibi in valeurs:
            if not 273 <= ibi <= 2000:
                raise ValueError("intervalle hors bornes (30 à 220 bpm)")
        return valeurs