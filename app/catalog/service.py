from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.catalog.models import Producto
from app.ocr.normalizacion import ItemPropuesto


def buscar_por_codigos(db: Session, codigos: set[str]) -> dict[str, Producto]:
    if not codigos:
        return {}
    consulta = select(Producto).where(Producto.codigo.in_(codigos))
    return {producto.codigo: producto for producto in db.scalars(consulta)}


def aplicar_catalogo(db: Session, items: list[ItemPropuesto]) -> list[ItemPropuesto]:
    """Para los ítems cuyo código está en el catálogo, usa el nombre y la categoría
    del catálogo (que ya confirmó algún usuario) en vez de los de la IA."""
    catalogo = buscar_por_codigos(db, {item.codigo for item in items if item.codigo})
    resultado = []
    for item in items:
        producto = catalogo.get(item.codigo) if item.codigo else None
        if producto is None:
            resultado.append(item)
            continue
        resultado.append(
            item.model_copy(
                update={
                    "nombre": producto.nombre,
                    "categoria": producto.categoria or item.categoria,
                    "origen": "catalogo",
                }
            )
        )
    return resultado


def guardar_producto(
    db: Session, codigo: str, nombre: str, categoria: str | None, unidad: str
) -> int:
    """Inserta el producto, o lo actualiza si el código ya existe (upsert). Devuelve su id.

    Usa INSERT ... ON CONFLICT de Postgres: es una sola sentencia, así que dos
    confirmaciones simultáneas con el mismo código no chocan. No hace commit.
    """
    sentencia = (
        insert(Producto)
        .values(codigo=codigo, nombre=nombre, categoria=categoria, unidad=unidad)
        .on_conflict_do_update(
            index_elements=[Producto.codigo],
            set_={
                "nombre": nombre,
                "categoria": categoria,
                "unidad": unidad,
                "actualizado_en": func.now(),
            },
        )
        .returning(Producto.id)
    )
    return db.execute(sentencia).scalar_one()
