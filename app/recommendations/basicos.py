"""Básicos de cocina: lo que se asume que todo hogar tiene (agua, sal, aceite, azúcar,
pimienta).

En una receta no aparecen como faltantes ni se toman del inventario, aunque estén:
nadie registra cuánta sal gasta, y sugerir "comprar sal" no aporta nada.
"""

import re

from app.ocr.recorte import normalizar

# Sin tildes y en minúsculas. Un nombre es básico si EMPIEZA por una de estas palabras:
# "Aceite vegetal 1 L", "Sal y pimienta al gusto", "Agua sin gas". \b evita que
# "salsa", "salchicha" o "aceitunas" cuenten como sal o aceite.
_BASICO = re.compile(r"^(?:agua|sal|aceite|azucar|pimienta)(?:e?s)?\b")
# "Agua de coco" o "agua de panela" no son agua: son otro ingrediente que hay que tener.
_NO_BASICO = re.compile(r"^aguas? de\b")


def es_basico(nombre: str) -> bool:
    texto = normalizar(nombre).lower().strip()
    return bool(_BASICO.match(texto)) and not _NO_BASICO.match(texto)
