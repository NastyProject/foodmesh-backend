from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ItemInventario(Base):
    __tablename__ = "items_inventario"

    id: Mapped[int] = mapped_column(primary_key=True)
    hogar_id: Mapped[int] = mapped_column(ForeignKey("hogares.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    categoria: Mapped[str | None] = mapped_column(String(60))
    cantidad: Mapped[float]
    unidad: Mapped[str] = mapped_column(String(20), default="unidad")
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
