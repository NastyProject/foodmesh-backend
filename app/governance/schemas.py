from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.inventory.schemas import ItemOut
from app.invoices.schemas import FacturaOut
from app.preferences.schemas import Preferencias
from app.recommendations.models import TipoRecomendacion
from app.recommendations.schemas import RecetaOut

# --- Consentimiento ---


class ConsentimientoIn(BaseModel):
    acepta_tratamiento: bool
    acepta_analitica_agregada: bool = False
    # La versión de la política que el frontend le mostró al usuario.
    version_politica: str = Field(min_length=1, max_length=20)


class ConsentimientoOut(BaseModel):
    """Si el usuario nunca respondió, acepta_tratamiento es false y el resto es null."""

    model_config = ConfigDict(from_attributes=True)

    acepta_tratamiento: bool
    acepta_analitica_agregada: bool
    version_politica: str | None
    otorgado_en: datetime | None
    actualizado_en: datetime | None
    # La versión que el frontend debe mostrar (y enviar al aceptar).
    version_politica_vigente: str


# --- Borrado de cuenta ---


class ConfirmacionBorrado(BaseModel):
    # Cualquier otro valor (o no enviarlo) responde 422: evita borrados accidentales.
    confirmar: Literal["ELIMINAR"]


# --- Exportación (derecho de acceso) ---


class UsuarioExportado(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    # El identificador de Auth0 también es un dato personal que guardamos: se incluye.
    auth0_sub: str
    email: str | None
    creado_en: datetime


class HogarExportado(BaseModel):
    nombre: str
    creado_en: datetime
    # Solo cuántos: los datos de los demás miembros son de ellos, no de quien exporta.
    otros_miembros: int


class ConsentimientoExportado(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    acepta_tratamiento: bool
    acepta_analitica_agregada: bool
    version_politica: str
    otorgado_en: datetime | None
    actualizado_en: datetime


class RecomendacionExportada(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    creada_en: datetime
    tipo: TipoRecomendacion
    modelo: str
    recetas: list[RecetaOut]
    feedback: dict[str, bool]


class Exportacion(BaseModel):
    exportado_en: datetime
    usuario: UsuarioExportado
    hogar: HogarExportado
    consentimiento: ConsentimientoExportado | None
    preferencias: Preferencias
    inventario: list[ItemOut]
    # Sin las imágenes: se borran al confirmar la factura y no se exponen por la API.
    facturas: list[FacturaOut]
    recomendaciones: list[RecomendacionExportada]
