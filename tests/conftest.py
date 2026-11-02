import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.auth.dependencies import get_hogar_id
from app.core.db import SessionLocal
from app.inventory.models import ItemInventario
from app.main import app
from app.users.models import Hogar

HOGAR_TEST = 9001
OTRO_HOGAR = 9002


@pytest.fixture
def client():
    """Cliente de pruebas que se hace pasar por el hogar HOGAR_TEST."""
    # items_inventario.hogar_id tiene FK a hogares: los hogares de prueba deben existir.
    # merge() inserta o actualiza, por si quedaron de una corrida interrumpida.
    with SessionLocal() as db:
        for hogar_id in (HOGAR_TEST, OTRO_HOGAR):
            db.merge(Hogar(id=hogar_id, nombre=f"Hogar de prueba {hogar_id}"))
        db.commit()

    app.dependency_overrides[get_hogar_id] = lambda: HOGAR_TEST
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

    # Limpieza: borra lo que crearon los tests (primero los ítems, por la FK)
    with SessionLocal() as db:
        hogares = [HOGAR_TEST, OTRO_HOGAR]
        db.execute(delete(ItemInventario).where(ItemInventario.hogar_id.in_(hogares)))
        db.execute(delete(Hogar).where(Hogar.id.in_(hogares)))
        db.commit()
