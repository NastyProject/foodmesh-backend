from sqlalchemy import select

from app.auth.dependencies import get_hogar_id
from app.catalog.models import Producto
from app.core.db import SessionLocal
from app.core.storage import key_imagen_factura
from app.inventory.models import ItemInventario
from app.invoices.models import Factura
from app.invoices.router import get_normalizador
from app.main import app
from tests.conftest import (
    CODIGO_LECHE,
    HOGAR_TEST,
    OTRO_HOGAR,
    imagen_factura,
    item_detectado,
    ocr_falso,
)
from tests.factura_d1 import FACTURA_D1
from tests.factura_d1_real import FACTURA_D1_REAL

LECHE = {"nombre": "Leche entera 1.1 L", "categoria": "lacteos", "cantidad": 2, "unidad": "unidad"}


def normalizador_que_falla(texto: str):
    raise RuntimeError("Gemini no responde")


def subir(client, datos: bytes | None = None, tipo: str = "image/png"):
    datos = imagen_factura() if datos is None else datos
    return client.post("/facturas", files={"archivo": ("factura.png", datos, tipo)})


def test_subir_factura(client, almacenamiento):
    respuesta = subir(client)
    assert respuesta.status_code == 201
    factura = respuesta.json()
    assert factura["estado"] == "pendiente_validacion"
    assert factura["metodo"] == "texto"
    # Sin encabezado de columnas no hay bloque: se guardan (y se enviaron) solo las
    # líneas que parecen de productos.
    assert "LECHE" in factura["texto_ocr"] and "PAN" in factura["texto_ocr"]
    nombres = [i["nombre"] for i in factura["items_detectados"]]
    assert nombres == ["Leche entera 1.1 L", "Pan tajado"]
    assert "hogar_id" not in factura and "imagen_key" not in factura
    # La imagen quedó guardada con la key esperada
    assert almacenamiento.leer(key_imagen_factura(HOGAR_TEST, factura["id"]))


def test_tipo_de_archivo_no_permitido(client):
    respuesta = subir(client, b"%PDF-1.4 ...", tipo="application/pdf")
    assert respuesta.status_code == 415


def test_archivo_que_dice_ser_imagen_pero_no_lo_es(client):
    respuesta = subir(client, b"esto no es una imagen", tipo="image/jpeg")
    assert respuesta.status_code == 415


def test_imagen_demasiado_grande(client, monkeypatch):
    monkeypatch.setattr("app.invoices.router.TAMANO_MAXIMO", 1000)
    assert subir(client).status_code == 413


def test_factura_queda_en_error_si_falla_el_pipeline(client):
    app.dependency_overrides[get_normalizador] = lambda: normalizador_que_falla
    respuesta = subir(client)
    assert respuesta.status_code == 201
    factura = respuesta.json()
    assert factura["estado"] == "error"
    assert factura["error"]
    assert factura["items_detectados"] == []
    # Se guarda lo que se le envió a Gemini (las líneas de productos), no el texto completo.
    assert factura["texto_ocr"] == "SUPERMERCADO EL ROBLE\nLECHE ENTERA 4.500\nPAN TAJADO 6.200"


def test_listar_y_obtener(client):
    factura_id = subir(client).json()["id"]

    assert [f["id"] for f in client.get("/facturas").json()] == [factura_id]
    assert client.get(f"/facturas/{factura_id}").json()["id"] == factura_id


def test_confirmar_crea_items_y_borra_imagen(client, almacenamiento):
    factura_id = subir(client).json()["id"]

    respuesta = client.post(f"/facturas/{factura_id}/confirmar", json=[LECHE])
    assert respuesta.status_code == 201
    assert [i["nombre"] for i in respuesta.json()] == ["Leche entera 1.1 L"]

    assert [i["nombre"] for i in client.get("/inventario").json()] == ["Leche entera 1.1 L"]
    assert client.get(f"/facturas/{factura_id}").json()["estado"] == "confirmada"
    ruta_imagen = almacenamiento.directorio / key_imagen_factura(HOGAR_TEST, factura_id)
    assert not ruta_imagen.exists()


def test_confirmar_factura_en_error(client):
    """Si el pipeline falló, el usuario puede cargar los ítems a mano y confirmar."""
    app.dependency_overrides[get_normalizador] = lambda: normalizador_que_falla
    factura_id = subir(client).json()["id"]

    respuesta = client.post(f"/facturas/{factura_id}/confirmar", json=[LECHE])
    assert respuesta.status_code == 201
    assert client.get(f"/facturas/{factura_id}").json()["error"] is None


