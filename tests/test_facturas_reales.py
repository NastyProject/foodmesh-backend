"""El pipeline contra las facturas reales de noviembre de 2026 (tests/facturas_reales.py).

Cada test sale de un problema encontrado al probarlas: datos personales que se
guardaban, el supermercado o la fecha mal detectados, el formato multilínea y el
total que pasaba como verificado sin cuadrar.
"""

from datetime import date

import pytest

from app.ocr.anonimizacion import anonimizar
from app.ocr.encabezado import detectar_fecha, detectar_supermercado
from app.ocr.normalizacion import (
    INSTRUCCIONES,
    INSTRUCCIONES_VISION,
    ItemDetectado,
    ItemPropuesto,
    RespuestaNormalizacion,
    RespuestaVision,
)
from app.ocr.pipeline import procesar_factura
from app.ocr.recorte import extraer_total_impreso, recortar_productos
from tests.conftest import imagen_factura, item_detectado, ocr_falso
from tests.factura_d1_real import FACTURA_D1_REAL
from tests.facturas_reales import FACTURA_2_D1, FACTURA_3_D1, FACTURA_4_MERKAMAX, FACTURA_5_D1

# --- 1. Anonimización más tolerante ---


@pytest.mark.parametrize(
    ("linea", "esperado"),
    [
        # Factura 5: el nombre del cliente quedaba en el texto guardado.
        ("| ¡ CLIENTE: Juan Perez Prueba [CEDULA] e SN", "| ¡ CLIENTE: [NOMBRE]"),
        # Factura 4: el nombre del vendedor.
        (". VEND: Pedro Gomez Prueba 2 | . . ,", ". VEND: [NOMBRE]"),
        ("VENDEDOR: Ana Ruiz", "VENDEDOR: [NOMBRE]"),
        ("CAJERO: Ana Ruiz", "CAJERO: [NOMBRE]"),
        ("ATENDIDO POR: PEDRO PRUEBA 000001", "ATENDIDO POR: [NOMBRE]"),
        # Tarjeta, con las lecturas del OCR de "TARJ" de las facturas 2 y 5.
        ("o TAR):4242 [TRANSACCION] RRN-123456 o ,", "o [TARJETA] [TRANSACCION] [TRANSACCION] o ,"),
        ("TARO: 4242 [TRANSACCION]", "[TARJETA] [TRANSACCION]"),
        ("TARI 4242", "[TARJETA]"),
        ("TAR] 4242", "[TARJETA]"),
        ("TARJ:9419 Recibo: 152078 RAN: 201884", "[TARJETA] [TRANSACCION] [TRANSACCION]"),
    ],
)
def test_anonimiza_las_variantes_de_las_facturas_reales(linea, esperado):
    assert anonimizar(linea) == esperado


@pytest.mark.parametrize(
    "linea",
    [
        # "Consumidor Final" no es una persona: se conserva (con sus lecturas de OCR).
        ". d CLIENTE: Consuuidor Final [CEDULA]",
        "CLIENTE: Consunidor Final [CEDULA] o",
        "CLIENTE: Consuaidor-Final [CEDULA] o o",
        "CLIENTE: CONSUMIDOR FINAL ps : s",
        "e 10. CLIENTE: 'undefined- ] :",
        "Cliente: [CEDULA] [EMAIL]",  # solo marcadores: no hay nombre que borrar
        # Las cuentas de la tarjeta no son el número de la tarjeta.
        ". TARJ CRE/DES $ 77,620",
        # Productos que empiezan por TAR no son una tarjeta.
        "1 1UN 2,500 7700304684823 TARRO 1250 2,500",
        "1 1UN 2,500 7700304684823 TARTA FRUTAS 2,500",
    ],
)
def test_no_borra_lo_que_no_es_personal(linea):
    assert anonimizar(linea) == linea


@pytest.mark.parametrize("factura", [FACTURA_2_D1, FACTURA_3_D1, FACTURA_4_MERKAMAX, FACTURA_5_D1])
def test_la_anonimizacion_no_cambia_los_productos(factura):
    bloque = recortar_productos(factura)
    assert anonimizar(bloque) == bloque


@pytest.mark.parametrize(
    ("factura", "datos_personales"),
    [
        (FACTURA_2_D1, ["4242", "123456"]),
        (FACTURA_4_MERKAMAX, ["Pedro", "Gomez"]),
        (FACTURA_5_D1, ["Juan", "Perez", "4242"]),
    ],
)
def test_la_anonimizacion_quita_lo_que_antes_se_escapaba(factura, datos_personales):
    anonimo = anonimizar(factura)
    for dato in datos_personales:
        assert dato not in anonimo


