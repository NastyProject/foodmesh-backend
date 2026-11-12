import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    # Calidad mínima de la foto de una factura, antes del OCR. Si no la cumple, POST
    # /facturas responde 422 sin llamar a Gemini. QUALITY_MIN_ENFOQUE es la varianza
    # del laplaciano (calibrarla con scripts/probar_factura.py, que la muestra);
    # QUALITY_MIN_LADO_PX, el lado mayor de la foto en píxeles.
    # El enfoque es solo un filtro rápido de fotos MUY desenfocadas (no separa fotos
    # legibles de ilegibles: eso lo hace la legibilidad del OCR, abajo). Bajo a
    # propósito, para no rechazar fotos que se leen bien (20.jpeg dio 277).
    quality_min_enfoque: float = 50
    quality_min_lado_px: int = 600
    # Legibilidad del OCR, medida después de Tesseract y antes de Gemini (ver
    # app/ocr/legibilidad.py). Confianza media de Tesseract (0-100) y proporción de
    # tokens legibles (0-1). Con las facturas reales, los tokens dieron 0.26-0.28 en
    # las ilegibles y 0.36 o más en las legibles: calibrar con probar_factura.py.
    quality_min_confianza_ocr: float = 45
    quality_min_tokens_legibles: float = 0.32
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
    # Orígenes del frontend que pueden llamar a la API desde el navegador. En la env
    # var se aceptan separados por comas (CORS_ORIGINS=http://a.com,http://b.com) o
    # como lista JSON (CORS_ORIGINS=["http://a.com","http://b.com"]).
    # NoDecode: sin él, pydantic-settings intenta leer cualquier lista como JSON y
    # falla con "http://a.com" antes de llegar al validador.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _separar_origenes(cls, valor: object) -> object:
        """Texto de la env var → lista de orígenes, sin espacios ni valores vacíos."""
        if isinstance(valor, str):
            texto = valor.strip()
            if texto.startswith("["):
                try:
                    valor = json.loads(texto)
                except json.JSONDecodeError as error:
                    raise ValueError(f"CORS_ORIGINS no es una lista JSON válida: {error}") from None
            else:
                valor = texto.split(",")
        if isinstance(valor, list):
            return [o.strip() for o in valor if isinstance(o, str) and o.strip()]
        return valor  # otro tipo: que lo rechace la validación normal de list[str]


@lru_cache
def get_settings() -> Settings:
    return Settings()