def test_confirmar_dos_veces(client):
    factura_id = subir(client).json()["id"]

    assert client.post(f"/facturas/{factura_id}/confirmar", json=[LECHE]).status_code == 201
    assert client.post(f"/facturas/{factura_id}/confirmar", json=[LECHE]).status_code == 409
    assert len(client.get("/inventario").json()) == 1  # no se duplicaron


def test_confirmar_con_item_invalido_no_crea_nada(client):
    factura_id = subir(client).json()["id"]

    items = [LECHE, {**LECHE, "cantidad": -1}]
    assert client.post(f"/facturas/{factura_id}/confirmar", json=items).status_code == 422
    assert client.get("/inventario").json() == []
    assert client.get(f"/facturas/{factura_id}").json()["estado"] == "pendiente_validacion"


def test_un_hogar_no_ve_facturas_de_otro(client):
    factura_id = subir(client).json()["id"]

    app.dependency_overrides[get_hogar_id] = lambda: OTRO_HOGAR
    assert client.get(f"/facturas/{factura_id}").status_code == 404
    assert client.get("/facturas").json() == []
    assert client.post(f"/facturas/{factura_id}/confirmar", json=[LECHE]).status_code == 404


def _producto(codigo: str) -> Producto | None:
    with SessionLocal() as db:
        return db.scalar(select(Producto).where(Producto.codigo == codigo))


def test_factura_guarda_encabezado_y_recorte(client, monkeypatch):
    ocr_falso(monkeypatch, FACTURA_D1)
    factura = subir(client).json()

    assert factura["supermercado"] == "D1"
    assert factura["fecha_compra"] == "2026-10-30"
    assert "recortada" not in factura  # es solo para la evaluación
    with SessionLocal() as db:
        assert db.get(Factura, factura["id"]).recortada is True


def test_items_detectados_traen_origen_y_revisar(client):
    def normalizador(texto):
        return [item_detectado(precio_unitario=4500, precio_total=6500)]

    app.dependency_overrides[get_normalizador] = lambda: normalizador
    [item] = subir(client).json()["items_detectados"]
    assert item["origen"] == "ia"
    assert item["revisar"] is True


def test_confirmar_guarda_el_producto_en_el_catalogo(client, factura_verificada):
    factura_id = subir(client).json()["id"]

    leche = {**LECHE, "nombre": "Leche entera Alquería 1.1 L", "codigo": CODIGO_LECHE}
    respuesta = client.post(f"/facturas/{factura_id}/confirmar", json=[leche])
    assert respuesta.status_code == 201

    producto = _producto(CODIGO_LECHE)
    assert producto.nombre == "Leche entera Alquería 1.1 L"  # lo que confirmó el usuario
    assert producto.categoria == "lacteos"
    with SessionLocal() as db:
        item = db.get(ItemInventario, respuesta.json()[0]["id"])
        assert item.producto_id == producto.id


def test_producto_conocido_usa_el_catalogo(client, factura_verificada):
    """Una segunda factura con el mismo código toma el nombre del catálogo, no el de la IA."""
    primera = subir(client).json()["id"]
    leche = {**LECHE, "nombre": "Leche Alquería 1.1 L", "categoria": "otros"}
    leche["codigo"] = CODIGO_LECHE
    client.post(f"/facturas/{primera}/confirmar", json=[leche])

    leche_detectada, pan_detectado = subir(client).json()["items_detectados"]
    assert leche_detectada["nombre"] == "Leche Alquería 1.1 L"
    assert leche_detectada["categoria"] == "otros"
    assert leche_detectada["origen"] == "catalogo"
    assert pan_detectado["origen"] == "ia"  # sin código


def test_confirmar_actualiza_el_catalogo(client, factura_verificada):
    for nombre in ("Leche entera 1.1 L", "Leche entera Alquería 1.1 L"):
        factura_id = subir(client).json()["id"]
        leche = {**LECHE, "nombre": nombre, "codigo": CODIGO_LECHE}
        assert client.post(f"/facturas/{factura_id}/confirmar", json=[leche]).status_code == 201

    assert _producto(CODIGO_LECHE).nombre == "Leche entera Alquería 1.1 L"


def test_confirmar_con_codigo_invalido(client):
    factura_id = subir(client).json()["id"]
    leche = {**LECHE, "codigo": "ABC123"}
    assert client.post(f"/facturas/{factura_id}/confirmar", json=[leche]).status_code == 422


