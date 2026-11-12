"""Gobernanza: consentimiento, borrado y exportación de la cuenta, y auditoría."""

import logging

import fakeredis
import pytest
from sqlalchemy import select

from app.auth.security import get_token_claims
from app.catalog.models import Producto
from app.core.db import SessionLocal
from app.governance.models import Consentimiento, RegistroAuditoria
from app.governance.service import VERSION_POLITICA_VIGENTE, hash_sub
from app.inventory.models import ItemInventario
from app.invoices.models import Factura
from app.main import app
from app.preferences.models import PreferenciasHogar
from app.recommendations.models import Recomendacion
from app.users.models import Hogar, Usuario
from tests.conftest import (
    CODIGO_LECHE,
    HOGAR_TEST,
    OTRO_HOGAR,
    SUB_OTRO,
    SUB_SEGUNDO_MIEMBRO,
    SUB_TEST,
    actuar_como,
    crear_usuario,
    imagen_factura,
)

ACEPTAR = {"acepta_tratamiento": True, "version_politica": VERSION_POLITICA_VIGENTE}
REVOCAR = {"acepta_tratamiento": False, "version_politica": VERSION_POLITICA_VIGENTE}
ELIMINAR = {"confirmar": "ELIMINAR"}


def crear_item(client, nombre="Arroz", categoria="granos_cereales"):
    respuesta = client.post(
        "/inventario", json={"nombre": nombre, "categoria": categoria, "cantidad": 1}
    )
    assert respuesta.status_code == 201
    return respuesta.json()["id"]


def eliminar_cuenta(client, body=ELIMINAR):
    return client.request("DELETE", "/cuenta", json=body)


def auditoria() -> list[RegistroAuditoria]:
    with SessionLocal() as db:
        return list(db.scalars(select(RegistroAuditoria).order_by(RegistroAuditoria.id)))


def acciones(sub: str) -> list[str]:
    return [r.accion for r in auditoria() if r.usuario_sub_hash == hash_sub(sub)]


@pytest.fixture
def sin_consentimiento(client):
    """Actúa como un usuario del hogar de prueba que nunca aceptó el tratamiento."""
    crear_usuario(SUB_SEGUNDO_MIEMBRO, HOGAR_TEST, consentimiento=False)
    actuar_como(SUB_SEGUNDO_MIEMBRO)
    return client


# --- Consentimiento requerido ---


@pytest.mark.parametrize(
    ("metodo", "ruta"),
    [
        ("GET", "/inventario"),
        ("POST", "/inventario"),
        ("GET", "/facturas"),
        ("POST", "/facturas"),
        ("GET", "/preferencias"),
        ("PUT", "/preferencias"),
        ("POST", "/recomendaciones/recetas"),
        ("POST", "/recomendaciones/1/feedback"),
    ],
)
def test_sin_consentimiento_los_datos_del_hogar_dan_403(sin_consentimiento, metodo, ruta):
    respuesta = sin_consentimiento.request(metodo, ruta, json={})

    assert respuesta.status_code == 403
    detalle = respuesta.json()["detail"]
    assert detalle["codigo"] == "consentimiento_requerido"
    assert detalle["version_politica_vigente"] == VERSION_POLITICA_VIGENTE


@pytest.mark.parametrize("ruta", ["/me", "/health", "/consentimiento", "/cuenta/exportar"])
def test_sin_consentimiento_quedan_libres(sin_consentimiento, ruta):
    assert sin_consentimiento.get(ruta).status_code == 200


def test_consentimiento_sin_responder(sin_consentimiento):
    assert sin_consentimiento.get("/consentimiento").json() == {
        "acepta_tratamiento": False,
        "acepta_analitica_agregada": False,
        "version_politica": None,
        "otorgado_en": None,
        "actualizado_en": None,
        "version_politica_vigente": VERSION_POLITICA_VIGENTE,
    }


