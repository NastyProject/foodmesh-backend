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


DETERGENTE = {"nombre": "Detergente líquido", "categoria": "aseo_hogar", "cantidad": 1}


def test_es_alimento_se_calcula_de_la_categoria(client):
    leche = client.post("/inventario", json=LECHE).json()
    detergente = client.post("/inventario", json=DETERGENTE).json()
    assert leche["es_alimento"] is True
    assert detergente["es_alimento"] is False


def test_el_cliente_no_puede_fijar_es_alimento(client):
    item = client.post("/inventario", json={**DETERGENTE, "es_alimento": True}).json()
    assert item["es_alimento"] is False  # el campo se ignora


def test_cambiar_categoria_recalcula_es_alimento(client):
    item_id = client.post("/inventario", json=LECHE).json()["id"]

    respuesta = client.patch(f"/inventario/{item_id}", json={"categoria": "mascotas"})
    assert respuesta.json()["es_alimento"] is False


def test_filtro_solo_alimentos(client):
    client.post("/inventario", json=LECHE)
    client.post("/inventario", json=DETERGENTE)
    client.post("/inventario", json={**LECHE, "nombre": "Sin categoría", "categoria": None})

    todos = client.get("/inventario").json()
    alimentos = client.get("/inventario", params={"solo_alimentos": "true"}).json()
    assert len(todos) == 3
    assert sorted(i["nombre"] for i in alimentos) == ["Leche entera", "Sin categoría"]


def test_filtro_solo_alimentos_respeta_el_hogar(client):
    client.post("/inventario", json=LECHE)

    app.dependency_overrides[get_hogar_id] = lambda: OTRO_HOGAR
    assert client.get("/inventario", params={"solo_alimentos": "true"}).json() == []


def test_categoria_fuera_de_la_lista_es_rechazada(client):
    assert client.post("/inventario", json={**LECHE, "categoria": "leches"}).status_code == 422
    assert client.post("/inventario", json={**LECHE, "categoria": "aseo"}).status_code == 422
    assert client.get("/inventario").json() == []


def test_categoria_sigue_siendo_opcional(client):
    sin_categoria = {k: v for k, v in LECHE.items() if k != "categoria"}
    assert client.post("/inventario", json=sin_categoria).json()["categoria"] is None
    assert client.post("/inventario", json={**LECHE, "categoria": None}).status_code == 201


def test_frutos_secos_es_alimento(client):
    mani = client.post("/inventario", json={**LECHE, "categoria": "frutos_secos"}).json()
    assert mani["es_alimento"] is True


def test_actualizar_con_categoria_invalida(client):
    item_id = client.post("/inventario", json=LECHE).json()["id"]

    respuesta = client.patch(f"/inventario/{item_id}", json={"categoria": "juguetes"})
    assert respuesta.status_code == 422
    assert client.get(f"/inventario/{item_id}").json()["categoria"] == "lacteos"
