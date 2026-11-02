"""Validación del token con la dependencia real, sin llamar a Auth0.

En vez del JWKS de Auth0 usamos una llave RSA generada aquí: firmamos tokens
con ella y hacemos que get_jwks_client devuelva su llave pública.
"""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app.auth import security
from app.auth.security import get_token_claims
from app.core.config import get_settings
from app.main import app

LLAVE_PRIVADA = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def client_sin_overrides():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def jwks_falso(monkeypatch):
    class ClienteJWKSFalso:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=LLAVE_PRIVADA.public_key())

    monkeypatch.setattr(security, "get_jwks_client", lambda: ClienteJWKSFalso())


def _token(llave=LLAVE_PRIVADA, **cambios) -> str:
    settings = get_settings()
    ahora = int(time.time())
    claims = {
        "sub": "auth0|test",
        "aud": settings.auth0_audience,
        "iss": f"https://{settings.auth0_domain}/",
        "iat": ahora,
        "exp": ahora + 300,
        **cambios,
    }
    return jwt.encode(claims, llave, algorithm="RS256")


def _validar(token: str) -> dict:
    return get_token_claims(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))


@pytest.mark.parametrize("ruta", ["/inventario", "/me"])
def test_sin_token_responde_401(client_sin_overrides, ruta):
    respuesta = client_sin_overrides.get(ruta)
    assert respuesta.status_code == 401
    assert respuesta.headers["www-authenticate"] == "Bearer"


def test_token_malformado_responde_401(client_sin_overrides):
    respuesta = client_sin_overrides.get("/me", headers={"Authorization": "Bearer no-es-un-jwt"})
    assert respuesta.status_code == 401


def test_token_valido_devuelve_claims(jwks_falso):
    assert _validar(_token())["sub"] == "auth0|test"


@pytest.mark.parametrize(
    "cambios",
    [
        {"exp": int(time.time()) - 10},  # expirado
        {"aud": "https://otra-api.example"},  # audience equivocada
        {"iss": "https://otro-tenant.example/"},  # issuer equivocado
    ],
)
def test_token_con_claims_invalidos_responde_401(jwks_falso, cambios):
    with pytest.raises(HTTPException) as error:
        _validar(_token(**cambios))
    assert error.value.status_code == 401


def test_token_firmado_con_otra_llave_responde_401(jwks_falso):
    otra_llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException) as error:
        _validar(_token(llave=otra_llave))
    assert error.value.status_code == 401
