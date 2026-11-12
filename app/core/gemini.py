import logging
import random
import time
from dataclasses import dataclass
from functools import lru_cache

import httpx
from google import genai
from google.genai import errors, types

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Thinking al mínimo: ni facturas ni recetas necesitan razonamiento largo, y los tokens
# de thinking se generan antes de la respuesta (suman latencia). Los modelos Gemini 3
# no permiten apagarlo del todo; "minimal" es el nivel más bajo y lo aceptan
# gemini-3.5-flash-lite, gemini-3.6-flash y gemini-3-flash-preview. Si se cambia a un
# modelo que no lo acepta (p. ej. los "pro"), la API responde 400: usar LOW.
THINKING_MINIMO = types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL)

# Reintento: una sola vez, y solo ante errores pasajeros. 429 es límite de cuota por
# minuto, 503 es "modelo saturado" y 504 es que se cumplió el deadline en el servidor.
# Un 400 o 404 (petición o modelo inválidos) fallaría igual al repetirlo.
MAX_INTENTOS = 2
CODIGOS_REINTENTABLES = {429, 503, 504}
# Espera al azar en este rango antes de reintentar: si muchas peticiones fallan a la
# vez, no reintentan todas en el mismo instante.
ESPERA_REINTENTO_SEGUNDOS = (2.0, 4.0)
# Si el modelo principal agota sus intentos por un error pasajero, se hace UN intento
# más con el modelo de respaldo (otro modelo suele tener otra carga). En el peor caso,
# una llamada hace MAX_INTENTOS + 1 peticiones.
INTENTOS_CON_RESPALDO = MAX_INTENTOS + 1


@lru_cache
def cliente_gemini() -> genai.Client:
    """Cliente compartido por facturas y recetas. Se crea una sola vez por proceso."""
    api_key = get_settings().gemini_api_key
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY no está configurada")
    return genai.Client(api_key=api_key)


def _motivo_reintentable(error: Exception) -> str | None:
    """Por qué vale la pena reintentar (para el log), o None si no se debe reintentar."""
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, errors.APIError) and error.code in CODIGOS_REINTENTABLES:
        return "timeout" if error.code == 504 else f"HTTP {error.code}"
    return None


def _esperar(segundos: float) -> None:
    # Función aparte para que los tests la reemplacen y no esperen de verdad.
    time.sleep(segundos)


def _registrar_exito(etapa: str, modelo: str, intento: str, ms: int, respuesta) -> None:
    """Deja en el log qué modelo respondió, cuánto tardó y cuántos tokens usó (entrada,
    thinking y salida), para diagnosticar de dónde sale la latencia."""
    uso = getattr(respuesta, "usage_metadata", None)  # los falsos de los tests no lo traen
    logger.info(
        "Gemini %s [%s], %s: %d ms, tokens entrada=%s thinking=%s salida=%s",
        etapa,
        modelo,
        intento,
        ms,
        uso.prompt_token_count if uso else None,
        uso.thoughts_token_count if uso else None,
        uso.candidates_token_count if uso else None,
    )


@dataclass
class RespuestaGemini:
    respuesta: types.GenerateContentResponse
    modelo: str  # el que respondió de verdad: el principal o el de respaldo


def _con_reintento(
    cliente: genai.Client,
    etapa: str,
    modelo: str,
    contenido: types.ContentListUnion,
    config: types.GenerateContentConfig,
) -> types.GenerateContentResponse:
    """Hasta MAX_INTENTOS llamadas al mismo modelo; reintenta solo errores pasajeros."""
    for intento in range(1, MAX_INTENTOS + 1):
        etiqueta = f"intento HTTP {intento}/{MAX_INTENTOS}"
        inicio = time.perf_counter()
        try:
            respuesta = cliente.models.generate_content(
                model=modelo, contents=contenido, config=config
            )
        except Exception as error:
            ms = round((time.perf_counter() - inicio) * 1000)
            motivo = _motivo_reintentable(error)
            if motivo is None or intento == MAX_INTENTOS:
                logger.warning(
                    "Gemini %s [%s], %s: falló en %d ms (%s), sin más reintentos",
                    etapa,
                    modelo,
                    etiqueta,
                    ms,
                    motivo or type(error).__name__,
                )
                raise
            espera = random.uniform(*ESPERA_REINTENTO_SEGUNDOS)
            logger.warning(
                "Gemini %s [%s], %s: falló en %d ms (%s), reintento por error "
                "de red/timeout/servidor en %.1f s",
                etapa,
                modelo,
                etiqueta,
                ms,
                motivo,
                espera,
            )
            _esperar(espera)
            continue
        _registrar_exito(
            etapa, modelo, etiqueta, round((time.perf_counter() - inicio) * 1000), respuesta
        )
        return respuesta
    raise AssertionError("inalcanzable: el último intento retorna o lanza")


def generar_contenido(
    cliente: genai.Client,
    etapa: str,
    *,
    modelo: str,
    contenido: types.ContentListUnion,
    config: types.GenerateContentConfig,
    timeout_segundos: float,
    modelo_respaldo: str | None = None,
) -> RespuestaGemini:
    """generate_content con timeout, un reintento ante errores pasajeros y, si aun así
    falla por uno de esos errores, un intento con `modelo_respaldo`.

    `etapa` ("recetas", "facturas") solo sirve para el log. El timeout es por petición:
    en el peor caso la función tarda INTENTOS_CON_RESPALDO × timeout más la espera
    entre intentos. Un 400 o 404 no pasa al respaldo: es un problema de la petición (o
    del nombre del modelo), y hay que verlo en vez de taparlo.
    """
    # El SDK manda el timeout también al servidor, como deadline (mínimo 10 s).
    config = config.model_copy(
        update={"http_options": types.HttpOptions(timeout=round(timeout_segundos * 1000))}
    )
    try:
        return RespuestaGemini(_con_reintento(cliente, etapa, modelo, contenido, config), modelo)
    except Exception as error:
        motivo = _motivo_reintentable(error)
        if motivo is None or not modelo_respaldo or modelo_respaldo == modelo:
            raise
        logger.warning(
            "Gemini %s: %s agotó sus reintentos (%s), se intenta una vez con el modelo de "
            "respaldo %s",
            etapa,
            modelo,
            motivo,
            modelo_respaldo,
        )

    inicio = time.perf_counter()
    try:
        respuesta = cliente.models.generate_content(
            model=modelo_respaldo, contents=contenido, config=config
        )
    except Exception as error:
        logger.warning(
            "Gemini %s [%s], respaldo: falló en %d ms (%s), sin más reintentos",
            etapa,
            modelo_respaldo,
            round((time.perf_counter() - inicio) * 1000),
            _motivo_reintentable(error) or type(error).__name__,
        )
        raise
    ms = round((time.perf_counter() - inicio) * 1000)
    _registrar_exito(etapa, modelo_respaldo, "respaldo", ms, respuesta)
    return RespuestaGemini(respuesta, modelo_respaldo)
