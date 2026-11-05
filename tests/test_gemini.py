"""Timeout y reintento de las llamadas a Gemini (app/core/gemini.py), con un cliente falso."""

import logging
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors, types

from app.core import gemini
from app.ocr.normalizacion import RespuestaNormalizacion, normalizar_items
from app.recommendations.generacion import generar_recetas
from app.recommendations.schemas import RespuestaRecetasIA


def error_api(codigo: int) -> errors.APIError:
    clase = errors.ServerError if codigo >= 500 else errors.ClientError
    return clase(codigo, {"error": {"code": codigo, "message": "falso", "status": "X"}})


class ClienteFalso:
    """Hace de genai.Client: cada llamada lanza o devuelve el siguiente elemento de
    `resultados`, y guarda los argumentos con los que se llamó."""

    def __init__(self, *resultados):
        self.resultados = list(resultados)
        self.llamadas = []
        self.models = SimpleNamespace(generate_content=self._generate_content)

    def _generate_content(self, **kwargs):
        self.llamadas.append(kwargs)
        resultado = self.resultados.pop(0)
        if isinstance(resultado, Exception):
            raise resultado
        return resultado


RESPUESTA = SimpleNamespace(text="{}")


@pytest.fixture
def esperas(monkeypatch):
    """Reemplaza la espera entre intentos: registra cuánto se habría esperado."""
    esperas = []
    monkeypatch.setattr(gemini, "_esperar", esperas.append)
    return esperas


def llamar(cliente, timeout=30):
    return gemini.generar_contenido(
        cliente,
        "pruebas",
        modelo="modelo",
        contenido="hola",
        config=types.GenerateContentConfig(temperature=0),
        timeout_segundos=timeout,
    )


@pytest.mark.parametrize(
    ("error", "motivo"),
    [
        (error_api(503), "HTTP 503"),
        (error_api(429), "HTTP 429"),
        (error_api(504), "timeout"),
        (httpx.ReadTimeout("lento"), "timeout"),
    ],
)
def test_reintenta_una_vez_ante_errores_pasajeros(esperas, caplog, error, motivo):
    cliente = ClienteFalso(error, RESPUESTA)
    with caplog.at_level(logging.INFO, logger="app.core.gemini"):
        assert llamar(cliente).respuesta is RESPUESTA

    assert len(cliente.llamadas) == 2
    [espera] = esperas
    assert 2 <= espera <= 4
    assert "intento HTTP 1/2: falló en" in caplog.text
    assert f"({motivo}), reintento por error de red/timeout/servidor" in caplog.text
    assert "Gemini pruebas [modelo], intento HTTP 2/2:" in caplog.text
    assert " ms, tokens" in caplog.text


@pytest.mark.parametrize("codigo", [400, 404])
def test_no_reintenta_errores_de_la_peticion(esperas, caplog, codigo):
    cliente = ClienteFalso(error_api(codigo), RESPUESTA)
    with pytest.raises(errors.ClientError):
        llamar(cliente)

    assert len(cliente.llamadas) == 1
    assert esperas == []
    assert "intento HTTP 1/2: falló" in caplog.text and "sin más reintentos" in caplog.text


def test_otros_errores_no_se_reintentan(esperas):
    cliente = ClienteFalso(ValueError("raro"), RESPUESTA)
    with pytest.raises(ValueError):
        llamar(cliente)
    assert len(cliente.llamadas) == 1


def test_si_el_reintento_tambien_falla_lanza_el_error(esperas, caplog):
    cliente = ClienteFalso(error_api(503), error_api(503), RESPUESTA)
    with pytest.raises(errors.ServerError):
        llamar(cliente)

    assert len(cliente.llamadas) == 2  # un solo reintento
    assert len(esperas) == 1
    assert "intento HTTP 2/2: falló" in caplog.text
    assert "(HTTP 503), sin más reintentos" in caplog.text


def test_el_timeout_se_pasa_en_milisegundos_sin_cambiar_la_config_original(esperas):
    config = types.GenerateContentConfig(temperature=0)
    cliente = ClienteFalso(RESPUESTA)
    gemini.generar_contenido(
        cliente, "pruebas", modelo="m", contenido="x", config=config, timeout_segundos=12.5
    )

    assert cliente.llamadas[0]["config"].http_options.timeout == 12500
    assert cliente.llamadas[0]["config"].temperature == 0
    assert config.http_options is None


def test_timeouts_interactivo_y_de_fondo(esperas, monkeypatch):
    """POST de recetas y facturas usan el interactivo; el precálculo, el de fondo."""
    from app.core.config import get_settings
    from app.recommendations import generacion

    monkeypatch.setattr(get_settings(), "gemini_timeout_interactivo", 45)
    monkeypatch.setattr(get_settings(), "gemini_timeout_fondo", 90)
    sin_recetas = RespuestaRecetasIA(recetas=[]).model_dump_json()
    cliente = ClienteFalso(*[SimpleNamespace(text=sin_recetas)] * 2)
    monkeypatch.setattr(generacion, "cliente_gemini", lambda: cliente)
    facturas = ClienteFalso(
        SimpleNamespace(text=RespuestaNormalizacion(items=[]).model_dump_json())
    )

    generacion.generar_con_gemini("x")
    generacion.generar_con_gemini_en_fondo("x")
    normalizar_items("x", facturas, "m")

    timeouts = [llamada["config"].http_options.timeout for llamada in cliente.llamadas]
    assert timeouts == [45_000, 90_000]
    assert facturas.llamadas[0]["config"].http_options.timeout == 45_000
    assert facturas.llamadas[0]["config"].thinking_config.thinking_level == "MINIMAL"


