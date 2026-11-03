from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Producto(Base):
    """Catálogo global de productos por código de barras (EAN/PLU).

    No tiene hogar_id: lo comparten todos los hogares. Se alimenta con lo que los
    usuarios confirman en sus facturas, y sirve para no depender de la IA cada vez
    que aparece un producto ya conocido.
    """

    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    categoria: Mapped[str | None] = mapped_column(String(60))
    unidad: Mapped[str] = mapped_column(String(20), default="unidad")
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
