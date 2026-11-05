from fastapi import APIRouter

from app.auth.dependencies import HogarId
from app.core.db import DbSession
from app.preferences import service
from app.preferences.schemas import Preferencias
from app.recommendations.precalculo import PrecalculoDep

router = APIRouter(prefix="/preferencias", tags=["preferencias"])


@router.get("", response_model=Preferencias)
def obtener(db: DbSession, hogar_id: HogarId):
    return service.obtener_preferencias(db, hogar_id)


@router.put("", response_model=Preferencias)
def guardar(datos: Preferencias, db: DbSession, hogar_id: HogarId, precalculo: PrecalculoDep):
    """Reemplaza todas las preferencias: los campos que no se envían vuelven a su valor
    por defecto."""
    preferencias = service.guardar_preferencias(db, hogar_id, datos)
    precalculo.programar(hogar_id)
    return preferencias
