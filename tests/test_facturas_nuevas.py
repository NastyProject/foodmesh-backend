"""Facturas nuevas del compañero B (Alkosto, Dollarcity, D1 de otra ciudad).

La de Alkosto está completa en tests/facturas_reales.py. De las de Dollarcity y D1
solo se usan los fragmentos citados en el reporte ("NO. TARJ; ... 3064",
"Tarjeta No.: ... 1133", los formatos de total), marcados como tales.
"""

from datetime import date

import cv2
import numpy as np
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.invoices.models import Factura
from app.invoices.router import get_normalizador
from app.main import app
from app.ocr import preprocesamiento
from app.ocr.anonimizacion import anonimizar
from app.ocr.encabezado import detectar_fecha, detectar_supermercado
from app.ocr.pipeline import SIN_PRODUCTOS_EN_EL_TEXTO, procesar_factura
from app.ocr.recorte import extraer_total_impreso, lineas_de_productos, recortar_productos
from tests.conftest import HOGAR_TEST, imagen_factura, ocr_falso
from tests.factura_d1_real import FACTURA_D1_REAL
from tests.facturas_reales import (
    FACTURA_2_D1,
    FACTURA_3_D1,
    FACTURA_4_MERKAMAX,
    FACTURA_5_D1,
    FACTURA_6_ALKOSTO,
)
from tests.test_invoices import subir

ALKOSTO_SIN_ENCABEZADO = FACTURA_6_ALKOSTO.replace("$ Articulo IVA Iro Cant Total\n", "")
DATOS_PERSONALES_ALKOSTO = (
    "PRUEBA FICTICIO",
    "Ficticio-Sector",
    "correoprueba",
    "hotmail",
    "Clánte",
    "Barrio",
)


class Espia:
    """Hace de Gemini (modo texto): guarda lo que recibió."""

    def __init__(self):
        self.textos = []

    def __call__(self, texto):
        self.textos.append(texto)
        return []


# --- 1. Privacidad: nunca el texto completo ---


def test_alkosto_se_recorta_con_el_encabezado_articulo():
    bloque = recortar_productos(FACTURA_6_ALKOSTO)
    lineas = bloque.splitlines()

    assert lineas[0] == "$ Articulo IVA Iro Cant Total"
    assert len(lineas) == 1 + 2 * 5  # 5 productos, cada uno en dos líneas
    assert "Leche Álk Entera" in bloque and "7705994331005" in bloque
    # Termina antes de "Total Lineas factura: 5".
    assert "Total Lineas" not in bloque and "Subtotal" not in bloque


def test_sin_bloque_solo_se_envian_las_lineas_de_productos(monkeypatch):
    """Si el OCR no lee el encabezado de columnas, antes se enviaba el texto completo
    y se filtraban el nombre, el barrio y el email. Ahora, solo líneas de productos."""
    ocr_falso(monkeypatch, ALKOSTO_SIN_ENCABEZADO)
    espia = Espia()
    resultado = procesar_factura(imagen_factura(), espia)

    assert not resultado.recortada
    [enviado] = espia.textos
    for producto in ("Leche Álk Entera", "77035850119355", "Mortadela", "Quesillo", "24.900"):
        assert producto in enviado
    for dato in DATOS_PERSONALES_ALKOSTO:
        assert dato not in enviado
    assert "[TELEFONO]" not in enviado and "[CEDULA]" not in enviado
    # Se guarda lo mismo que se envió; el texto completo, nunca.
    assert resultado.texto_guardado == enviado
    assert resultado.texto_completo != enviado


def test_lineas_de_productos_toman_la_descripcion_de_arriba_y_de_abajo():
    texto = (
        "Cliente: [NOMBRE]\n"  # vecina con un marcador: no se envía
        "1 Leche Alk Entera 1100ml x6\n"  # descripción arriba del precio (Alkosto)
        "770102353683 67.800\n"
        "7702432759756\n"  # código arriba de la descripción (multilínea)
        "TOALLAS PEQUEÑIN\n"
        "Barrio Centro\n"  # vecina con etiqueta personal: no se envía
    )
    assert lineas_de_productos(texto) == (
        "1 Leche Alk Entera 1100ml x6\n770102353683 67.800\n7702432759756\nTOALLAS PEQUEÑIN"
    )


@pytest.mark.parametrize(
    "texto",
    [
        "",
        "Cliente: [NOMBRE]\nFecha 2026/11/02\nPedido No. 357738 Caja 24",  # sin precios
        FACTURA_6_ALKOSTO.split("$ Articulo")[0],  # solo el encabezado de Alkosto
    ],
)
def test_sin_lineas_de_productos_no_hay_nada_que_enviar(texto):
    assert lineas_de_productos(anonimizar(texto)) is None


def test_sin_productos_no_se_llama_a_gemini(monkeypatch):
    encabezado_alkosto = FACTURA_6_ALKOSTO.split("$ Articulo")[0]
    ocr_falso(monkeypatch, encabezado_alkosto)
    espia = Espia()
    resultado = procesar_factura(imagen_factura(), espia)

    assert espia.textos == []
    assert resultado.error == SIN_PRODUCTOS_EN_EL_TEXTO
    assert resultado.texto_guardado is None
    assert resultado.requiere_revision is True


