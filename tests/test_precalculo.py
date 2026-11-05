"""Precálculo de recetas en segundo plano. Gemini siempre es un falso (GeneradorEspia).

TestClient corre las BackgroundTasks antes de devolver la respuesta, así que al
terminar cada `client.post(...)` el precálculo ya ocurrió.
"""

import fakeredis
import pytest

from app.recommendations import service
from tests.conftest import HOGAR_TEST, imagen_factura
from tests.test_recommendations import (
    GeneradorEspia,
    crear_item,
    recomendar,
    registros,
    usar,
)


@pytest.fixture
def cache(servidor_redis):
    """El mismo Redis falso que usa la app en los tests."""
    return fakeredis.FakeRedis(server=servidor_redis, decode_responses=True)


@pytest.fixture
def espia():
    return usar(GeneradorEspia())


def _tipos() -> list[tuple[str, bool]]:
    return [(r.tipo, r.cache_hit) for r in registros()]


def _claves_de_recetas(cache) -> list[str]:
    return list(cache.scan_iter("recetas:*"))


def test_crear_un_alimento_precalcula_y_la_siguiente_peticion_es_hit(
    client, precalculo_activo, espia, cache
):
    crear_item(client, "Arroz", dias=2)

    assert len(espia.textos) == 1
    assert len(_claves_de_recetas(cache)) == 1
    [registro] = registros()
    assert (registro.tipo, registro.cache_hit, registro.intentos) == ("precalculo", False, 1)
    assert isinstance(registro.latencia_gemini_ms, int)

    respuesta = recomendar(client).json()
    assert respuesta["cache"] == "hit"
    assert len(espia.textos) == 1  # no se volvió a llamar a Gemini
    assert _tipos() == [("precalculo", False), ("normal", True)]


def test_apagado_no_precalcula(client, espia, cache):
    # Sin la fixture precalculo_activo: PRECALCULAR_RECETAS=false.
    crear_item(client, "Arroz", dias=2)

    assert espia.textos == []
    assert registros() == []


def test_productos_que_no_son_alimento_no_precalculan(client, precalculo_activo, espia):
    crear_item(client, "Arroz", dias=2)
    crear_item(client, "Detergente", categoria="aseo_hogar")

    assert len(espia.textos) == 1  # solo por el arroz


def test_editar_y_borrar_un_alimento_precalculan(client, precalculo_activo, espia):
    arroz = crear_item(client, "Arroz", dias=2)
    crear_item(client, "Papa", dias=5, categoria="frutas_verduras")
    client.patch(f"/inventario/{arroz}", json={"cantidad": 3})
    client.delete(f"/inventario/{arroz}")

    # Crear arroz, crear papa, editar arroz, borrar arroz: cada uno cambió la clave.
    assert len(espia.textos) == 4
    assert "Arroz" not in espia.textos[-1]
    assert [tipo for tipo, _ in _tipos()] == ["precalculo"] * 4


def test_cambiar_la_categoria_a_no_alimento_precalcula(client, precalculo_activo, espia):
    # Jabón primero: así el inventario final ({Arroz}) no coincide con una clave que ya
    # esté en caché, y el precálculo sí llama a Gemini.
    jabon = crear_item(client, "Jabón", dias=2)  # mal categorizado como alimento
    crear_item(client, "Arroz", dias=2)
    client.patch(f"/inventario/{jabon}", json={"categoria": "aseo_hogar"})

    assert len(espia.textos) == 3
    assert "Jabón" not in espia.textos[-1] and "Arroz" in espia.textos[-1]


def test_guardar_preferencias_precalcula(client, precalculo_activo, espia):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"dieta": "vegetariana"})

    assert len(espia.textos) == 2
    assert "Dieta: vegetariana" in espia.textos[-1]


def test_confirmar_factura_precalcula(client, precalculo_activo, espia):
    archivo = {"archivo": ("factura.png", imagen_factura(), "image/png")}
    factura_id = client.post("/facturas", files=archivo).json()["id"]
    leche = {"nombre": "Leche entera", "categoria": "lacteos", "cantidad": 1, "unidad": "unidad"}
    respuesta = client.post(f"/facturas/{factura_id}/confirmar", json=[leche])

    assert respuesta.status_code == 201
    [texto] = espia.textos
    assert "Leche entera" in texto


def test_si_ya_hay_un_precalculo_en_curso_no_lanza_otro(client, precalculo_activo, espia, cache):
    cache.set(f"lock_recetas:{HOGAR_TEST}", "1", ex=60)
    crear_item(client, "Arroz", dias=2)

    assert espia.textos == []
    # La marca es del otro precálculo: este no la borra.
    assert cache.get(f"lock_recetas:{HOGAR_TEST}") == "1"


def test_la_marca_se_borra_al_terminar(client, precalculo_activo, espia, cache):
    crear_item(client, "Arroz", dias=2)
    assert cache.get(f"lock_recetas:{HOGAR_TEST}") is None

    crear_item(client, "Papa", dias=5, categoria="frutas_verduras")
    assert len(espia.textos) == 2  # el segundo no quedó bloqueado por el primero


def test_si_las_recetas_ya_estan_en_cache_no_llama_a_gemini(client, precalculo_activo, espia):
    arroz = crear_item(client, "Arroz", dias=2)
    # La categoría no se le envía a Gemini ni hace parte de la clave de la caché.
    client.patch(f"/inventario/{arroz}", json={"categoria": "panaderia"})

    assert len(espia.textos) == 1
    assert len(registros()) == 1  # el segundo precálculo no registra nada


def test_si_gemini_falla_el_request_responde_igual(client, precalculo_activo, cache, caplog):
    def generador_que_falla(texto):
        raise RuntimeError("Gemini no responde")

    usar(generador_que_falla)
    respuesta = client.post(
        "/inventario", json={"nombre": "Arroz", "categoria": "granos_cereales", "cantidad": 1}
    )

    assert respuesta.status_code == 201
    assert "Falló el precálculo de recetas" in caplog.text
    assert registros() == []
    assert cache.get(f"lock_recetas:{HOGAR_TEST}") is None  # se borra aunque falle


def test_con_redis_caido_no_precalcula_y_el_request_responde(
    client, precalculo_activo, espia, servidor_redis
):
    servidor_redis.connected = False
    respuesta = client.post(
        "/inventario", json={"nombre": "Arroz", "categoria": "granos_cereales", "cantidad": 1}
    )

    assert respuesta.status_code == 201
    assert espia.textos == []  # sin caché no hay dónde dejar las recetas


def test_precalcular_usa_su_propia_sesion(client, espia, cache):
    """Llamado directamente, sin request ni sesión: abre la suya."""
    crear_item(client, "Arroz", dias=2)
    service.precalcular_recetas(HOGAR_TEST, cache, espia)

    assert len(espia.textos) == 1
    assert _tipos() == [("precalculo", False)]


def test_sin_alimentos_no_hace_nada(client, espia, cache):
    service.precalcular_recetas(HOGAR_TEST, cache, espia)

    assert espia.textos == []
    assert registros() == []
