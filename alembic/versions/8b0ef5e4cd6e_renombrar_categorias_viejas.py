"""renombrar categorias viejas

Migración solo de datos (no cambia tablas): las categorías pasan a ser una lista
cerrada. Las de la lista anterior se renombran y cualquier otro valor pasa a
"otros", en items_inventario, productos y el JSON items_detectados de facturas.

Revision ID: 8b0ef5e4cd6e
Revises: 51b77275d293
Create Date: 2026-11-02 23:16:10.099221

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8b0ef5e4cd6e'
down_revision: Union[str, Sequence[str], None] = '51b77275d293'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Copiadas aquí (no importadas de app/) para que la migración no cambie si el código cambia.
RENOMBRES = {
    'carnes': 'carnes_pescados',
    'granos': 'granos_cereales',
    'aseo': 'aseo_hogar',
}
CATEGORIAS = (
    'lacteos', 'carnes_pescados', 'frutas_verduras', 'granos_cereales',
    'enlatados_conservas', 'panaderia', 'bebidas', 'condimentos_especias',
    'frutos_secos', 'snacks_dulces', 'congelados', 'aseo_hogar', 'cuidado_personal',
    'mascotas', 'otros',
)
NO_ALIMENTO = ('aseo_hogar', 'cuidado_personal', 'mascotas')


def _lista_sql(valores) -> str:
    return ', '.join(f"'{v}'" for v in valores)


def _categoria_nueva(expresion: str) -> str:
    """CASE de SQL que convierte el valor de `expresion` en una categoría válida.
    NULL se queda en NULL (la categoría es opcional)."""
    renombres = ' '.join(f"WHEN '{viejo}' THEN '{nuevo}'" for viejo, nuevo in RENOMBRES.items())
    return (
        f"CASE WHEN {expresion} IS NULL THEN NULL "
        f"WHEN {expresion} IN ({_lista_sql(CATEGORIAS)}) THEN {expresion} "
        f"ELSE CASE {expresion} {renombres} ELSE 'otros' END END"
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(f"UPDATE items_inventario SET categoria = {_categoria_nueva('categoria')}")
    # Con las categorías corregidas, se recalcula es_alimento (un valor desconocido
    # que pasó a "otros" cuenta como alimento).
    op.execute(
        "UPDATE items_inventario SET es_alimento = "
        f"categoria IS NULL OR categoria NOT IN ({_lista_sql(NO_ALIMENTO)})"
    )
    op.execute(f"UPDATE productos SET categoria = {_categoria_nueva('categoria')}")

    # items_detectados es una lista JSON: se arma de nuevo, elemento por elemento y en
    # el mismo orden (WITH ORDINALITY), cambiando solo la clave "categoria".
    op.execute(
        f"""
        UPDATE facturas SET items_detectados = (
            SELECT jsonb_agg(
                CASE WHEN item ? 'categoria' AND item->>'categoria' IS NOT NULL
                    THEN jsonb_set(
                        item, '{{categoria}}', to_jsonb({_categoria_nueva("item->>'categoria'")})
                    )
                    ELSE item
                END
                ORDER BY posicion
            )
            FROM jsonb_array_elements(items_detectados) WITH ORDINALITY AS t(item, posicion)
        )
        WHERE jsonb_array_length(items_detectados) > 0
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    # No se puede deshacer: los valores que pasaron a "otros" se perdieron, y las
    # categorías renombradas no se distinguen de las que ya venían con el nombre nuevo.
    # Las categorías nuevas siguen siendo texto válido para el esquema anterior.
    pass
