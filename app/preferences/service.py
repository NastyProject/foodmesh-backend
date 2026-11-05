from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.preferences.models import PreferenciasHogar
from app.preferences.schemas import Preferencias


def obtener_preferencias(db: Session, hogar_id: int) -> Preferencias:
    """Las preferencias guardadas del hogar, o las de por defecto si no tiene (sin crear fila)."""
    fila = db.get(PreferenciasHogar, hogar_id)
    return Preferencias.model_validate(fila) if fila else Preferencias()


def guardar_preferencias(db: Session, hogar_id: int, datos: Preferencias) -> Preferencias:
    """Crea o reemplaza las preferencias del hogar (upsert).

    INSERT ... ON CONFLICT: dos PUT simultáneos de un hogar sin preferencias no chocan.
    """
    valores = datos.model_dump()
    sentencia = (
        insert(PreferenciasHogar)
        .values(hogar_id=hogar_id, **valores)
        .on_conflict_do_update(
            index_elements=[PreferenciasHogar.hogar_id],
            # onupdate del modelo no aplica dentro de ON CONFLICT: va a mano.
            set_={**valores, "actualizado_en": func.now()},
        )
    )
    db.execute(sentencia)
    db.commit()
    return datos
