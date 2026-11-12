"""Etapa 3: quitar datos personales del texto antes de enviarlo a un servicio externo.

Las cédulas solo se reconocen si van precedidas de una etiqueta (C.C., cédula,
documento...): un número suelto de 8-10 dígitos en una factura puede ser un
código de producto, y no queremos borrar información útil.
"""

import re
import unicodedata
from difflib import SequenceMatcher

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
    # Email con la @ mal leída ("correopruebaéhotmail.com"): se reconoce por el dominio
    # de un correo personal, también si el OCR leyó ".con".
    (
        re.compile(r"\S*(?:hotmail|gmail|outlook|yahoo|live|icloud)\.c[o0][mn]?\S*", re.IGNORECASE),
        "[EMAIL]",
    ),
    # Barrio y dirección del cliente: se borra el resto del renglón.
    # Sin \b al final: el OCR pega la etiqueta al dato ("DIRECCIONSCL 84 Bis", factura 16).
    (re.compile(r"\b(BARRIO|DIRECCI[OÓ]N)[^\n]*", re.IGNORECASE), r"\1: [DIRECCION]"),
    (re.compile(r"\bDIR\b\.?[ \t]*:[^\n]*", re.IGNORECASE), "DIR: [DIRECCION]"),
    # "Tarjeta No.: ****1133", "NO. TARJ; ... 3064": con esas etiquetas se borra el
    # resto del renglón, sin importar qué haya entre la etiqueta y los dígitos.
    (re.compile(r"\bTARJETA[ \t]*N[O0o°º]\b\.?[^\n]*", re.IGNORECASE), "[TARJETA]"),
    (re.compile(r"\bN[O0][.:]?[ \t]*TARJ\b[^\n]*", re.IGNORECASE), "[TARJETA]"),
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
    # Tarjeta: "TARJ ************1234", "Tarjeta: XXXX XXXX 1234", "TARJ. DEBITO **1234",
    # y las lecturas del OCR de "TARJ": "TAR):9999", "TARO: 1543", "TARI", "TAR]", "TAR|".
    # Después de TAR se exige uno de esos caracteres (y que no siga una letra): así no
    # se toma un producto como "TARRO 1250".
    (
        re.compile(
            r"(?<![A-Z])TAR(?:JETA|[JIOl1)\]|])(?![A-Z])\.?[^\n\d*Xx#]{0,20}[*Xx# -]*\d{4}(?!\d)",
            re.IGNORECASE,
        ),
        "[TARJETA]",
    ),
    # Número enmascarado sin etiqueta: "************1234"
    (re.compile(r"[*Xx#]{4,}[ -]?\d{4}(?!\d)"), "[TARJETA]"),
    # Datos de la transacción con datáfono: "Recibo: 001234", "Ápro: 267787", "RRN 123456789012",
    # "RRN-442167", "TRX: 2712 02 0183". RAN es como el OCR suele leer RRN.
    (
        re.compile(
            rf"\b(?:Recibo|RRN|RAN)\b\.?{_SEP}(?:No\.?|#)?{_SEP}[:.-]?{_SEP}\d{{4,}}"
            rf"|\bTRX\b\.?{_SEP}[:.]?{_SEP}\d[\d \t]{{2,}}\d"
            rf"|(?<!\w)[AÁ]pro(?:baci[oó]n)?\b\.?{_SEP}(?:No\.?|#)?{_SEP}[:.]?{_SEP}"
            r"(?=[A-Z]*\d)[A-Z\d]{4,}",
            re.IGNORECASE,
        ),
        "[TRANSACCION]",
    ),
    # Nombre de quien atendió: se borra el resto del renglón. "ATENDIDO POR: JUAN PEREZ",
    # "CAJERO 05 ANA", "VEND: ANA RUIZ", "VENDEDOR: ANA RUIZ".
    (
        # ATENDIDO solo: el OCR lee "Atendido Pur" (factura 20).
        re.compile(r"\b(ATENDIDO(?:[ \t]+P[OU]R)?|CAJER[OA]|VEND(?:EDOR)?)\b[^\n]*", re.IGNORECASE),
        r"\1: [NOMBRE]",
    ),
]

# "CLIENTE: <nombre> [CEDULA]": se borra el resto del renglón, salvo que sea
# "Consumidor Final" (con sus lecturas de OCR: "Consuuidor Final", "Consuaidor-Final")
# o el "undefined" que imprime el sistema del almacén cuando no hay cliente.
_CLIENTE = re.compile(r"\b(CLIENTE)\b[ \t]*[:.]?[ \t]*([^\n]*)", re.IGNORECASE)
_SIN_NOMBRE = ("CONSUMIDOR", "UNDEFINED")
_PARECIDO_SIN_NOMBRE = 0.7


def _sin_nombre(resto: str) -> bool:
    """True si lo que sigue a CLIENTE no es un nombre: solo marcadores que ya puso la
    anonimización ("[CEDULA]"), "Consumidor Final" o "undefined"."""
    palabras = re.findall(r"[A-Za-z]+", re.sub(r"\[[A-Z]+\]", " ", resto))
    return not palabras or any(
        SequenceMatcher(None, palabras[0].upper(), objetivo).ratio() >= _PARECIDO_SIN_NOMBRE
        for objetivo in _SIN_NOMBRE
    )


def _cliente(coincidencia: re.Match[str]) -> str:
    if _sin_nombre(coincidencia[2]):
        return coincidencia[0]
    return f"{coincidencia[1]}: [NOMBRE]"


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


# La etiqueta CLIENTE mal leída por el OCR ("Clánte", "Cl1ente"). Una palabra que se
# le parece puede ser un producto ("SALSA CALIENTE 3.500"), así que estas variantes
# solo cuentan al inicio del renglón (tras basura corta del OCR) y si el renglón no
# trae un precio ni un código: un producto siempre trae alguno de los dos.
_CLIENTE_OCR = re.compile(
    r"(?m)^(?P<prefijo>[^\w\n]*(?:\w{1,2}[^\w\n]+){0,2})(?P<etiqueta>C\w{4,7})\b"
    r"[ \t]*[:.]?[ \t]*(?P<resto>[^\n]*)"
)
_PARECIDO_CLIENTE = 0.7
_PRECIO_O_CODIGO = re.compile(r"\d{1,3}[.,]\d{3}(?!\d)|\d{8,}")


def _cliente_mal_leido(coincidencia: re.Match[str]) -> str:
    # Sin tildes y en mayúsculas: "Clánte" -> "CLANTE".
    etiqueta = unicodedata.normalize("NFKD", coincidencia["etiqueta"]).encode("ascii", "ignore")
    if (
        SequenceMatcher(None, etiqueta.decode().upper(), "CLIENTE").ratio() < _PARECIDO_CLIENTE
        or _PRECIO_O_CODIGO.search(coincidencia["resto"])
        or _sin_nombre(coincidencia["resto"])
    ):
        return coincidencia[0]
    return f"{coincidencia['prefijo']}{coincidencia['etiqueta']}: [NOMBRE]"


def anonimizar(texto: str) -> str:
    for patron, reemplazo in _PATRONES:
        texto = patron.sub(reemplazo, texto)
    texto = _CLIENTE.sub(_cliente, texto)
    texto = _CLIENTE_OCR.sub(_cliente_mal_leido, texto)
    return _PALABRA_LARGA.sub(lambda m: "[CUFE]" if _parece_hash(m[0]) else m[0], texto)
