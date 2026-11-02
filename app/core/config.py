from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str = "postgresql+psycopg://foodmesh:foodmesh@localhost:5432/foodmesh"
    auth0_domain: str = ""
    auth0_audience: str = ""
    llm_api_key: str = ""
    # Orígenes del frontend que pueden llamar a la API desde el navegador.
    # En env var va como lista JSON: CORS_ORIGINS='["http://localhost:5173"]'
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()