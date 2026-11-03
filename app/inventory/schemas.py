from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.catalog.categorias import Categoria


class ItemBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    # Lista cerrada (app/catalog/categorias.py): cualquier otro valor responde 422.
    categoria: Categoria | None = None
    cantidad: float = Field(gt=0)
    unidad: str = Field(default="unidad", max_length=20)
    fecha_vencimiento: date | None = None


class ItemCreate(ItemBase):
    """Lo que el cliente envía para crear un ítem."""


class ItemUpdate(BaseModel):
    """Para PATCH: todos los campos son opcionales."""

    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    categoria: Categoria | None = None
    cantidad: float | None = Field(default=None, gt=0)
    unidad: str | None = Field(default=None, max_length=20)
    fecha_vencimiento: date | None = None


class ItemOut(ItemBase):
    """Lo que la API devuelve. Fíjate que NO incluye hogar_id."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    # Lo calcula el backend a partir de la categoría; el cliente no lo envía.
    es_alimento: bool
    creado_en: datetime
