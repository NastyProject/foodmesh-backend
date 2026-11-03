"""Categorías de productos y cuáles cuentan como alimento.

Lo usan el OCR (lista cerrada que se le pide a Gemini) y el inventario (para
separar los alimentos, que son los que importan para recetas y desperdicio).
"""

from typing import Literal

Categoria = Literal[
    "lacteos",
    "carnes_pescados",
    "frutas_verduras",
    "granos_cereales",
    "enlatados_conservas",
    "panaderia",
    "bebidas",
    "condimentos_especias",
    "frutos_secos",
    "snacks_dulces",
    "congelados",
    "aseo_hogar",
    "cuidado_personal",
    "mascotas",
    "otros",
]

# Lo que no es alimento. Cualquier otra categoría, o ninguna, se considera alimento.
CATEGORIAS_NO_ALIMENTO = frozenset({"aseo_hogar", "cuidado_personal", "mascotas"})


def es_alimento(categoria: str | None) -> bool:
    return categoria not in CATEGORIAS_NO_ALIMENTO
