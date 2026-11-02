from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.users.models import Hogar, Usuario


def buscar_por_sub(db: Session, auth0_sub: str) -> Usuario | None:
    return db.scalar(select(Usuario).where(Usuario.auth0_sub == auth0_sub))


def obtener_o_crear_usuario(db: Session, claims: dict[str, Any]) -> Usuario:
    """Devuelve el usuario del token; en su primer login le crea un hogar propio."""
    sub = claims["sub"]
    usuario = buscar_por_sub(db, sub)
    if usuario is not None:
        return usuario

    email = claims.get("email")
    hogar = Hogar(nombre=f"Hogar de {email or sub}"[:120])
    db.add(hogar)
    db.flush()  # asigna hogar.id sin cerrar la transacción

    usuario = Usuario(auth0_sub=sub, email=email, hogar_id=hogar.id)
    db.add(usuario)
    try:
        db.commit()
    except IntegrityError:
        # Dos requests simultáneos del mismo usuario nuevo (el frontend suele
        # disparar varios al iniciar sesión): el otro ya lo creó, así que
        # deshacemos el nuestro (incluido su hogar) y usamos el existente.
        db.rollback()
        usuario = buscar_por_sub(db, sub)
        if usuario is None:
            raise
    return usuario
