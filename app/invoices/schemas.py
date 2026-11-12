from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.inventory.schemas import ItemCreate
from app.invoices.models import EstadoFactura, MetodoFactura
from app.ocr.normalizacion import ItemPropuesto


class FacturaOut(BaseModel):
    """Lo que la API devuelve. No incluye hogar_id, imagen_key ni recortada (son internos)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    estado: EstadoFactura
    supermercado: str | None
    fecha_compra: date | None
    total_impreso: float | None
    total_calculado: float | None
    requiere_revision: bool
    # Solo el bloque de productos leído por el OCR (sin encabezado ni pie), o null.
    texto_ocr: str | None
    # "texto" (OCR) o "vision" (se reprocesó con la foto, con permiso del usuario).
    metodo: MetodoFactura
    items_detectados: list[ItemPropuesto]
    # Productos que la IA propuso pero que no están en el texto leído: se descartaron.
    items_descartados: int
    error: str | None
    creado_en: datetime


class ReprocesoConImagen(BaseModel):
    # Autorización explícita: la foto completa (con todos sus datos) se envía a Google.
    # Cualquier otro valor, o no enviarlo, responde 422.
    acepto_enviar_imagen: Literal[True]


class ItemFactura(ItemCreate):
    """Un ítem revisado por el usuario al confirmar una factura.

    Igual que ItemCreate (incluida la lista cerrada de categorías), más el código de
    barras (si lo tenía el ítem detectado), que se usa para actualizar el catálogo.
    """

    codigo: str | None = Field(default=None, pattern=r"^\d{4,14}$")
