from typing import Literal

from pydantic import BaseModel, Field

# --- Lo que se le pide a Gemini (esquema de structured output) ---


class IngredienteIA(BaseModel):
    nombre: str
    cantidad: float | None
    unidad: str | None
    # Id corto del inventario ("p1", "p2"...) o null si hay que comprarlo.
    item_id: str | None


class RecetaIA(BaseModel):
    titulo: str
    descripcion: str
    tiempo_minutos: int
    porciones: int
    ingredientes: list[IngredienteIA]
    pasos: list[str]
    por_que: str  # cómo aprovecha los productos próximos a vencer


class RespuestaRecetasIA(BaseModel):
    recetas: list[RecetaIA]


# --- Lo que devuelve la API ---


class IngredienteOut(BaseModel):
    nombre: str
    cantidad: float | None
    unidad: str | None
    # Id real del ítem en el inventario del hogar; null si hay que comprarlo.
    item_id: int | None


class ItemProximoAVencer(BaseModel):
    item_id: int
    nombre: str
    dias_para_vencer: int


class RecetaOut(BaseModel):
    titulo: str
    descripcion: str
    tiempo_minutos: int
    porciones: int
    ingredientes: list[IngredienteOut]
    pasos: list[str]
    por_que: str
    # Calculados por el backend, no por la IA:
    usa_proximos_a_vencer: list[ItemProximoAVencer]
    ingredientes_faltantes: list[str]


class PedidoRecetas(BaseModel):
    # True para "otras recetas": no usa la caché y evita repetir las últimas recetas.
    nuevas: bool = False


class RespuestaRecomendacion(BaseModel):
    recomendacion_id: int
    recetas: list[RecetaOut]
    aviso: str
    # Solo cuando no quedó ninguna receta: explicación para mostrarle al usuario.
    mensaje: str | None
    cache: Literal["hit", "miss"]
    latencia_ms: int
    modelo: str


class FeedbackIn(BaseModel):
    receta_indice: int = Field(ge=0)
    util: bool
