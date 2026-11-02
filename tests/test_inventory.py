from app.auth.dependencies import get_hogar_id
from app.main import app
from tests.conftest import OTRO_HOGAR

LECHE = {"nombre": "Leche entera", "categoria": "lacteos", "cantidad": 2, "unidad": "l"}


def test_crear_y_listar(client):
    creado = client.post("/inventario", json=LECHE)
    assert creado.status_code == 201
    assert creado.json()["nombre"] == "Leche entera"
    assert "hogar_id" not in creado.json()

    lista = client.get("/inventario")
    assert lista.status_code == 200
    assert [i["nombre"] for i in lista.json()] == ["Leche entera"]


def test_cantidad_negativa_es_rechazada(client):
    respuesta = client.post("/inventario", json={**LECHE, "cantidad": -1})
    assert respuesta.status_code == 422


def test_actualizar_parcialmente(client):
    item_id = client.post("/inventario", json=LECHE).json()["id"]

    respuesta = client.patch(f"/inventario/{item_id}", json={"cantidad": 1})
    assert respuesta.status_code == 200
    assert respuesta.json()["cantidad"] == 1
    assert respuesta.json()["nombre"] == "Leche entera"  # lo demás no cambia


def test_eliminar(client):
    item_id = client.post("/inventario", json=LECHE).json()["id"]

    assert client.delete(f"/inventario/{item_id}").status_code == 204
    assert client.get(f"/inventario/{item_id}").status_code == 404


def test_un_hogar_no_ve_items_de_otro(client):
    item_id = client.post("/inventario", json=LECHE).json()["id"]

    app.dependency_overrides[get_hogar_id] = lambda: OTRO_HOGAR
    assert client.get(f"/inventario/{item_id}").status_code == 404
    assert client.get("/inventario").json() == []