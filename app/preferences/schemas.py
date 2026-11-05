from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.preferences.models import Dieta

Alergia = Literal[
    "lacteos", "gluten", "huevo", "mani", "frutos_secos", "mariscos", "pescado", "soya"
]
# Un ingrediente que no le gusta al hogar: texto libre, sin espacios sobrantes.
Ingrediente = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class Preferencias(BaseModel):
    """Lo que el cliente envía en PUT y lo que la API devuelve (no incluye hogar_id).

    Los valores por defecto son los que se usan si el hogar nunca guardó preferencias.
    """

    model_config = ConfigDict(from_attributes=True)

    dieta: Dieta = Dieta.omnivora
    alergias: list[Alergia] = []
    no_le_gusta: list[Ingrediente] = Field(default=[], max_length=20)
    porciones: int = Field(default=2, ge=1, le=12)
    tiempo_max_minutos: int | None = Field(default=None, ge=5, le=600)

    @field_validator("alergias", "no_le_gusta")
    @classmethod
    def sin_repetidos(cls, valores: list[str]) -> list[str]:
        """Quita repetidos conservando el orden ("Cebolla" y "cebolla" cuentan como uno)."""
        vistos: set[str] = set()
        unicos = []
        for valor in valores:
            if valor.lower() not in vistos:
                vistos.add(valor.lower())
                unicos.append(valor)
        return unicos
