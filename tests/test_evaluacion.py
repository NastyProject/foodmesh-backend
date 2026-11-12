"""Métricas de evaluación del OCR (app/ocr/evaluacion.py), sin llamar a Gemini."""

import pytest

from app.ocr.evaluacion import (
    ORIGENES_IMAGEN,
    ItemVerdad,
    ResultadoFactura,
    calcular_metricas,
    emparejar,
    leer_verdad,
    origen_imagen,
    parecido_nombres,
    precio_correcto,
)
from app.ocr.normalizacion import a_propuesto
from tests.conftest import item_detectado

CSV = """\
factura,nombre,cantidad,precio_unitario,precio_total
factura3,Azúcar blanca,1,3190,3190
factura3,Clavo entero,1,"2,200","2,200"
factura3,Arroz premium,1,3.990,3990
factura4,Banano,"1,25",,3125
"""


def _verdad(tmp_path, contenido=CSV):
    ruta = tmp_path / "verdad.csv"
    ruta.write_text(contenido, encoding="utf-8")
    return leer_verdad(ruta)


def _detectado(nombre, total, cantidad=1, unitario=None):
    return a_propuesto(
        item_detectado(
            nombre=nombre,
            cantidad=cantidad,
            precio_unitario=unitario if unitario is not None else total,
            precio_total=total,
        )
    )


def _real(nombre, total, cantidad=1, unitario=None):
    return ItemVerdad("f", nombre, cantidad, unitario, total)


def test_leer_verdad(tmp_path):
    verdad = _verdad(tmp_path)

    assert sorted(verdad) == ["factura3", "factura4"]
    azucar, clavo, arroz = verdad["factura3"]
    assert (azucar.nombre, azucar.precio_total) == ("Azúcar blanca", 3190)
    assert (clavo.precio_unitario, clavo.precio_total) == (2200, 2200)  # "2,200"
    assert arroz.precio_unitario == 3990  # "3.990"
    [banano] = verdad["factura4"]
    assert banano.cantidad == 1.25  # decimal con coma
    assert banano.precio_unitario is None  # vacío