# --- 1. Minimización: solo se guarda el bloque de productos ---


def test_solo_se_guarda_el_bloque_de_productos(monkeypatch):
    ocr_falso(monkeypatch, FACTURA_5_D1)
    resultado = procesar_factura(imagen_factura(), lambda texto: [])

    assert resultado.texto_guardado == resultado.texto_enviado
    assert resultado.texto_guardado.splitlines() == [
        "4 WI CAN UN VALOR Y CODIGO DESCRIPCION VALOR 10",
        "1 1UN 17,450 7700304280650 YOGURT GRIEGO 17,450 A no.",
        "1 2 1UN 4,450 7700304377589 GELATINA SABO 4,450 A |",
    ]
    # Lo demás solo vive en memoria (para el script de pruebas).
    assert "CLIENTE" in resultado.texto_completo
    for fuera_del_bloque in ("CLIENTE", "BOGOTA", "TARJ", "ATENDIDO", "Generacion"):
        assert fuera_del_bloque not in resultado.texto_guardado


# --- 4. Supermercado ---


@pytest.mark.parametrize(
    ("factura", "esperado"),
    [
        (FACTURA_D1_REAL, "D1"),  # por NIT: "NITS00276952-1" (S por 9 y un dígito mal)
        (FACTURA_2_D1, "D1"),
        (FACTURA_3_D1, "D1"),  # "pi sas": antes no se detectaba
        (FACTURA_4_MERKAMAX, "Surtimax (aliado)"),  # "MERKAMAR" / "MERKAMAX": antes no se detectaba
        (FACTURA_5_D1, "D1"),
    ],
)
def test_supermercado_de_las_facturas_reales(factura, esperado):
    assert detectar_supermercado(factura) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("NIT 900.276.962-1", "D1"),
        ("NITS00276952-1", "D1"),  # como lo leyó el OCR en la factura 1
        ("Nit: 9O1.O43.O20-0", "Surtimax (aliado)"),  # O por 0
        ("NIT 901043020-0", "Surtimax (aliado)"),
        ("NIT 860.007.538-1", None),  # un NIT que no es de una cadena conocida
        ("7700304276962 PRODUCTO", None),  # 9 dígitos dentro de un EAN no son un NIT
        ("pi sas Gran contribuyente", "D1"),
        ("MERKAMAR ss MER", "Surtimax (aliado)"),
        ("ARAS", None),  # los nombres cortos solo exactos
    ],
)
def test_supermercado_por_nit_y_por_nombre_aproximado(texto, esperado):
    assert detectar_supermercado(texto) == esperado


def test_el_nit_se_busca_antes_de_anonimizar():
    """Después de anonimizar, el NIT es [NIT]: hay que detectarlo sobre el texto crudo."""
    texto = "TIENDA SIN NOMBRE CONOCIDO NIT 900.276.962-1"
    assert detectar_supermercado(texto) == "D1"
    assert detectar_supermercado(anonimizar(texto)) is None


# --- 5. Fecha ---


@pytest.mark.parametrize(
    ("factura", "esperado"),
    [
        (FACTURA_2_D1, date(2026, 11, 8)),
        (FACTURA_3_D1, date(2026, 11, 8)),
        # Antes tomaba 2026-05-30, la de la autorización de numeración de la DIAN.
        (FACTURA_4_MERKAMAX, date(2026, 11, 8)),
        (FACTURA_5_D1, date(2026, 11, 8)),
    ],
)
def test_fecha_de_las_facturas_reales(factura, esperado):
    assert detectar_fecha(factura) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        # La etiquetada gana, aunque aparezca después.
        ("Caja 1 2026-01-15\nFECHA: 2026-11-08", date(2026, 11, 8)),
        ("Generacion: 2026/11/08 18:01:39", date(2026, 11, 8)),
        # Las de la autorización y la vigencia se ignoran, con o sin etiqueta.
        ("autorización de numeración 2026-05-30\n2026-11-08", date(2026, 11, 8)),
        ("Fecha de autorización: 2026-05-30\nFECHA: 2026-11-08", date(2026, 11, 8)),
        ("Vigencia hasta 2028-05-30", None),
    ],
)
def test_fecha_prefiere_la_etiquetada_e_ignora_la_dian(texto, esperado):
    assert detectar_fecha(texto) == esperado


