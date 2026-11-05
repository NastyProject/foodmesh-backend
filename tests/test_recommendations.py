import re
from datetime import date, timedelta
from types import SimpleNamespace

import fakeredis
import pytest
from sqlalchemy import select

from app.auth.dependencies import get_hogar_id
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.inventory.models import ItemInventario
from app.main import app
from app.preferences.schemas import Preferencias
from app.recommendations import service
from app.recommendations.basicos import es_basico
from app.recommendations.generacion import INSTRUCCIONES, MAX_TOKENS_SALIDA, generar_recetas
from app.recommendations.models import Recomendacion
from app.recommendations.router import get_generador, get_generador_fondo
from app.recommendations.schemas import IngredienteIA, RespuestaRecetasIA
from tests.conftest import HOGAR_TEST, OTRO_HOGAR, generadas, generador_falso, receta_falsa


class GeneradorEspia:
    """Hace de Gemini: cuenta las llamadas y guarda el texto que recibió.

    Con `recetas` devuelve siempre lo mismo; con `por_llamada`, una lista distinta en
    cada llamada (la última se repite si se acaban). `modelo` es el que "respondió".
    """

    def __init__(self, recetas=None, por_llamada=None, modelo=None):
        self.por_llamada = por_llamada or ([recetas] if recetas is not None else None)
        self.modelo = modelo
        self.textos = []

    def __call__(self, texto):
        self.textos.append(texto)
        if self.por_llamada is None:
            return generadas(generador_falso(texto).recetas, self.modelo)
        recetas = self.por_llamada[min(len(self.textos), len(self.por_llamada)) - 1]
        return generadas(recetas, self.modelo)


def usar(espia):
    """Reemplaza a Gemini por `espia` en el POST y en el precálculo."""
    app.dependency_overrides[get_generador] = lambda: espia
    app.dependency_overrides[get_generador_fondo] = lambda: espia
    return espia


@pytest.fixture
def espia():
    return usar(GeneradorEspia())


def crear_item(client, nombre, dias=None, categoria="granos_cereales", cantidad=1):
    vence = (service.hoy() + timedelta(days=dias)).isoformat() if dias is not None else None
    datos = {
        "nombre": nombre,
        "categoria": categoria,
        "cantidad": cantidad,
        "fecha_vencimiento": vence,
    }
    respuesta = client.post("/inventario", json=datos)
    assert respuesta.status_code == 201
    return respuesta.json()["id"]


def recomendar(client):
    return client.post("/recomendaciones/recetas")


def registros() -> list[Recomendacion]:
    with SessionLocal() as db:
        consulta = (
            select(Recomendacion)
            .where(Recomendacion.hogar_id == HOGAR_TEST)
            .order_by(Recomendacion.id)
        )
        return list(db.scalars(consulta))


# --- Flujo y validación ---


def test_recomendar_recetas(client, espia):
    arroz = crear_item(client, "Arroz blanco", dias=1)
    crear_item(client, "Papa pastusa", dias=10, categoria="frutas_verduras")
    crear_item(client, "Detergente", dias=None, categoria="aseo_hogar")

    respuesta = recomendar(client)
    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert datos["cache"] == "miss"
    assert isinstance(datos["latencia_ms"], int)
    assert datos["aviso"] == (
        "Verifica siempre los ingredientes si tienes alergias: las recetas son generadas por IA."
    )
    assert len(datos["recetas"]) == 3

    receta = datos["recetas"][0]
    # "p1" (el que vence primero) se tradujo al id real del inventario.
    assert [i["item_id"] for i in receta["ingredientes"]] == [arroz, None]
    assert receta["usa_proximos_a_vencer"] == [
        {"item_id": arroz, "nombre": "Arroz blanco", "dias_para_vencer": 1}
    ]
    assert receta["ingredientes_faltantes"] == ["Cebolla larga"]

    # Lo que se le envió a Gemini: ids cortos, solo alimentos y nada del hogar.
    [texto] = espia.textos
    assert "- p1: Arroz blanco, 1 unidad, vence en 1 día" in texto
    assert "- p2: Papa pastusa" in texto
    assert "Detergente" not in texto
    assert str(HOGAR_TEST) not in texto and "hogar_id" not in texto
    assert not re.search(rf"\b{arroz}\b", texto)  # el id real no aparece

    [registro] = registros()
    assert registro.id == datos["recomendacion_id"]
    assert registro.cache_hit is False
    assert registro.recetas[0]["usa_proximos_a_vencer"][0]["item_id"] == arroz


def test_envia_las_preferencias(client, espia):
    crear_item(client, "Arroz", dias=2)
    preferencias = {
        "dieta": "vegetariana",
        "alergias": ["mani"],
        "no_le_gusta": ["cilantro"],
        "porciones": 4,
        "tiempo_max_minutos": 30,
    }
    client.put("/preferencias", json=preferencias)

    recomendar(client)
    texto = espia.textos[0]
    for linea in (
        "Dieta: vegetariana",
        "Alergias: mani",
        "No le gusta: cilantro",
        "Porciones: 4",
        "Tiempo máximo: 30 minutos",
    ):
        assert linea in texto


def test_item_id_inventado_o_de_otro_hogar_queda_como_a_comprar(client):
    crear_item(client, "Arroz", dias=2)
    app.dependency_overrides[get_hogar_id] = lambda: OTRO_HOGAR
    ajeno = crear_item(client, "Queso de otro hogar", dias=1, categoria="lacteos")
    app.dependency_overrides[get_hogar_id] = lambda: HOGAR_TEST

    ingredientes = [
        IngredienteIA(nombre="Arroz", cantidad=1, unidad="taza", item_id="p1"),
        IngredienteIA(nombre="Papa", cantidad=1, unidad="unidad", item_id="p99"),
        IngredienteIA(nombre="Tomate", cantidad=1, unidad="unidad", item_id=str(ajeno)),
    ]
    espia = GeneradorEspia([receta_falsa(ingredientes=ingredientes)])
    app.dependency_overrides[get_generador] = lambda: espia

    [receta] = recomendar(client).json()["recetas"]
    assert [i["item_id"] for i in receta["ingredientes"]][1:] == [None, None]
    assert receta["ingredientes_faltantes"] == ["Papa", "Tomate"]


