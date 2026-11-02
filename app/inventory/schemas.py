from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ItemBase(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    categoria: str | None = Field(default=None, max_length=60)
    cantidad: float = Field(gt=0)
    unidad: str = Field(default="unidad", max_length=20)
    fecha_vencimiento: date | None = None


class ItemCreate(ItemBase):
    """Lo que el cliente envía para crear un ítem."""


class ItemUpdate(BaseModel):
    """Para PATCH: todos los campos son opcionales."""

    nombre: str | None = Field(default=None, min_length=1, max_length=120)
    categoria: str | None = Field(default=None, max_length=60)
    cantidad: float | None = Field(default=None, gt=0)
    unidad: str | None = Field(default=None, max_length=20)
    fecha_vencimiento: date | None = None


class ItemOut(ItemBase):
    """Lo que la API devuelve. Fíjate que NO incluye hogar_id."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    creado_en: datetime