@pytest.mark.parametrize(
    ("contenido", "mensaje"),
    [
        ("factura,nombre,cantidad\nf,a,1\n", "faltan columnas"),
        (
            "factura,nombre,cantidad,precio_unitario,precio_total\nf,Arroz,1,3990,\n",
            "Fila 2: falta precio_total",
        ),
    ],
)
def test_leer_verdad_con_errores(tmp_path, contenido, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        _verdad(tmp_path, contenido)


@pytest.mark.parametrize(
    ("detectado", "real", "minimo"),
    [
        ("Lonchitas de queso amarillo", "Lonchita amarilla", 0.5),
        ("Huevos", "Huevos de codorniz", 0.3),
        ("Bolsas para hogar", "Bolsa hogar", 0.5),
    ],
)
def test_parecido_nombres(detectado, real, minimo):
    assert parecido_nombres(detectado, real) >= minimo


def test_emparejar_uno_a_uno_por_nombre_y_precio():
    detectados = [
        _detectado("Arroz premium", 3905),  # precio mal, pero el nombre empareja
        _detectado("Azúcar blanca", 3190),
        _detectado("Almendras 100 g", 1345),  # no existe: falso positivo
    ]
    reales = [
        _real("Azúcar blanca", 3190),
        _real("Arroz premium", 3990),
        _real("Bolsa plástica", 200),  # no se detectó
    ]
    parejas = emparejar(detectados, reales)

    assert sorted((d.nombre, r.nombre) for d, r in parejas) == [
        ("Arroz premium", "Arroz premium"),
        ("Azúcar blanca", "Azúcar blanca"),
    ]


def test_emparejar_con_el_mismo_precio_acepta_nombres_menos_parecidos():
    """'Queso crema Alquería' por 'Suero costeño Alquería' (factura 4): mismo precio y
    algo de parecido, cuenta como detectado (con el nombre mal)."""
    parejas = emparejar(
        [_detectado("Queso crema Alquería", 5900)], [_real("Suero costeño Alquería", 5900)]
    )
    assert len(parejas) == 1


@pytest.mark.parametrize(
    ("detectado", "real", "correcto"),
    [
        (_detectado("Arroz", 3990), _real("Arroz", 3990, unitario=3990), True),
        (_detectado("Arroz", 3905), _real("Arroz", 3990), False),
        # Factura 4: compota 5 × 4,600 leída como 1 × 23,000 (total bien, cantidad mal).
        (_detectado("Compota", 23000), _real("Compota", 23000, cantidad=5, unitario=4600), False),
        # Sin precio unitario en la verdad, solo se compara cantidad y total.
        (
            _detectado("Banano", 3125, cantidad=1.25, unitario=2500),
            _real("Banano", 3125, 1.25),
            True,
        ),
    ],
)
def test_precio_correcto(detectado, real, correcto):
    assert precio_correcto(detectado, real) is correcto


def test_calcular_metricas(tmp_path):
    verdad = _verdad(tmp_path)
    resultados = [
        ResultadoFactura(
            factura="factura3",
            items=[
                _detectado("Azúcar blanca", 3190),
                _detectado("Clavo entero", 2200),
                _detectado("Arroz premium", 3905, unitario=3990),
            ],
            requiere_revision=True,
            latencia_ms=20000,
        ),
        ResultadoFactura(
            factura="factura4",
            items=[_detectado("Banano", 3125, cantidad=1.25, unitario=2500)],
            requiere_revision=False,
            latencia_ms=10000,
        ),
    ]
    metricas = calcular_metricas(resultados, verdad)

    assert (metricas.items_reales, metricas.items_detectados, metricas.emparejados) == (4, 4, 4)
    assert metricas.precision == metricas.recall == metricas.f1 == 1.0
    assert metricas.precios_correctos == 3  # el arroz quedó mal
    assert metricas.porcentaje_precios_correctos == 0.75
    assert metricas.porcentaje_facturas_verificadas == 0.5
    assert metricas.latencias_ms == [20000, 10000]


def test_metricas_sin_detecciones():
    metricas = calcular_metricas(
        [ResultadoFactura("f", [], requiere_revision=True, latencia_ms=1)],
        {"f": [_real("Arroz", 3990)]},
    )
    assert (metricas.precision, metricas.recall, metricas.f1) == (0.0, 0.0, 0.0)


# --- origen_imagen: original o mejorada con IA ---

CSV_CON_ORIGEN = """\
factura,nombre,cantidad,precio_unitario,precio_total,origen_imagen
factura3,Arroz premium,1,3990,3990,original
9gpt,Leche Alkosto x6,6,11300,67800,mejorada_ia
9gpt,Quesillo Alkosto,1,24900,24900,mejorada_ia
"""


def test_leer_verdad_con_origen_de_la_imagen(tmp_path):
    verdad = _verdad(tmp_path, CSV_CON_ORIGEN)
    assert origen_imagen(verdad, "factura3") == "original"
    assert origen_imagen(verdad, "9gpt") == "mejorada_ia"


def test_sin_la_columna_todas_son_originales(tmp_path):
    verdad = _verdad(tmp_path)  # el CSV de arriba, sin origen_imagen
    assert {origen_imagen(verdad, f) for f in verdad} == {"original"}


@pytest.mark.parametrize(
    ("ultima_fila", "mensaje"),
    [
        ("9gpt,Pan,1,4200,4200,retocada", "origen_imagen debe ser original o mejorada_ia"),
        ("9gpt,Pan,1,4200,4200,original", "distinto origen_imagen"),
    ],
)
def test_origen_invalido_o_mezclado(tmp_path, ultima_fila, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        _verdad(tmp_path, CSV_CON_ORIGEN + ultima_fila + "\n")


def test_metricas_por_separado_segun_el_origen(tmp_path):
    verdad = _verdad(tmp_path, CSV_CON_ORIGEN)
    resultados = [
        ResultadoFactura("factura3", [_detectado("Arroz premium", 3990)], False, 1000),
        ResultadoFactura("9gpt", [_detectado("Leche Alkosto x6", 67800, cantidad=6)], True, 2000),
    ]
    por_origen = {
        origen: calcular_metricas(
            [r for r in resultados if origen_imagen(verdad, r.factura) == origen], verdad
        )
        for origen in ORIGENES_IMAGEN
    }
    assert (por_origen["original"].recall, por_origen["original"].facturas_verificadas) == (1.0, 1)
    assert por_origen["mejorada_ia"].recall == 0.5  # faltó el quesillo
    assert por_origen["mejorada_ia"].facturas_verificadas == 0