def test_receta_con_alergeno_declarado_se_descarta(client):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"alergias": ["lacteos"]})
    con_queso = receta_falsa(
        "Arepa rellena",
        ingredientes=[IngredienteIA(nombre="Quesito", cantidad=1, unidad="tajada", item_id=None)],
    )
    con_leche_en_pasos = receta_falsa("Arroz cremoso", pasos=["Agregar media taza de leche."])
    espia = GeneradorEspia([receta_falsa(), con_queso, con_leche_en_pasos])
    app.dependency_overrides[get_generador] = lambda: espia

    recetas = recomendar(client).json()["recetas"]
    # Se devuelven las que quedaron, aunque sean menos de 3.
    assert [r["titulo"] for r in recetas] == ["Calentado de arroz"]


def test_alergeno_detectado_por_el_nombre_del_inventario():
    """Red de seguridad. Por la API ya no pasa (el queso ni se le envía a Gemini, ver
    test_inventario_incompatible_no_se_envia_a_gemini), así que se prueba la validación
    directamente: si un item_id apunta a un ítem con alérgeno, la receta se descarta."""
    queso = ItemInventario(id=1, nombre="Queso campesino", cantidad=1, unidad="unidad")
    # La IA lo llamó de otra forma, pero el item_id apunta al queso del inventario.
    ingredientes = [IngredienteIA(nombre="Lo que sobró", cantidad=1, unidad=None, item_id="p1")]
    validacion = service.validar_recetas(
        [receta_falsa(ingredientes=ingredientes)],
        {"p1": queso},
        Preferencias(alergias=["lacteos"]),
        service.hoy(),
    )
    assert validacion.recetas == []


def test_devuelve_maximo_tres_recetas(client):
    crear_item(client, "Arroz", dias=2)
    espia = GeneradorEspia([receta_falsa(f"Receta {i}") for i in range(5)])
    app.dependency_overrides[get_generador] = lambda: espia

    assert len(recomendar(client).json()["recetas"]) == 3


@pytest.mark.parametrize(
    "items",
    [
        [],
        [("Detergente", None, "aseo_hogar"), ("Concentrado", None, "mascotas")],
        [("Leche vencida", -1, "lacteos")],  # los vencidos no se proponen
    ],
)
def test_sin_alimentos_responde_409(client, espia, items):
    for nombre, dias, categoria in items:
        crear_item(client, nombre, dias=dias, categoria=categoria)

    respuesta = recomendar(client)
    assert respuesta.status_code == 409
    assert "No hay alimentos" in respuesta.json()["detail"]
    assert espia.textos == []  # ni se llamó a Gemini
    assert registros() == []


def test_si_gemini_falla_responde_503(client):
    crear_item(client, "Arroz", dias=2)

    def generador_que_falla(texto):
        raise RuntimeError("Gemini no responde")

    app.dependency_overrides[get_generador] = lambda: generador_que_falla
    respuesta = recomendar(client)
    assert respuesta.status_code == 503
    assert "no está disponible" in respuesta.json()["detail"]


# --- Caché ---


def test_misma_consulta_usa_la_cache(client, espia):
    crear_item(client, "Arroz", dias=2)

    primera = recomendar(client).json()
    segunda = recomendar(client).json()
    assert (primera["cache"], segunda["cache"]) == ("miss", "hit")
    assert segunda["recetas"] == primera["recetas"]
    assert len(espia.textos) == 1  # Gemini se llamó una sola vez
    # Las dos llamadas quedan registradas, para comparar latencias.
    assert [r.cache_hit for r in registros()] == [False, True]
    assert segunda["recomendacion_id"] != primera["recomendacion_id"]


def test_cambiar_el_inventario_invalida_la_cache(client, espia):
    arroz = crear_item(client, "Arroz", dias=2)
    recomendar(client)

    client.patch(f"/inventario/{arroz}", json={"cantidad": 3})
    assert recomendar(client).json()["cache"] == "miss"
    client.patch(f"/inventario/{arroz}", json={"fecha_vencimiento": "2099-01-01"})
    assert recomendar(client).json()["cache"] == "miss"
    crear_item(client, "Papa", dias=5)
    assert recomendar(client).json()["cache"] == "miss"
    assert len(espia.textos) == 4


def test_productos_que_no_son_alimento_no_afectan_la_cache(client, espia):
    crear_item(client, "Arroz", dias=2)
    recomendar(client)

    crear_item(client, "Detergente", categoria="aseo_hogar")
    assert recomendar(client).json()["cache"] == "hit"


def test_cambiar_preferencias_invalida_la_cache(client, espia):
    crear_item(client, "Arroz", dias=2)
    recomendar(client)

    client.put("/preferencias", json={"porciones": 4})
    assert recomendar(client).json()["cache"] == "miss"


def test_otro_dia_invalida_la_cache(client, espia, monkeypatch):
    crear_item(client, "Arroz", dias=2)
    recomendar(client)

    manana = service.hoy() + timedelta(days=1)
    monkeypatch.setattr(service, "hoy", lambda: manana)
    assert recomendar(client).json()["cache"] == "miss"


def test_otro_hogar_no_usa_la_cache_de_este(client, espia):
    crear_item(client, "Arroz", dias=2)
    recomendar(client)

    app.dependency_overrides[get_hogar_id] = lambda: OTRO_HOGAR
    crear_item(client, "Arroz", dias=2)
    assert recomendar(client).json()["cache"] == "miss"


def test_con_redis_caido_funciona_sin_cache(client, espia, servidor_redis, caplog):
    crear_item(client, "Arroz", dias=2)
    servidor_redis.connected = False  # cualquier comando a Redis lanza ConnectionError

    respuestas = [recomendar(client), recomendar(client)]
    assert [r.status_code for r in respuestas] == [201, 201]
    assert [r.json()["cache"] for r in respuestas] == ["miss", "miss"]
    assert len(espia.textos) == 2
    assert "Redis no disponible" in caplog.text


