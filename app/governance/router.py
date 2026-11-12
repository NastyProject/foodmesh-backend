from fastapi import APIRouter, status

from app.auth.dependencies import UsuarioActual
from app.core.cache import Cache
from app.core.db import DbSession
from app.core.storage import Storage
from app.governance import service
from app.governance.schemas import (
    ConfirmacionBorrado,
    ConsentimientoIn,
    ConsentimientoOut,
    Exportacion,
)

# Estos endpoints usan UsuarioActual, no HogarId: funcionan sin consentimiento.
router = APIRouter(tags=["gobernanza"])


def _consentimiento_out(db: DbSession, usuario_id: int) -> ConsentimientoOut:
    consentimiento = service.obtener_consentimiento(db, usuario_id)
    if consentimiento is None:
        # Nunca respondió: no ha aceptado nada.
        return ConsentimientoOut(
            acepta_tratamiento=False,
            acepta_analitica_agregada=False,
            version_politica=None,
            otorgado_en=None,
            actualizado_en=None,
            version_politica_vigente=service.VERSION_POLITICA_VIGENTE,
        )
    return ConsentimientoOut(
        acepta_tratamiento=consentimiento.acepta_tratamiento,
        acepta_analitica_agregada=consentimiento.acepta_analitica_agregada,
        version_politica=consentimiento.version_politica,
        otorgado_en=consentimiento.otorgado_en,
        actualizado_en=consentimiento.actualizado_en,
        version_politica_vigente=service.VERSION_POLITICA_VIGENTE,
    )


@router.get("/consentimiento", response_model=ConsentimientoOut)
def obtener_consentimiento(db: DbSession, usuario: UsuarioActual):
    return _consentimiento_out(db, usuario.id)


@router.post("/consentimiento", response_model=ConsentimientoOut)
def guardar_consentimiento(datos: ConsentimientoIn, db: DbSession, usuario: UsuarioActual):
    """Crea o reemplaza el consentimiento. Con acepta_tratamiento=false se revoca: los
    endpoints con datos del hogar vuelven a responder 403."""
    service.guardar_consentimiento(db, usuario, datos)
    return _consentimiento_out(db, usuario.id)


@router.delete("/cuenta", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_cuenta(
    confirmacion: ConfirmacionBorrado,
    db: DbSession,
    usuario: UsuarioActual,
    almacenamiento: Storage,
    cache: Cache,
):
    """Borra la cuenta (y el hogar, si es su único miembro). Body obligatorio:
    {"confirmar": "ELIMINAR"}. La identidad en Auth0 no se borra."""
    hogar_id = usuario.hogar_id
    resultado = service.eliminar_cuenta(db, usuario)
    # Después del commit: lo que pase aquí ya no puede deshacer el borrado de la BD.
    service.borrar_imagenes(almacenamiento, resultado.imagenes)
    service.invalidar_cache(cache, hogar_id)


@router.get("/cuenta/exportar", response_model=Exportacion)
def exportar_cuenta(db: DbSession, usuario: UsuarioActual):
    """Todos los datos del hogar del usuario (derecho de acceso, Ley 1581)."""
    return service.exportar_cuenta(db, usuario)
