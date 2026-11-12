"""Lectura de CORS_ORIGINS desde la env var: JSON o separada por comas."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def cors_desde_env(monkeypatch, valor: str) -> list[str]:
    monkeypatch.setenv("CORS_ORIGINS", valor)
    # _env_file=None: que no influya el .env local, solo la env var.
    return Settings(_env_file=None).cors_origins


@pytest.mark.parametrize(
    "valor",
    [
        '["http://a.com","http://b.com"]',
        '[" http://a.com ", "", "http://b.com"]',  # JSON con espacios y vacíos
        "http://a.com,http://b.com",
        " http://a.com , http://b.com ,",  # comas con espacios y una coma al final
    ],
)
def test_json_o_separado_por_comas(monkeypatch, valor):
    assert cors_desde_env(monkeypatch, valor) == ["http://a.com", "http://b.com"]


def test_un_solo_valor(monkeypatch):
    assert cors_desde_env(monkeypatch, "https://foodmesh.example") == ["https://foodmesh.example"]


@pytest.mark.parametrize("valor", ["", "   ", "[]", ","])
def test_vacio_no_permite_ningun_origen(monkeypatch, valor):
    assert cors_desde_env(monkeypatch, valor) == []


def test_json_mal_formado_da_un_error_claro(monkeypatch):
    with pytest.raises(ValidationError, match="CORS_ORIGINS no es una lista JSON válida"):
        cors_desde_env(monkeypatch, '["http://a.com"')


def test_sin_env_var_usa_el_valor_por_defecto(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert Settings(_env_file=None).cors_origins == ["http://localhost:5173"]
