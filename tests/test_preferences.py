import pytest

from app.auth.dependencies import get_hogar_id
from app.main import app
from tests.conftest import HOGAR_TEST, OTRO_HOGAR

POR_DEFECTO = {
    "dieta": "omnivora",
    "alergias": [],
    "no_le_gusta": [],
    "porciones": 2,
    "tiempo_max_minutos": None,
}
VEGETARIANO = {
    "dieta": "vegetariana",
    "alergias": ["lacteos", "mani"],
    "no_le_gusta": ["cilantro", "berenjena"],
    "porciones": 4,
    "tiempo_max_minutos": 30,
}


def test_sin_preferencias_devuelve_los_valores_por_defecto(client):
    respuesta = client.get("/preferencias")
    assert respuesta.status_code == 200
    assert respuesta.json() == POR_DEFECTO
    assert "hogar_id" not in respuesta.json()


def test_guardar_y_leer(client):
    respuesta = client.put("/preferencias", json=VEGETARIANO)
    assert respuesta.status_code == 200
    assert respuesta.json() == VEGETARIANO
    assert client.get("/preferencias").json() == VEGETARIANO


def test_put_reemplaza_todo(client):
    client.put("/preferencias", json=VEGETARIANO)
    client.put("/preferencias", json={"dieta": "vegana"})  # lo demás vuelve al defecto

    assert client.get("/preferencias").json() == {**POR_DEFECTO, "dieta": "vegana"}


def test_un_hogar_no_ve_preferencias_de_otro(client):
    client.put("/preferencias", json=VEGETARIANO)

    app.dependency_overrides[get_hogar_id] = lambda: OTRO_HOGAR
    assert client.get("/preferencias").json() == POR_DEFECTO
    client.put("/preferencias", json={"dieta": "pescetariana"})

    app.dependency_overrides[get_hogar_id] = lambda: HOGAR_TEST
    assert client.get("/preferencias").json() == VEGETARIANO


def test_quita_repetidos_y_espacios(client):
    datos = {"alergias": ["gluten", "gluten"], "no_le_gusta": [" Cebolla ", "cebolla", "ajo"]}
    respuesta = client.put("/preferencias", json=datos).json()
    assert respuesta["alergias"] == ["gluten"]
    assert respuesta["no_le_gusta"] == ["Cebolla", "ajo"]


@pytest.mark.parametrize(
    "datos",
    [
        {"dieta": "carnivora"},
        {"alergias": ["lactosa"]},  # no está en la lista cerrada
        {"no_le_gusta": [f"ingrediente {i}" for i in range(21)]},  # máximo 20
        {"no_le_gusta": [""]},
        {"no_le_gusta": ["x" * 61]},
        {"porciones": 0},
        {"porciones": 13},
        {"tiempo_max_minutos": 0},
    ],
)
def test_validacion(client, datos):
    assert client.put("/preferencias", json=datos).status_code == 422
    assert client.get("/preferencias").json() == POR_DEFECTO
