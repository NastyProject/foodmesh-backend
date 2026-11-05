import logging
from functools import lru_cache
from typing import Annotated

import redis
from fastapi import Depends

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Tiempos cortos: si Redis está caído, mejor seguir sin caché que dejar la petición
# esperando la conexión.
TIMEOUT_SEGUNDOS = 0.5


@lru_cache
def get_cache() -> redis.Redis | None:
    """Cliente de Redis, o None si REDIS_URL es inválida. Crear el cliente no se
    conecta: si Redis no responde, el error sale al usarlo y quien lo usa lo maneja."""
    try:
        return redis.Redis.from_url(
            get_settings().redis_url,
            socket_timeout=TIMEOUT_SEGUNDOS,
            socket_connect_timeout=TIMEOUT_SEGUNDOS,
            decode_responses=True,
        )
    except ValueError:
        logger.warning("REDIS_URL inválida: se trabajará sin caché")
        return None


Cache = Annotated[redis.Redis | None, Depends(get_cache)]
