import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.auth.dependencies import get_hogar_id
from app.catalog.models import Producto
from app.core.db import SessionLocal
from app.core.storage import AlmacenamientoLocal, get_storage
from app.inventory.models import ItemInventario
from app.invoices.models import Factura
from app.invoices.router import get_normalizador
from app.main import app
from app.ocr.normalizacion import ItemDetectado
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


@pytest.fixture
def client(almacenamiento):
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
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

    # Limpieza: borra lo que crearon los tests (en orden, por las FK)
    with SessionLocal() as db:
        hogares = [HOGAR_TEST, OTRO_HOGAR]
        db.execute(delete(ItemInventario).where(ItemInventario.hogar_id.in_(hogares)))
        db.execute(delete(Factura).where(Factura.hogar_id.in_(hogares)))
        db.execute(delete(Producto).where(Producto.codigo.startswith(PREFIJO_CODIGO_TEST)))
        db.execute(delete(Hogar).where(Hogar.id.in_(hogares)))
        db.commit()
