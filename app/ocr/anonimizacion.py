"""Etapa 3: quitar datos personales del texto antes de enviarlo a un servicio externo.

Las cédulas solo se reconocen si van precedidas de una etiqueta (C.C., cédula,
documento...): un número suelto de 8-10 dígitos en una factura puede ser un
código de producto, y no queremos borrar información útil.
"""

import re

# Un número de documento, con o sin separadores de miles: 1.023.456.789, 52 123 456, 52123456
_NUMERO_DOCUMENTO = r"(?:\d{1,3}(?:[. ]\d{3}){1,3}|\d{6,10})(?!\d)"
# Separadores dentro de un mismo renglón: nunca saltar a la línea siguiente.
_SEP = r"[ \t]*"
# (?<!\d) y (?!\d) evitan tomar un pedazo de un número más largo (p. ej. un código de barras).
_SIN_DIGITOS_ALREDEDOR = r"(?<!\d){}(?!\d)"

# Un dígito o una letra que el OCR suele leer en lugar de un dígito (9→S, 0→O, 1→I/l, 8→B).
_DIGITO_OCR = r"[\dSOIlB]"

_PATRONES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[EMAIL]"),
    # CUFE con etiqueta: se borra el resto del renglón (el hash puede venir con errores de OCR).
    (re.compile(r"\bCUFE\b[^\n]*", re.IGNORECASE), "[CUFE]"),
    # NIT con etiqueta: "NIT 900.123.456-7", "Nit: 900123456-7", "N.I.T. 860007538".
    # Tolera basura de OCR entre la etiqueta y el número ("Nit*890.930.534") y letras
    # leídas en lugar de dígitos, incluso pegadas a la etiqueta ("NITS00276952-1").
    # El lookahead exige al menos 6 dígitos reales para no tomar una palabra cualquiera.
    (
        re.compile(
            rf"\bN\.?I\.?T\.?{_SEP}(?:No\.?|#)?[ \t:.*#°º-]*"
            rf"(?=(?:[^\d\n]{{0,3}}\d){{6}}){_DIGITO_OCR}(?:[., ]?{_DIGITO_OCR}){{5,11}}"
            rf"(?:{_SEP}-{_SEP}{_DIGITO_OCR})?(?![\w])",
            re.IGNORECASE,
        ),
        "[NIT]",
    ),
    # NIT sin etiqueta, reconocible por el dígito de verificación: 900.123.456-7
    (
        re.compile(_SIN_DIGITOS_ALREDEDOR.format(r"\d{3}\.?\d{3}\.?\d{3} ?- ?\d")),
        "[NIT]",
    ),
    # Cédula con etiqueta: "C.C. 1.023.456.789", "CC: 52123456", "Cédula 79.555.123"
    (
        re.compile(
            r"(?:\bC\. ?C\.?|\bCC\b|\bc[eé]dula(?: de ciudadan[ií]a)?|\bdocumento"
            r"|\bidentificaci[oó]n|\bdoc\.)"
            rf"{_SEP}(?:No\.?|N[°º]\.?|#)?{_SEP}[:.]?{_SEP}{_NUMERO_DOCUMENTO}",
            re.IGNORECASE,
        ),
        "[CEDULA]",
    ),
    # Celulares colombianos (10 dígitos, empiezan por 3) y fijos nuevos (60X + 7 dígitos),
    # con o sin +57 y separadores: 310 555 1234, +57 3105551234, (601) 555-1234
    (
        re.compile(
            _SIN_DIGITOS_ALREDEDOR.format(
                r"(?:\+?57[ -]?)?\(?(?:3\d{2}|60\d)\)?[ .-]?\d{3}[ .-]?\d{4}"
            )
        ),
        "[TELEFONO]",
    ),
    # Teléfonos con etiqueta en formato viejo: "Tel: 555 12 34", "PBX 6123456"
    (
        re.compile(
            r"\b(?:tel[eé]fono|tel|cel(?:ular)?|m[oó]vil|whatsapp|pbx)\.?[ \t]*[:.#]?[ \t]*"
            r"\+?\d[\d \t().-]{5,}\d",
            re.IGNORECASE,
        ),
        "[TELEFONO]",
    ),
    # Tarjeta: "TARJ ************1234", "Tarjeta: XXXX XXXX 1234", "TARJ. DEBITO **1234"
    (
        re.compile(r"\bTARJ(?:ETA)?\b\.?[^\n\d*Xx#]{0,20}[*Xx# -]*\d{4}(?!\d)", re.IGNORECASE),
        "[TARJETA]",
    ),
    # Número enmascarado sin etiqueta: "************1234"
    (re.compile(r"[*Xx#]{4,}[ -]?\d{4}(?!\d)"), "[TARJETA]"),
    # Datos de la transacción con datáfono: "Recibo: 001234", "Ápro: 267787", "RRN 123456789012",
    # "TRX: 2712 02 0183". RAN es como el OCR suele leer RRN.
    (
        re.compile(
            rf"\b(?:Recibo|RRN|RAN)\b\.?{_SEP}(?:No\.?|#)?{_SEP}[:.]?{_SEP}\d{{4,}}"
            rf"|\bTRX\b\.?{_SEP}[:.]?{_SEP}\d[\d \t]{{2,}}\d"
            rf"|(?<!\w)[AÁ]pro(?:baci[oó]n)?\b\.?{_SEP}(?:No\.?|#)?{_SEP}[:.]?{_SEP}"
            r"(?=[A-Z]*\d)[A-Z\d]{4,}",
            re.IGNORECASE,
        ),
        "[TRANSACCION]",
    ),
    # Nombre del cajero: se borra el resto del renglón. "ATENDIDO POR: JUAN PEREZ", "CAJERO 05 ANA"
    (
        re.compile(r"\b(ATENDIDO[ \t]+POR|CAJER[OA])\b[^\n]*", re.IGNORECASE),
        r"\1: [NOMBRE]",
    ),
]


# Pedazos de hash (CUFE) sin etiqueta. El OCR los parte en renglones y les mete letras
# que no son hexadecimales ("9fa2dóBo4oa3", "2674a0dO5391..."), así que no basta con
# buscar [0-9a-f]+: se evalúa cada palabra larga por separado.
_PALABRA_LARGA = re.compile(r"\S{12,}")
_MINIMO_HEX = 0.75  # fracción de caracteres alfanuméricos que deben ser hexadecimales
_MINIMO_LETRAS_HEX = 3  # letras a-f: distingue un hash de un número ("Res.000200/24")


def _parece_hash(palabra: str) -> bool:
    alfanumericos = [c for c in palabra if c.isalnum()]
    hex_ = [c for c in alfanumericos if c in "0123456789abcdefABCDEF"]
    letras_hex = [c for c in hex_ if c.isalpha()]
    return (
        any(c.isdigit() for c in alfanumericos)
        and len(letras_hex) >= _MINIMO_LETRAS_HEX
        and len(hex_) >= _MINIMO_HEX * len(alfanumericos)
    )


def anonimizar(texto: str) -> str:
    for patron, reemplazo in _PATRONES:
        texto = patron.sub(reemplazo, texto)
    return _PALABRA_LARGA.sub(lambda m: "[CUFE]" if _parece_hash(m[0]) else m[0], texto)
