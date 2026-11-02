from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import get_settings

# auto_error=False: si falta el header, FastAPI no responde 403 por su cuenta;
# nos deja None y respondemos nosotros con 401.
bearer = HTTPBearer(auto_error=False)


@lru_cache
def get_jwks_client() -> jwt.PyJWKClient:
    """Cliente que descarga (y cachea) las llaves públicas de Auth0.

    Con lru_cache se crea una sola vez por proceso, así su caché de llaves
    sirve entre requests en vez de descargar el JWKS cada vez.
    """
    dominio = get_settings().auth0_domain
    return jwt.PyJWKClient(f"https://{dominio}/.well-known/jwks.json")


def _no_autorizado(detalle: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detalle,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_token_claims(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> dict[str, Any]:
    """Valida el access token de Auth0 y devuelve sus claims (sub, aud, exp, ...)."""
    if credenciales is None:
        raise _no_autorizado("Falta el token de acceso")

    settings = get_settings()
    token = credenciales.credentials
    try:
        # El header del token dice qué llave (kid) lo firmó; buscamos esa en el JWKS.
        llave = get_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            llave.key,
            algorithms=["RS256"],
            audience=settings.auth0_audience,
            issuer=f"https://{settings.auth0_domain}/",
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as error:
        # Firma, audience, issuer, expiración o formato inválidos
        # (también si no se pudo descargar el JWKS).
        raise _no_autorizado("Token inválido") from error


TokenClaims = Annotated[dict[str, Any], Depends(get_token_claims)]