def test_valor_corrupto_en_cache_se_ignora(client, espia, servidor_redis, monkeypatch):
    crear_item(client, "Arroz", dias=2)
    monkeypatch.setattr(service, "clave_cache", lambda *args: "recetas:prueba")
    fakeredis.FakeRedis(server=servidor_redis).set("recetas:prueba", "esto no es json")

    assert recomendar(client).json()["cache"] == "miss"
    assert len(espia.textos) == 1


def test_clave_no_depende_del_orden():
    def item(id_, cantidad, vence):
        return ItemInventario(id=id_, cantidad=cantidad, fecha_vencimiento=vence)

    items = [item(1, 2, date(2026, 11, 5)), item(2, 1, None)]
    prefs = Preferencias(alergias=["mani", "gluten"], no_le_gusta=["Ajo", "cebolla"])
    prefs_reordenadas = Preferencias(alergias=["gluten", "mani"], no_le_gusta=["cebolla", "Ajo"])
    hoy = date(2026, 11, 2)

    clave = service.clave_cache(HOGAR_TEST, items, prefs, hoy, "modelo-x")
    assert clave == service.clave_cache(HOGAR_TEST, items[::-1], prefs_reordenadas, hoy, "modelo-x")
    assert clave != service.clave_cache(HOGAR_TEST, items, prefs, hoy, "otro-modelo")
    assert clave.startswith("recetas:")


# --- Feedback ---


def test_feedback(client, espia):
    crear_item(client, "Arroz", dias=2)
    recomendacion_id = recomendar(client).json()["recomendacion_id"]

    url = f"/recomendaciones/{recomendacion_id}/feedback"
    assert client.post(url, json={"receta_indice": 0, "util": True}).status_code == 204
    assert client.post(url, json={"receta_indice": 2, "util": False}).status_code == 204
    assert client.post(url, json={"receta_indice": 0, "util": False}).status_code == 204
    assert registros()[0].feedback == {"0": False, "2": False}  # la última opinión gana


@pytest.mark.parametrize("indice", [3, -1])
def test_feedback_con_indice_invalido(client, espia, indice):
    crear_item(client, "Arroz", dias=2)
    recomendacion_id = recomendar(client).json()["recomendacion_id"]

    url = f"/recomendaciones/{recomendacion_id}/feedback"
    assert client.post(url, json={"receta_indice": indice, "util": True}).status_code == 422


def test_feedback_de_otro_hogar_responde_404(client, espia):
    crear_item(client, "Arroz", dias=2)
    recomendacion_id = recomendar(client).json()["recomendacion_id"]

    app.dependency_overrides[get_hogar_id] = lambda: OTRO_HOGAR
    url = f"/recomendaciones/{recomendacion_id}/feedback"
    assert client.post(url, json={"receta_indice": 0, "util": True}).status_code == 404
    assert (
        client.post(
            "/recomendaciones/999999/feedback", json={"receta_indice": 0, "util": True}
        ).status_code
        == 404
    )
    assert registros()[0].feedback == {}


# --- Piezas sueltas ---


def test_instrucciones_de_recetas():
    for regla in ("3 días o menos", "alergias", "no le gustan", "colombiana", "aseo", "mascotas"):
        assert regla in INSTRUCCIONES


def test_generar_recetas_usa_structured_output():
    llamadas = []

    def generate_content(**kwargs):
        llamadas.append(kwargs)
        return SimpleNamespace(text=RespuestaRecetasIA(recetas=[receta_falsa()]).model_dump_json())

    cliente = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    resultado = generar_recetas("Alimentos disponibles: ...", cliente, "modelo-recetas")

    assert [r.titulo for r in resultado.recetas] == ["Calentado de arroz"]
    assert resultado.modelo == "modelo-recetas"
    assert llamadas[0]["model"] == "modelo-recetas"
    assert llamadas[0]["config"].response_schema is RespuestaRecetasIA
    assert llamadas[0]["config"].thinking_config.thinking_level == "MINIMAL"
    assert llamadas[0]["config"].max_output_tokens == MAX_TOKENS_SALIDA


def test_generar_recetas_sin_respuesta():
    cliente = SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(text=None))
    )
    with pytest.raises(ValueError):
        generar_recetas("x", cliente, "modelo")


# --- Clave con el nombre ---


def test_renombrar_un_item_invalida_la_cache(client, espia):
    arroz = crear_item(client, "Arroz", dias=2)
    recomendar(client)

    client.patch(f"/inventario/{arroz}", json={"nombre": "Arroz integral"})
    assert recomendar(client).json()["cache"] == "miss"
    assert "p1: Arroz integral" in espia.textos[-1]


# --- Dieta y tiempo ---


def test_receta_que_no_cumple_la_dieta_se_descarta(client):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"dieta": "vegetariana"})
    con_pollo = receta_falsa(
        "Arroz con pollo",
        ingredientes=[IngredienteIA(nombre="Pechuga", cantidad=1, unidad="unidad", item_id=None)],
    )
    con_atun = receta_falsa("Arroz con atún")
    usar(GeneradorEspia([con_pollo, receta_falsa("Arroz con verduras"), con_atun]))

    recetas = recomendar(client).json()["recetas"]
    assert [r["titulo"] for r in recetas] == ["Arroz con verduras"]


def test_pescetariana_acepta_pescado_pero_no_carne(client):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"dieta": "pescetariana"})
    usar(GeneradorEspia([receta_falsa("Arroz con atún"), receta_falsa("Arroz con chorizo")]))

    assert [r["titulo"] for r in recomendar(client).json()["recetas"]] == ["Arroz con atún"]


