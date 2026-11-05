from fastapi import APIRouter, HTTPException, status

from app.auth.dependencies import HogarId
from app.core.db import DbSession
from app.inventory import service
from app.inventory.models import ItemInventario
from app.inventory.schemas import ItemCreate, ItemOut, ItemUpdate
from app.recommendations.precalculo import PrecalculoDep

router = APIRouter(prefix="/inventario", tags=["inventario"])


def _buscar_o_404(db: DbSession, hogar_id: int, item_id: int) -> ItemInventario:
    item = service.obtener_item(db, hogar_id, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ítem no encontrado")
    return item


@router.get("", response_model=list[ItemOut])
def listar(db: DbSession, hogar_id: HogarId, solo_alimentos: bool = False):
    """Con ?solo_alimentos=true omite aseo, cuidado personal y productos para mascotas."""
    return service.listar_items(db, hogar_id, solo_alimentos=solo_alimentos)


@router.post("", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
def crear(datos: ItemCreate, db: DbSession, hogar_id: HogarId, precalculo: PrecalculoDep):
    item = service.crear_item(db, hogar_id, datos)
    # Solo los alimentos cambian las recetas (aseo y mascotas no se le envían a Gemini).
    if item.es_alimento:
        precalculo.programar(hogar_id)
    return item


@router.get("/{item_id}", response_model=ItemOut)
def obtener(item_id: int, db: DbSession, hogar_id: HogarId):
    return _buscar_o_404(db, hogar_id, item_id)


@router.patch("/{item_id}", response_model=ItemOut)
def actualizar(
    item_id: int, datos: ItemUpdate, db: DbSession, hogar_id: HogarId, precalculo: PrecalculoDep
):
    item = _buscar_o_404(db, hogar_id, item_id)
    era_alimento = item.es_alimento  # cambiar la categoría puede sacarlo de los alimentos
    item = service.actualizar_item(db, item, datos)
    if era_alimento or item.es_alimento:
        precalculo.programar(hogar_id)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(item_id: int, db: DbSession, hogar_id: HogarId, precalculo: PrecalculoDep):
    item = _buscar_o_404(db, hogar_id, item_id)
    era_alimento = item.es_alimento
    service.eliminar_item(db, item)
    if era_alimento:
        precalculo.programar(hogar_id)
