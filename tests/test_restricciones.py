import pytest

from app.preferences.models import Dieta
from app.recommendations.restricciones import (
    EXCEPCIONES,
    alergenos_en,
    grupos_en,
    violaciones_de_dieta,
)

TODAS = ["lacteos", "gluten", "huevo", "mani", "frutos_secos", "mariscos", "pescado", "soya"]


@pytest.mark.parametrize(
    ("texto", "alergias", "esperado"),
    [
        ("Arepa con queso campesino", ["lacteos"], {"lacteos"}),
        ("Arroz con camarones", ["mariscos", "pescado"], {"mariscos"}),
        ("Ensalada de atún", ["pescado"], {"pescado"}),
        ("Pan tajado", ["gluten"], {"gluten"}),
        ("Agua de panela", ["gluten"], set()),  # "panela" no es "pan"
        ("Quesito y lechita", ["lacteos"], {"lacteos"}),  # diminutivos
        ("Huevitos", ["huevo"], {"huevo"}),
        ("Pancitos", ["gluten"], {"gluten"}),
        ("Huevos pericos", ["huevo"], {"huevo"}),
        ("Salsa de maní", ["mani"], {"mani"}),
        ("Nueces caramelizadas", ["frutos_secos"], {"frutos_secos"}),
        ("Tofu salteado", ["soya"], {"soya"}),
        ("Arepa con queso", [], set()),  # sin alergias declaradas no se revisa nada
        ("Sudado de pollo con papa", ["lacteos", "gluten", "huevo"], set()),
    ],
)
def test_alergenos_en(texto, alergias, esperado):
    assert alergenos_en([texto], alergias) == esperado


# --- Excepciones ---


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        # Falsos positivos comunes: se exceptúan SOLO para el grupo indicado, y los
        # demás alérgenos que contienen se siguen detectando.
        ("Arroz con leche de coco", set()),
        ("Avena con leche de almendras", {"frutos_secos", "gluten"}),
        ("Batido con leche de soya", {"soya"}),
        ("Crema de ahuyama", set()),
        ("Crema de verduras", set()),
        ("Espaguetis en pasta de tomate", {"gluten"}),  # "espaguetis" sí es gluten
        ("Guiso con pasta de tomate", set()),
        ("Tostada con mantequilla de maní", {"gluten", "mani"}),
        ("Mantequilla de maní casera", {"mani"}),
        # La excepción solo quita esa frase: el resto del texto se sigue revisando.
        ("Crema de ahuyama con crema de leche", {"lacteos"}),
        ("Leche de coco y queso rallado", {"lacteos"}),
        ("Mantequilla de maní con mantequilla", {"lacteos", "mani"}),
    ],
)
def test_excepciones_no_ocultan_otros_alergenos(texto, esperado):
    assert alergenos_en([texto], TODAS) == esperado


def test_excepcion_en_un_texto_no_afecta_a_otro():
    assert alergenos_en(["Leche de coco", "Leche entera"], ["lacteos"]) == {"lacteos"}


def test_excepciones_son_de_grupos_existentes():
    from app.recommendations.restricciones import PALABRAS_CLAVE

    assert EXCEPCIONES.keys() <= PALABRAS_CLAVE.keys()


# --- Dieta ---


@pytest.mark.parametrize(
    ("texto", "dieta", "esperado"),
    [
        ("Sudado de pollo", Dieta.omnivora, set()),
        ("Sudado de pollo", Dieta.vegetariana, {"carnes"}),
        ("Carne de res desmechada", Dieta.vegetariana, {"carnes"}),
        ("Calentado con chorizo y tocineta", Dieta.vegetariana, {"carnes"}),
        ("Ensalada de atún", Dieta.vegetariana, {"pescado"}),
        ("Arroz con camarones", Dieta.vegetariana, {"mariscos"}),
        ("Arepa con queso y huevo", Dieta.vegetariana, set()),
        ("Hamburguesa de lenteja", Dieta.vegetariana, set()),
        ("Hamburguesa de res", Dieta.vegetariana, {"carnes"}),
        ("Carne de soya en salsa", Dieta.vegana, set()),
        ("Ensalada de atún", Dieta.pescetariana, set()),
        ("Arroz con camarones", Dieta.pescetariana, set()),
        ("Arroz con pollo", Dieta.pescetariana, {"carnes"}),
        ("Arepa con queso y huevo", Dieta.vegana, {"lacteos", "huevo"}),
        ("Yogur con miel", Dieta.vegana, {"lacteos", "miel"}),
        ("Agua de panela con limón y miel de panela", Dieta.vegana, set()),
        ("Arroz con leche de coco", Dieta.vegana, set()),
        ("Lentejas con arroz y plátano", Dieta.vegana, set()),
        ("Tres golpes con salsa", Dieta.vegana, set()),  # "tres" no es "res"
    ],
)
def test_violaciones_de_dieta(texto, dieta, esperado):
    assert violaciones_de_dieta([texto], dieta) == esperado


def test_grupos_en_sin_grupos():
    assert grupos_en(["Sudado de pollo"], ()) == set()
