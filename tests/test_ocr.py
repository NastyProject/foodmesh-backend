from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.catalog.categorias import es_alimento
from app.ocr import extraccion, preprocesamiento
from app.ocr.normalizacion import (
    INSTRUCCIONES,
    ItemPropuesto,
    RespuestaNormalizacion,
    a_propuesto,
    cuadran,
    limpiar_codigo,
    normalizar_items,
    precios_cuadran,
)
from app.ocr.pipeline import procesar_factura
from tests.conftest import ITEMS_FALSOS, imagen_factura, item_detectado, normalizador_falso
from tests.factura_d1 import BLOQUE_PRODUCTOS_D1, FACTURA_D1
from tests.factura_d1_real import FACTURA_D1_REAL


def test_preprocesar_y_extraer_texto():
    imagen = preprocesamiento.decodificar(imagen_factura(extension=".jpg"))
    procesada = preprocesamiento.preprocesar(imagen)

    assert procesada.ndim == 2  # escala de grises
    assert set(np.unique(procesada)) <= {0, 255}  # binarizada
    texto = extraccion.extraer_texto(procesada)
    assert "LECHE ENTERA" in texto
    assert "PAN TAJADO" in texto


def test_decodificar_rechaza_datos_que_no_son_imagen():
    with pytest.raises(ValueError):
        preprocesamiento.decodificar(b"no soy una imagen")


def test_corrige_perspectiva_si_encuentra_el_papel():
    # Papel blanco, girado, sobre una mesa oscura de 800x800
    foto = np.full((800, 800), 40, np.uint8)
    esquinas = np.array([[150, 100], [650, 160], [600, 700], [120, 650]], np.int32)
    cv2.fillPoly(foto, [esquinas], 250)

    corregida = preprocesamiento.corregir_perspectiva(foto)
    alto, ancho = corregida.shape
    assert 500 < alto < 600 and 450 < ancho < 550  # quedó solo el papel
    assert corregida.mean() > 200  # sin la mesa oscura


def test_sin_contorno_de_papel_no_cambia_la_imagen():
    gris = preprocesamiento.a_grises(preprocesamiento.decodificar(imagen_factura()))
    assert preprocesamiento.corregir_perspectiva(gris) is gris


def test_pipeline_completo_con_normalizador_falso():
    resultado = procesar_factura(imagen_factura(), normalizador_falso)
    assert resultado.error is None
    assert "LECHE" in resultado.texto_ocr
    assert [i.nombre for i in resultado.items] == [i.nombre for i in ITEMS_FALSOS]
    assert all(i.origen == "ia" and not i.revisar for i in resultado.items)
    # La imagen sintética no tiene encabezado de columnas: se envía el texto completo.
    assert not resultado.recortada
    assert resultado.texto_enviado == resultado.texto_ocr


def test_pipeline_envia_solo_el_bloque_de_productos(monkeypatch):
    textos_recibidos = []

    def normalizador_espia(texto):
        textos_recibidos.append(texto)
        return []

    # Reemplazamos Tesseract por un texto fijo con la forma de una factura real.
    monkeypatch.setattr(extraccion, "extraer_texto", lambda imagen: FACTURA_D1)
    resultado = procesar_factura(imagen_factura(), normalizador_espia)

    assert resultado.recortada
    assert textos_recibidos == [BLOQUE_PRODUCTOS_D1]
    assert resultado.texto_enviado == BLOQUE_PRODUCTOS_D1
    for dato in ("276952", "MARIA", "4321", "CUFE", "BOGOTA"):
        assert dato not in textos_recibidos[0]
    # Supermercado y fecha salen del encabezado, aunque no se envíe.
    assert resultado.supermercado == "D1"
    assert resultado.fecha_compra.isoformat() == "2026-10-30"


def test_pipeline_anonimiza_antes_de_normalizar():
    textos_recibidos = []

    def normalizador_espia(texto):
        textos_recibidos.append(texto)
        return []

    imagen = imagen_factura(["NIT 900123456-7", "LECHE ENTERA 4500"])
    resultado = procesar_factura(imagen, normalizador_espia)
    assert "900123456" not in textos_recibidos[0]
    assert "[NIT]" in resultado.texto_ocr


def test_pipeline_con_imagen_en_blanco():
    _, blanca = cv2.imencode(".png", np.full((200, 200), 255, np.uint8))
    resultado = procesar_factura(blanca.tobytes(), normalizador_falso)
    assert resultado.error == "No se detectó texto en la imagen."
    assert resultado.items == []


class ClienteGeminiFalso:
    """Imita client.models.generate_content y guarda con qué se llamó."""

    def __init__(self, texto_respuesta: str | None):
        self.texto_respuesta = texto_respuesta
        self.llamadas = []
        self.models = self

    def generate_content(self, **kwargs):
        self.llamadas.append(kwargs)
        return SimpleNamespace(text=self.texto_respuesta)


def test_normalizar_items_usa_structured_output():
    cliente = ClienteGeminiFalso(
        '{"items": [{"codigo": "7702001001234", "nombre": "Leche entera 1.1 L", "cantidad": 1,'
        ' "unidad": "unidad", "precio_unitario": 4500, "precio_total": 4500,'
        ' "categoria": "lacteos"}]}'
    )
    items = normalizar_items("LECHE ALQ ENT 1100ML 4.500", cliente, "modelo-x")

    assert [(i.codigo, i.nombre, i.precio_total) for i in items] == [
        ("7702001001234", "Leche entera 1.1 L", 4500)
    ]
    llamada = cliente.llamadas[0]
    assert llamada["model"] == "modelo-x"
    assert llamada["contents"] == "LECHE ALQ ENT 1100ML 4.500"
    assert llamada["config"].response_mime_type == "application/json"
    assert llamada["config"].response_schema is RespuestaNormalizacion


