from typing import Annotated

from fastapi import Depends


def get_hogar_id() -> int:
    """TEMPORAL: todos los requests pertenecen al hogar 1.

    Cuando integremos Auth0, esta función leerá el token y buscará el hogar del usuario.
    Como el resto del código solo depende de esta función, nada más tendrá que cambiar.
    """
    return 1


HogarId = Annotated[int, Depends(get_hogar_id)]