def test_vegana_descarta_huevo_lacteos_y_miel(client):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"dieta": "vegana"})
    recetas = [
        receta_falsa("Arroz con huevo"),
        receta_falsa("Arroz con leche de coco"),  # excepción: sí es vegana
        receta_falsa("Postre de arroz con miel"),
        receta_falsa("Arroz con queso"),
    ]
    usar(GeneradorEspia(recetas))

    titulos = [r["titulo"] for r in recomendar(client).json()["recetas"]]
    assert titulos == ["Arroz con leche de coco"]


@pytest.mark.parametrize(
    ("tiempo_receta", "se_queda"),
    [(30, True), (36, True), (37, False), (90, False)],  # máximo 30 + 20 % = 36
)
def test_receta_que_se_pasa_del_tiempo_se_descarta(client, tiempo_receta, se_queda):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"tiempo_max_minutos": 30})
    lenta = receta_falsa("Arroz lento", tiempo_minutos=tiempo_receta)
    usar(GeneradorEspia([receta_falsa("Arroz rápido", tiempo_minutos=15), lenta]))

    titulos = [r["titulo"] for r in recomendar(client).json()["recetas"]]
    assert ("Arroz lento" in titulos) is se_queda


def test_sin_tiempo_maximo_no_se_descarta_por_tiempo(client):
    crear_item(client, "Arroz", dias=2)
    usar(GeneradorEspia([receta_falsa("Arroz de 3 horas", tiempo_minutos=180)]))

    assert len(recomendar(client).json()["recetas"]) == 1


# --- Otras recetas ---


def test_sin_body_o_con_nuevas_false_usa_la_cache(client, espia):
    crear_item(client, "Arroz", dias=2)
    recomendar(client)

    respuesta = client.post("/recomendaciones/recetas", json={"nuevas": False})
    assert respuesta.json()["cache"] == "hit"


def test_otras_recetas_salta_la_cache_y_evita_las_anteriores(client):
    crear_item(client, "Arroz", dias=2)
    primeras = [receta_falsa("Calentado"), receta_falsa("Arroz con verduras")]
    otras = [receta_falsa("Arroz frito"), receta_falsa("Tortilla de arroz")]
    espia = usar(GeneradorEspia(por_llamada=[primeras, otras]))

    recomendar(client)
    respuesta = client.post("/recomendaciones/recetas", json={"nuevas": True}).json()
    assert respuesta["cache"] == "miss"
    assert [r["titulo"] for r in respuesta["recetas"]] == ["Arroz frito", "Tortilla de arroz"]
    assert len(espia.textos) == 2

    # A Gemini se le pidió no repetir las anteriores.
    assert "Calentado" not in espia.textos[0]
    texto = espia.textos[1]
    assert "Ya se le propusieron estas recetas; propón otras distintas:" in texto
    assert "- Calentado\n- Arroz con verduras" in texto

    # El resultado nuevo quedó en caché: la siguiente consulta normal lo devuelve.
    siguiente = recomendar(client).json()
    assert siguiente["cache"] == "hit"
    assert [r["titulo"] for r in siguiente["recetas"]] == ["Arroz frito", "Tortilla de arroz"]


def test_otras_recetas_solo_evita_las_de_este_hogar(client):
    app.dependency_overrides[get_hogar_id] = lambda: OTRO_HOGAR
    crear_item(client, "Arroz", dias=2)
    usar(GeneradorEspia([receta_falsa("Receta del otro hogar")]))
    recomendar(client)

    app.dependency_overrides[get_hogar_id] = lambda: HOGAR_TEST
    crear_item(client, "Arroz", dias=2)
    espia = usar(GeneradorEspia([receta_falsa()]))
    client.post("/recomendaciones/recetas", json={"nuevas": True})
    assert "Receta del otro hogar" not in espia.textos[0]
    assert "Ya se le propusieron" not in espia.textos[0]  # este hogar no tenía ninguna


def test_nuevas_debe_ser_booleano(client, espia):
    crear_item(client, "Arroz", dias=2)
    respuesta = client.post("/recomendaciones/recetas", json={"nuevas": "tal vez"})
    assert respuesta.status_code == 422


# --- Reintento y lista vacía ---


def test_si_ninguna_receta_pasa_reintenta_una_vez(client):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"alergias": ["lacteos"]})
    malas = [receta_falsa("Arroz con queso"), receta_falsa("Arroz con leche")]
    buenas = [receta_falsa("Arroz con verduras")]
    espia = usar(GeneradorEspia(por_llamada=[malas, buenas]))

    respuesta = recomendar(client).json()
    assert [r["titulo"] for r in respuesta["recetas"]] == ["Arroz con verduras"]
    assert respuesta["mensaje"] is None
    assert len(espia.textos) == 2

    # El reintento le explica a Gemini qué incumplió.
    assert "IMPORTANTE" not in espia.textos[0]
    reintento = espia.textos[1]
    assert "no cumplían las restricciones" in reintento
    assert "- Arroz con queso: contiene alérgenos declarados (lacteos)" in reintento


def test_si_el_reintento_tambien_falla_devuelve_lista_vacia(client):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"dieta": "vegetariana"})
    espia = usar(GeneradorEspia([receta_falsa("Arroz con pollo")]))

    respuesta = recomendar(client)
    assert respuesta.status_code == 201  # no es un error
    datos = respuesta.json()
    assert datos["recetas"] == []
    assert "No encontramos recetas" in datos["mensaje"]
    assert datos["aviso"]  # el aviso de alergias sigue saliendo
    assert len(espia.textos) == 2  # un solo reintento
    assert "Arroz con pollo: no es vegetariana (contiene carnes)" in espia.textos[1]

    # La lista vacía no se guarda en caché: la próxima vez se intenta de nuevo.
    assert recomendar(client).json()["cache"] == "miss"
    assert len(espia.textos) == 4
    # Pero sí queda registrada, para las métricas.
    assert [r.recetas for r in registros()] == [[], []]


def test_si_gemini_no_devuelve_recetas_tambien_reintenta(client):
    crear_item(client, "Arroz", dias=2)
    espia = usar(GeneradorEspia(por_llamada=[[], [receta_falsa()]]))

    assert len(recomendar(client).json()["recetas"]) == 1
    assert "no propusiste ninguna receta" in espia.textos[1]