# --- 6. Recorte: los dos formatos ---


@pytest.mark.parametrize(
    ("factura", "productos", "total"),
    [
        (FACTURA_2_D1, 17, 77620),
        (FACTURA_3_D1, 3, 9380),
        (FACTURA_5_D1, 2, 21900),
    ],
)
def test_recorte_formato_de_una_linea_por_producto(factura, productos, total):
    lineas = recortar_productos(factura).splitlines()
    assert len(lineas) == 1 + productos  # encabezado de columnas + productos
    assert extraer_total_impreso(factura) == total


def test_recorte_formato_multilinea():
    bloque = recortar_productos(FACTURA_4_MERKAMAX)
    lineas = bloque.splitlines()

    assert "DESCRIPCIÓN" in lineas[0]
    # Todos los EAN de los productos quedan en el bloque, también el de la bolsa y el
    # de la última línea.
    for ean in ("7702432759756", "7702024040040", "8719200259232", "7702001086023"):
        assert ean in bloque
    assert "PLASTICA" in bloque
    # El encabezado de columnas repetido a mitad de la factura se quita.
    assert sum("DESCRIPCI" in linea for linea in lineas) == 1
    # El bloque se corta en "TOTAL XTEMS" (TOTAL ITEMS): lo de abajo no son productos.
    for despues_de_los_productos in ("XTEMS", "SUBTOTAL", "CAMBIO", "19XIVA", "EXENTO"):
        assert despues_de_los_productos not in bloque
    assert lineas[-1].startswith("HOUEIA DOME")  # el último renglón antes de TOTAL ITEMS


def test_total_items_corta_el_bloque_pero_no_es_el_total():
    texto = "DESCRIPCION VALOR\nPAN 4,200\nTOTAL ITEMS: 1\nSUBTOTAL 4,200\nTOTAL 4,200"
    assert recortar_productos(texto) == "DESCRIPCION VALOR\nPAN 4,200"
    assert extraer_total_impreso(texto) == 4200


def test_total_items_sin_total_igual_recorta():
    """Si el OCR no leyó la línea del TOTAL, el bloque igual queda bien cortado."""
    texto = "DESCRIPCION VALOR\nPAN 4,200\nTOTAL ITEMS: 1"
    assert recortar_productos(texto) == "DESCRIPCION VALOR\nPAN 4,200"
    assert extraer_total_impreso(texto) is None


def test_total_items_no_es_el_total():
    """Antes, al llegar a "TOTAL ITEMS" se dejaba de buscar el TOTAL impreso."""
    # $135,504 es como el OCR leyó los $125,500 de esta factura: no cuadrará con la
    # suma de los ítems y se pedirá revisión, que es lo que debe pasar.
    assert extraer_total_impreso(FACTURA_4_MERKAMAX) == 135504
    assert (
        extraer_total_impreso("DESCRIPCION VALOR\nPAN 4,200\nTOTAL ITEMS: 1\nTOTAL 4,200") == 4200
    )


def test_instrucciones_explican_los_dos_formatos():
    assert "Una línea por producto" in INSTRUCCIONES
    assert "Multilínea" in INSTRUCCIONES
    assert "línea de ARRIBA" in INSTRUCCIONES
    assert "CANT" in INSTRUCCIONES
    assert "TOTAL ITEMS" in INSTRUCCIONES


# --- 2. Total exacto ---


def _arroz(leido_total: float, leido_unitario: float = 3990) -> ItemDetectado:
    return item_detectado(
        descripcion_impresa="ARROZ PREMIUN",
        nombre="Arroz premium",
        cantidad=1,
        precio_unitario=leido_unitario,
        precio_total=leido_total,
        categoria="granos_cereales",
    )


def _factura_3(monkeypatch, arroz: ItemDetectado):
    ocr_falso(monkeypatch, FACTURA_3_D1)
    items = [
        item_detectado(
            descripcion_impresa="AZUCAR BLANCA",
            nombre="Azúcar blanca",
            cantidad=1,
            precio_unitario=3190,
            precio_total=3190,
        ),
        item_detectado(
            descripcion_impresa="CLAVO ENTERO",
            nombre="Clavo entero",
            cantidad=1,
            precio_unitario=2200,
            precio_total=2200,
        ),
        arroz,
    ]
    return procesar_factura(imagen_factura(), lambda texto: items)