def test_api_sin_productos_deja_la_factura_en_error_y_ofrece_la_vision(client, monkeypatch):
    encabezado_alkosto = FACTURA_6_ALKOSTO.split("$ Articulo")[0]
    ocr_falso(monkeypatch, encabezado_alkosto)
    espia = Espia()
    app.dependency_overrides[get_normalizador] = lambda: espia
    factura = subir(client).json()

    assert espia.textos == []
    assert factura["estado"] == "error"
    assert "con la imagen" in factura["error"]
    assert factura["texto_ocr"] is None


# --- 1. Anonimización ---


@pytest.mark.parametrize(
    ("linea", "esperado"),
    [
        # Alkosto: la etiqueta CLIENTE mal leída.
        ("Clánte PRUEBA FICTICIO NOMBRE APELLIDO 10", "Clánte: [NOMBRE]"),
        ("Cl1ente: ANA RUIZ", "Cl1ente: [NOMBRE]"),
        ("Barrio Ficticio-Sector Prueba", "Barrio: [DIRECCION]"),
        ("Dirección: CL 1 # 2-3", "Dirección: [DIRECCION]"),
        # Email con la @ leída como "é".
        ("Email correopruebaéhotmail.com", "Email [EMAIL]"),
        ("correo pruebagmail.con", "correo [EMAIL]"),
        # Fragmentos citados de las facturas de Dollarcity y D1 (no el renglón completo).
        ("NO. TARJ; ... 3064", "[TARJETA]"),
        ("Tarjeta No.: ... 1133", "[TARJETA]"),
    ],
)
def test_anonimiza_lo_que_se_filtraba(linea, esperado):
    assert anonimizar(linea) == esperado


@pytest.mark.parametrize(
    "linea",
    [
        "1 SALSA CALIENTE 3.500",  # se parece a CLIENTE, pero es un producto con precio
        "CALIENTE SALSA PICANTE 3.500",
        "Clánte Consumidor Final",
        "vezclientegalkosto.con.co",  # el email de la tienda no es un dato personal
        "Medio de Pago. TARJETA DEBITO/CREDITO",
        "| Estimado Cliente: [NOMBRE]",
    ],
)
def test_no_anonimiza_de_mas(linea):
    assert anonimizar(linea) == linea


def test_la_factura_de_alkosto_queda_sin_datos_personales():
    anonimo = anonimizar(FACTURA_6_ALKOSTO)
    for dato in ("PRUEBA FICTICIO", "Ficticio-Sector", "correoprueba"):
        assert dato not in anonimo
    # Los productos no se tocan.
    assert anonimizar(recortar_productos(FACTURA_6_ALKOSTO)) == recortar_productos(
        FACTURA_6_ALKOSTO
    )


@pytest.mark.parametrize("pago", ["Pagos:", "DETALLE DE PAGO", "Forma de pago: CONTADO"])
def test_el_bloque_termina_en_las_lineas_de_pago(pago):
    texto = f"DESCRIPCION VALOR\nLECHE 4.500\n{pago}\nTARJETA CREDITO 4.500\nTOTAL 4.500"
    assert recortar_productos(texto) == "DESCRIPCION VALOR\nLECHE 4.500"
    assert extraer_total_impreso(texto) == 4500  # el TOTAL se sigue buscando abajo


# --- 2. Total ---


@pytest.mark.parametrize(
    ("linea", "total"),
    [
        ("TOTAL 32,760", 32760),
        ("TOTAL 32.760", 32760),  # punto de miles (Alkosto)
        ("Valor Total 138.600", 138600),  # Alkosto
        ("TOTAL COMPRA 29500.00", 29500),
        ("TOTAL A PAGAR $ 29.500,00", 29500),
        ("4 TOTAL o 130,690 1", 130690),  # D1, con basura de OCR
    ],
)
def test_lineas_de_total_validas(linea, total):
    assert extraer_total_impreso(f"DESCRIPCION VALOR\nPAN 4.500\n{linea}") == total


@pytest.mark.parametrize(
    "linea",
    [
        "SUBTOTAL 30.000",
        "| Subtotal OS 132.672",  # Alkosto
        "TOTAL DESCUENTOS 2.000",
        "TOTAL ITEMS: 3",
        "TOTAL DE ARTÍCULOS 3",
        "Total Lineas factura: 5",  # Alkosto
        "- 1D ( TOTAL BASE IVA 21,900",  # fila de la tabla de IVA
        "Valor IVA 5.992 -",  # Alkosto
    ],
)
def test_lineas_que_no_son_el_total(linea):
    assert extraer_total_impreso(f"DESCRIPCION VALOR\nPAN 4.500\n{linea}") is None


def test_si_hay_varios_totales_gana_el_que_mas_se_repite():
    texto = (
        "DESCRIPCION VALOR\nPAN 4.500\n"
        "TOTAL 30.000\n"  # mal leído
        "TOTAL A PAGAR 29.500\n"
        "TOTAL COMPRA $ 29.500,00\n"
    )
    assert extraer_total_impreso(texto) == 29500


