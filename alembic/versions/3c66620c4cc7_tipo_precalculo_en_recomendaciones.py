"""tipo precalculo en recomendaciones

Revision ID: 3c66620c4cc7
Revises: 72d2169e8e86
Create Date: 2026-11-04 10:20:03.838386

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3c66620c4cc7'
down_revision: Union[str, Sequence[str], None] = '72d2169e8e86'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Escrita a mano: autogenerate no detecta valores nuevos en un enum de Postgres.
    # Desde Postgres 12, ADD VALUE puede correr dentro de la transacción de la migración
    # (lo que no se puede es usar el valor nuevo en esa misma transacción).
    op.execute("ALTER TYPE tipo_recomendacion ADD VALUE IF NOT EXISTS 'precalculo'")


def downgrade() -> None:
    """Downgrade schema."""
    # Postgres no permite quitar un valor de un enum: se crea el tipo sin él y se cambia
    # la columna al tipo nuevo. Antes se borran las filas que lo usan (son métricas de
    # precálculo, que en la versión anterior no existían).
    op.execute("DELETE FROM recomendaciones WHERE tipo = 'precalculo'")
    op.execute("ALTER TYPE tipo_recomendacion RENAME TO tipo_recomendacion_viejo")
    op.execute("CREATE TYPE tipo_recomendacion AS ENUM ('normal', 'nuevas')")
    op.execute(
        "ALTER TABLE recomendaciones ALTER COLUMN tipo TYPE tipo_recomendacion "
        "USING tipo::text::tipo_recomendacion"
    )
    op.execute("DROP TYPE tipo_recomendacion_viejo")
