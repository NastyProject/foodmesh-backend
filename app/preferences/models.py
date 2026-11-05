import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Dieta(enum.StrEnum):
    omnivora = "omnivora"
    vegetariana = "vegetariana"
    vegana = "vegana"
    pescetariana = "pescetariana"


class PreferenciasHogar(Base):
    """Preferencias de cocina del hogar (una fila por hogar, como máximo)."""

    __tablename__ = "preferencias_hogar"

    # hogar_id es la llave primaria: así la relación 1 a 1 la garantiza la BD.
    hogar_id: Mapped[int] = mapped_column(ForeignKey("hogares.id"), primary_key=True)
    dieta: Mapped[Dieta] = mapped_column(Enum(Dieta, name="dieta"), default=Dieta.omnivora)
    # Arreglos de Postgres: la validación de valores (lista cerrada, máximos) la hace el schema.
    alergias: Mapped[list[str]] = mapped_column(ARRAY(String(20)), default=list)
    no_le_gusta: Mapped[list[str]] = mapped_column(ARRAY(String(60)), default=list)
    porciones: Mapped[int] = mapped_column(default=2)
    tiempo_max_minutos: Mapped[int | None]
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
