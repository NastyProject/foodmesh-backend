"""Etapa 3: recortar el bloque de productos antes de anonimizar y enviar a Gemini.

Una factura tiene encabezado (almacén, NIT, dirección, cliente), el bloque de
productos y un pie (totales, medios de pago, CUFE). A Gemini solo le sirve el
bloque de productos, así que enviamos solo ese: menos datos personales que
podrían escaparse a la anonimización y menos ruido para el modelo.

El bloque va desde la línea de encabezado de columnas (DESCRIPCION / VALOR)
hasta la primera línea que empieza por TOTAL. Los nombres se comparan de forma
aproximada para tolerar errores de OCR ("DESCRIPC1ON", "T0TAL").
"""

import re
import unicodedata
from difflib import SequenceMatcher

# Palabras que identifican la línea de encabezado de columnas, con el parecido
# mínimo (0 a 1) que debe tener una palabra del OCR para contar como esa palabra.
_PALABRAS_ENCABEZADO = {"DESCRIPCION": 0.75, "VALOR": 0.8}
_PARECIDO_TOTAL = 0.8
# El OCR suele leer bordes y sombras del papel como basura al inicio de la línea
# ("4 TOTAL o 130,690"): se ignoran hasta este número de palabras cortas antes de TOTAL.
_BASURA_INICIAL = 3
_LARGO_BASURA = 2
# Un valor en pesos: con separador de miles ("130,690", "18.625") o sin él ("4500").
# Los lookarounds evitan tomar los centavos de "130.690,00" como otro número.
_VALOR = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+|\d+)(?![\d])")


def normalizar(texto: str) -> str:
    """Mayúsculas y sin tildes: "Descripción" -> "DESCRIPCION"."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.upper()


def _palabras(linea: str) -> list[str]:
    return re.findall(r"[A-Z0-9]+", normalizar(linea))


def _se_parece(palabra: str, objetivo: str, minimo: float) -> bool:
    return SequenceMatcher(None, palabra, objetivo).ratio() >= minimo


def _es_total(linea: str) -> bool:
    for palabra in _palabras(linea)[: _BASURA_INICIAL + 1]:
        if _se_parece(palabra, "TOTAL", _PARECIDO_TOTAL):
            return True
        if len(palabra) > _LARGO_BASURA:  # una palabra de verdad que no es TOTAL
            return False
    return False


def es_encabezado_columnas(linea: str) -> bool:
    if _es_total(linea):  # "TOTAL VALOR ..." es el pie, no el encabezado
        return False
    return any(
        _se_parece(palabra, objetivo, minimo)
        for palabra in _palabras(linea)
        for objetivo, minimo in _PALABRAS_ENCABEZADO.items()
    )


def indice_encabezado(lineas: list[str]) -> int | None:
    """Posición de la línea de encabezado de columnas, o None si no aparece."""
    return next((i for i, linea in enumerate(lineas) if es_encabezado_columnas(linea)), None)


def indice_total(lineas: list[str], desde: int = 0) -> int | None:
    """Posición de la primera línea de TOTAL a partir de `desde`, o None."""
    return next((i for i in range(desde, len(lineas)) if _es_total(lineas[i])), None)


def recortar_productos(texto: str) -> str | None:
    """Devuelve el encabezado de columnas y los renglones de productos, sin la
    línea de TOTAL. None si no encuentra los dos marcadores."""
    lineas = texto.splitlines()
    inicio = indice_encabezado(lineas)
    if inicio is None:
        return None
    fin = indice_total(lineas, inicio + 1)
    if fin is None:
        return None
    bloque = "\n".join(lineas[inicio:fin]).strip()
    # Si solo quedó el encabezado de columnas, no hay productos que recortar.
    return bloque if fin - inicio > 1 else None


def extraer_total_impreso(texto: str) -> float | None:
    """Valor de la línea de TOTAL (la misma que cierra el bloque de productos).

    La línea puede traer basura del OCR ("4 TOTAL o 130,690 1"), así que se toma
    el número más grande de la línea: el total siempre es mayor que esa basura.
    """
    lineas = texto.splitlines()
    inicio = indice_encabezado(lineas)
    fin = indice_total(lineas, inicio + 1 if inicio is not None else 0)
    if fin is None:
        return None
    valores = [int(re.sub(r"[.,]", "", m[1])) for m in _VALOR.finditer(lineas[fin])]
    return float(max(valores)) if valores else None