def test_si_gemini_falla_en_el_reintento_responde_503(client):
    crear_item(client, "Arroz", dias=2)
    llamadas = []

    def generador(texto):
        llamadas.append(texto)
        if len(llamadas) == 1:
            return generadas([receta_falsa("Arroz con huevo")])
        raise RuntimeError("Gemini no responde")

    client.put("/preferencias", json={"alergias": ["huevo"]})
    usar(generador)
    assert recomendar(client).status_code == 503
    assert len(llamadas) == 2


def test_con_recetas_no_hay_mensaje(client, espia):
    crear_item(client, "Arroz", dias=2)
    assert recomendar(client).json()["mensaje"] is None


# --- Registro para métricas: tipo, intentos y recetas descartadas ---


def _metricas() -> list[tuple[str, bool, int, int]]:
    return [(r.tipo, r.cache_hit, r.intentos, r.recetas_descartadas) for r in registros()]


def test_registro_de_miss_y_hit(client, espia):
    crear_item(client, "Arroz", dias=2)
    recomendar(client)
    recomendar(client)

    assert _metricas() == [("normal", False, 1, 0), ("normal", True, 0, 0)]


def test_registro_de_otras_recetas(client, espia):
    crear_item(client, "Arroz", dias=2)
    recomendar(client)
    client.post("/recomendaciones/recetas", json={"nuevas": True})

    assert _metricas() == [("normal", False, 1, 0), ("nuevas", False, 1, 0)]


def test_registro_cuenta_descartes_del_primer_intento(client):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"alergias": ["lacteos"]})
    malas = [receta_falsa("Arroz con queso"), receta_falsa("Arroz con leche")]
    buenas = [receta_falsa("Arroz con verduras")]
    usar(GeneradorEspia(por_llamada=[malas, buenas]))
    recomendar(client)

    assert _metricas() == [("normal", False, 2, 2)]


def test_registro_suma_descartes_de_los_dos_intentos(client):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"dieta": "vegetariana"})
    primeras = [receta_falsa("Arroz con pollo"), receta_falsa("Arroz con atún")]
    segundas = [receta_falsa("Arroz con chorizo")]
    usar(GeneradorEspia(por_llamada=[primeras, segundas]))
    client.post("/recomendaciones/recetas", json={"nuevas": True})

    assert _metricas() == [("nuevas", False, 2, 3)]


def test_registro_con_descartes_parciales_no_reintenta(client):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"tiempo_max_minutos": 30})
    recetas = [receta_falsa("Rápida"), receta_falsa("Lenta", tiempo_minutos=120)]
    usar(GeneradorEspia(recetas))
    recomendar(client)

    assert _metricas() == [("normal", False, 1, 1)]


def test_lista_vacia_de_gemini_no_cuenta_como_descarte(client):
    crear_item(client, "Arroz", dias=2)
    usar(GeneradorEspia(por_llamada=[[], [receta_falsa()]]))
    recomendar(client)

    assert _metricas() == [("normal", False, 2, 0)]


def test_recetas_de_sobra_no_cuentan_como_descartadas(client):
    crear_item(client, "Arroz", dias=2)
    usar(GeneradorEspia([receta_falsa(f"Receta {i}") for i in range(5)]))
    recomendar(client)

    assert _metricas() == [("normal", False, 1, 0)]  # se recortan a 3, no se descartan


def test_registro_de_latencia_de_gemini(client, espia):
    crear_item(client, "Arroz", dias=2)
    recomendar(client)
    recomendar(client)

    miss, hit = registros()
    assert isinstance(miss.latencia_gemini_ms, int)
    assert miss.latencia_gemini_ms <= miss.latencia_ms
    assert hit.latencia_gemini_ms is None  # desde la caché no se llamó a Gemini


# --- Básicos de cocina ---


@pytest.mark.parametrize(
    "nombre",
    [
        "Agua",
        "agua sin gas",
        "Sal",
        "Sal y pimienta",
        "Aceite vegetal 1 L",
        "Azúcar morena",
        "Pimienta negra molida",
        "Aceite de oliva",
    ],
)
def test_es_basico(nombre):
    assert es_basico(nombre)


@pytest.mark.parametrize(
    "nombre",
    [
        "Salsa de tomate",
        "Salchicha",
        "Aceitunas",
        "Agua de coco",
        "Agua de panela",
        "Pimentón",
        "Arroz",
    ],
)
def test_no_es_basico(nombre):
    assert not es_basico(nombre)


def test_basicos_no_se_envian_ni_se_toman_del_inventario(client):
    arroz = crear_item(client, "Arroz", dias=2)
    # Aunque estén en el inventario y por vencer, no se le envían a Gemini.
    crear_item(client, "Aceite vegetal 1 L", dias=1, categoria="condimentos_especias")
    crear_item(client, "Sal refinada", dias=None, categoria="condimentos_especias")
    ingredientes = [
        IngredienteIA(nombre="Arroz", cantidad=2, unidad="taza", item_id="p1"),
        # Un básico con item_id (la IA lo asoció a otro ítem) igual queda en null.
        IngredienteIA(nombre="Aceite", cantidad=1, unidad="cucharada", item_id="p1"),
        IngredienteIA(nombre="Sal", cantidad=None, unidad=None, item_id=None),
        IngredienteIA(nombre="Agua sin gas", cantidad=2, unidad="taza", item_id=None),
        IngredienteIA(nombre="Cebolla larga", cantidad=1, unidad="unidad", item_id=None),
    ]
    espia = usar(GeneradorEspia([receta_falsa(ingredientes=ingredientes)]))

    [receta] = recomendar(client).json()["recetas"]
    assert [i["item_id"] for i in receta["ingredientes"]] == [arroz, None, None, None, None]
    assert receta["ingredientes_faltantes"] == ["Cebolla larga"]
    assert [p["nombre"] for p in receta["usa_proximos_a_vencer"]] == ["Arroz"]

    [texto] = espia.textos
    assert "Aceite" not in texto.split("Preferencias")[0]
    assert "Sal refinada" not in texto