def test_recetas_reintentan_ante_un_503(esperas):
    cliente = ClienteFalso(
        error_api(503), SimpleNamespace(text=RespuestaRecetasIA(recetas=[]).model_dump_json())
    )
    assert generar_recetas("x", cliente, "m").recetas == []
    assert len(cliente.llamadas) == 2


# --- Modelo de respaldo ---


def llamar_con_respaldo(cliente, respaldo="respaldo"):
    return gemini.generar_contenido(
        cliente,
        "pruebas",
        modelo="principal",
        modelo_respaldo=respaldo,
        contenido="hola",
        config=types.GenerateContentConfig(temperature=0),
        timeout_segundos=30,
    )


def _modelos(cliente) -> list[str]:
    return [llamada["model"] for llamada in cliente.llamadas]


@pytest.mark.parametrize(
    "error", [error_api(503), error_api(429), error_api(504), httpx.ReadTimeout("lento")]
)
def test_si_el_principal_agota_sus_reintentos_responde_el_respaldo(esperas, caplog, error):
    cliente = ClienteFalso(error, error, RESPUESTA)
    with caplog.at_level(logging.INFO, logger="app.core.gemini"):
        resultado = llamar_con_respaldo(cliente)

    assert resultado.respuesta is RESPUESTA
    assert resultado.modelo == "respaldo"
    assert _modelos(cliente) == ["principal", "principal", "respaldo"]
    assert len(esperas) == 1  # solo entre los dos intentos del principal
    assert "principal agotó sus reintentos" in caplog.text
    assert "Gemini pruebas [respaldo], respaldo:" in caplog.text


def test_si_el_principal_responde_no_se_usa_el_respaldo(esperas):
    cliente = ClienteFalso(error_api(503), RESPUESTA)
    resultado = llamar_con_respaldo(cliente)

    assert resultado.modelo == "principal"
    assert _modelos(cliente) == ["principal", "principal"]


@pytest.mark.parametrize("codigo", [400, 404])
def test_errores_de_la_peticion_no_pasan_al_respaldo(esperas, codigo):
    cliente = ClienteFalso(error_api(codigo), RESPUESTA)
    with pytest.raises(errors.ClientError):
        llamar_con_respaldo(cliente)

    assert _modelos(cliente) == ["principal"]


def test_si_el_respaldo_tambien_falla_lanza_su_error(esperas, caplog):
    cliente = ClienteFalso(error_api(503), error_api(503), error_api(429), RESPUESTA)
    with pytest.raises(errors.ClientError) as excinfo:
        llamar_con_respaldo(cliente)

    assert excinfo.value.code == 429
    assert _modelos(cliente) == ["principal", "principal", "respaldo"]  # un solo intento
    assert "Gemini pruebas [respaldo], respaldo: falló" in caplog.text


@pytest.mark.parametrize("respaldo", [None, "", "principal"])
def test_sin_respaldo_o_igual_al_principal_falla_como_antes(esperas, respaldo):
    cliente = ClienteFalso(error_api(503), error_api(503), RESPUESTA)
    with pytest.raises(errors.ServerError):
        llamar_con_respaldo(cliente, respaldo=respaldo)

    assert _modelos(cliente) == ["principal", "principal"]


def test_recetas_y_facturas_usan_su_modelo_de_respaldo(esperas, monkeypatch):
    from app.core.config import get_settings
    from app.ocr import normalizacion
    from app.recommendations import generacion

    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_model_recetas", "principal-recetas")
    monkeypatch.setattr(settings, "gemini_model_recetas_respaldo", "respaldo-recetas")
    monkeypatch.setattr(settings, "gemini_model", "principal-facturas")
    monkeypatch.setattr(settings, "gemini_model_respaldo", "respaldo-facturas")
    sin_recetas = SimpleNamespace(text=RespuestaRecetasIA(recetas=[]).model_dump_json())
    sin_items = SimpleNamespace(text=RespuestaNormalizacion(items=[]).model_dump_json())
    recetas = ClienteFalso(*[error_api(503)] * 2, sin_recetas, *[error_api(503)] * 2, sin_recetas)
    facturas = ClienteFalso(error_api(503), error_api(503), sin_items)
    monkeypatch.setattr(generacion, "cliente_gemini", lambda: recetas)
    monkeypatch.setattr(normalizacion, "cliente_gemini", lambda: facturas)

    assert generacion.generar_con_gemini("x").modelo == "respaldo-recetas"
    assert generacion.generar_con_gemini_en_fondo("x").modelo == "respaldo-recetas"
    assert normalizacion.normalizar_con_gemini("x") == []
    assert _modelos(facturas)[-1] == "respaldo-facturas"
