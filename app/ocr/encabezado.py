"""Supermercado y fecha de compra, con reglas locales.

Se hace aquí y no con Gemini para no enviarle el encabezado de la factura, que
es donde están el NIT, la dirección y los datos del cliente. Corre sobre el texto
crudo, antes de anonimizar: el NIT de la cadena es un dato de la empresa, no de la
persona, y es la pista más confiable de qué supermercado es.
"""

import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher

from app.ocr.recorte import indice_encabezado, normalizar

# NIT (sin dígito de verificación) -> cadena. Son públicos (RUES) y salen impresos
# en la factura.
_NITS = {
    "900276962": "D1",  # D1 S.A.S., antes Koba Colombia S.A.S.
    # Distribuciones Merkamax S.A.S. opera tiendas "Aliado Surtimax" (con el logo de
    # Surtimax): se guardan así, para distinguirlas de las Surtimax del Grupo Éxito.
    "901043020": "Surtimax (aliado)",
}
# El OCR confunde algunos dígitos con letras parecidas ("NITS00276952": la S es un 9):
# se traducen antes de comparar.
_LETRA_A_DIGITO = str.maketrans({"S": "9", "O": "0", "I": "1", "L": "1", "B": "8"})
# 9 dígitos (o letras de esas), con o sin separadores: 900.276.962, S00276952.
# Sin un dígito pegado antes ni después, para no tomar 9 dígitos de un EAN.
_CANDIDATO_NIT = re.compile(r"(?<!\d)([\dSOILB](?:[., ]?[\dSOILB]){8})(?!\d)")
# Al menos estos dígitos de verdad: "SOLIS BOLIO" no es un NIT.
_MINIMO_DIGITOS_NIT = 6
# Hasta un dígito distinto: el OCR de la factura real de D1 leyó 900276952 por 900276962.
_DIGITOS_DISTINTOS_NIT = 1

# Variantes que el OCR produce y que no se pueden escribir como una palabra fija.
# "D1 SAS" sale como "DI SAS", "Dl SAS" o "pi sas"; se exige el SAS para no tomar
# cualquier "DI".
_SUPERMERCADOS_OCR = {r"\b[DP][1IL][ \t]*S\.?[ \t]*A\.?[ \t]*S\b": "D1"}
# Nombre que aparece en la factura (sin tildes, mayúsculas) -> nombre que guardamos.
# Incluye la razón social, que a veces es lo único legible (D1 es Koba Colombia).
_SUPERMERCADOS = {
    "D1": "D1",
    "KOBA": "D1",
    # "ARA" suelto no: en el texto basura de una foto ilegible aparecía "ara" y se
    # detectaba Ara. Se exige "TIENDAS ARA" o la razón social.
    "TIENDAS ARA": "Ara",
    "JERONIMO MARTINS": "Ara",
    "EXITO": "Éxito",
    "CARULLA": "Carulla",
    "SURTIMAX": "Surtimax",
    "MERKAMAX": "Surtimax (aliado)",
    "OLIMPICA": "Olímpica",
    "JUMBO": "Jumbo",
    "METRO": "Metro",
    "CENCOSUD": "Jumbo",
    "ALKOSTO": "Alkosto",
    "MAKRO": "Makro",
    "COLSUBSIDIO": "Colsubsidio",
    "ISIMO": "Isimo",
    "ZAPATOCA": "Zapatoca",
    # No es un supermercado sino una tienda de variedades, pero vende alimentos y el
    # campo se llama igual: se guarda como "Dollarcity".
    "DOLLARCITY": "Dollarcity",
    "DOLLAR CITY": "Dollarcity",
}
# Los nombres de una sola palabra de al menos este largo se aceptan con errores de
# OCR ("MERKAMAR" por MERKAMAX). Los cortos ("ARA", "D1") solo exactos: con tan pocas
# letras, el parecido aproximado confunde cualquier palabra.
_LARGO_MINIMO_APROXIMADO = 6
_PARECIDO_NOMBRE = 0.85
# Si no hay encabezado de columnas, el nombre del almacén se busca en estas primeras líneas.
_LINEAS_ENCABEZADO = 10

# 30/10/2026, 30-10-26, 30.10.2026 (día primero, como en Colombia) y 2026/10/30, 2026-10-30.
_FECHA_DMA = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})(?!\d)")
_FECHA_AMD = re.compile(r"(?<!\d)(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})(?!\d)")
# Renglones con la fecha de la compra: "FECHA: 2026-11-08", "Generacion: 2026/11/08".
_ETIQUETA_FECHA = re.compile(r"\b(?:FECHA|GENERACION)\b")
# Renglones con fechas que no son de la compra: la autorización de numeración de la
# DIAN, su vigencia y la resolución (la factura 4 tomaba "autorización ... 2026-05-30";
# Alkosto trae "Res No 0008527 Ago. 24 2.010").
_FECHA_QUE_NO_ES_DE_COMPRA = re.compile(r"AUTORIZ|VIGEN|RESOLU|NUMERACI|\bRES\b")


@dataclass
class Encabezado:
    supermercado: str | None
    fecha_compra: date | None