def test_inventario_solo_con_basicos_responde_409(client, espia):
    crear_item(client, "Sal", categoria="condimentos_especias")
    crear_item(client, "Aceite vegetal", categoria="condimentos_especias")

    assert recomendar(client).status_code == 409
    assert espia.textos == []


def test_instrucciones_mencionan_basicos():
    assert "Agua, sal, aceite, azúcar y pimienta" in INSTRUCCIONES
    assert "siempre disponibles" in INSTRUCCIONES


# --- Variedad ---


def _receta_con(titulo, *ids_cortos):
    """Receta que usa esos ítems del inventario, en ese orden (de más a menos importante)."""
    ingredientes = [
        IngredienteIA(nombre=f"Ingrediente {id}", cantidad=1, unidad="unidad", item_id=id)
        for id in ids_cortos
    ]
    return receta_falsa(titulo, ingredientes=ingredientes)


def _tres_items(client):
    """Los ids cortos van por fecha de vencimiento: p1 (espinaca) vence mañana; p2 (arroz)
    y p3 (pollo) no están próximos a vencer."""
    crear_item(client, "Espinaca", dias=1, categoria="frutas_verduras")
    crear_item(client, "Arroz", dias=20)
    crear_item(client, "Pollo", dias=30, categoria="carnes_pescados")


def test_recetas_con_los_mismos_principales_se_queda_la_que_aprovecha_mas(client):
    _tres_items(client)
    recetas = [
        _receta_con("Arroz con pollo", "p2", "p3"),
        # Mismos principales (en otro orden), pero además usa la espinaca que vence mañana.
        _receta_con("Arroz con pollo y espinaca", "p3", "p2", "p1"),
        _receta_con("Crema de espinaca", "p1"),
    ]
    usar(GeneradorEspia(recetas))

    titulos = [r["titulo"] for r in recomendar(client).json()["recetas"]]
    assert titulos == ["Arroz con pollo y espinaca", "Crema de espinaca"]
    assert _metricas() == [("normal", False, 1, 1)]  # la repetida cuenta como descartada


def test_recetas_repetidas_con_el_mismo_aprovechamiento_se_queda_la_primera(client):
    _tres_items(client)
    usar(GeneradorEspia([_receta_con("Primera", "p2", "p3"), _receta_con("Segunda", "p2", "p3")]))

    assert [r["titulo"] for r in recomendar(client).json()["recetas"]] == ["Primera"]


def test_recetas_que_comparten_un_solo_principal_no_se_descartan(client):
    _tres_items(client)
    recetas = [
        _receta_con("Arroz con pollo", "p2", "p3"),
        _receta_con("Arroz con espinaca", "p2", "p1"),
        # El tercer ingrediente no cuenta: los principales son los dos primeros.
        _receta_con("Pollo con espinaca", "p3", "p1", "p2"),
    ]
    usar(GeneradorEspia(recetas))

    assert len(recomendar(client).json()["recetas"]) == 3


def test_la_variedad_se_revisa_antes_de_recortar_a_tres(client):
    _tres_items(client)
    recetas = [
        _receta_con("A", "p2", "p3"),
        _receta_con("B", "p2", "p3"),
        _receta_con("C", "p2", "p1"),
        _receta_con("D", "p3", "p1"),
    ]
    usar(GeneradorEspia(recetas))

    assert [r["titulo"] for r in recomendar(client).json()["recetas"]] == ["A", "C", "D"]


def test_instrucciones_piden_variedad():
    for regla in ("distintas entre sí", "misma proteína", "sopa", "salteado", "guiso"):
        assert regla in INSTRUCCIONES


# --- Inventario filtrado por dieta y alergias antes de llamar a Gemini ---


def test_inventario_incompatible_no_se_envia_a_gemini(client, espia):
    crear_item(client, "Pechuga de pollo", dias=1, categoria="carnes_pescados")
    crear_item(client, "Atún en lata", dias=1, categoria="enlatados_conservas")
    crear_item(client, "Arroz", dias=5)
    client.put("/preferencias", json={"dieta": "vegetariana"})

    assert recomendar(client).status_code == 201
    [texto] = espia.textos
    alimentos = texto.split("Preferencias")[0].lower()
    assert "pollo" not in alimentos and "atún" not in alimentos
    assert "- p1: Arroz" in texto  # los ids cortos solo cuentan lo que se envía


def test_sin_alimentos_compatibles_responde_409(client, espia):
    crear_item(client, "Pechuga de pollo", dias=1, categoria="carnes_pescados")
    crear_item(client, "Queso campesino", dias=2, categoria="lacteos")
    client.put("/preferencias", json={"dieta": "vegana"})

    respuesta = recomendar(client)
    assert respuesta.status_code == 409
    assert "No tienes alimentos compatibles con tu dieta" in respuesta.json()["detail"]
    assert espia.textos == []
    assert registros() == []


def test_alergia_filtra_por_categoria_y_por_nombre(client, espia):
    crear_item(client, "Kumis Alpina", dias=1, categoria="lacteos")  # por categoría
    crear_item(client, "Arepa de queso", dias=1, categoria="panaderia")  # por nombre
    crear_item(client, "Arroz", dias=5)
    client.put("/preferencias", json={"alergias": ["lacteos"]})

    recomendar(client)
    alimentos = espia.textos[0].split("Preferencias")[0]
    assert "Kumis" not in alimentos and "Arepa de queso" not in alimentos
    assert "Arroz" in alimentos


def test_cambiar_un_item_incompatible_igual_invalida_la_cache(client, espia):
    """La clave depende del inventario completo, aunque a Gemini solo llegue lo compatible."""
    crear_item(client, "Arroz", dias=5)
    pollo = crear_item(client, "Pollo", dias=1, categoria="carnes_pescados")
    client.put("/preferencias", json={"dieta": "vegetariana"})
    recomendar(client)
    client.patch(f"/inventario/{pollo}", json={"cantidad": 3})

    assert recomendar(client).json()["cache"] == "miss"
    assert len(espia.textos) == 2


