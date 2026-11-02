from pydantic import BaseModel, ConfigDict


class UsuarioOut(BaseModel):
    """Datos del propio usuario. Aquí sí va hogar_id porque es su propio hogar."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str | None
    hogar_id: int
