"""Fotos originales del compañero B (3, 4, 16 y 20.jpeg): legibilidad del OCR antes de
Gemini, anclaje de lo que devuelve Gemini al texto enviado, y Ara."""

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.invoices.models import Factura
from app.invoices.router import get_normalizador
from app.main import app
from app.ocr.anclaje import anclar
from app.ocr.anonimizacion import anonimizar
from app.ocr.encabezado import detectar_supermercado
from app.ocr.extraccion import LecturaOCR
from app.ocr.legibilidad import es_legible, es_token_legible, medir_legibilidad
from app.ocr.normalizacion import INSTRUCCIONES
from app.ocr.pipeline import procesar_factura, procesar_factura_con_imagen
from app.ocr.recorte import recortar_productos
from tests.conftest import HOGAR_TEST, imagen_factura, item_detectado, ocr_falso
from tests.factura_d1_real import FACTURA_D1_REAL
from tests.facturas_reales import (
    FACTURA_2_D1,
    FACTURA_4_MERKAMAX,
    FACTURA_5_D1,
    FACTURA_6_ALKOSTO,
    FACTURA_B3_ILEGIBLE,
    FACTURA_B4_ILEGIBLE,
    FACTURA_B16_ARA,
    FACTURA_B20,
)
from tests.test_invoices import subir

MIN_TOKENS = 0.32  # el valor por defecto de QUALITY_MIN_TOKENS_LEGIBLES


class Espia:
    def __init__(self, items=None):
        self.items = items or []
        self.textos = []

    def __call__(self, texto):
        self.textos.append(texto)
        return self.items


def _tokens_legibles(texto: str) -> float:
    return medir_legibilidad(LecturaOCR(texto)).tokens_legibles


# --- 1. Legibilidad del OCR ---


@pytest.mark.parametrize("factura", [FACTURA_B3_ILEGIBLE, FACTURA_B4_ILEGIBLE])
def test_las_fotos_ilegibles_no_pasan(factura):
    """3.jpeg y 4.jpeg tenían buen enfoque (461 y 729) pero el OCR leyó basura."""
    assert _tokens_legibles(factura) < MIN_TOKENS


@pytest.mark.parametrize(
    "factura",
    [
        FACTURA_B16_ARA,  # legible a medias
        FACTURA_B20,  # enfoque 277, el más bajo, pero se lee a medias
        FACTURA_D1_REAL,
        FACTURA_2_D1,
        FACTURA_4_MERKAMAX,
        FACTURA_5_D1,
        FACTURA_6_ALKOSTO,
    ],
)
def test_las_fotos_legibles_pasan(factura):
    assert _tokens_legibles(factura) >= MIN_TOKENS


@pytest.mark.parametrize(
    "token",
    [
        "LONCHITA",
        "ARANDANOS",
        "Cocacola",
        "16.950",
        "$10.490",
        "29500.00",
        "7702603019160",
        "1100ML",
        "x6",
        "QUESO",
    ],
)
def test_tokens_legibles(token):
    assert es_token_legible(token)


@pytest.mark.parametrize(
    "token",
    ["TIOAZE96300ZA", "ENIMGM0O", "NAAA", "a", "E,", "o", "1:2.109", "CION9-6", "XKJS"],
)
def test_tokens_no_legibles(token):
    assert not es_token_legible(token)


def test_confianza_media_solo_de_palabras_de_3_o_mas_alfanumericos():
    lectura = LecturaOCR(
        "LECHE a 4.500 E,", [("LECHE", 90.0), ("a", 10.0), ("4.500", 80.0), ("E,", 5.0)]
    )
    legibilidad = medir_legibilidad(lectura)
    assert legibilidad.confianza_media == 85.0  # (90 + 80) / 2
    assert es_legible(legibilidad, min_confianza=80, min_tokens=0.5)
    assert not es_legible(legibilidad, min_confianza=90, min_tokens=0.5)


@pytest.mark.parametrize(
    ("texto", "confianza"),
    [
        (FACTURA_B4_ILEGIBLE, 90.0),  # basura aunque Tesseract esté "seguro"
        (FACTURA_5_D1, 30.0),  # texto bueno, pero Tesseract dudó de casi todo
    ],
)
def test_ilegible_no_llama_a_gemini(monkeypatch, texto, confianza):
    ocr_falso(monkeypatch, texto, confianza=confianza)
    espia = Espia()
    resultado = procesar_factura(imagen_factura(), espia)

    assert espia.textos == []
    assert resultado.problema_calidad == "imagen_ilegible"
    assert resultado.items == []