def test_otorgar_y_revocar(sin_consentimiento):
    client = sin_consentimiento

    otorgado = client.post("/consentimiento", json={**ACEPTAR, "acepta_analitica_agregada": True})
    assert otorgado.status_code == 200
    datos = otorgado.json()
    assert datos["acepta_tratamiento"] is True
    assert datos["acepta_analitica_agregada"] is True
    assert datos["otorgado_en"] is not None
    assert client.get("/inventario").status_code == 200

    revocado = client.post("/consentimiento", json=REVOCAR).json()
    assert revocado["acepta_tratamiento"] is False
    assert revocado["acepta_analitica_agregada"] is False  # default al no enviarlo
    assert revocado["otorgado_en"] is None
    assert client.get("/inventario").status_code == 403

    assert client.get("/consentimiento").json()["acepta_tratamiento"] is False


def test_analitica_es_opcional_y_por_defecto_false(sin_consentimiento):
    datos = sin_consentimiento.post("/consentimiento", json=ACEPTAR).json()
    assert datos["acepta_analitica_agregada"] is False


@pytest.mark.parametrize(
    "body",
    [
        {"acepta_tratamiento": True},  # falta la versión
        {"acepta_tratamiento": True, "version_politica": ""},
        {"version_politica": "1.0"},  # falta acepta_tratamiento
    ],
)
def test_consentimiento_invalido_da_422(sin_consentimiento, body):
    assert sin_consentimiento.post("/consentimiento", json=body).status_code == 422


def test_el_consentimiento_es_de_cada_usuario(sin_consentimiento):
    """Otro miembro del mismo hogar con consentimiento no habilita a quien no lo dio."""
    actuar_como(SUB_TEST)
    assert sin_consentimiento.get("/inventario").status_code == 200
    actuar_como(SUB_SEGUNDO_MIEMBRO)
    assert sin_consentimiento.get("/inventario").status_code == 403


# --- Auditoría ---


def test_auditoria_del_consentimiento(sin_consentimiento):
    client = sin_consentimiento
    client.post("/consentimiento", json=ACEPTAR)
    client.post("/consentimiento", json={**ACEPTAR, "acepta_analitica_agregada": True})
    client.post("/consentimiento", json=REVOCAR)

    assert acciones(SUB_SEGUNDO_MIEMBRO) == [
        "consentimiento_otorgado",
        "consentimiento_actualizado",
        "consentimiento_revocado",
    ]
    ultimo = auditoria()[-1]
    assert ultimo.detalle == {
        "acepta_tratamiento": False,
        "acepta_analitica_agregada": False,
        "version_politica": VERSION_POLITICA_VIGENTE,
    }


def test_auditoria_no_guarda_el_sub_en_claro(client):
    client.post("/consentimiento", json=ACEPTAR)
    client.get("/cuenta/exportar")
    eliminar_cuenta(client)

    registros = [r for r in auditoria() if r.usuario_sub_hash == hash_sub(SUB_TEST)]
    assert [r.accion for r in registros] == [
        "consentimiento_actualizado",
        "cuenta_exportada",
        "cuenta_eliminada",
    ]
    for registro in registros:
        assert len(registro.usuario_sub_hash) == 64  # hex de SHA-256
        texto = f"{registro.usuario_sub_hash} {registro.accion} {registro.detalle}"
        assert SUB_TEST not in texto
        assert "pytest-hogar" not in texto


def test_no_hay_endpoints_para_editar_o_borrar_la_auditoria(client):
    rutas = {getattr(ruta, "path", "") for ruta in app.routes}
    assert not any("auditoria" in ruta for ruta in rutas)


# --- Borrado de cuenta ---


