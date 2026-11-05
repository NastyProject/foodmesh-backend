"""Revisión de alergias y dieta por palabras clave, como segunda barrera después del prompt.

La IA puede ignorar una instrucción, así que cada receta se revisa en código antes
de devolverla. Es una revisión conservadora: ante la duda, descarta. Para los falsos
positivos más comunes ("leche de coco" no es un lácteo) hay excepciones explícitas.

Cada grupo (lacteos, carnes, miel...) tiene sus palabras clave y sus excepciones.
Las excepciones de un grupo solo se quitan del texto al revisar ESE grupo: "mantequilla
de maní" deja de contar como lácteo, pero se sigue detectando como maní.
"""

import re

from app.ocr.recorte import normalizar
from app.preferences.models import Dieta

# Palabras sin tildes y en singular; el plural (-s, -es) y el diminutivo (-ito, -ita)
# se reconocen solos.
PALABRAS_CLAVE: dict[str, tuple[str, ...]] = {
    "lacteos": (
        "leche",
        "queso",
        "quesillo",
        "cuajada",
        "mantequilla",
        "crema",
        "yogur",
        "yogurt",
        "kumis",
        "suero costeno",
        "arequipe",
        "lacteo",
        "kefir",
        "ghee",
        "mozzarella",
        "parmesano",
        "requeson",
    ),
    "gluten": (
        "trigo",
        "harina de trigo",
        "pan",
        "pancito",
        "pasta",
        "espagueti",
        "spaghetti",
        "fideo",
        "macarron",
        "galleta",
        "cebada",
        "avena",  # casi siempre contaminada con trigo
        "centeno",
        "cerveza",
        "seitan",
        "cuscus",
        "apanado",
        "miga de pan",
        "tostada",
        "ponque",
        "bizcocho",
        "tortilla de harina",
    ),
    "huevo": ("huevo", "clara de huevo", "yema", "mayonesa", "merengue"),
    "mani": ("mani", "cacahuate", "cacahuete"),
    "frutos_secos": (
        "almendra",
        "nuez",
        "nueces",
        "avellana",
        "maranon",
        "pistacho",
        "macadamia",
        "pecana",
        "castana",
    ),
    "mariscos": (
        "marisco",
        "camaron",
        "langostino",
        "langosta",
        "cangrejo",
        "jaiba",
        "calamar",
        "pulpo",
        "mejillon",
        "almeja",
        "ostra",
        "piangua",
        "chipi chipi",
    ),
    "pescado": (
        "pescado",
        "atun",
        "salmon",
        "tilapia",
        "mojarra",
        "bagre",
        "trucha",
        "sardina",
        "bacalao",
        "robalo",
        "pargo",
        "anchoa",
        "bocachico",
    ),
    "soya": ("soya", "soja", "tofu", "edamame", "miso"),
    # Los siguientes no son alergias de la lista, sino grupos para revisar la dieta.
    "carnes": (
        "carne",
        "res",
        "cerdo",
        "pollo",
        "gallina",
        "pavo",
        "pato",
        "cordero",
        "conejo",
        "tocino",
        "tocineta",
        "chicharron",
        "chorizo",
        "salchicha",
        "salchichon",
        "butifarra",
        "longaniza",
        "morcilla",
        "jamon",
        "mortadela",
        "salami",
        "pechuga",
        "muslo",
        "costilla",
        "chuleta",
        "lomo",
        "pernil",
        "sobrebarriga",
        "bistec",
        "higado",
        "hamburguesa",
        "albondiga",
    ),
    "miel": ("miel",),
}

# Frases que contienen una palabra clave del grupo pero no son de ese grupo. Mismas
# reglas: sin tildes, en singular (el plural y el diminutivo se reconocen solos).
EXCEPCIONES: dict[str, tuple[str, ...]] = {
    "lacteos": (
        "leche de coco",
        "leche de almendra",  # sigue contando como frutos_secos
        "leche de soya",  # sigue contando como soya
        "leche de avena",  # sigue contando como gluten
        "leche de arroz",
        "mantequilla de mani",  # sigue contando como mani
        "mantequilla de cacao",
        "crema de ahuyama",  # si lleva crema de leche, "leche" la sigue delatando
        "crema de verdura",
        "crema de tomate",
        "crema de zanahoria",
        "crema de espinaca",
        "crema de champinon",
        "crema de arveja",
    ),
    "gluten": ("pasta de tomate", "pasta de ajo"),
    "carnes": (
        "carne de soya",  # sigue contando como soya
        "hamburguesa de lenteja",
        "hamburguesa de frijol",
        "hamburguesa de garbanzo",
        "hamburguesa vegetal",
    ),
    "miel": ("miel de panela", "miel de cana"),  # son de caña, no de abejas
}