def test_sin_validar_la_legibilidad_si_se_llama_a_gemini(monkeypatch):
    ocr_falso(monkeypatch, FACTURA_B4_ILEGIBLE)
    espia = Espia()
    resultado = procesar_factura(imagen_factura(), espia, validar_legibilidad=False)

    assert resultado.problema_calidad is None
    assert len(espia.textos) == 1


def test_la_vision_no_depende_de_la_legibilidad_del_ocr(monkeypatch):
    from app.ocr.normalizacion import RespuestaVision

    ocr_falso(monkeypatch, FACTURA_B4_ILEGIBLE)
    respuesta = RespuestaVision(items=[item_detectado()], total_impreso=9000)
    resultado = procesar_factura_con_imagen(imagen_factura(), lambda imagen: respuesta)

    assert resultado.problema_calidad is None
    assert len(resultado.items) == 1


def _facturas_del_hogar() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).where(Factura.hogar_id == HOGAR_TEST))


def test_api_foto_ilegible_responde_422_sin_gemini_ni_factura(client, monkeypatch, almacenamiento):
    ocr_falso(monkeypatch, FACTURA_B4_ILEGIBLE)
    espia = Espia()
    app.dependency_overrides[get_normalizador] = lambda: espia
    respuesta = subir(client)

    assert respuesta.status_code == 422
    detalle = respuesta.json()["detail"]
    assert detalle["codigo"] == "imagen_ilegible"
    assert detalle["mensaje"] and detalle["consejo"]
    assert espia.textos == []
    assert _facturas_del_hogar() == 0
    assert not any(almacenamiento.directorio.rglob("*.jpg"))  # ni la imagen se guardó


def test_los_umbrales_de_legibilidad_son_configurables(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "quality_min_tokens_legibles", 0.2)
    ocr_falso(monkeypatch, FACTURA_B4_ILEGIBLE)
    assert subir(client).status_code == 201


def test_el_enfoque_minimo_ya_no_rechaza_la_foto_20():
    """20.jpeg (enfoque 277) se lee a medias: el filtro rápido no debe rechazarla."""
    assert get_settings().quality_min_enfoque <= 277


# --- 2. Anclaje al texto enviado ---


def _respuesta_de_gemini_16():
    """Lo que devolvió Gemini con la foto 16: los EAN, inventados a partir de basura."""
    return [
        item_detectado(
            codigo="7702963002498",  # el OCR leyó "TIOAZE96300ZA"
            descripcion_impresa="YOGUR GRIEGO 13 L",  # leído "YESURT GRIEGO 13 LUN"
            nombre="Yogur griego 1.3 L",
            cantidad=1,
            precio_unitario=20520,
            precio_total=20520,
        ),
        item_detectado(
            codigo="7702910243572",
            descripcion_impresa="QUESO CUAJADA",  # leído "DUESO CUAJADA"
            nombre="Queso cuajada",
            cantidad=2,
            precio_unitario=9450,
            precio_total=18900,
        ),
        item_detectado(
            codigo="7702910303022",
            descripcion_impresa="ACEITE OLIVA",  # leído "ACENTE OL IV 504"
            nombre="Aceite de oliva",
            cantidad=1,
            precio_unitario=16950,
            precio_total=16950,
        ),
    ]


def test_codigos_que_no_estan_en_el_texto_se_quitan():
    bloque = recortar_productos(FACTURA_B16_ARA)
    anclados = anclar(_respuesta_de_gemini_16(), bloque)

    assert anclados.descartados == 0  # las descripciones sí están (con errores de OCR)
    assert [i.codigo for i in anclados.items] == [None, None, None]
    assert not any(i.revisar for i in anclados.items)  # 20.520, 9.450 y 16.950 sí están


def test_codigos_que_si_estan_en_el_texto_se_conservan():
    bloque = recortar_productos(FACTURA_B20)
    queso = item_detectado(
        codigo="0001178",
        descripcion_impresa="QUESTO TAJADO 1ELE UND",
        cantidad=1,
        precio_unitario=10430,
        precio_total=10430,
    )
    [item] = anclar([queso], bloque).items
    assert item.codigo == "0001178"


