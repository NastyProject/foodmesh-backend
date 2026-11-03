import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog import service as catalog_service
from app.core.storage import Almacenamiento, key_imagen_factura
from app.inventory import service as inventory_service
from app.inventory.models import ItemInventario
from app.inventory.schemas import ItemCreate
from app.invoices.models import EstadoFactura, Factura
from app.invoices.schemas import ItemFactura
from app.ocr.pipeline import Normalizador, procesar_factura

logger = logging.getLogger(__name__)


class FacturaYaConfirmada(Exception):
    pass


def listar_facturas(db: Session, hogar_id: int) -> list[Factura]:
    consulta = (
        select(Factura).where(Factura.hogar_id == hogar_id).order_by(Factura.creado_en.desc())
    )
    return list(db.scalars(consulta))


def obtener_factura(
    db: Session, hogar_id: int, factura_id: int, *, bloquear: bool = False
) -> Factura | None:
    consulta = select(Factura).where(Factura.id == factura_id, Factura.hogar_id == hogar_id)
    if bloquear:
        # SELECT ... FOR UPDATE: si llegan dos confirmaciones a la vez, la segunda
        # espera a que termine la primera y ya ve la factura confirmada.
        consulta = consulta.with_for_update()
    return db.scalar(consulta)


def crear_factura(
    db: Session,
    hogar_id: int,
    imagen: bytes,
    almacenamiento: Almacenamiento,
    normalizar: Normalizador,
) -> Factura:
    # El pipeline va primero y fuera de la BD: tarda varios segundos (Tesseract +
    # Gemini) y así no dejamos una transacción abierta mientras tanto.
    resultado = procesar_factura(imagen, normalizar)
    items = catalog_service.aplicar_catalogo(db, resultado.items)

    factura = Factura(
        hogar_id=hogar_id,
        estado=EstadoFactura.error if resultado.error else EstadoFactura.pendiente_validacion,
        supermercado=resultado.supermercado,
        fecha_compra=resultado.fecha_compra,
        recortada=resultado.recortada,
        total_impreso=resultado.total_impreso,
        total_calculado=resultado.total_calculado,
        requiere_revision=resultado.requiere_revision,
        texto_ocr=resultado.texto_ocr,
        items_detectados=[item.model_dump() for item in items],
        error=resultado.error,
    )
    db.add(factura)
    db.flush()  # asigna factura.id, que hace falta para la key de la imagen

    factura.imagen_key = key_imagen_factura(hogar_id, factura.id)
    almacenamiento.guardar(factura.imagen_key, imagen)
    db.commit()
    db.refresh(factura)
    return factura


def confirmar_factura(
    db: Session,
    factura: Factura,
    items: list[ItemFactura],
    almacenamiento: Almacenamiento,
) -> list[ItemInventario]:
    """Crea los ítems revisados por el usuario en el inventario, actualiza el
    catálogo con los que traen código y borra la imagen.

    `factura` debe haberse obtenido con bloquear=True.
    """
    if factura.estado == EstadoFactura.confirmada:
        raise FacturaYaConfirmada

    # Todos los ítems, el catálogo y el cambio de estado van en una sola
    # transacción: o queda todo, o no queda nada.
    creados = []
    for datos in items:
        producto_id = None
        if datos.codigo:
            # El catálogo guarda lo que confirmó el usuario, no lo que propuso la IA.
            producto_id = catalog_service.guardar_producto(
                db, datos.codigo, datos.nombre, datos.categoria, datos.unidad
            )
        item = ItemCreate.model_validate(datos.model_dump(exclude={"codigo"}))
        creados.append(
            inventory_service.crear_item(
                db,
                factura.hogar_id,
                item,
                factura_id=factura.id,
                producto_id=producto_id,
                commit=False,
            )
        )
    factura.estado = EstadoFactura.confirmada
    factura.error = None
    db.commit()

    # La imagen ya no hace falta. Se borra después del commit: si borrarla falla,
    # la factura sigue confirmada y conserva imagen_key para limpiarla después.
    if factura.imagen_key:
        try:
            almacenamiento.borrar(factura.imagen_key)
        except Exception:
            logger.exception("No se pudo borrar la imagen %s", factura.imagen_key)
        else:
            factura.imagen_key = None
            db.commit()

    for item in creados:
        db.refresh(item)
    return creados
