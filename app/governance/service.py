"""Gobernanza de datos: consentimiento, auditoría, borrado y exportación de la cuenta."""

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import redis
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.storage import Almacenamiento
from app.governance.models import Consentimiento, RegistroAuditoria
from app.governance.schemas import ConsentimientoIn, Exportacion, HogarExportado
from app.inventory.models import ItemInventario
from app.invoices.models import Factura
from app.preferences import service as preferences_service
from app.preferences.models import PreferenciasHogar
from app.recommendations import service as recommendations_service
from app.recommendations.models import Recomendacion
from app.users.models import Hogar, Usuario

logger = logging.getLogger(__name__)

# Versión de la política de tratamiento de datos que muestra el frontend. Cambiarla
# cuando cambie el texto de la política.
VERSION_POLITICA_VIGENTE = "1.0"


class Accion:
    """Acciones que quedan en la auditoría."""

    CONSENTIMIENTO_OTORGADO = "consentimiento_otorgado"
    CONSENTIMIENTO_ACTUALIZADO = "consentimiento_actualizado"
    CONSENTIMIENTO_REVOCADO = "consentimiento_revocado"
    CUENTA_EXPORTADA = "cuenta_exportada"
    CUENTA_ELIMINADA = "cuenta_eliminada"
    # El usuario autorizó enviar la foto completa de una factura a Gemini (visión).
    FACTURA_REPROCESADA_CON_IMAGEN = "factura_reprocesada_con_imagen"


# --- Auditoría ---


def hash_sub(sub: str) -> str:
    """SHA-256 del sub de Auth0. Seudonimiza, no anonimiza: quien conozca el sub puede
    calcular el mismo hash y encontrar sus registros."""
    return hashlib.sha256(sub.encode()).hexdigest()


def registrar_auditoria(
    db: Session, accion: str, sub: str, detalle: dict[str, Any] | None = None
) -> None:
    """Agrega una fila a la auditoría, en la transacción de quien llama (que hace el
    commit): así la acción y su registro se guardan juntos o ninguno de los dos."""
    db.add(RegistroAuditoria(accion=accion, usuario_sub_hash=hash_sub(sub), detalle=detalle or {}))


# --- Consentimiento ---


def obtener_consentimiento(db: Session, usuario_id: int) -> Consentimiento | None:
    return db.get(Consentimiento, usuario_id)


def tiene_consentimiento(db: Session, usuario_id: int) -> bool:
    consentimiento = obtener_consentimiento(db, usuario_id)
    return consentimiento is not None and consentimiento.acepta_tratamiento


def guardar_consentimiento(
    db: Session, usuario: Usuario, datos: ConsentimientoIn
) -> Consentimiento:
    """Crea o actualiza el consentimiento del usuario y lo deja en la auditoría."""
    consentimiento = obtener_consentimiento(db, usuario.id)
    tenia = consentimiento is not None and consentimiento.acepta_tratamiento
    if consentimiento is None:
        consentimiento = Consentimiento(usuario_id=usuario.id)
        db.add(consentimiento)

    consentimiento.acepta_tratamiento = datos.acepta_tratamiento
    consentimiento.acepta_analitica_agregada = datos.acepta_analitica_agregada
    consentimiento.version_politica = datos.version_politica
    if datos.acepta_tratamiento and not tenia:
        accion = Accion.CONSENTIMIENTO_OTORGADO
        consentimiento.otorgado_en = datetime.now(UTC)
    elif not datos.acepta_tratamiento and tenia:
        accion = Accion.CONSENTIMIENTO_REVOCADO
        consentimiento.otorgado_en = None
    else:
        accion = Accion.CONSENTIMIENTO_ACTUALIZADO

    registrar_auditoria(db, accion, usuario.auth0_sub, datos.model_dump())
    db.commit()
    db.refresh(consentimiento)  # trae actualizado_en, que lo pone la BD
    return consentimiento


# --- Borrado de cuenta ---


@dataclass
class ResultadoBorrado:
    hogar_eliminado: bool
    # Imágenes de facturas que quedaron en el storage: se borran después del commit.
    imagenes: list[str] = field(default_factory=list)


