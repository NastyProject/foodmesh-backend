import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class TipoRecomendacion(enum.StrEnum):
    normal = "normal"  # se puede responder desde la caché
    nuevas = "nuevas"  # "otras recetas": siempre llama a Gemini
    precalculo = "precalculo"  # en segundo plano, al cambiar inventario o preferencias


class Recomendacion(Base):
    """Registro de cada llamada a POST /recomendaciones/recetas.

    Se guarda siempre (también con caché): son los datos para medir latencia con y
    sin caché, cuántas recetas usan productos próximos a vencer y si le sirvieron
    al usuario.
    """

    __tablename__ = "recomendaciones"

    id: Mapped[int] = mapped_column(primary_key=True)
    hogar_id: Mapped[int] = mapped_column(ForeignKey("hogares.id"), index=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    tipo: Mapped[TipoRecomendacion] = mapped_column(
        Enum(TipoRecomendacion, name="tipo_recomendacion"),
        default=TipoRecomendacion.normal,
    )
    cache_hit: Mapped[bool]
    # Rondas de validación: 0 si se respondió desde la caché, 1, o 2 si ninguna receta
    # pasó la primera. Los reintentos por error de red/timeout no cuentan aquí: van al log.
    intentos: Mapped[int]
    # Recetas descartadas por la validación (alergias, dieta, tiempo, repetidas),
    # sumando los intentos.
    recetas_descartadas: Mapped[int]
    # Tiempo total de la petición (incluye BD, validación y llamadas a Gemini).
    latencia_ms: Mapped[int]
    # Solo el tiempo esperando a Gemini, sumando los intentos (cada llamada por
    # separado queda en el log). None si se respondió desde la caché.
    latencia_gemini_ms: Mapped[int | None]
    # El modelo que generó las recetas (puede ser el de respaldo), no el configurado.
    # En un hit de caché, el que las generó en su momento.
    modelo: Mapped[str] = mapped_column(String(60))
    # Las recetas ya validadas, tal como se devolvieron (lista de RecetaOut).
    recetas: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # Opinión del usuario por receta: {"0": true, "2": false}. JSONB y no una tabla
    # aparte porque es poca información y siempre se lee junto con la recomendación.
    feedback: Mapped[dict[str, bool]] = mapped_column(JSONB, default=dict, server_default="{}")