def test_en_un_empate_gana_el_primero():
    texto = "DESCRIPCION VALOR\nPAN 4.500\nTOTAL 29.500\nTOTAL A PAGAR 30.000"
    assert extraer_total_impreso(texto) == 29500


@pytest.mark.parametrize(
    ("factura", "total"),
    [
        (FACTURA_D1_REAL, 130690),
        (FACTURA_2_D1, 77620),
        (FACTURA_3_D1, 9380),
        (FACTURA_4_MERKAMAX, 135504),
        (FACTURA_5_D1, 21900),
        (FACTURA_6_ALKOSTO, 138600),  # antes no se encontraba
    ],
)
def test_total_de_todas_las_facturas_reales(factura, total):
    assert extraer_total_impreso(factura) == total


# --- 3. Fecha ---

HOY = date(2026, 11, 11)


def test_fecha_de_alkosto():
    assert detectar_fecha(FACTURA_6_ALKOSTO, hoy=HOY) == date(2026, 11, 2)


def test_sin_etiqueta_toma_la_mas_reciente_que_no_sea_futura():
    """Alkosto sin la etiqueta "Fecha": está también la vigencia de la numeración
    ("del 2026/07/17 al 2028/07/17"). La de 2028 es futura y la de julio, anterior."""
    sin_etiqueta = FACTURA_6_ALKOSTO.replace("Fecha 2026/11/02", "2026/11/02")
    assert detectar_fecha(sin_etiqueta, hoy=HOY) == date(2026, 11, 2)


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        # Las de la resolución se ignoran aunque sean las más recientes.
        ("Res 18764 del 2026-11-09\n2026-11-02 09:56", date(2026, 11, 2)),
        ("RESOLUCION DIAN 2026-11-09\n2026-11-02", date(2026, 11, 2)),
        ("Autorizada 2026-11-09\n2026-11-02", date(2026, 11, 2)),
        # La etiquetada gana aunque haya otra más reciente.
        ("Fecha 2026-10-01\n2026-11-02", date(2026, 10, 1)),
        # Solo fechas futuras: no hay fecha de compra.
        ("2027/01/01", None),
    ],
)
def test_fecha_sin_etiqueta(texto, esperado):
    assert detectar_fecha(texto, hoy=HOY) == esperado


# --- 4. Supermercado: Alkosto y Dollarcity ---


def test_alkosto_por_su_dominio_y_no_por_un_producto():
    assert detectar_supermercado(FACTURA_6_ALKOSTO) == "Alkosto"
    # "Quesillo Alkosto" es un producto (después del encabezado de columnas): no cuenta.
    assert detectar_supermercado("TIENDA X\nDESCRIPCION VALOR\nQuesillo Alkosto 24.900") is None


@pytest.mark.parametrize("texto", ["DOLLARCITY", "Dollar City Colombia", "DOLARCITY S.A.S"])
def test_dollarcity(texto):
    assert detectar_supermercado(texto) == "Dollarcity"


# --- 5. Calidad de la foto ---


def _borrosa(k: int = 15) -> bytes:
    imagen = cv2.imdecode(np.frombuffer(imagen_factura(), np.uint8), cv2.IMREAD_COLOR)
    _, datos = cv2.imencode(".png", cv2.GaussianBlur(imagen, (k, k), 0))
    return datos.tobytes()


def _facturas_del_hogar() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).where(Factura.hogar_id == HOGAR_TEST))


def test_medir_calidad():
    nitida = preprocesamiento.decodificar(imagen_factura())
    borrosa = preprocesamiento.decodificar(_borrosa())
    calidad = preprocesamiento.medir_calidad(nitida)

    assert (calidad.ancho, calidad.alto) == (900, 220)
    assert calidad.enfoque > 1000
    assert preprocesamiento.medir_calidad(borrosa).enfoque < 100


def test_foto_borrosa_responde_422_sin_llamar_a_gemini(client):
    espia = Espia()
    app.dependency_overrides[get_normalizador] = lambda: espia
    respuesta = subir(client, _borrosa())

    assert respuesta.status_code == 422
    detalle = respuesta.json()["detail"]
    assert detalle["codigo"] == "imagen_borrosa"
    assert detalle["consejo"] and detalle["mensaje"]
    assert espia.textos == []
    assert _facturas_del_hogar() == 0  # no se guardó nada


def test_foto_muy_pequena_responde_422(client):
    _, pequena = cv2.imencode(".png", np.full((200, 300, 3), 255, np.uint8))
    respuesta = subir(client, pequena.tobytes())

    assert respuesta.status_code == 422
    assert respuesta.json()["detail"]["codigo"] == "imagen_pequena"


def test_el_umbral_de_enfoque_es_configurable(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "quality_min_enfoque", 10)
    assert subir(client, _borrosa(k=9)).status_code == 201  # enfoque ~64


# --- 6. Evaluación por origen de la imagen: ver tests/test_evaluacion.py ---
