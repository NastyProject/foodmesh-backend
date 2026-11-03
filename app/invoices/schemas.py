from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.inventory.schemas import ItemCreate
from app.invoices.models import EstadoFactura
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
    texto_ocr: str | None
    items_detectados: list[ItemPropuesto]
    error: str | None
    creado_en: datetime


class ItemFactura(ItemCreate):
    """Un ítem revisado por el usuario al confirmar una factura.

    Igual que ItemCreate (incluida la lista cerrada de categorías), más el código de
    barras (si lo tenía el ítem detectado), que se usa para actualizar el catálogo.
    """

    codigo: str | None = Field(default=None, pattern=r"^\d{4,14}$")