# Qué grupos no puede tener cada dieta.
PROHIBIDOS_POR_DIETA: dict[Dieta, tuple[str, ...]] = {
    Dieta.omnivora: (),
    Dieta.pescetariana: ("carnes",),
    Dieta.vegetariana: ("carnes", "pescado", "mariscos"),
    Dieta.vegana: ("carnes", "pescado", "mariscos", "lacteos", "huevo", "miel"),
}


def _variantes(palabra: str) -> str:
    """Patrón de la palabra con plural y diminutivo: queso → queso(s), quesito(s)."""
    escapada = re.escape(palabra)
    if palabra[-1] in "aeo":
        escapada = rf"{re.escape(palabra[:-1])}(?:{palabra[-1]}|it[oa])"
    return rf"{escapada}(?:e?s)?"


def _patron(frases: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(_variantes(f) for f in frases) + r")\b")


_PATRONES = {grupo: _patron(palabras) for grupo, palabras in PALABRAS_CLAVE.items()}
_PATRONES_EXCEPCION = {grupo: _patron(frases) for grupo, frases in EXCEPCIONES.items()}


def grupos_en(textos: list[str], grupos: list[str] | tuple[str, ...]) -> set[str]:
    """Cuáles de los `grupos` aparecen en alguno de los textos."""
    contenido = normalizar(" \n ".join(textos)).lower()  # sin tildes y en minúsculas
    encontrados = set()
    for grupo in grupos:
        texto = contenido
        if grupo in _PATRONES_EXCEPCION:
            # Solo las excepciones de este grupo, y sobre una copia: los demás grupos
            # se revisan sobre el texto completo.
            texto = _PATRONES_EXCEPCION[grupo].sub(" ", texto)
        if _PATRONES[grupo].search(texto):
            encontrados.add(grupo)
    return encontrados


def alergenos_en(textos: list[str], alergias: list[str]) -> set[str]:
    """Cuáles de las alergias declaradas aparecen en los textos."""
    return grupos_en(textos, alergias)


def violaciones_de_dieta(textos: list[str], dieta: Dieta) -> set[str]:
    """Grupos prohibidos por la dieta que aparecen en los textos (vacío si cumple)."""
    return grupos_en(textos, PROHIBIDOS_POR_DIETA[dieta])


# --- Filtro del inventario antes de llamar a Gemini ---
#
# Si a Gemini le llega pollo que vence mañana con dieta vegetariana, el prompt le pide
# a la vez "aprovecha lo que vence" y "nada de carne": suele ganar lo primero. Por eso
# los ítems incompatibles ni se le envían. Además de las palabras clave sobre el nombre
# se usa la categoría, para nombres que no delatan el contenido ("Lomo fino" sí,
# "Bandeja x6 Zenú" no).

# Categorías que la dieta excluye por completo. pescetariana no excluye carnes_pescados
# porque la categoría mezcla carne y pescado: ahí decide el nombre.
CATEGORIAS_PROHIBIDAS_POR_DIETA: dict[Dieta, tuple[str, ...]] = {
    Dieta.omnivora: (),
    Dieta.pescetariana: (),
    Dieta.vegetariana: ("carnes_pescados",),
    Dieta.vegana: ("carnes_pescados", "lacteos"),
}
# Solo las alergias con una categoría propia. Pescado y mariscos están en
# carnes_pescados junto con el pollo y la res: excluir la categoría sería demasiado.
CATEGORIAS_PROHIBIDAS_POR_ALERGIA: dict[str, tuple[str, ...]] = {
    "lacteos": ("lacteos",),
    "frutos_secos": ("frutos_secos",),
}


def item_compatible(nombre: str, categoria: str | None, dieta: Dieta, alergias: list[str]) -> bool:
    """Si un ítem del inventario se puede usar en recetas con esa dieta y esas alergias."""
    if alergenos_en([nombre], alergias) or violaciones_de_dieta([nombre], dieta):
        return False
    prohibidas = set(CATEGORIAS_PROHIBIDAS_POR_DIETA[dieta])
    for alergia in alergias:
        prohibidas.update(CATEGORIAS_PROHIBIDAS_POR_ALERGIA.get(alergia, ()))
    if categoria not in prohibidas:
        return True
    # Los huevos se categorizan como carnes_pescados (así lo pide el prompt de facturas),
    # pero la dieta vegetariana los permite. Para vegana o alergia al huevo, las
    # palabras clave de arriba ya lo descartaron.
    return categoria == "carnes_pescados" and bool(grupos_en([nombre], ["huevo"]))
