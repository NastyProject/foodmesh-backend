from fastapi import APIRouter

from app.auth.dependencies import UsuarioActual
from app.users.schemas import UsuarioOut

router = APIRouter(tags=["usuarios"])


@router.get("/me", response_model=UsuarioOut)
def me(usuario: UsuarioActual):
    return usuario
