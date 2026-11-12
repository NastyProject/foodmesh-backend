import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.catalog import service as catalog_service
from app.core.storage import Almacenamiento, key_imagen_factura
from app.governance.service import Accion, registrar_auditoria
from app.inventory import service as inventory_service
from app.inventory.models import ItemInventario
from app.inventory.schemas import ItemCreate
from app.invoices.models import EstadoFactura, Factura, MetodoFactura
from app.invoices.schemas import ItemFactura
from app.ocr.pipeline import (
    Normalizador,
    NormalizadorImagen,
    leer_con_imagen,
    procesar_factura,
    requiere_revision,
    total_de,
)
from app.users.models import Usuario

logger = logging.getLogger(__name__)


class FacturaYaConfirmada(Exception):
    pass


class ImagenIlegible(Exception):
    """El OCR leyó basura: no se llamó a Gemini y la factura no se crea."""

    def __init__(self, legibilidad):
        super().__init__("imagen_ilegible")
        self.legibilidad = legibilidad


class FacturaNoReprocesable(Exception):
    """La factura ya está confirmada, o su imagen ya no está en el storage."""


class ReprocesoFallido(Exception):
    """Gemini (con visión) no respondió o devolvió algo inválido."""


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
    if resultado.problema_calidad == "imagen_ilegible":
        # Antes de guardar nada (ni la factura ni la imagen): el usuario repite la foto.
        raise ImagenIlegible(resultado.legibilidad)
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
        # Solo el bloque de productos; el texto completo no se guarda.
        texto_ocr=resultado.texto_guardado,
        metodo=MetodoFactura.texto,
        items_detectados=[item.model_dump() for item in items],
        items_descartados=resultado.items_descartados,
        error=resultado.error,
    )
    db.add(factura)
    db.flush()  # asigna factura.id, que hace falta para la key de la imagen

    factura.imagen_key = key_imagen_factura(hogar_id, factura.id)
    almacenamiento.guardar(factura.imagen_key, imagen)
    db.commit()
    db.refresh(factura)
    return factura


def _codigos_aprendibles(factura: Factura) -> set[str]:
    """Códigos que el catálogo puede aprender de esta factura.

    El catálogo es global: un código mal asociado le pone el nombre equivocado a ese
    producto en las facturas de todos los hogares. En una factura de Surtimax (aliado) los EAN
    quedaron corridos un producto, y confirmar habría asociado el código del pan a otro
    producto. Por eso solo se aprenden códigos si:
    - la factura tiene el total verificado (no requiere_revision);
    - el ítem detectado con ese código no está marcado como revisar ni nombre_incierto;
    - el código es un GTIN con dígito de control válido.
    """
    if factura.requiere_revision:
        return set()
    detectados: list[dict[str, Any]] = factura.items_detectados or []
    return {
        item["codigo"]
        for item in detectados
        if item.get("codigo")
        and not item.get("revisar")
        and not item.get("nombre_incierto")
        and catalog_service.es_gtin_valido(item["codigo"])
    }


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
    aprendibles = _codigos_aprendibles(factura)
    creados = []
    for datos in items:
        producto_id = None
        if datos.codigo and datos.codigo in aprendibles:
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


def reprocesar_con_imagen(
    db: Session,
    factura: Factura,
    usuario: Usuario,
    almacenamiento: Almacenamiento,
    normalizar_imagen: NormalizadorImagen,
) -> Factura:
    """Respaldo con visión: envía la foto a Gemini multimodal (el usuario ya lo
    autorizó) y reemplaza los items_detectados. Solo si la factura no está confirmada
    y su imagen sigue en el storage (se borra al confirmar).

    Gemini también lee el TOTAL de la foto, y desde ahí la factura se verifica contra
    ese total, no contra el del OCR (que en formatos difíciles es el que falla). Si la
    visión no lo pudo leer, la factura pide revisión.
    """
    if factura.estado == EstadoFactura.confirmada or not factura.imagen_key:
        raise FacturaNoReprocesable
    try:
        imagen = almacenamiento.leer(factura.imagen_key)
    except Exception:
        logger.exception("No se pudo leer la imagen %s para reprocesar", factura.imagen_key)
        raise FacturaNoReprocesable from None

    # Gemini va antes de tocar la factura, sin transacción abierta: tarda segundos.
    db.commit()
    try:
        lectura = leer_con_imagen(imagen, normalizar_imagen)
    except Exception as error:
        logger.exception("Falló el reproceso con imagen de la factura %d", factura.id)
        raise ReprocesoFallido from error
    items = catalog_service.aplicar_catalogo(db, lectura.items)

    # Mientras Gemini respondía, la factura pudo confirmarse en otra petición: se
    # vuelve a leer bloqueada (SELECT ... FOR UPDATE) y se revisa antes de escribir.
    db.refresh(factura, with_for_update=True)
    if factura.estado == EstadoFactura.confirmada:
        raise FacturaNoReprocesable

    factura.items_detectados = [item.model_dump() for item in items]
    factura.items_descartados = 0  # la visión no se ancla a un texto
    factura.total_impreso = lectura.total_impreso
    factura.total_calculado = total_de(items)
    factura.requiere_revision = requiere_revision(factura.total_impreso, factura.total_calculado)
    factura.metodo = MetodoFactura.vision
    factura.estado = EstadoFactura.pendiente_validacion
    factura.error = None
    registrar_auditoria(
        db,
        Accion.FACTURA_REPROCESADA_CON_IMAGEN,
        usuario.auth0_sub,
        {"factura_id": factura.id, "acepto_enviar_imagen": True, "items": len(items)},
    )
    db.commit()
    db.refresh(factura)
    return factura