def test_normalizar_items_rechaza_categoria_fuera_de_la_lista():
    cliente = ClienteGeminiFalso(
        '{"items": [{"codigo": null, "nombre": "X", "cantidad": 1, "unidad": "unidad",'
        ' "precio_unitario": null, "precio_total": null, "categoria": "juguetes"}]}'
    )
    with pytest.raises(ValueError):
        normalizar_items("X", cliente, "modelo-x")


def test_normalizar_items_sin_respuesta():
    with pytest.raises(ValueError):
        normalizar_items("X", ClienteGeminiFalso(None), "modelo-x")


def test_el_esquema_de_gemini_no_incluye_campos_calculados():
    campos = RespuestaNormalizacion.model_json_schema()["$defs"]["ItemDetectado"]["properties"]
    assert {"codigo", "precio_unitario", "precio_total"} <= campos.keys()
    assert "origen" not in campos and "revisar" not in campos


def test_instrucciones_piden_verificar_precios():
    assert "cantidad × precio_unitario = precio_total" in INSTRUCCIONES
    assert "6/500" in INSTRUCCIONES and "7,3506" in INSTRUCCIONES


@pytest.mark.parametrize(
    ("cantidad", "unitario", "total", "cuadra"),
    [
        (2, 4500, 9000, True),
        (1.25, 2500, 3125, True),  # producto por peso
        (3, 3333, 10000, True),  # redondeo: diferencia menor al 1 %
        (2, 4500, 6500, False),
        (1, 7350, 73506, False),  # código de IVA pegado al precio
        (1, None, 6500, True),  # sin precio unitario no hay con qué comparar
        (1, 6500, None, True),
    ],
)
def test_precios_cuadran(cantidad, unitario, total, cuadra):
    item = item_detectado(cantidad=cantidad, precio_unitario=unitario, precio_total=total)
    assert precios_cuadran(item) is cuadra
    assert a_propuesto(item).revisar is not cuadra


@pytest.mark.parametrize(
    ("codigo", "esperado"),
    [
        ("7702001001234", "7702001001234"),
        ("770 2001 001234", "7702001001234"),
        ("4011", "4011"),  # PLU
        ("12", None),
        ("77O2001001234", None),  # con una letra: lectura dudosa
        (None, None),
    ],
)
def test_limpiar_codigo(codigo, esperado):
    assert limpiar_codigo(codigo) == esperado


@pytest.mark.parametrize(
    ("categoria", "esperado"),
    [
        ("lacteos", True),
        ("enlatados_conservas", True),
        ("condimentos_especias", True),
        ("otros", True),
        ("aseo_hogar", False),
        ("cuidado_personal", False),
        ("mascotas", False),
        ("frutos_secos", True),
        (None, True),
    ],
)
def test_es_alimento(categoria, esperado):
    assert es_alimento(categoria) is esperado


def test_item_propuesto_expone_es_alimento():
    item = a_propuesto(item_detectado(nombre="Varsol brillante", categoria="aseo_hogar"))
    assert item.model_dump()["es_alimento"] is False
    # Si el catálogo le cambia la categoría, es_alimento se recalcula.
    assert item.model_copy(update={"categoria": "lacteos"}).es_alimento is True
    # Se puede volver a leer desde el JSONB, aunque traiga el campo calculado.
    assert ItemPropuesto.model_validate(item.model_dump()) == item


def test_categorias_viejas_ya_no_son_validas():
    with pytest.raises(ValueError):
        item_detectado(categoria="aseo")


def test_instrucciones_traen_ejemplos_de_categorias():
    for ejemplo in (
        "atún en lata",
        "canela",
        "comino",
        "compotas",
        "galletas",
        "Varsol",
        "detergente",
    ):
        assert ejemplo in INSTRUCCIONES


@pytest.mark.parametrize(
    ("calculado", "impreso", "esperado"),
    [
        (130690, 130690, True),
        (130000, 130690, True),  # 0.5 % de diferencia
        (120000, 130690, False),
        (None, 130690, True),
        (130690, None, True),
    ],
)
def test_cuadran(calculado, impreso, esperado):
    assert cuadran(calculado, impreso) is esperado


@pytest.mark.parametrize(
    ("totales", "requiere_revision"),
    [
        ([100000, 30690], False),  # suman el TOTAL impreso (130,690)
        ([100000], True),  # faltó un ítem
        ([100000, None], True),  # un ítem sin precio cuenta como 0
    ],
)
def test_pipeline_compara_total_impreso_con_calculado(monkeypatch, totales, requiere_revision):
    monkeypatch.setattr(extraccion, "extraer_texto", lambda imagen: FACTURA_D1_REAL)

    def normalizador(texto):
        return [item_detectado(precio_unitario=None, precio_total=t) for t in totales]

    resultado = procesar_factura(imagen_factura(), normalizador)
    assert resultado.total_impreso == 130690
    assert resultado.total_calculado == sum(t or 0 for t in totales)
    assert resultado.requiere_revision is requiere_revision


def test_sin_total_impreso_pide_revision():
    resultado = procesar_factura(imagen_factura(), normalizador_falso)
    assert resultado.total_impreso is None
    assert resultado.requiere_revision is True


def test_si_falla_la_normalizacion_pide_revision(monkeypatch):
    def normalizador_que_falla(texto):
        raise RuntimeError("Gemini no responde")

    monkeypatch.setattr(extraccion, "extraer_texto", lambda imagen: FACTURA_D1_REAL)
    resultado = procesar_factura(imagen_factura(), normalizador_que_falla)
    assert resultado.total_impreso == 130690
    assert resultado.total_calculado is None
    assert resultado.requiere_revision is True
