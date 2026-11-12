"""¿El OCR leyó algo legible? Se mide después de Tesseract y antes de Gemini.

El enfoque de la foto (varianza del laplaciano) no basta: en las fotos originales del
compañero B, 3.jpeg (enfoque 461) y 4.jpeg (729) dieron texto basura, mientras que
20.jpeg (277) se leyó a medias. Lo que sí las separa es lo que leyó el OCR:

- confianza media de Tesseract en las palabras con 3 o más caracteres alfanuméricos;
- proporción de tokens legibles: palabras con vocales y consonantes en un orden
  plausible, o números con formato de precio o de código. Los fragmentos sueltos de
  1 o 2 caracteres ("a", "E,", "o") cuentan como no legibles: son el ruido típico de
  una foto que el OCR no entendió. Con las facturas reales: basura 0.26-0.28, leídas a
  medias 0.36-0.51, bien leídas 0.47-0.59.
"""

import re
import unicodedata
from dataclasses import dataclass

from app.ocr.extraccion import LecturaOCR

_VOCALES = set("AEIOU")
# Precio ("16.950", "$10.490", "29500.00") o código (4 a 14 dígitos).
_NUMERO = re.compile(r"^\$?(?:\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|\d+[.,]\d{2}|\d{4,14})$")
# Cantidades con unidad: "1100ML", "2.5L", "500G", "X6".
_CON_UNIDAD = re.compile(r"^(?:\d+(?:[.,]\d+)?(?:ML|M1|L|LT|G|GR|KG|UN|UND|U|CC|OZ)|X\d+)$")
_BORDES = ".,:;()|\"'!?-*“”»«/\\+=_~¡¿"
# Una palabra plausible no tiene más de 3 consonantes ni más de 2 vocales seguidas
# ("ENIMGM0O", "NAAA", "TUCZNE" no lo son; "ARANDANOS", "SUPERMERCADO" sí).
_MAX_CONSONANTES_SEGUIDAS = 3
_MAX_VOCALES_SEGUIDAS = 2
_MINIMO_ALFANUMERICOS = 3


@dataclass
class Legibilidad:
    confianza_media: float  # 0 a 100; 0 si no hay palabras para medir
    tokens_legibles: float  # 0 a 1
    tokens: int


def _normalizar(token: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", token).encode("ascii", "ignore").decode()
    return sin_tildes.upper().strip(_BORDES)


def es_token_legible(token: str) -> bool:
    t = _normalizar(token)
    if _NUMERO.match(t) or _CON_UNIDAD.match(t):
        return True
    if len(t) < _MINIMO_ALFANUMERICOS or not t.isalpha():
        return False
    vocales = sum(c in _VOCALES for c in t)
    if vocales in (0, len(t)):
        return False
    consonantes = max(map(len, re.findall(r"[^AEIOU]+", t)), default=0)
    seguidas = max(map(len, re.findall(r"[AEIOU]+", t)))
    return consonantes <= _MAX_CONSONANTES_SEGUIDAS and seguidas <= _MAX_VOCALES_SEGUIDAS


def _tokens(texto: str) -> list[str]:
    # Los marcadores de la anonimización ("[NIT]") no son texto leído: no cuentan.
    crudos = (t for t in texto.split() if not t.startswith("["))
    return [t for t in crudos if _normalizar(t)]


def medir_legibilidad(lectura: LecturaOCR) -> Legibilidad:
    tokens = _tokens(lectura.texto)
    confianzas = [
        confianza
        for palabra, confianza in lectura.palabras
        if sum(c.isalnum() for c in palabra) >= _MINIMO_ALFANUMERICOS
    ]
    return Legibilidad(
        confianza_media=sum(confianzas) / len(confianzas) if confianzas else 0.0,
        tokens_legibles=sum(map(es_token_legible, tokens)) / len(tokens) if tokens else 0.0,
        tokens=len(tokens),
    )


def es_legible(legibilidad: Legibilidad, min_confianza: float, min_tokens: float) -> bool:
    return (
        legibilidad.confianza_media >= min_confianza and legibilidad.tokens_legibles >= min_tokens
    )
