import cv2
import fakeredis
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.auth.dependencies import get_hogar_id
from app.catalog.models import Producto
from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.storage import AlmacenamientoLocal, get_storage
from app.inventory.models import ItemInventario
from app.invoices.models import Factura
from app.invoices.router import get_normalizador
from app.main import app
from app.ocr.normalizacion import ItemDetectado
from app.preferences.models import PreferenciasHogar
from app.recommendations.generacion import RecetasGeneradas
from app.recommendations.models import Recomendacion
from app.recommendations.router import get_generador, get_generador_fondo
from app.recommendations.schemas import IngredienteIA, RecetaIA
from app.users.models import Hogar

HOGAR_TEST = 9001
OTRO_HOGAR = 9002
# El catálogo es global (no tiene hogar_id): los tests usan códigos con este
# prefijo para poder borrar solo lo que crearon.
PREFIJO_CODIGO_TEST = "9990"
CODIGO_LECHE = PREFIJO_CODIGO_TEST + "000000011"


def item_detectado(**cambios) -> ItemDetectado:
    datos = {
        "codigo": None,
        "nombre": "Leche entera 1.1 L",
        "cantidad": 2,
        "unidad": "unidad",
        "precio_unitario": 4500,
        "precio_total": 9000,
        "categoria": "lacteos",
    }
    return ItemDetectado(**(datos | cambios))


ITEMS_FALSOS = [
    item_detectado(codigo=CODIGO_LECHE),
    item_detectado(
        nombre="Pan tajado",
        cantidad=1,
        precio_unitario=6200,
        precio_total=6200,
        categoria="panaderia",
    ),
]


def normalizador_falso(texto: str) -> list[ItemDetectado]:
    """Reemplaza a Gemini en los tests: siempre devuelve los mismos ítems."""
    return ITEMS_FALSOS


def receta_falsa(titulo: str = "Calentado de arroz", **cambios) -> RecetaIA:
    """Receta como la devolvería Gemini. Usa el alimento "p1" y algo que hay que comprar."""
    datos = {
        "titulo": titulo,
        "descripcion": "Un desayuno rápido para aprovechar lo que sobró.",
        "tiempo_minutos": 20,
        "porciones": 2,
        "ingredientes": [
            IngredienteIA(nombre="Arroz", cantidad=2, unidad="taza", item_id="p1"),
            IngredienteIA(nombre="Cebolla larga", cantidad=1, unidad="unidad", item_id=None),
        ],
        "pasos": ["Picar la cebolla.", "Sofreír y agregar el arroz."],
        "por_que": "Usa el arroz antes de que se dañe.",
    }
    return RecetaIA(**(datos | cambios))


def generadas(recetas: list[RecetaIA], modelo: str | None = None) -> RecetasGeneradas:
    """Lo que devuelve un generador: las recetas y el modelo que respondió (por defecto,
    el principal de la configuración)."""
    return RecetasGeneradas(recetas=recetas, modelo=modelo or get_settings().gemini_model_recetas)


def generador_falso(texto: str) -> RecetasGeneradas:
    """Reemplaza a Gemini en las recetas: siempre devuelve las mismas tres."""
    return generadas(
        [receta_falsa(), receta_falsa("Sudado de papa"), receta_falsa("Arroz con verduras")]
    )


def imagen_factura(lineas: list[str] | None = None, extension: str = ".png") -> bytes:
    """Imagen sintética de una factura: texto negro sobre fondo blanco."""
    lineas = lineas or ["SUPERMERCADO EL ROBLE", "LECHE ENTERA 4500", "PAN TAJADO 6200"]
    imagen = np.full((60 * len(lineas) + 40, 900, 3), 255, np.uint8)
    for i, linea in enumerate(lineas):
        cv2.putText(
            imagen,
            linea,
            (20, 60 + 60 * i),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )
    _, datos = cv2.imencode(extension, imagen)
    return datos.tobytes()


@pytest.fixture
def almacenamiento(tmp_path):
    """Storage local en un directorio temporal que pytest borra solo."""
    return AlmacenamientoLocal(tmp_path)


@pytest.fixture(autouse=True)
def sin_precalculo(monkeypatch):
    """El precálculo de recetas queda apagado en todos los tests, sin importar el .env:
    si no, cada POST a /inventario generaría recetas y registros de más. Los tests de
    precálculo lo encienden con la fixture `precalculo_activo`."""
    monkeypatch.setattr(get_settings(), "precalcular_recetas", False)


@pytest.fixture
def precalculo_activo(monkeypatch):
    monkeypatch.setattr(get_settings(), "precalcular_recetas", True)


@pytest.fixture
def servidor_redis():
    """Redis en memoria (fakeredis). Con servidor_redis.connected = False simula que se cayó."""
    return fakeredis.FakeServer()


@pytest.fixture
def client(almacenamiento, servidor_redis):
    """Cliente de pruebas que se hace pasar por el hogar HOGAR_TEST."""
    # items_inventario.hogar_id tiene FK a hogares: los hogares de prueba deben existir.
    # merge() inserta o actualiza, por si quedaron de una corrida interrumpida.
    with SessionLocal() as db:
        for hogar_id in (HOGAR_TEST, OTRO_HOGAR):
            db.merge(Hogar(id=hogar_id, nombre=f"Hogar de prueba {hogar_id}"))
        db.commit()

    app.dependency_overrides[get_hogar_id] = lambda: HOGAR_TEST
    app.dependency_overrides[get_storage] = lambda: almacenamiento
    app.dependency_overrides[get_normalizador] = lambda: normalizador_falso
    cache = fakeredis.FakeRedis(server=servidor_redis, decode_responses=True)
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_generador] = lambda: generador_falso
    app.dependency_overrides[get_generador_fondo] = lambda: generador_falso
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

    # Limpieza: borra lo que crearon los tests (en orden, por las FK)
    with SessionLocal() as db:
        hogares = [HOGAR_TEST, OTRO_HOGAR]
        db.execute(delete(Recomendacion).where(Recomendacion.hogar_id.in_(hogares)))
        db.execute(delete(PreferenciasHogar).where(PreferenciasHogar.hogar_id.in_(hogares)))
        db.execute(delete(ItemInventario).where(ItemInventario.hogar_id.in_(hogares)))
        db.execute(delete(Factura).where(Factura.hogar_id.in_(hogares)))
        db.execute(delete(Producto).where(Producto.codigo.startswith(PREFIJO_CODIGO_TEST)))
        db.execute(delete(Hogar).where(Hogar.id.in_(hogares)))
        db.commit()
