"""Dependencia para que otros módulos (inventario, facturas, preferencias) programen el
precálculo de recetas sin conocer sus detalles (caché, Gemini, BackgroundTasks)."""

from typing import Annotated

from fastapi import BackgroundTasks, Depends

from app.core.cache import Cache
from app.core.config import get_settings
from app.recommendations import service
from app.recommendations.router import GeneradorFondoDep


class Precalculo:
    def __init__(self, tareas: BackgroundTasks, cache: Cache, generar: GeneradorFondoDep):
        self.tareas = tareas
        self.cache = cache
        self.generar = generar

    def programar(self, hogar_id: int) -> None:
        """Agrega el precálculo a las tareas del request: FastAPI lo corre después de
        enviar la respuesta, así que no la demora. No hace nada si
        PRECALCULAR_RECETAS=false."""
        if get_settings().precalcular_recetas:
            self.tareas.add_task(service.precalcular_recetas, hogar_id, self.cache, self.generar)


# FastAPI resuelve los parámetros de __init__ como dependencias (BackgroundTasks es la
# del request actual), así que la clase misma sirve de dependencia.
PrecalculoDep = Annotated[Precalculo, Depends(Precalculo)]
