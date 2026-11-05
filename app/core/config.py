from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str = "postgresql+psycopg://foodmesh:foodmesh@localhost:5432/foodmesh"
    auth0_domain: str = ""
    auth0_audience: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"
    # Modelos de respaldo: se usan una vez si el principal agota sus reintentos por
    # 429/503/timeout (ver app/core/gemini.py). Vacío = sin respaldo.
    gemini_model_respaldo: str = "gemini-3.1-flash-lite"
    # Modelo para las recetas, aparte del de facturas: así se pueden comparar o
    # cambiar por separado (p. ej. uno más capaz para recetas).
    gemini_model_recetas: str = "gemini-3.5-flash-lite"
    gemini_model_recetas_respaldo: str = "gemini-3.1-flash-lite"
    # Timeout de cada llamada a Gemini, en segundos (mínimo 10: lo exige la API). Hay
    # un reintento ante 429/503/timeout, así que el peor caso es ~2 × timeout + 4 s.
    # Interactivo: el usuario está esperando (POST de recetas, subir una factura).
    # Fondo: el precálculo de recetas, que nadie espera y puede tardar más.
    gemini_timeout_interactivo: float = 45
    gemini_timeout_fondo: float = 90
    # Generar recetas en segundo plano cuando cambia el inventario o las preferencias,
    # para que el usuario las encuentre en caché.
    precalcular_recetas: bool = True
    # Caché de recetas. Si Redis no responde, la API funciona igual, sin caché.
    redis_url: str = "redis://localhost:6379/0"
    recetas_cache_ttl: int = 86400  # segundos (1 día)
    # Dónde se guardan las imágenes de facturas: disco local o un bucket de S3.
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: str = "./storage"
    s3_bucket: str = ""
    # Orígenes del frontend que pueden llamar a la API desde el navegador.
    # En env var va como lista JSON: CORS_ORIGINS='["http://localhost:5173"]'
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
