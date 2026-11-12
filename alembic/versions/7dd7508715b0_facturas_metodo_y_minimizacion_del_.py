"""facturas: metodo y minimizacion del texto ocr

Revision ID: 7dd7508715b0
Revises: 302316e1d447
Create Date: 2026-11-11 16:57:11.419724

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7dd7508715b0'
down_revision: Union[str, Sequence[str], None] = '302316e1d447'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Revisión manual. add_column no crea el tipo enum de Postgres (create_table sí):
    # se crea antes. Las facturas existentes quedan con metodo = 'texto'.
    metodo = sa.Enum('texto', 'vision', name='metodo_factura')
    metodo.create(op.get_bind(), checkfirst=True)
    op.add_column('facturas', sa.Column('metodo', metodo, server_default='texto', nullable=False))

    # Minimización de datos: texto_ocr guardaba el texto completo (anonimizado, pero
    # la anonimización dejó escapar nombres y datos de tarjetas en facturas reales).
    # Se reemplaza por solo el bloque de productos, o NULL si no se puede recortar.
    # Se usa el código de la app (recorte y anonimización) a propósito: es la misma
    # regla que aplica ahora a las facturas nuevas.
    from app.ocr.anonimizacion import anonimizar
    from app.ocr.recorte import recortar_productos

    conexion = op.get_bind()
    facturas = conexion.execute(
        sa.text("SELECT id, texto_ocr FROM facturas WHERE texto_ocr IS NOT NULL")
    ).all()
    for factura_id, texto in facturas:
        bloque = recortar_productos(texto)
        conexion.execute(
            sa.text("UPDATE facturas SET texto_ocr = :texto WHERE id = :id"),
            {"texto": anonimizar(bloque).strip() if bloque else None, "id": factura_id},
        )


def downgrade() -> None:
    """Downgrade schema."""
    # El texto completo que se reemplazó por el bloque de productos no se puede
    # recuperar (era la idea): el downgrade solo quita la columna metodo.
    op.drop_column('facturas', 'metodo')
    sa.Enum(name='metodo_factura').drop(op.get_bind(), checkfirst=True)