@pytest.mark.parametrize(
    ("nombre", "categoria", "dieta", "alergias", "compatible"),
    [
        ("Pechuga de pollo", "carnes_pescados", "vegetariana", [], False),
        ("Bandeja x6", "carnes_pescados", "vegetariana", [], False),  # por categoría
        ("Huevos AA x12", "carnes_pescados", "vegetariana", [], True),  # el huevo sí
        ("Huevos AA x12", "carnes_pescados", "vegana", [], False),
        ("Huevos AA x12", "carnes_pescados", "omnivora", ["huevo"], False),
        ("Filete de tilapia", "carnes_pescados", "pescetariana", [], True),
        ("Chorizo", "carnes_pescados", "pescetariana", [], False),
        ("Yogur griego", "lacteos", "vegana", [], False),
        ("Yogur griego", "lacteos", "vegetariana", [], True),
        ("Leche de coco", "bebidas", "omnivora", ["lacteos"], True),
        ("Mix de almendras", "frutos_secos", "omnivora", ["frutos_secos"], False),
        ("Pan tajado", "panaderia", "omnivora", ["gluten"], False),
        ("Arroz", "granos_cereales", "vegana", ["lacteos", "gluten"], True),
    ],
)
def test_item_compatible(nombre, categoria, dieta, alergias, compatible):
    from app.preferences.models import Dieta
    from app.recommendations.restricciones import item_compatible

    assert item_compatible(nombre, categoria, Dieta(dieta), alergias) is compatible


# --- Lock compartido entre el POST y el precálculo ---


def _lock(servidor_redis):
    cache = fakeredis.FakeRedis(server=servidor_redis, decode_responses=True)
    return cache, f"lock_recetas:{HOGAR_TEST}"


def test_post_con_lock_espera_y_usa_lo_que_genero_el_otro(client, servidor_redis, monkeypatch):
    crear_item(client, "Arroz", dias=2)
    cache, lock = _lock(servidor_redis)
    cache.set(lock, "del-precalculo", ex=60)

    otro = GeneradorEspia()  # lo que habría generado el precálculo
    espera = []

    def esperar(segundos):
        espera.append(segundos)
        if len(espera) == 3:
            # A la tercera revisión, "el precálculo" deja sus recetas en caché.
            cache.delete(lock)
            service.precalcular_recetas(HOGAR_TEST, cache, otro)
            cache.set(lock, "del-precalculo", ex=60)  # sigue "tomado" un momento

    monkeypatch.setattr(service, "_esperar", esperar)
    espia = usar(GeneradorEspia())

    datos = recomendar(client).json()
    assert datos["cache"] == "hit"
    assert espia.textos == []  # el POST no llamó a Gemini
    assert len(otro.textos) == 1
    assert espera == [1.0, 1.0, 1.0]
    assert [r.tipo for r in registros()] == ["precalculo", "normal"]


def test_post_con_lock_genera_si_se_agota_la_espera(client, servidor_redis, monkeypatch):
    crear_item(client, "Arroz", dias=2)
    cache, lock = _lock(servidor_redis)
    cache.set(lock, "de-otro", ex=600)
    monkeypatch.setattr(get_settings(), "gemini_timeout_interactivo", 5)
    espera = []
    monkeypatch.setattr(service, "_esperar", espera.append)
    espia = usar(GeneradorEspia())

    assert recomendar(client).json()["cache"] == "miss"
    assert len(espera) == 5  # una revisión por segundo durante el timeout interactivo
    assert len(espia.textos) == 1
    assert cache.get(lock) == "de-otro"  # no borra el lock ajeno


def test_post_deja_de_esperar_si_el_otro_suelta_el_lock_sin_recetas(
    client, servidor_redis, monkeypatch
):
    crear_item(client, "Arroz", dias=2)
    cache, lock = _lock(servidor_redis)
    cache.set(lock, "de-otro", ex=600)
    espera = []

    def esperar(segundos):
        espera.append(segundos)
        cache.delete(lock)  # el otro falló o no le quedó ninguna receta

    monkeypatch.setattr(service, "_esperar", esperar)
    espia = usar(GeneradorEspia())

    assert recomendar(client).json()["cache"] == "miss"
    assert len(espera) == 1
    assert len(espia.textos) == 1
    assert cache.get(lock) is None  # tomó el lock, generó y lo soltó


def test_post_sin_lock_toma_el_lock_mientras_genera(client, servidor_redis):
    crear_item(client, "Arroz", dias=2)
    cache, lock = _lock(servidor_redis)
    durante = []

    def generador(texto):
        durante.append(cache.get(lock))
        return generador_falso(texto)

    usar(generador)
    recomendar(client)

    assert durante[0] is not None  # tenía el lock mientras llamaba a Gemini
    assert cache.get(lock) is None  # y lo soltó al terminar


def test_precalculo_no_arranca_si_el_post_tiene_el_lock(client, servidor_redis):
    crear_item(client, "Arroz", dias=2)
    cache, lock = _lock(servidor_redis)
    cache.set(lock, "del-post", ex=60)
    espia = GeneradorEspia()

    service.precalcular_recetas(HOGAR_TEST, cache, espia)
    assert espia.textos == []
    assert cache.get(lock) == "del-post"


def test_sin_redis_el_post_genera_como_antes(client, servidor_redis, espia):
    crear_item(client, "Arroz", dias=2)
    servidor_redis.connected = False

    assert recomendar(client).status_code == 201
    assert len(espia.textos) == 1


