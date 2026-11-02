"""Primer login y /me, sobreescribiendo get_token_claims (no se llama a Auth0).

Aquí get_hogar_id NO se sobreescribe: se prueba la cadena real
token -> usuario -> hogar_id.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.auth.security import get_token_claims
from app.core.db import SessionLocal
from app.inventory.models import ItemInventario
from app.main import app
from app.users.models import Hogar, Usuario

PREFIJO_SUB = "auth0|pytest-"


def _claims(email: str | None = "ana@example.com") -> dict:
    return {"sub": f"{PREFIJO_SUB}{uuid.uuid4()}", "email": email}


@pytest.fixture
def client_con_token():
    """Devuelve una función para fijar los claims del 'token' de los siguientes requests."""

    def usar_claims(claims: dict) -> None:
        app.dependency_overrides[get_token_claims] = lambda: claims

    with TestClient(app) as c:
        c.usar_claims = usar_claims
        yield c
    app.dependency_overrides.clear()

    # Limpieza en orden de FKs: ítems -> usuarios -> hogares
    with SessionLocal() as db:
        usuarios = db.scalars(select(Usuario).where(Usuario.auth0_sub.startswith(PREFIJO_SUB)))
        hogares = [u.hogar_id for u in usuarios]
        db.execute(delete(ItemInventario).where(ItemInventario.hogar_id.in_(hogares)))
        db.execute(delete(Usuario).where(Usuario.auth0_sub.startswith(PREFIJO_SUB)))
        db.execute(delete(Hogar).where(Hogar.id.in_(hogares)))
        db.commit()


def test_me_crea_usuario_y_hogar_en_el_primer_login_y_luego_los_reutiliza(client_con_token):
    claims = _claims()
    client_con_token.usar_claims(claims)

    primera = client_con_token.get("/me")
    assert primera.status_code == 200
    datos = primera.json()
    assert datos["email"] == "ana@example.com"
    assert set(datos) == {"id", "email", "hogar_id"}

    segunda = client_con_token.get("/me")
    assert segunda.json() == datos

    with SessionLocal() as db:
        usuarios = db.scalars(select(Usuario).where(Usuario.auth0_sub == claims["sub"])).all()
        assert len(usuarios) == 1
        hogar = db.get(Hogar, datos["hogar_id"])
        assert hogar.nombre == "Hogar de ana@example.com"


def test_sin_email_el_hogar_usa_el_sub(client_con_token):
    claims = _claims(email=None)
    client_con_token.usar_claims(claims)

    datos = client_con_token.get("/me").json()

    assert datos["email"] is None
    with SessionLocal() as db:
        assert db.get(Hogar, datos["hogar_id"]).nombre == f"Hogar de {claims['sub']}"


def test_dos_usuarios_no_comparten_inventario(client_con_token):
    client_con_token.usar_claims(_claims())
    respuesta = client_con_token.post("/inventario", json={"nombre": "Arroz", "cantidad": 1})
    assert respuesta.status_code == 201
