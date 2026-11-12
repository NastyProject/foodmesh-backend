from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Consentimiento(Base):
    """Autorización del usuario para tratar sus datos (Ley 1581 de 2012).

    Una fila por usuario como máximo. Sin fila, el usuario no ha dado consentimiento:
    así quedan los usuarios que existían antes de este módulo.
    """

    __tablename__ = "consentimientos"

    # usuario_id es la llave primaria: así la relación 1 a 1 la garantiza la BD.
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), primary_key=True)
    # Obligatorio para usar la app: sin él, los endpoints con datos del hogar dan 403.
    acepta_tratamiento: Mapped[bool]
    # Opcional: participar con datos anónimos y agregados en las señales de demanda
    # para supermercados.
    acepta_analitica_agregada: Mapped[bool] = mapped_column(default=False, server_default=false())
    # Versión de la política de tratamiento que el usuario vio al aceptar.
    version_politica: Mapped[str] = mapped_column(String(20))
    # Cuándo se otorgó el consentimiento vigente; None si no está otorgado (nunca lo
    # aceptó o lo revocó).
    otorgado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RegistroAuditoria(Base):
    """Bitácora de acciones de gobernanza. Solo se agregan filas: ningún endpoint ni
    función del código las edita o borra.

    No tiene llave foránea a usuarios a propósito: el registro debe sobrevivir al
    borrado de la cuenta. Por eso guarda un hash del sub de Auth0 y no el sub en claro
    ni el id del usuario.
    """

    __tablename__ = "registros_auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    momento: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    accion: Mapped[str] = mapped_column(String(40), index=True)
    # SHA-256 (hex) del sub de Auth0: permite agrupar las acciones de una misma
    # persona sin guardar su identificador.
    usuario_sub_hash: Mapped[str] = mapped_column(String(64), index=True)
    # Contexto de la acción, sin datos personales (p. ej. cuántas facturas se borraron).
    detalle: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
