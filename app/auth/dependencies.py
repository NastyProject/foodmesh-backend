from typing import Annotated

from fastapi import Depends

from app.auth.security import TokenClaims
from app.core.db import DbSession
from app.users.models import Usuario
from app.users.service import obtener_o_crear_usuario


def get_usuario_actual(db: DbSession, claims: TokenClaims) -> Usuario:
    """Usuario dueño del token; si es su primer login se crea junto con su hogar."""
    return obtener_o_crear_usuario(db, claims)


UsuarioActual = Annotated[Usuario, Depends(get_usuario_actual)]


def get_hogar_id(usuario: UsuarioActual) -> int:
    """Hogar del usuario autenticado. Es la única fuente de hogar_id de la API."""
    return usuario.hogar_id


HogarId = Annotated[int, Depends(get_hogar_id)]