def _llenar_hogar(client) -> dict:
    """Un hogar con de todo: ítems, factura pendiente (con imagen), factura confirmada
    (que crea un producto en el catálogo), preferencias y recomendación en caché."""
    crear_item(client, "Arroz")
    archivo = {"archivo": ("factura.png", imagen_factura(), "image/png")}
    pendiente = client.post("/facturas", files=archivo).json()
    otra = client.post("/facturas", files=archivo).json()
    leche = {
        "nombre": "Leche",
        "categoria": "lacteos",
        "cantidad": 1,
        "unidad": "unidad",
        "codigo": CODIGO_LECHE,
    }
    assert client.post(f"/facturas/{otra['id']}/confirmar", json=[leche]).status_code == 201
    client.put("/preferencias", json={"dieta": "vegetariana"})
    assert client.post("/recomendaciones/recetas").status_code == 201
    with SessionLocal() as db:
        imagen = db.get(Factura, pendiente["id"]).imagen_key
    return {"imagen": imagen}


def test_borrado_completo(client, almacenamiento, servidor_redis, factura_verificada):
    cache = fakeredis.FakeRedis(server=servidor_redis, decode_responses=True)
    datos = _llenar_hogar(client)
    assert almacenamiento.leer(datos["imagen"])
    assert list(cache.scan_iter(f"recetas:{HOGAR_TEST}:*"))
    # Datos del otro hogar, que no deben tocarse.
    actuar_como(SUB_OTRO)
    crear_item(client, "Papa del otro hogar")
    cache.set(f"recetas:{OTRO_HOGAR}:abc", "[]")
    actuar_como(SUB_TEST)

    assert eliminar_cuenta(client).status_code == 204

    with SessionLocal() as db:
        assert db.get(Hogar, HOGAR_TEST) is None
        assert db.scalar(select(Usuario).where(Usuario.auth0_sub == SUB_TEST)) is None
        for modelo in (ItemInventario, Factura, PreferenciasHogar, Recomendacion):
            assert db.scalars(select(modelo).where(modelo.hogar_id == HOGAR_TEST)).all() == []
        assert db.scalars(select(Consentimiento)).all() != []  # los de otros usuarios siguen
        # El catálogo global no se toca.
        assert db.scalar(select(Producto).where(Producto.codigo == CODIGO_LECHE)) is not None
        # El otro hogar sigue intacto.
        assert db.get(Hogar, OTRO_HOGAR) is not None
        otros = db.scalars(select(ItemInventario).where(ItemInventario.hogar_id == OTRO_HOGAR))
        assert [i.nombre for i in otros] == ["Papa del otro hogar"]

    with pytest.raises(FileNotFoundError):
        almacenamiento.leer(datos["imagen"])
    assert list(cache.scan_iter(f"recetas:{HOGAR_TEST}:*")) == []
    assert cache.get(f"recetas:{OTRO_HOGAR}:abc") == "[]"

    [registro] = [r for r in auditoria() if r.accion == "cuenta_eliminada"]
    assert registro.detalle == {
        "hogar_eliminado": True,
        "recomendaciones": 1,
        "preferencias": 1,
        "items": 2,  # el arroz y la leche de la factura confirmada
        "facturas": 2,
    }


def test_borrado_con_otro_miembro_en_el_hogar(client):
    crear_item(client, "Arroz")
    crear_usuario(SUB_SEGUNDO_MIEMBRO, HOGAR_TEST)

    assert eliminar_cuenta(client).status_code == 204

    with SessionLocal() as db:
        assert db.scalar(select(Usuario).where(Usuario.auth0_sub == SUB_TEST)) is None
        assert db.get(Hogar, HOGAR_TEST) is not None
        items = db.scalars(select(ItemInventario).where(ItemInventario.hogar_id == HOGAR_TEST))
        assert [i.nombre for i in items] == ["Arroz"]
    # El otro miembro sigue usando el hogar, con su consentimiento.
    actuar_como(SUB_SEGUNDO_MIEMBRO)
    assert [i["nombre"] for i in client.get("/inventario").json()] == ["Arroz"]
    [registro] = [r for r in auditoria() if r.accion == "cuenta_eliminada"]
    assert registro.detalle == {"hogar_eliminado": False}


@pytest.mark.parametrize("body", [None, {}, {"confirmar": "eliminar"}, {"confirmar": "SI"}])
def test_confirmacion_incorrecta_da_422_y_no_borra_nada(client, body):
    crear_item(client)
    respuesta = client.request("DELETE", "/cuenta", json=body)

    assert respuesta.status_code == 422
    assert len(client.get("/inventario").json()) == 1
    assert acciones(SUB_TEST) == []


