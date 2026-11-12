from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.auth.security import TokenClaims
from app.core.db import DbSession
from app.governance.service import VERSION_POLITICA_VIGENTE, tiene_consentimiento
from app.users.models import Usuario
from app.users.service import obtener_o_crear_usuario


def get_usuario_actual(db: DbSession, claims: TokenClaims) -> Usuario:
    """Usuario dueño del token; si es su primer login se crea junto con su hogar."""
    return obtener_o_crear_usuario(db, claims)


UsuarioActual = Annotated[Usuario, Depends(get_usuario_actual)]


def get_usuario_con_consentimiento(db: DbSession, usuario: UsuarioActual) -> Usuario:
    """El usuario actual, solo si aceptó el tratamiento de datos; si no, 403.

    El frontend reconoce el caso por detail.codigo y muestra la pantalla de
    consentimiento. Quedan libres los endpoints que usan UsuarioActual directamente:
    /me, /consentimiento y los de /cuenta (exportar y borrar son derechos del titular,
    con o sin consentimiento).
    """
    if not tiene_consentimiento(db, usuario.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "codigo": "consentimiento_requerido",
                "mensaje": "Debes aceptar la política de tratamiento de datos para usar FoodMesh.",
                "version_politica_vigente": VERSION_POLITICA_VIGENTE,
            },
        )
    return usuario


UsuarioConConsentimiento = Annotated[Usuario, Depends(get_usuario_con_consentimiento)]


def get_hogar_id(usuario: UsuarioConConsentimiento) -> int:
    """Hogar del usuario autenticado. Es la única fuente de hogar_id de la API.

    Pasa por el consentimiento: todo endpoint que procesa datos del hogar (inventario,
    facturas, recetas, preferencias) usa HogarId, así que todos lo exigen, también
    los que se agreguen después.
    """
    return usuario.hogar_id


HogarId = Annotated[int, Depends(get_hogar_id)]
