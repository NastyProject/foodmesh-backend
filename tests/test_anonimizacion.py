import pytest

from app.ocr.anonimizacion import anonimizar


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("C.C. 1.023.456.789", "[CEDULA]"),
        ("CC: 52123456", "[CEDULA]"),
        ("Cédula de ciudadanía No. 79 555 123", "[CEDULA]"),
        ("NIT 900.123.456-7", "[NIT]"),
        ("Nit: 860007538-1", "[NIT]"),
        ("N.I.T. 800.197.268", "[NIT]"),
        ("900.123.456-7", "[NIT]"),
        ("Tel: 310 555 1234", "Tel: [TELEFONO]"),
        ("+57 3105551234", "[TELEFONO]"),
        ("(601) 555-1234", "[TELEFONO]"),
        ("PBX 6123456", "[TELEFONO]"),
        ("cliente@correo.com", "[EMAIL]"),
        ("factura.electronica@exito.com.co", "[EMAIL]"),
    ],
)
def test_quita_datos_personales(texto, esperado):
    assert anonimizar(texto) == esperado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        # NIT pegado a la etiqueta, con letras leídas en lugar de dígitos o con basura de OCR
        ("NITS00276952-1", "[NIT]"),
        ("Nit*890.930.534", "[NIT]"),
        ("NIT:900.276.952-1", "[NIT]"),
        ("NIT. 9OO276952 - 1", "[NIT]"),
        # Tarjeta (últimos 4 dígitos)
        ("TARJ ************4321", "[TARJETA]"),
        ("TARJETA DEBITO **4321", "[TARJETA]"),
        ("Tarjeta: XXXX XXXX XXXX 4321", "[TARJETA]"),
        ("************4321", "[TARJETA]"),
        # Datos de la transacción con datáfono
        ("Recibo: 001234", "[TRANSACCION]"),
        ("Apro: 12A456", "[TRANSACCION]"),
        ("RRN 123456789012", "[TRANSACCION]"),
        ("RAN: 123456789012", "[TRANSACCION]"),
        (
            "Recibo: 001234 Apro: 12A456 RRN 123456789012",
            "[TRANSACCION] [TRANSACCION] [TRANSACCION]",
        ),
        # Nombre del cajero
        ("ATENDIDO POR: MARIA PEREZ", "ATENDIDO POR: [NOMBRE]"),
        ("Atendido por Juan Gomez", "Atendido por: [NOMBRE]"),
        ("CAJERO: 0123 ANA RUIZ", "CAJERO: [NOMBRE]"),
        # CUFE, con etiqueta o como hash suelto
        ("CUFE: 3f9a2c4e5b6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f", "[CUFE]"),
        ("3f9a2c4e5b6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f", "[CUFE]"),
        ("A1B2C3D4E5F6A7B8C9D0E1F2", "[CUFE]"),
    ],
)
def test_quita_datos_de_pago_y_de_la_factura(texto, esperado):
    assert anonimizar(texto) == esperado


# Líneas exactas del OCR de una factura real de D1 (ver tests/factura_d1_real.py).
@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (
            ". DI SAS NITS00276952-1 Gran contribuyente y Agente | :",
            ". DI SAS [NIT] Gran contribuyente y Agente | :",
        ),
        (
            "OS Ñ - . FACTURADOR ELECTRONICO:E factura Cadena Nit*890.930.534 “|",
            "OS Ñ - . FACTURADOR ELECTRONICO:E factura Cadena [NIT] “|",
        ),
        (
            "o «| TARJ:9419 Recibo: 152078 RAN: 201884 - --..",
            "o «| [TARJETA] [TRANSACCION] [TRANSACCION] - --..",
        ),
        ("“| Ápro: 267787 a e", "“| [TRANSACCION] a e"),
        (". pa ATENDIDO POR: RAUL TATIS 871527 > o", ". pa ATENDIDO POR: [NOMBRE]"),
        (
            "Lo pa NUM ART. ENTREGADOS: 35, TRX: 2712 02 0183 |",
            "Lo pa NUM ART. ENTREGADOS: 35, [TRANSACCION] |",
        ),
        (
            "9fa2dóBo4oa3 4 pd 2674a0dO53917a7e4F1f86185e03fcd818702e",
            "[CUFE] 4 pd [CUFE]",
        ),
        ("442257b79638/500db700210056789 :", "[CUFE] :"),
        # Sin datos personales: deben quedar intactas.
        (
            "| : . Petenedor de IVA Res.000200/24 [TELEFONO] l",
            "| : . Petenedor de IVA Res.000200/24 [TELEFONO] l",
        ),
        (
            "| TARJ CRE/DEB $ 130,690 : e",  # el valor pagado, no el número de tarjeta
            "| TARJ CRE/DEB $ 130,690 : e",
        ),
        (
            ". $ Resolucion DIAN 18764094754937 de 20230624 Prefijo 6788",
            ". $ Resolucion DIAN 18764094754937 de 20230624 Prefijo 6788",
        ),
    ],
)
def test_lineas_de_factura_real_d1(texto, esperado):
    assert anonimizar(texto) == esperado


@pytest.mark.parametrize(
    "texto",
    [
        "7702001001234 LECHE ALQ ENT 1100ML 2 9.000 6",
        "7701234567890 PAN TAJADO BLANCO 1 6/500 6",
        "77020010012347701234567890",  # números largos sin letras: no son un hash
        "CAFE MOLIDO 500G 12.900",
        "NITRO BEBIDA 1.500",
        "GRAN RECIBO 2X1",
        "BEBE FACIAL 3.200",
        # Renglones reales de D1, con su basura de OCR
        ": | + 4 1UN 6,500 7700304928750 ARANDANOS--125 “3 6/500 6",
        "| 15 3 UN 2,150 (000077035684 GASEOSA COCA 6,450 A :",
        "++ 19 2UN 2,750 0706460249279 ALIMENTO HUHE 5,500 C A",
    ],
)
def test_no_borra_renglones_de_productos(texto):
    assert anonimizar(texto) == texto


def test_conserva_los_productos():
    factura = (
        "ALMACENES EL ROBLE NIT 900.123.456-7\n"
        "Tel: 601 555 1234\n"
        "Cliente: C.C. 1.023.456.789 cliente@correo.com\n"
        "7702001001234 LECHE ALQ ENT 1100ML 4.500\n"
        "BANANO 1.250 KG 3.125\n"
        "TOTAL 7.625\n"
    )
    assert anonimizar(factura) == (
        "ALMACENES EL ROBLE [NIT]\n"
        "Tel: [TELEFONO]\n"
        "Cliente: [CEDULA] [EMAIL]\n"
        "7702001001234 LECHE ALQ ENT 1100ML 4.500\n"
        "BANANO 1.250 KG 3.125\n"
        "TOTAL 7.625\n"
    )
