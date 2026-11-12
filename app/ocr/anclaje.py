"""Anclaje: lo que devuelve Gemini (modo texto) debe salir del texto que se le envió.

El prompt ya le pide no inventar, pero con un OCR malo Gemini completa: del código
"TIOAZE96300ZA" devolvió el EAN 7702963002498, y de "Ltda Yuca, o ENIMGM0O: 31.000"
sacó un producto "Yuca $31,000". Aquí se verifica en código:

- codigo: debe aparecer literalmente, como secuencia de dígitos, en el texto. Si no,
  se quita (null): un código inventado envenenaría el catálogo.
- precio_total o precio_unitario: al menos uno debe aparecer en el texto, en algún
  formato (16.950, 16,950, 16950). Si no, el ítem se marca revisar.
- descripcion_impresa: debe parecerse (rapidfuzz) a algún renglón del texto, o a
  varios renglones seguidos (las descripciones multilínea se devuelven en una sola
  línea). Si no, el ítem se descarta: no hay de dónde salió.

En el modo visión no se aplica: ahí Gemini lee la foto, no un texto.
"""

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.ocr.normalizacion import ItemDetectado, ItemPropuesto, a_propuesto

# Parecido mínimo (0 a 100, rapidfuzz.partial_ratio) entre descripcion_impresa y el
# texto. En las facturas reales, las descripciones copiadas (aun con letras
# corregidas: "YOGUR GRIEGO" por "YESURT GRIEGO") dieron 82 o más; las inventadas
# ("Kumis Alpina", "Leche entera"), 67 o menos.
UMBRAL_DESCRIPCION = 75
# Una descripción multilínea puede ocupar hasta estos renglones seguidos.
_RENGLONES_POR_DESCRIPCION = 4


@dataclass
class ItemsAnclados:
    items: list[ItemPropuesto]
    descartados: int  # ítems cuya descripción no aparece en el texto


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.upper()).strip()


def _ventanas(texto: str) -> list[str]:
    """Cada renglón y cada grupo de hasta _RENGLONES_POR_DESCRIPCION renglones seguidos."""
    renglones = [_normalizar(r) for r in texto.splitlines() if r.strip()]
    return [
        " ".join(renglones[i : i + largo])
        for largo in range(1, _RENGLONES_POR_DESCRIPCION + 1)
        for i in range(len(renglones) - largo + 1)
    ]


def _numeros(texto: str) -> set[int]:
    """Los números del texto en pesos, sin importar el formato: "16.950", "16,950" y
    "16950" dan 16950; "$ 29.500,00" y "29500.00" dan 29500."""
    numeros = set()
    for crudo in re.findall(r"\d[\d.,]*\d|\d", texto):
        numeros.add(int(re.sub(r"[.,]", "", crudo)))
        # Si termina en dos decimales ("29.500,00", "56.00"), también sin ellos.
        if centavos := re.fullmatch(r"(.+)[.,]\d{2}", crudo):
            numeros.add(int(re.sub(r"[.,]", "", centavos[1])))
    return numeros


def _anclada(descripcion: str | None, ventanas: list[str]) -> bool:
    if not descripcion or not descripcion.strip():
        return False
    buscada = _normalizar(descripcion)
    return any(fuzz.partial_ratio(buscada, ventana) >= UMBRAL_DESCRIPCION for ventana in ventanas)


def anclar(detectados: list[ItemDetectado], texto: str) -> ItemsAnclados:
    ventanas = _ventanas(texto)
    secuencias = re.findall(r"\d+", texto)
    numeros = _numeros(texto)
    items = []
    descartados = 0
    for detectado in detectados:
        if not _anclada(detectado.descripcion_impresa, ventanas):
            descartados += 1
            continue
        item = a_propuesto(detectado)
        cambios: dict = {}
        if item.codigo and not any(item.codigo in secuencia for secuencia in secuencias):
            cambios["codigo"] = None
        precios = [p for p in (item.precio_total, item.precio_unitario) if p is not None]
        if precios and not any(round(p) in numeros for p in precios):
            cambios["revisar"] = True
        items.append(item.model_copy(update=cambios) if cambios else item)
    return ItemsAnclados(items=items, descartados=descartados)
