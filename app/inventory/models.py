from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ItemInventario(Base):
    __tablename__ = "items_inventario"

    id: Mapped[int] = mapped_column(primary_key=True)
    hogar_id: Mapped[int] = mapped_column(ForeignKey("hogares.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    categoria: Mapped[str | None] = mapped_column(String(60))
    # Se calcula de la categoría (app/catalog/categorias.py) al crear o editar el ítem.
    # Es columna, y no solo un cálculo en Python, para poder filtrar en la consulta.
    es_alimento: Mapped[bool] = mapped_column(default=True, server_default=true())
    cantidad: Mapped[float]
    unidad: Mapped[str] = mapped_column(String(20), default="unidad")
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date)
    # Factura de la que salió el ítem; None si se creó a mano.
    factura_id: Mapped[int | None] = mapped_column(ForeignKey("facturas.id"), index=True)
    # Producto del catálogo global, si el ítem vino de una factura con código de barras.
    producto_id: Mapped[int | None] = mapped_column(ForeignKey("productos.id"), index=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