def test_factura_3_con_los_valores_leidos_marca_el_arroz_y_la_factura(monkeypatch):
    """Lo que el prompt pide ahora: devolver 3,990 y 3,905 tal como se leyeron."""
    resultado = _factura_3(monkeypatch, _arroz(leido_total=3905))

    assert [i.revisar for i in resultado.items] == [False, False, True]
    assert resultado.total_calculado == 9295
    assert resultado.requiere_revision is True  # antes salía ✓


def test_factura_3_aunque_gemini_cuadre_el_renglon_el_total_lo_delata(monkeypatch):
    """Lo que hacía Gemini antes: cambiar el precio unitario a 3,905 para que cuadrara.
    El renglón ya no se ve mal, pero la suma no da el TOTAL exacto."""
    resultado = _factura_3(monkeypatch, _arroz(leido_total=3905, leido_unitario=3905))

    assert not any(i.revisar for i in resultado.items)
    assert resultado.requiere_revision is True


def test_factura_3_bien_leida_queda_verificada(monkeypatch):
    resultado = _factura_3(monkeypatch, _arroz(leido_total=3990))
    assert resultado.total_calculado == 9380
    assert resultado.requiere_revision is False


def test_instrucciones_no_dejan_cambiar_precios_para_que_cuadren():
    assert "NO cambies ninguno para que cuadre" in INSTRUCCIONES
    assert "3,905" in INSTRUCCIONES


# --- 3. nombre_incierto ---


def test_nombre_incierto_es_parte_del_esquema_de_gemini():
    campos = RespuestaNormalizacion.model_json_schema()["$defs"]["ItemDetectado"]["properties"]
    assert "nombre_incierto" in campos


def test_nombre_incierto_por_defecto_false_en_facturas_viejas():
    """Las facturas guardadas antes de este campo se siguen pudiendo leer."""
    viejo = {
        "nombre": "Huevos",
        "cantidad": 1,
        "unidad": "unidad",
        "categoria": "carnes_pescados",
    }
    assert ItemPropuesto.model_validate(viejo).nombre_incierto is False


def test_instrucciones_piden_conservar_lo_legible():
    assert '"HUEVO DE cooo" -> "Huevos de c…"' in INSTRUCCIONES
    assert "nombre_incierto" in INSTRUCCIONES


# --- descripcion_impresa: lo impreso, sin corregir ---


@pytest.mark.parametrize("esquema", [RespuestaNormalizacion, RespuestaVision])
def test_descripcion_impresa_esta_en_los_dos_esquemas(esquema):
    item = esquema.model_json_schema()["$defs"]["ItemDetectado"]
    assert "descripcion_impresa" in item["properties"]
    assert "descripcion_impresa" in item["required"]
    # Antes que nombre: Gemini genera en ese orden, transcribe y luego normaliza.
    orden = list(item["properties"])
    assert orden.index("descripcion_impresa") < orden.index("nombre")


def test_descripcion_impresa_por_defecto_none_en_facturas_viejas():
    viejo = {"nombre": "Huevos", "cantidad": 1, "unidad": "unidad", "categoria": "otros"}
    assert ItemPropuesto.model_validate(viejo).descripcion_impresa is None


def test_instrucciones_de_vision_no_dejan_inventar_marcas():
    assert "SOLO de descripcion_impresa" in INSTRUCCIONES_VISION
    assert "nunca agregues una marca, un sabor, un tamaño" in INSTRUCCIONES_VISION
    # Los 4 casos reales de la factura de Surtimax aliado, como lo que NO hacer.
    for impreso, inventado in [
        ("BON YURT ZUCARITAS", "Kumis Alpina"),
        ("BIG COLA NARANJA", "Jugo Hit naranja"),
        ("TOALLAS PEQUEÑIN ALMENDRA", "Almendras"),
        ("PARMESAANO ALPINA", "Arequipe Alpina"),
    ]:
        assert f'"{impreso}" -> "{inventado}" (mal)' in INSTRUCCIONES_VISION


def test_las_dos_instrucciones_definen_descripcion_impresa():
    for instrucciones in (INSTRUCCIONES, INSTRUCCIONES_VISION):
        assert "descripcion_impresa: la descripción del producto tal como aparece" in instrucciones
        assert "derivado solo de descripcion_impresa" in instrucciones
