"""Protección del catálogo (punto 7) y respaldo con visión (punto 8)."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.catalog.models import Producto
from app.catalog.service import es_gtin_valido
from app.core.db import SessionLocal
from app.governance.models import RegistroAuditoria
from app.governance.service import hash_sub
from app.inventory.models import ItemInventario
from app.invoices.models import EstadoFactura, Factura
from app.invoices.router import get_normalizador, get_normalizador_imagen
from app.main import app
from app.ocr.normalizacion import (
    INSTRUCCIONES,
    INSTRUCCIONES_VISION,
    RespuestaNormalizacion,
    RespuestaVision,
    normalizar_imagen_items,
    tipo_de_imagen,
)
from app.ocr.pipeline import procesar_factura_con_imagen
from tests.conftest import (
    CODIGO_LECHE,
    HOGAR_TEST,
    ITEMS_FALSOS,
    PREFIJO_CODIGO_TEST,
    SUB_OTRO,
    SUB_SEGUNDO_MIEMBRO,
    SUB_TEST,
    actuar_como,
    crear_usuario,
    imagen_factura,
    item_detectado,
    ocr_falso,
)
from tests.facturas_reales import FACTURA_4_MERKAMAX, FACTURA_5_D1
from tests.test_invoices import LECHE, normalizador_que_falla, subir

# Otro EAN-13 válido con el prefijo de los tests (para el código que "escribe" el usuario).
OTRO_CODIGO = PREFIJO_CODIGO_TEST + "000000029"


def _producto(codigo: str) -> Producto | None:
    with SessionLocal() as db:
        return db.scalar(select(Producto).where(Producto.codigo == codigo))


def _confirmar(client, factura_id: int, codigo: str = CODIGO_LECHE):
    leche = {**LECHE, "nombre": "Leche Alquería 1.1 L", "codigo": codigo}
    respuesta = client.post(f"/facturas/{factura_id}/confirmar", json=[leche])
    assert respuesta.status_code == 201
    return respuesta.json()[0]


def _usar_normalizador(items):
    app.dependency_overrides[get_normalizador] = lambda: lambda texto: items


# --- 7. Dígito de control GTIN ---


@pytest.mark.parametrize(
    "codigo",
    [
        # EAN-13 reales de las facturas de noviembre.
        "7700304280650",
        "7702603019160",
        "7702432759756",
        "8719200259232",
        CODIGO_LECHE,
        OTRO_CODIGO,
        "96385074",  # EAN-8
        "036000291452",  # UPC-12
        "10012345678902",  # GTIN-14
    ],
)
def test_gtin_valido(codigo):
    assert es_gtin_valido(codigo)


@pytest.mark.parametrize(
    "codigo",
    [
        "7700304973617",  # factura 2 (NACHOS): un dígito mal leído por el OCR
        "770101358245",  # factura 4 (Ranchera): 12 dígitos leídos de "AroL1o13s8z45"
        "7702001001235",  # dígito de control cambiado
        "4011",  # PLU: no es un GTIN, no se aprende
        "77020010012",  # largo que no existe
        "77O2001001234",
    ],
)
def test_gtin_invalido(codigo):
    assert not es_gtin_valido(codigo)


# --- 7. El catálogo solo aprende de facturas confiables ---


def test_aprende_con_total_verificado_y_gtin_valido(client, factura_verificada):
    factura = subir(client).json()
    assert factura["requiere_revision"] is False

    item = _confirmar(client, factura["id"])
    assert _producto(CODIGO_LECHE).nombre == "Leche Alquería 1.1 L"
    with SessionLocal() as db:
        assert db.get(ItemInventario, item["id"]).producto_id is not None


def test_no_aprende_si_la_factura_requiere_revision(client):
    # La imagen sintética no trae TOTAL: no se puede verificar.
    factura = subir(client).json()
    assert factura["requiere_revision"] is True

    item = _confirmar(client, factura["id"])
    assert _producto(CODIGO_LECHE) is None
    with SessionLocal() as db:
        # El ítem sí entra al inventario; solo no se asocia al catálogo.
        assert db.get(ItemInventario, item["id"]).producto_id is None


@pytest.mark.parametrize(
    "cambios",
    [
        # El renglón no cuadra (2 × 4,000 no es 9,000), aunque el total sí.
        {"precio_unitario": 4000},
        {"nombre_incierto": True},
    ],
)
def test_no_aprende_items_marcados(client, factura_verificada, cambios):
    _usar_normalizador([item_detectado(codigo=CODIGO_LECHE, **cambios), ITEMS_FALSOS[1]])
    factura = subir(client).json()
    assert factura["requiere_revision"] is False

    _confirmar(client, factura["id"])
    assert _producto(CODIGO_LECHE) is None


def test_no_aprende_codigos_con_digito_de_control_invalido(client, factura_verificada):
    invalido = PREFIJO_CODIGO_TEST + "000000011"
    assert not es_gtin_valido(invalido)
    _usar_normalizador([item_detectado(codigo=invalido), ITEMS_FALSOS[1]])
    factura = subir(client).json()

    _confirmar(client, factura["id"], codigo=invalido)
    assert _producto(invalido) is None


def test_no_aprende_codigos_que_no_detecto_el_ocr(client, factura_verificada):
    """Un código escrito a mano al confirmar no viene de la factura: no se aprende."""
    factura = subir(client).json()
    _confirmar(client, factura["id"], codigo=OTRO_CODIGO)
    assert _producto(OTRO_CODIGO) is None


def test_factura_merkamax_con_ean_corridos_no_envenena_el_catalogo(client, monkeypatch):
    """Caso real: los EAN quedaron corridos un producto (el del pan, en el Nesquik).
    Como el TOTAL no cuadra, la factura pide revisión y no se aprende ningún código."""
    ocr_falso(monkeypatch, FACTURA_4_MERKAMAX)
    pan_con_codigo_del_nesquik = PREFIJO_CODIGO_TEST + "000000036"
    _usar_normalizador(
        [
            item_detectado(
                nombre="Pan pequeño Comapan",
                codigo=pan_con_codigo_del_nesquik,
                cantidad=1,
                precio_unitario=4200,
                precio_total=4200,
                categoria="panaderia",
            )
        ]
    )
    factura = subir(client).json()
    assert factura["supermercado"] == "Surtimax (aliado)"
    assert factura["requiere_revision"] is True

    _confirmar(client, factura["id"], codigo=pan_con_codigo_del_nesquik)
    assert _producto(pan_con_codigo_del_nesquik) is None


def test_nombre_incierto_se_expone_en_los_items_detectados(client):
    _usar_normalizador([item_detectado(nombre="Huevos de c…", nombre_incierto=True)])
    [item] = subir(client).json()["items_detectados"]
    assert item["nombre"] == "Huevos de c…"
    assert item["nombre_incierto"] is True


# --- 8. Respaldo con visión ---


class VisionEspia:
    """Hace de Gemini con visión: guarda las imágenes que recibió y devuelve `items` y
    el total que "leyó" en la foto (por defecto, el que cuadra con ITEMS_FALSOS)."""

    def __init__(self, items=None, total_impreso=15200):
        self.items = items if items is not None else ITEMS_FALSOS
        self.total_impreso = total_impreso
        self.imagenes = []

    def __call__(self, imagen):
        self.imagenes.append(imagen)
        return RespuestaVision(items=self.items, total_impreso=self.total_impreso)


@pytest.fixture
def vision():
    espia = VisionEspia()
    app.dependency_overrides[get_normalizador_imagen] = lambda: espia
    return espia


def reprocesar(client, factura_id, body=None):
    body = {"acepto_enviar_imagen": True} if body is None else body
    return client.post(f"/facturas/{factura_id}/reprocesar-con-imagen", json=body)


@pytest.mark.parametrize("body", [{}, {"acepto_enviar_imagen": False}, {"acepto": True}])
def test_reprocesar_sin_autorizacion_da_422(client, vision, body):
    factura_id = subir(client).json()["id"]

    assert reprocesar(client, factura_id, body).status_code == 422
    assert vision.imagenes == []  # la foto no salió


def test_reprocesar_sin_body_da_422(client, vision):
    factura_id = subir(client).json()["id"]
    respuesta = client.post(f"/facturas/{factura_id}/reprocesar-con-imagen")
    assert respuesta.status_code == 422


def test_reprocesar_con_imagen(client, vision, factura_verificada):
    # El texto no resolvió la factura: Gemini devolvió un solo ítem.
    _usar_normalizador([ITEMS_FALSOS[1]])
    imagen = imagen_factura(["UNA FACTURA DIFICIL"])
    factura = subir(client, imagen).json()
    assert factura["requiere_revision"] is True
    assert factura["metodo"] == "texto"

    respuesta = reprocesar(client, factura["id"])
    assert respuesta.status_code == 200
    datos = respuesta.json()

    assert vision.imagenes == [imagen]  # la foto guardada, tal cual
    assert datos["metodo"] == "vision"
    assert [i["nombre"] for i in datos["items_detectados"]] == ["Leche entera 1.1 L", "Pan tajado"]
    # Se verifica contra el TOTAL que leyó la visión en la foto.
    assert datos["total_impreso"] == 15200
    assert datos["total_calculado"] == 15200
    assert datos["requiere_revision"] is False
    assert client.get(f"/facturas/{factura['id']}").json()["metodo"] == "vision"

    # Queda en la auditoría, sin el sub en claro.
    with SessionLocal() as db:
        [registro] = db.scalars(
            select(RegistroAuditoria).where(
                RegistroAuditoria.accion == "factura_reprocesada_con_imagen",
                RegistroAuditoria.usuario_sub_hash == hash_sub(SUB_TEST),
            )
        ).all()
    assert registro.detalle == {
        "factura_id": factura["id"],
        "acepto_enviar_imagen": True,
        "items": 2,
    }
    assert SUB_TEST not in str(registro.detalle)


def test_reprocesar_una_factura_en_error(client, vision):
    app.dependency_overrides[get_normalizador] = lambda: normalizador_que_falla
    factura = subir(client).json()
    assert factura["estado"] == "error"

    datos = reprocesar(client, factura["id"]).json()
    assert datos["estado"] == "pendiente_validacion"
    assert datos["error"] is None
    assert len(datos["items_detectados"]) == 2


def test_no_se_reprocesa_una_factura_confirmada(client, vision):
    factura_id = subir(client).json()["id"]
    client.post(f"/facturas/{factura_id}/confirmar", json=[LECHE])

    assert reprocesar(client, factura_id).status_code == 409
    assert vision.imagenes == []


def test_no_se_reprocesa_si_la_imagen_ya_no_esta(client, vision, almacenamiento):
    factura_id = subir(client).json()["id"]
    with SessionLocal() as db:
        almacenamiento.borrar(db.get(Factura, factura_id).imagen_key)

    respuesta = reprocesar(client, factura_id)
    assert respuesta.status_code == 409
    assert "imagen" in respuesta.json()["detail"]


def test_si_falla_la_vision_responde_503_y_no_cambia_la_factura(client):
    def vision_que_falla(imagen):
        raise RuntimeError("Gemini no responde")

    app.dependency_overrides[get_normalizador_imagen] = lambda: vision_que_falla
    factura = subir(client).json()

    assert reprocesar(client, factura["id"]).status_code == 503
    despues = client.get(f"/facturas/{factura['id']}").json()
    assert despues["metodo"] == "texto"
    assert despues["items_detectados"] == factura["items_detectados"]


def test_si_se_confirma_mientras_responde_gemini_no_la_pisa(client):
    """La factura se confirma en otra petición mientras Gemini procesa la imagen: el
    reproceso no debe devolverla a pendiente ni cambiar sus ítems."""
    factura = subir(client).json()

    def vision_lenta(imagen):
        with SessionLocal() as db:
            db.get(Factura, factura["id"]).estado = EstadoFactura.confirmada
            db.commit()
        return RespuestaVision(items=ITEMS_FALSOS, total_impreso=15200)

    app.dependency_overrides[get_normalizador_imagen] = lambda: vision_lenta
    assert reprocesar(client, factura["id"]).status_code == 409
    with SessionLocal() as db:
        guardada = db.get(Factura, factura["id"])
        assert guardada.estado == EstadoFactura.confirmada
        assert guardada.metodo == "texto"


def test_no_se_reprocesa_la_factura_de_otro_hogar(client, vision):
    factura_id = subir(client).json()["id"]
    actuar_como(SUB_OTRO)  # el usuario de prueba del otro hogar

    assert reprocesar(client, factura_id).status_code == 404
    assert vision.imagenes == []


def test_reprocesar_requiere_consentimiento(client, vision):
    factura_id = subir(client).json()["id"]
    crear_usuario(SUB_SEGUNDO_MIEMBRO, HOGAR_TEST, consentimiento=False)
    actuar_como(SUB_SEGUNDO_MIEMBRO)

    respuesta = reprocesar(client, factura_id)
    assert respuesta.status_code == 403
    assert respuesta.json()["detail"]["codigo"] == "consentimiento_requerido"


# --- 8. Las piezas de la visión ---


@pytest.mark.parametrize(
    ("datos", "tipo"),
    [
        (b"\x89PNG\r\n\x1a\n...", "image/png"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        (b"\xff\xd8\xff\xe0...", "image/jpeg"),
    ],
)
def test_tipo_de_imagen(datos, tipo):
    assert tipo_de_imagen(datos) == tipo


def test_normalizar_imagen_envia_la_foto_con_las_instrucciones_de_vision():
    llamadas = []

    def generate_content(**kwargs):
        llamadas.append(kwargs)
        return SimpleNamespace(text='{"items": [], "total_impreso": 125500}')

    cliente = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    imagen = b"\x89PNG\r\n\x1a\nfalsa"
    respuesta = normalizar_imagen_items(imagen, cliente, "modelo-x")
    assert respuesta == RespuestaVision(items=[], total_impreso=125500)

    [llamada] = llamadas
    foto, pedido = llamada["contents"]
    assert foto.inline_data.data == imagen
    assert foto.inline_data.mime_type == "image/png"
    assert "Extrae los productos" in pedido
    assert llamada["config"].system_instruction == INSTRUCCIONES_VISION
    assert llamada["config"].response_schema is RespuestaVision
    assert "FOTO" in INSTRUCCIONES_VISION and "nombre_incierto" in INSTRUCCIONES_VISION


def _yogur_y_gelatina():
    return [
        item_detectado(nombre="Yogur", cantidad=1, precio_unitario=17450, precio_total=17450),
        item_detectado(nombre="Gelatina", cantidad=1, precio_unitario=4450, precio_total=4450),
    ]


def test_pipeline_con_imagen_toma_el_encabezado_del_ocr_y_el_resto_de_la_vision(monkeypatch):
    # El OCR lee bien el encabezado; el total y los ítems salen de la visión.
    ocr_falso(monkeypatch, FACTURA_5_D1)
    resultado = procesar_factura_con_imagen(
        imagen_factura(),
        lambda imagen: RespuestaVision(items=_yogur_y_gelatina(), total_impreso=21900),
    )

    assert resultado.supermercado == "D1"
    assert resultado.total_impreso == 21900
    assert [i.nombre for i in resultado.items] == ["Yogur", "Gelatina"]
    assert resultado.requiere_revision is False


# --- 5. En modo visión, el total también lo lee Gemini ---


def test_el_total_de_la_vision_es_un_campo_aparte_solo_en_ese_modo():
    texto = RespuestaNormalizacion.model_json_schema()["properties"]
    vision = RespuestaVision.model_json_schema()["properties"]
    assert "total_impreso" not in texto  # en modo texto lo leen las reglas locales
    assert "total_impreso" in vision
    # Es de la factura, no de cada ítem.
    assert "total_impreso" not in vision["items"]["items"]["$ref"]


def test_instrucciones_de_vision_piden_leer_el_total_sin_ajustarlo():
    assert "total_impreso" in INSTRUCCIONES_VISION
    assert "no lo calcules sumando los productos" in INSTRUCCIONES_VISION
    assert "nunca lo ajustes para que cuadre" in INSTRUCCIONES_VISION
    assert "total_impreso" not in INSTRUCCIONES


def test_surtimax_aliado_con_vision_se_verifica_contra_el_total_de_la_foto(client, monkeypatch):
    """La factura de noviembre: el OCR leyó el TOTAL como 135,504 (era 125,500). Con la
    visión, Gemini lee 125,500 de la foto y los ítems suman eso: queda verificada."""
    ocr_falso(monkeypatch, FACTURA_4_MERKAMAX)
    _usar_normalizador([])
    factura = subir(client).json()
    assert factura["supermercado"] == "Surtimax (aliado)"
    assert factura["total_impreso"] == 135504  # la lectura del OCR
    assert factura["requiere_revision"] is True

    items = [
        item_detectado(nombre="Toallas", cantidad=1, precio_unitario=13500, precio_total=13500),
        item_detectado(nombre="Resto", cantidad=1, precio_unitario=112000, precio_total=112000),
    ]
    app.dependency_overrides[get_normalizador_imagen] = lambda: VisionEspia(items, 125500)
    datos = reprocesar(client, factura["id"]).json()

    assert datos["total_impreso"] == 125500
    assert datos["total_calculado"] == 125500
    assert datos["requiere_revision"] is False


@pytest.mark.parametrize(
    ("total_vision", "requiere_revision"),
    [
        (15200, False),
        (15300, True),  # la foto dice otra cosa: algún ítem se leyó mal
        (None, True),  # la visión no pudo leer el TOTAL: no se puede verificar
    ],
)
def test_reproceso_compara_contra_el_total_de_la_vision(
    client, factura_verificada, total_vision, requiere_revision
):
    factura = subir(client).json()
    assert factura["total_impreso"] == 15200  # lo que leyó el OCR

    app.dependency_overrides[get_normalizador_imagen] = lambda: VisionEspia(
        total_impreso=total_vision
    )
    datos = reprocesar(client, factura["id"]).json()

    assert datos["total_impreso"] == total_vision
    assert datos["requiere_revision"] is requiere_revision


def test_descripcion_impresa_se_expone_y_el_catalogo_no_la_pisa(client, factura_verificada):
    """El frontend la muestra junto al nombre. Si el nombre sale del catálogo, la
    descripción sigue siendo la de esta factura."""
    primera = subir(client).json()
    _confirmar(client, primera["id"])  # el catálogo aprende "Leche Alquería 1.1 L"

    leche, pan = subir(client).json()["items_detectados"]
    assert leche["origen"] == "catalogo"
    assert leche["nombre"] == "Leche Alquería 1.1 L"
    assert leche["descripcion_impresa"] == "LECHE ENTERA"
    assert pan["descripcion_impresa"] == "PAN TAJADO"
