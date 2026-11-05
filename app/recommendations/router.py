from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.dependencies import HogarId
from app.core.cache import Cache
from app.core.db import DbSession
from app.recommendations import service
from app.recommendations.generacion import (
    Generador,
    generar_con_gemini,
    generar_con_gemini_en_fondo,
)
from app.recommendations.schemas import FeedbackIn, PedidoRecetas, RespuestaRecomendacion

router = APIRouter(prefix="/recomendaciones", tags=["recomendaciones"])


def get_generador() -> Generador:
    """Dependencia para poder reemplazar Gemini por un falso en los tests."""
    return generar_con_gemini


def get_generador_fondo() -> Generador:
    """El del precálculo, aparte para que use el timeout de fondo."""
    return generar_con_gemini_en_fondo


GeneradorDep = Annotated[Generador, Depends(get_generador)]
GeneradorFondoDep = Annotated[Generador, Depends(get_generador_fondo)]


# `def` y no `async def`: la llamada a Gemini bloquea varios segundos y FastAPI
# corre las funciones `def` en un hilo aparte.
@router.post("/recetas", response_model=RespuestaRecomendacion, status_code=status.HTTP_201_CREATED)
def recomendar(
    db: DbSession,
    hogar_id: HogarId,
    cache: Cache,
    generar: GeneradorDep,
    pedido: PedidoRecetas | None = None,
):
    """El body es opcional: sin body (o con {"nuevas": false}) usa la caché;
    con {"nuevas": true} pide recetas distintas a las últimas."""
    nuevas = pedido.nuevas if pedido else False
    try:
        return service.recomendar_recetas(db, hogar_id, cache, generar, nuevas=nuevas)
    except service.SinAlimentos:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No hay alimentos vigentes en el inventario. Agrega productos o sube "
            "una factura para recibir recetas.",
        ) from None
    except service.SinAlimentosCompatibles:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No tienes alimentos compatibles con tu dieta o tus alergias. Agrega "
            "otros productos o revisa tus preferencias.",
        ) from None
    except service.GeneracionFallida:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de recetas no está disponible en este momento. "
            "Intenta de nuevo en unos minutos.",
        ) from None


@router.post("/{recomendacion_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def feedback(recomendacion_id: int, datos: FeedbackIn, db: DbSession, hogar_id: HogarId):
    recomendacion = service.obtener_recomendacion(db, hogar_id, recomendacion_id)
    if recomendacion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recomendación no encontrada"
        )
    try:
        service.guardar_feedback(db, recomendacion, datos.receta_indice, datos.util)
    except service.IndiceRecetaInvalido:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="receta_indice no corresponde a ninguna receta de esta recomendación",
        ) from None
