from fastapi import APIRouter, HTTPException, status

from app.auth.dependencies import HogarId
from app.core.db import DbSession
from app.inventory import service
from app.inventory.models import ItemInventario
from app.inventory.schemas import ItemCreate, ItemOut, ItemUpdate

router = APIRouter(prefix="/inventario", tags=["inventario"])


def _buscar_o_404(db: DbSession, hogar_id: int, item_id: int) -> ItemInventario:
    item = service.obtener_item(db, hogar_id, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ítem no encontrado")
    return item


@router.get("", response_model=list[ItemOut])
def listar(db: DbSession, hogar_id: HogarId):
    return service.listar_items(db, hogar_id)


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def crear(datos: ItemCreate, db: DbSession, hogar_id: HogarId):
    return service.crear_item(db, hogar_id, datos)


@router.get("/{item_id}", response_model=ItemOut)
def obtener(item_id: int, db: DbSession, hogar_id: HogarId):
    return _buscar_o_404(db, hogar_id, item_id)


@router.patch("/{item_id}", response_model=ItemOut)
def actualizar(item_id: int, datos: ItemUpdate, db: DbSession, hogar_id: HogarId):
    item = _buscar_o_404(db, hogar_id, item_id)
    return service.actualizar_item(db, item, datos)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(item_id: int, db: DbSession, hogar_id: HogarId):
    item = _buscar_o_404(db, hogar_id, item_id)
    service.eliminar_item(db, item)