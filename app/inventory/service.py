from sqlalchemy import select
from sqlalchemy.orm import Session

from app.inventory.models import ItemInventario
from app.inventory.schemas import ItemCreate, ItemUpdate


def listar_items(db: Session, hogar_id: int) -> list[ItemInventario]:
    consulta = (
        select(ItemInventario)
        .where(ItemInventario.hogar_id == hogar_id)
        .order_by(ItemInventario.fecha_vencimiento.asc().nulls_last())
    )
    return list(db.scalars(consulta))


def obtener_item(db: Session, hogar_id: int, item_id: int) -> ItemInventario | None:
    consulta = select(ItemInventario).where(
        ItemInventario.id == item_id,
        ItemInventario.hogar_id == hogar_id,
    )
    return db.scalar(consulta)


def crear_item(db: Session, hogar_id: int, datos: ItemCreate) -> ItemInventario:
    item = ItemInventario(hogar_id=hogar_id, **datos.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def actualizar_item(db: Session, item: ItemInventario, datos: ItemUpdate) -> ItemInventario:
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(item, campo, valor)
    db.commit()
    db.refresh(item)
    return item


def eliminar_item(db: Session, item: ItemInventario) -> None:
    db.delete(item)
    db.commit()