def test_factura_real_d1_de_punta_a_punta(client, monkeypatch):
    """Sube la factura real de D1 por la API, con Tesseract y Gemini reemplazados:
    el OCR devuelve el texto real y un espía hace de Gemini."""
    textos_enviados = []

    def gemini_espia(texto):
        textos_enviados.append(texto)
        return [item_detectado(descripcion_impresa="DETERGENTE LT")]

    ocr_falso(monkeypatch, FACTURA_D1_REAL)
    app.dependency_overrides[get_normalizador] = lambda: gemini_espia
    respuesta = subir(client)
    assert respuesta.status_code == 201
    factura = respuesta.json()

    # El recorte encontró el bloque aunque las líneas de los marcadores traen basura
    # al inicio ("4 WI CAN UH VALOR U — CODIGO). DESCRIPCION...", "4 TOTAL o 130,690 1").
    [enviado] = textos_enviados
    lineas = enviado.splitlines()
    assert lineas[0].startswith("4 WI CAN UH VALOR")
    assert len(lineas) == 1 + 22  # encabezado de columnas + 22 productos
    assert "CANELA EN AST" in lineas[-1]
    assert "TOTAL" not in enviado
    with SessionLocal() as db:
        assert db.get(Factura, factura["id"]).recortada is True

    # Nada del encabezado ni del pie llega a Gemini.
    for dato in ("TARJ", "9419", "PEDRO", "PRUEBA", "NIT", "Nit", "BOGOTA", "152078", "267787"):
        assert dato not in enviado
    for pedazo_de_hash in ("9fa2d", "2674a0d", "818702e", "442257b", "500db7"):
        assert pedazo_de_hash not in enviado

    # Supermercado y fecha salen del encabezado con reglas locales.
    assert factura["supermercado"] == "D1"
    assert factura["fecha_compra"] == "2026-11-01"
    # El espía devolvió un solo ítem de 9,000: no cuadra con el TOTAL de 130,690.
    assert factura["total_impreso"] == 130690
    assert factura["total_calculado"] == 9000
    assert factura["requiere_revision"] is True

    # El texto completo que se guarda también queda anonimizado.
    for dato in ("9419", "PEDRO", "PRUEBA", "S00276952", "890.930.534", "818702e"):
        assert dato not in factura["texto_ocr"]


def test_factura_cuadrada_no_requiere_revision(client, monkeypatch):
    def normalizador(texto):
        return [
            item_detectado(
                descripcion_impresa="DETERGENTE LT",
                cantidad=1,
                precio_unitario=100000,
                precio_total=100000,
            ),
            item_detectado(
                descripcion_impresa="VARSO. BRILLA",
                nombre="Varsol",
                cantidad=1,
                precio_unitario=30690,
                precio_total=30690,
                categoria="aseo_hogar",
            ),
        ]

    ocr_falso(monkeypatch, FACTURA_D1_REAL)
    app.dependency_overrides[get_normalizador] = lambda: normalizador
    factura = subir(client).json()

    assert factura["requiere_revision"] is False
    assert [i["es_alimento"] for i in factura["items_detectados"]] == [True, False]


def test_confirmar_calcula_es_alimento(client):
    factura_id = subir(client).json()["id"]
    varsol = {"nombre": "Varsol", "categoria": "aseo_hogar", "cantidad": 1, "unidad": "unidad"}

    creados = client.post(f"/facturas/{factura_id}/confirmar", json=[LECHE, varsol]).json()
    assert [i["es_alimento"] for i in creados] == [True, False]
    alimentos = client.get("/inventario", params={"solo_alimentos": "true"}).json()
    assert [i["nombre"] for i in alimentos] == ["Leche entera 1.1 L"]


def test_confirmar_con_categoria_invalida_no_crea_nada(client):
    factura_id = subir(client).json()["id"]

    items = [LECHE, {**LECHE, "categoria": "leches", "codigo": CODIGO_LECHE}]
    assert client.post(f"/facturas/{factura_id}/confirmar", json=items).status_code == 422
    assert client.get("/inventario").json() == []
    assert _producto(CODIGO_LECHE) is None  # tampoco tocó el catálogo


def test_factura_sin_total_impreso_requiere_revision(client):
    # La imagen sintética no tiene línea de TOTAL: no se puede verificar.
    factura = subir(client).json()
    assert factura["total_impreso"] is None
    assert factura["requiere_revision"] is True