def eliminar_cuenta(db: Session, usuario: Usuario) -> ResultadoBorrado:
    """Borra la cuenta en UNA transacción.

    Si el usuario es el único de su hogar, se borra todo el hogar: ítems, facturas,
    preferencias, recomendaciones, consentimiento, usuario y hogar. Si hay más
    miembros, solo su usuario y su consentimiento (los datos del hogar son de todos).
    El catálogo global de productos no se toca: no tiene datos personales.

    No borra las imágenes del storage ni la caché: eso va después del commit (ver
    borrar_imagenes e invalidar la caché en el router), porque no se puede deshacer.
    """
    hogar_id = usuario.hogar_id
    otros_miembros = db.scalar(
        select(func.count())
        .select_from(Usuario)
        .where(Usuario.hogar_id == hogar_id, Usuario.id != usuario.id)
    )
    resultado = ResultadoBorrado(hogar_eliminado=otros_miembros == 0)
    detalle: dict[str, Any] = {"hogar_eliminado": resultado.hogar_eliminado}

    if resultado.hogar_eliminado:
        resultado.imagenes = list(
            db.scalars(
                select(Factura.imagen_key).where(
                    Factura.hogar_id == hogar_id, Factura.imagen_key.is_not(None)
                )
            )
        )
        # En orden, por las llaves foráneas: los ítems apuntan a facturas, y todo
        # apunta al hogar. rowcount: cuántas filas se borraron (para la auditoría).
        for nombre, modelo in (
            ("recomendaciones", Recomendacion),
            ("preferencias", PreferenciasHogar),
            ("items", ItemInventario),
            ("facturas", Factura),
        ):
            borradas = db.execute(delete(modelo).where(modelo.hogar_id == hogar_id))
            detalle[nombre] = borradas.rowcount

    db.execute(delete(Consentimiento).where(Consentimiento.usuario_id == usuario.id))
    db.execute(delete(Usuario).where(Usuario.id == usuario.id))
    if resultado.hogar_eliminado:
        db.execute(delete(Hogar).where(Hogar.id == hogar_id))

    registrar_auditoria(db, Accion.CUENTA_ELIMINADA, usuario.auth0_sub, detalle)
    db.commit()
    return resultado


def borrar_imagenes(almacenamiento: Almacenamiento, claves: list[str]) -> None:
    """Borra imágenes del storage. Se llama después del commit: si alguna falla, se
    registra el error y se sigue (la cuenta ya está borrada en la BD)."""
    for clave in claves:
        try:
            almacenamiento.borrar(clave)
        except Exception:
            logger.exception("No se pudo borrar la imagen %s de una cuenta eliminada", clave)


def invalidar_cache(cache: redis.Redis | None, hogar_id: int) -> None:
    recommendations_service.invalidar_cache_hogar(cache, hogar_id)


# --- Exportación (derecho de acceso, Ley 1581) ---


def exportar_cuenta(db: Session, usuario: Usuario) -> Exportacion:
    """Todos los datos del hogar del usuario, y los suyos propios. De los demás
    miembros del hogar solo se dice cuántos son: sus datos personales son de ellos."""
    hogar_id = usuario.hogar_id
    hogar = db.get(Hogar, hogar_id)
    otros_miembros = db.scalar(
        select(func.count())
        .select_from(Usuario)
        .where(Usuario.hogar_id == hogar_id, Usuario.id != usuario.id)
    )
    inventario = db.scalars(
        select(ItemInventario)
        .where(ItemInventario.hogar_id == hogar_id)
        .order_by(ItemInventario.id)
    ).all()
    facturas = db.scalars(
        select(Factura).where(Factura.hogar_id == hogar_id).order_by(Factura.id)
    ).all()
    recomendaciones = db.scalars(
        select(Recomendacion).where(Recomendacion.hogar_id == hogar_id).order_by(Recomendacion.id)
    ).all()

    exportacion = Exportacion.model_validate(
        {
            "exportado_en": datetime.now(UTC),
            "usuario": usuario,
            "hogar": HogarExportado(
                nombre=hogar.nombre, creado_en=hogar.creado_en, otros_miembros=otros_miembros
            ),
            "consentimiento": obtener_consentimiento(db, usuario.id),
            "preferencias": preferences_service.obtener_preferencias(db, hogar_id),
            "inventario": inventario,
            "facturas": facturas,
            "recomendaciones": recomendaciones,
        },
        from_attributes=True,
    )

    registrar_auditoria(
        db,
        Accion.CUENTA_EXPORTADA,
        usuario.auth0_sub,
        {
            "items": len(inventario),
            "facturas": len(facturas),
            "recomendaciones": len(recomendaciones),
        },
    )
    db.commit()
    return exportacion