def test_lock_ttl_cubre_la_generacion_mas_lenta(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_timeout_fondo", 90)
    # 2 rondas × (3 peticiones (principal, reintento, respaldo) × 90 s + 4 s de espera)
    assert service._ttl_lock() == 548


# --- Logs ---


def test_logs_distinguen_rondas_de_validacion(client, caplog):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"alergias": ["lacteos"]})
    usar(GeneradorEspia(por_llamada=[[receta_falsa("Arroz con queso")], [receta_falsa()]]))
    with caplog.at_level("INFO", logger="app.recommendations.service"):
        recomendar(client)

    modelo = get_settings().gemini_model_recetas
    assert f"Ronda de validación 1/2: {modelo} respondió en" in caplog.text
    assert "1 recetas propuestas, 0 válidas" in caplog.text
    assert "se pide otra ronda con los motivos del descarte" in caplog.text
    assert "Ronda de validación 2/2" in caplog.text


def test_precalculo_sin_recetas_validas_no_guarda_nada_en_cache(client, servidor_redis, caplog):
    crear_item(client, "Arroz", dias=2)
    client.put("/preferencias", json={"alergias": ["lacteos"]})
    cache, _ = _lock(servidor_redis)
    malas = GeneradorEspia([receta_falsa("Arroz con queso")])

    with caplog.at_level("INFO", logger="app.recommendations.service"):
        service.precalcular_recetas(HOGAR_TEST, cache, malas)

    assert list(cache.scan_iter("recetas:*")) == []
    assert "no se guarda nada en caché" in caplog.text
    assert "0 recetas" not in caplog.text


# --- Modelo de respaldo: el registro y la caché usan el que respondió ---


def _claves_por_modelo_en_cache(servidor_redis) -> dict[str, bool]:
    """Para cada modelo (principal y respaldo), si hay recetas en caché con su clave."""
    cache = fakeredis.FakeRedis(server=servidor_redis, decode_responses=True)
    with SessionLocal() as db:
        items = service.alimentos_disponibles(db, HOGAR_TEST, service.hoy())
        prefs = service.preferences_service.obtener_preferencias(db, HOGAR_TEST)
    return {
        modelo: cache.get(service.clave_cache(HOGAR_TEST, items, prefs, service.hoy(), modelo))
        is not None
        for modelo in service.modelos_recetas()
    }


@pytest.fixture
def modelos(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_model_recetas", "modelo-principal")
    monkeypatch.setattr(settings, "gemini_model_recetas_respaldo", "modelo-respaldo")


def test_gemini_falso_con_503_en_el_principal_responde_el_respaldo(
    client, modelos, servidor_redis, monkeypatch
):
    """De punta a punta con el generador real: solo el cliente de Gemini es falso."""
    from app.core import gemini
    from app.recommendations import generacion
    from tests.test_gemini import ClienteFalso, error_api

    respuesta_ok = SimpleNamespace(
        text=RespuestaRecetasIA(recetas=[receta_falsa()]).model_dump_json()
    )
    cliente = ClienteFalso(error_api(503), error_api(503), respuesta_ok)
    monkeypatch.setattr(generacion, "cliente_gemini", lambda: cliente)
    monkeypatch.setattr(gemini, "_esperar", lambda segundos: None)
    usar(generacion.generar_con_gemini)
    crear_item(client, "Arroz", dias=2)

    datos = recomendar(client).json()
    assert [llamada["model"] for llamada in cliente.llamadas] == [
        "modelo-principal",
        "modelo-principal",
        "modelo-respaldo",
    ]
    assert datos["modelo"] == "modelo-respaldo"
    assert [r.modelo for r in registros()] == ["modelo-respaldo"]
    assert _claves_por_modelo_en_cache(servidor_redis) == {
        "modelo-principal": False,
        "modelo-respaldo": True,
    }


def test_recetas_del_respaldo_se_sirven_desde_la_cache(client, modelos):
    crear_item(client, "Arroz", dias=2)
    espia = usar(GeneradorEspia(modelo="modelo-respaldo"))
    recomendar(client)

    datos = recomendar(client).json()
    assert datos["cache"] == "hit"
    assert datos["modelo"] == "modelo-respaldo"  # quien las generó, no el configurado
    assert len(espia.textos) == 1
    assert [(r.modelo, r.cache_hit) for r in registros()] == [
        ("modelo-respaldo", False),
        ("modelo-respaldo", True),
    ]


def test_la_cache_del_principal_tiene_prioridad(client, modelos, servidor_redis):
    crear_item(client, "Arroz", dias=2)
    usar(GeneradorEspia(modelo="modelo-respaldo"))
    recomendar(client)
    # "Otras recetas" con el principal ya recuperado: deja su propia entrada en caché.
    usar(GeneradorEspia(por_llamada=[[receta_falsa("Del principal")]], modelo="modelo-principal"))
    client.post("/recomendaciones/recetas", json={"nuevas": True})

    datos = recomendar(client).json()
    assert datos["modelo"] == "modelo-principal"
    assert [r["titulo"] for r in datos["recetas"]] == ["Del principal"]
    assert _claves_por_modelo_en_cache(servidor_redis) == {
        "modelo-principal": True,
        "modelo-respaldo": True,
    }


def test_precalculo_con_respaldo_registra_y_guarda_con_ese_modelo(client, modelos, servidor_redis):
    crear_item(client, "Arroz", dias=2)
    cache = fakeredis.FakeRedis(server=servidor_redis, decode_responses=True)
    service.precalcular_recetas(HOGAR_TEST, cache, GeneradorEspia(modelo="modelo-respaldo"))

    assert [(r.tipo, r.modelo) for r in registros()] == [("precalculo", "modelo-respaldo")]
    assert _claves_por_modelo_en_cache(servidor_redis)["modelo-respaldo"] is True
    # Y el POST lo encuentra aunque el modelo configurado sea el principal.
    assert recomendar(client).json()["cache"] == "hit"


def test_sin_respaldo_configurado_solo_se_busca_el_principal(monkeypatch):
    monkeypatch.setattr(get_settings(), "gemini_model_recetas", "modelo-principal")
    monkeypatch.setattr(get_settings(), "gemini_model_recetas_respaldo", "")
    assert service.modelos_recetas() == ["modelo-principal"]
