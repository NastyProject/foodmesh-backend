from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog.categorias import es_alimento
from app.inventory.models import ItemInventario
from app.inventory.schemas import ItemCreate, ItemUpdate


def listar_items(
    db: Session, hogar_id: int, *, solo_alimentos: bool = False
) -> list[ItemInventario]:
    consulta = select(ItemInventario).where(ItemInventario.hogar_id == hogar_id)
    if solo_alimentos:
        consulta = consulta.where(ItemInventario.es_alimento)
    consulta = consulta.order_by(ItemInventario.fecha_vencimiento.asc().nulls_last())
    return list(db.scalars(consulta))


def obtener_item(db: Session, hogar_id: int, item_id: int) -> ItemInventario | None:
    consulta = select(ItemInventario).where(
        ItemInventario.id == item_id,
        ItemInventario.hogar_id == hogar_id,
    )
    return db.scalar(consulta)


def crear_item(
    db: Session,
    hogar_id: int,
    datos: ItemCreate,
    *,
    factura_id: int | None = None,
    producto_id: int | None = None,
    commit: bool = True,
) -> ItemInventario:
    """Crea un ítem. Con commit=False solo lo agrega a la transacción en curso, para
    que quien llama pueda crear varios ítems y confirmarlos todos juntos."""
    item = ItemInventario(
        hogar_id=hogar_id,
        factura_id=factura_id,
        producto_id=producto_id,
        es_alimento=es_alimento(datos.categoria),
        **datos.model_dump(),
    )
    db.add(item)
    if commit:
        db.commit()
        db.refresh(item)
    else:
        db.flush()  # asigna item.id sin cerrar la transacción
    return item


def actualizar_item(db: Session, item: ItemInventario, datos: ItemUpdate) -> ItemInventario:
    for campo, valor in datos.model_dump(exclude_unset=True).items():
        setattr(item, campo, valor)
    item.es_alimento = es_alimento(item.categoria)
    db.commit()
    db.refresh(item)
    return item


def eliminar_item(db: Session, item: ItemInventario) -> None:
    db.delete(item)
    db.commit()
