from datetime import date

import pytest

from app.ocr.encabezado import detectar_fecha, detectar_supermercado
from app.ocr.recorte import es_encabezado_columnas, extraer_total_impreso, recortar_productos
from tests.factura_d1 import BLOQUE_PRODUCTOS_D1, FACTURA_D1
from tests.factura_d1_real import FACTURA_D1_REAL


def test_recorta_el_bloque_de_productos():
    assert recortar_productos(FACTURA_D1) == BLOQUE_PRODUCTOS_D1


@pytest.mark.parametrize(
    "linea",
    [
        "DESCRIPCION VALOR",
        "Descripción  Cant  Valor",
        "DESCRIPC1ON",
        "CODIGO DESCR1PCION",
        "VAL0R",
        "4 WI CAN UH VALOR U — CODIGO). DESCRIPCION VALOR 1D. .",  # D1 real
    ],
)
def test_reconoce_encabezado_de_columnas_con_errores_de_ocr(linea):
    assert es_encabezado_columnas(linea)


@pytest.mark.parametrize("linea", ["LECHE ALQ ENT 1100ML 4.500", "TOTAL VALOR 18.625", ""])
def test_no_confunde_otras_lineas_con_el_encabezado(linea):
    assert not es_encabezado_columnas(linea)


@pytest.mark.parametrize(
    "linea", ["TOTAL 18.625", "T0TAL 18.625", "4 TOTAL o 130,690 1", "| : TOTAL 5.000"]
)
def test_total_con_basura_al_inicio_cierra_el_bloque(linea):
    assert recortar_productos(f"DESCRIPCION VALOR\nLECHE 4.500\n{linea}\nTARJ:9419") == (
        "DESCRIPCION VALOR\nLECHE 4.500"
    )


@pytest.mark.parametrize(
    "linea",
    [
        "| 1 1 UN 13,900 7700304755011 DETERGENTE LT 13,900 A ”- e",  # renglón de producto
        "1 2 3 4 TOTAL",  # TOTAL demasiado lejos del inicio
    ],
)
def test_no_confunde_productos_con_total(linea):
    assert recortar_productos(f"DESCRIPCION VALOR\n{linea}") is None


def test_subtotal_no_cierra_el_bloque():
    texto = "DESCRIPCION VALOR\nLECHE 4.500\nSUBTOTAL 4.500\nPAN 6.200\nTOTAL 10.700"
    assert recortar_productos(texto) == "DESCRIPCION VALOR\nLECHE 4.500\nSUBTOTAL 4.500\nPAN 6.200"


@pytest.mark.parametrize(
    "texto",
    [
        "LECHE 4.500\nTOTAL 4.500",  # sin encabezado de columnas
        "DESCRIPCION VALOR\nLECHE 4.500",  # sin TOTAL
        "TOTAL 4.500\nDESCRIPCION VALOR\nLECHE 4.500",  # TOTAL antes del encabezado
        "DESCRIPCION VALOR\nTOTAL 0",  # sin productos en medio
    ],
)
def test_sin_marcadores_no_recorta(texto):
    assert recortar_productos(texto) is None


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (FACTURA_D1, "D1"),
        ("TIENDAS D1\nDESCRIPCION VALOR", "D1"),
        (". DI SAS NITS00276952-1 Gran contribuyente y Agente | :", "D1"),  # D1 leído como DI
        ("Dl S.A.S.", "D1"),
        ("DI", None),  # sin el SAS, "DI" es demasiado ambiguo
        ("Almacenes Éxito S.A.\nNIT 890.900.608-9", "Éxito"),
        ("SUPERMERCADO EL ROBLE", None),
    ],
)
def test_detecta_supermercado(texto, esperado):
    assert detectar_supermercado(texto) == esperado


def test_supermercado_solo_se_busca_en_el_encabezado():
    # "ARA" en un producto (después del encabezado de columnas) no cuenta.
    assert detectar_supermercado("SUPERMERCADO X\nDESCRIPCION VALOR\nARA ARROZ 500G") is None


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (FACTURA_D1, date(2026, 10, 30)),
        ("Fecha 2026-10-30 10:15", date(2026, 10, 30)),
        ("05.11.26", date(2026, 11, 5)),
        # La primera no es una fecha válida (mes 13): se toma la siguiente.
        ("31/13/2026\nFecha: 01/10/2026", date(2026, 10, 1)),
        ("LECHE 1.250 KG 3.125", None),
        ("Resolución DIAN vigente desde 01/01/1990", None),
    ],
)
def test_detecta_fecha(texto, esperado):
    assert detectar_fecha(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (FACTURA_D1_REAL, 130690),  # "4 TOTAL o 130,690 1"
        (FACTURA_D1, 18625),  # "T0TAL 18.625"
        ("DESCRIPCION VALOR\nLECHE 4.500\nTOTAL A PAGAR $ 130.690,00", 130690),
        ("DESCRIPCION VALOR\nLECHE 4.500\nTOTAL 4500", 4500),
        # Sin encabezado de columnas también se busca, desde el inicio.
        ("LECHE 4.500\nTOTAL 4.500\nTOTAL BASE IVA 3.781", 4500),
        # El SUBTOTAL no es el TOTAL.
        ("DESCRIPCION VALOR\nLECHE 4.500\nSUBTOTAL 3.781\nTOTAL 4.500", 4500),
        ("DESCRIPCION VALOR\nLECHE 4.500", None),  # sin TOTAL
        ("DESCRIPCION VALOR\nLECHE 4.500\nTOTAL ilegible", None),
    ],
)
def test_extraer_total_impreso(texto, esperado):
    assert extraer_total_impreso(texto) == esperado
