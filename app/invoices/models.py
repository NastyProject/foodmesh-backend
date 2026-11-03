import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EstadoFactura(enum.StrEnum):
    pendiente_validacion = "pendiente_validacion"
    confirmada = "confirmada"
    error = "error"


class Factura(Base):
    __tablename__ = "facturas"

    id: Mapped[int] = mapped_column(primary_key=True)
    hogar_id: Mapped[int] = mapped_column(ForeignKey("hogares.id"), index=True)
    # Dónde está la imagen en el storage. None cuando ya se borró (al confirmar).
    imagen_key: Mapped[str | None] = mapped_column(String(255))
    estado: Mapped[EstadoFactura] = mapped_column(
        Enum(EstadoFactura, name="estado_factura"),
        default=EstadoFactura.pendiente_validacion,
    )
    # Texto que extrajo Tesseract, ya sin datos personales.
    texto_ocr: Mapped[str | None] = mapped_column(Text)
    # Ítems que propuso Gemini, para que el usuario los revise antes de confirmar.
    items_detectados: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # Detectados en el encabezado con reglas locales (None si no se encontraron).
    supermercado: Mapped[str | None] = mapped_column(String(60))
    fecha_compra: Mapped[date | None] = mapped_column(Date)
    # True si a Gemini se le envió solo el bloque de productos; False si el texto
    # completo. Para evaluar el recorte; no se expone en la API.
    recortada: Mapped[bool] = mapped_column(default=False, server_default=false())
    # Verificación de la factura completa: el TOTAL impreso (reglas locales) contra
    # la suma de precio_total de los ítems detectados. None si no se pudo obtener.
    total_impreso: Mapped[float | None]
    total_calculado: Mapped[float | None]
    # True si los dos totales difieren más del 1 %: algún ítem se leyó mal o faltó.
    requiere_revision: Mapped[bool] = mapped_column(default=False, server_default=false())
    # Mensaje para el usuario si falló el OCR o la normalización.
    error: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