def test_precio_que_no_esta_en_el_texto_marca_revisar():
    """Foto 20: el pan se leyó "s0.:30" y Gemini devolvió $5,030."""
    bloque = recortar_productos(FACTURA_B20)
    pan = item_detectado(
        descripcion_impresa="Pan 1alabo FRUTOS DE Unt1",
        cantidad=1,
        precio_unitario=5030,
        precio_total=5030,
    )
    [item] = anclar([pan], bloque).items
    assert item.revisar is True


@pytest.mark.parametrize("formato", ["16.950", "16,950", "16950", "$ 16.950,00", "16950.00"])
def test_precios_en_cualquier_formato(formato):
    aceite = item_detectado(
        descripcion_impresa="ACEITE OLIVA", cantidad=1, precio_unitario=16950, precio_total=16950
    )
    [item] = anclar([aceite], f"ACEITE OLIVA 1 UN {formato}").items
    assert item.revisar is False


def test_descripcion_que_no_esta_en_el_texto_se_descarta():
    bloque = recortar_productos(FACTURA_B16_ARA)
    inventado = item_detectado(descripcion_impresa="Leche entera", precio_total=20520)
    anclados = anclar([*_respuesta_de_gemini_16(), inventado], bloque)

    assert anclados.descartados == 1
    assert len(anclados.items) == 3


def test_descripcion_multilinea_se_ancla_a_varios_renglones():
    """Merkamax: "TOALLAS" / "PEQUEÑIN" / "ALMENDRA X100" en renglones distintos."""
    bloque = recortar_productos(FACTURA_4_MERKAMAX)
    toallas = item_detectado(
        descripcion_impresa="TOALLAS pEQueñta ALMENDRA X100", precio_total=23500
    )
    assert anclar([toallas], bloque).descartados == 0


def test_yuca_la_frena_la_legibilidad_no_el_anclaje():
    """ "Ltda Yuca, o ENIMGM0O: 31.000": "Yuca" y "31.000" sí están impresos, así que el
    anclaje no puede descartarlo. Lo frena la legibilidad: la foto 4 no llega a Gemini."""
    yuca = item_detectado(descripcion_impresa="Yuca", precio_total=31000, precio_unitario=31000)
    assert anclar([yuca], FACTURA_B4_ILEGIBLE).descartados == 0
    assert _tokens_legibles(FACTURA_B4_ILEGIBLE) < MIN_TOKENS


def test_api_cuenta_los_items_descartados(client, monkeypatch):
    ocr_falso(monkeypatch, FACTURA_B16_ARA)
    inventado = item_detectado(descripcion_impresa="Leche entera", precio_total=20520)
    espia = Espia([*_respuesta_de_gemini_16(), inventado])
    app.dependency_overrides[get_normalizador] = lambda: espia
    factura = subir(client).json()

    assert factura["items_descartados"] == 1
    assert len(factura["items_detectados"]) == 3
    assert all(i["codigo"] is None for i in factura["items_detectados"])
    assert factura["supermercado"] == "Ara"


def test_instrucciones_piden_copiar_el_codigo_tal_cual():
    assert "copiado tal cual" in INSTRUCCIONES
    assert "TIOAZE96300ZA" in INSTRUCCIONES
    assert "nunca lo completes, lo corrijas ni lo deduzcas" in INSTRUCCIONES


# --- 3. Ara ---


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (FACTURA_B16_ARA, "Ara"),  # "TIENDAS NRA JLRONIMO MIRTINS COLUPBIA"
        ("TIENDAS ARA", "Ara"),
        ("JERONIMO MARTINS COLOMBIA S.A.S.", "Ara"),
        (FACTURA_B4_ILEGIBLE, None),  # antes: "ara" en la basura daba Ara
        ("ARA ARROZ", None),
        ("PARA LLEVAR", None),
    ],
)
def test_ara(texto, esperado):
    assert detectar_supermercado(texto) == esperado


# --- Anonimización de lo nuevo en estas fotos ---


@pytest.mark.parametrize(
    ("linea", "esperado"),
    [
        # 16.jpeg: la etiqueta pegada a la dirección.
        ("2 afro d DIRECCIONSCL 00 Bis 00-000 FORMA FAGO", "2 afro d DIRECCION: [DIRECCION]"),
        # 20.jpeg: "Atendido Pur" (Por).
        (
            "Cencración 01 11 20%b 0:95:59 y.1. Atendido Pur pedro prueba FO",
            "Cencración 01 11 20%b 0:95:59 y.1. Atendido Pur: [NOMBRE]",
        ),
    ],
)
def test_anonimiza_las_variantes_de_estas_fotos(linea, esperado):
    assert anonimizar(linea) == esperado