def test_si_falla_el_storage_la_cuenta_igual_queda_borrada(client, almacenamiento, caplog):
    _llenar_hogar(client)

    def borrar_que_falla(key):
        raise OSError("S3 no responde")

    almacenamiento.borrar = borrar_que_falla
    with caplog.at_level(logging.ERROR):
        assert eliminar_cuenta(client).status_code == 204

    assert "No se pudo borrar la imagen" in caplog.text
    with SessionLocal() as db:
        assert db.get(Hogar, HOGAR_TEST) is None


def test_volver_a_entrar_crea_un_usuario_y_hogar_nuevos_y_vacios(client):
    crear_item(client, "Arroz")
    assert eliminar_cuenta(client).status_code == 204

    # Ahora por la cadena real de Auth0 (token falso), con el mismo sub.
    from app.auth.dependencies import get_usuario_actual

    del app.dependency_overrides[get_usuario_actual]
    app.dependency_overrides[get_token_claims] = lambda: {"sub": SUB_TEST}
    nuevo = client.get("/me").json()

    assert nuevo["hogar_id"] != HOGAR_TEST
    assert client.get("/consentimiento").json()["acepta_tratamiento"] is False
    assert client.get("/inventario").status_code == 403
    client.post("/consentimiento", json=ACEPTAR)
    assert client.get("/inventario").json() == []


def test_el_usuario_sin_consentimiento_tambien_puede_borrar_su_cuenta(sin_consentimiento):
    assert eliminar_cuenta(sin_consentimiento).status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(Usuario).where(Usuario.auth0_sub == SUB_SEGUNDO_MIEMBRO)) is None
        assert db.get(Hogar, HOGAR_TEST) is not None  # SUB_TEST sigue en el hogar


# --- Exportación ---


def test_exportacion(client):
    _llenar_hogar(client)
    crear_usuario(SUB_SEGUNDO_MIEMBRO, HOGAR_TEST)
    actuar_como(SUB_OTRO)
    crear_item(client, "Papa del otro hogar")
    actuar_como(SUB_TEST)

    respuesta = client.get("/cuenta/exportar")
    assert respuesta.status_code == 200
    datos = respuesta.json()

    assert set(datos) == {
        "exportado_en",
        "usuario",
        "hogar",
        "consentimiento",
        "preferencias",
        "inventario",
        "facturas",
        "recomendaciones",
    }
    assert datos["usuario"]["auth0_sub"] == SUB_TEST
    assert datos["hogar"]["otros_miembros"] == 1  # solo cuántos, no quiénes
    assert SUB_SEGUNDO_MIEMBRO not in respuesta.text
    assert datos["consentimiento"]["acepta_tratamiento"] is True
    assert datos["preferencias"]["dieta"] == "vegetariana"
    assert sorted(i["nombre"] for i in datos["inventario"]) == ["Arroz", "Leche"]
    assert len(datos["facturas"]) == 2
    assert len(datos["recomendaciones"]) == 1
    assert len(datos["recomendaciones"][0]["recetas"]) == 3
    # Aislamiento: nada del otro hogar. Y sin datos internos.
    assert "Papa del otro hogar" not in respuesta.text
    assert "hogar_id" not in respuesta.text
    assert "imagen_key" not in respuesta.text

    assert acciones(SUB_TEST)[-1] == "cuenta_exportada"
    assert auditoria()[-1].detalle == {"items": 2, "facturas": 2, "recomendaciones": 1}


def test_exportacion_sin_consentimiento_ni_datos(sin_consentimiento):
    datos = sin_consentimiento.get("/cuenta/exportar").json()

    assert datos["consentimiento"] is None
    assert datos["usuario"]["auth0_sub"] == SUB_SEGUNDO_MIEMBRO
    assert datos["hogar"]["otros_miembros"] == 1