def _por_nit(texto: str) -> str | None:
    """Cadena cuyo NIT aparece en el texto, tolerando errores de OCR."""
    for coincidencia in _CANDIDATO_NIT.finditer(normalizar(texto)):
        crudo = re.sub(r"[., ]", "", coincidencia[1])
        if sum(c.isdigit() for c in crudo) < _MINIMO_DIGITOS_NIT:
            continue
        digitos = crudo.translate(_LETRA_A_DIGITO)
        for nit, cadena in _NITS.items():
            if sum(a != b for a, b in zip(digitos, nit, strict=True)) <= _DIGITOS_DISTINTOS_NIT:
                return cadena
    return None


def _por_nombre(zona: str) -> str | None:
    patrones = _SUPERMERCADOS_OCR | {
        rf"\b{re.escape(nombre)}\b": canonico for nombre, canonico in _SUPERMERCADOS.items()
    }
    for patron, canonico in patrones.items():
        if re.search(patron, zona):
            return canonico
    # Segunda pasada, aproximada ("MERKAMAR", "NRA JLRONIMO MIRTINS"): se compara cada
    # nombre con cada grupo de tantas palabras seguidas como tenga el nombre. Solo
    # nombres largos: con pocas letras, el parecido aproximado confunde cualquier cosa.
    palabras = re.findall(r"[A-Z0-9]+", zona)
    for nombre, canonico in _SUPERMERCADOS.items():
        if len(nombre.replace(" ", "")) < _LARGO_MINIMO_APROXIMADO:
            continue
        largo = nombre.count(" ") + 1
        grupos = (" ".join(palabras[i : i + largo]) for i in range(len(palabras) - largo + 1))
        if any(
            SequenceMatcher(None, grupo, nombre).ratio() >= _PARECIDO_NOMBRE for grupo in grupos
        ):
            return canonico
    return None


def _por_dominio(texto: str) -> str | None:
    """Cadena cuyo dominio aparece en el texto: "alkosto.com/politicas", o el email de
    la tienda con la @ mal leída ("vezclientegalkosto.con.co"). Un producto nunca
    lleva ".com", así que se puede buscar en todo el texto. Solo con nombres largos y
    de una palabra: "ara.com" aparecería dentro de "para.com"."""
    normalizado = normalizar(texto)
    for nombre, canonico in _SUPERMERCADOS.items():
        if " " in nombre or len(nombre) < _LARGO_MINIMO_APROXIMADO:
            continue
        if re.search(rf"{re.escape(nombre)}\.C[O0][MN]?\b", normalizado):
            return canonico
    return None


def detectar_supermercado(texto: str) -> str | None:
    """Por NIT o por el dominio de la cadena (en todo el texto) y, si no, por nombre
    (solo en el encabezado: un producto como "ARA ARROZ" o "Quesillo Alkosto" no debe
    contar)."""
    if cadena := _por_nit(texto) or _por_dominio(texto):
        return cadena
    lineas = texto.splitlines()
    fin = indice_encabezado(lineas)
    return _por_nombre(
        normalizar("\n".join(lineas[: fin if fin is not None else _LINEAS_ENCABEZADO]))
    )


def _fecha_valida(anio: int, mes: int, dia: int) -> date | None:
    if anio < 100:
        anio += 2000
    try:
        fecha = date(anio, mes, dia)
    except ValueError:
        return None
    # Descarta lecturas absurdas (errores de OCR, fechas muy lejanas).
    return fecha if 2000 <= fecha.year <= date.today().year + 1 else None


def _fechas_del_renglon(linea: str) -> list[date]:
    candidatas = [(m.start(), int(m[3]), int(m[2]), int(m[1])) for m in _FECHA_DMA.finditer(linea)]
    candidatas += [(m.start(), int(m[1]), int(m[2]), int(m[3])) for m in _FECHA_AMD.finditer(linea)]
    fechas = (_fecha_valida(anio, mes, dia) for _, anio, mes, dia in sorted(candidatas))
    return [fecha for fecha in fechas if fecha]


def detectar_fecha(texto: str, hoy: date | None = None) -> date | None:
    """La fecha de la compra.

    Primero, la primera fecha válida en un renglón con etiqueta (FECHA, Generacion).
    Si no hay ninguna etiquetada, la más reciente del texto que no sea futura: las
    otras fechas de una factura (resolución, inicio de la numeración) son anteriores
    a la compra, y las futuras son el fin de la vigencia. En los dos casos se ignoran
    los renglones de la resolución, la autorización de numeración y su vigencia.
    """
    hoy = hoy or date.today()
    renglones = [
        linea
        for linea in texto.splitlines()
        if not _FECHA_QUE_NO_ES_DE_COMPRA.search(normalizar(linea))
    ]
    for linea in renglones:
        if _ETIQUETA_FECHA.search(normalizar(linea)) and (fechas := _fechas_del_renglon(linea)):
            return fechas[0]
    pasadas = [fecha for linea in renglones for fecha in _fechas_del_renglon(linea) if fecha <= hoy]
    return max(pasadas, default=None)


def extraer_encabezado(texto: str) -> Encabezado:
    return Encabezado(supermercado=detectar_supermercado(texto), fecha_compra=detectar_fecha(texto))
