"""Pedirle a Gemini recetas con lo que hay en el inventario.

Igual que en facturas, se usa structured output: Gemini responde con la forma
exacta de RespuestaRecetasIA. A Gemini solo le llega lo que está en el texto de
entrada (ítems con un id corto y preferencias), nunca datos del hogar.
"""

from collections.abc import Callable
from dataclasses import dataclass

from google import genai
from google.genai import types

from app.core.config import get_settings
from app.core.gemini import THINKING_MINIMO, cliente_gemini, generar_contenido
from app.preferences.schemas import Preferencias
from app.recommendations.schemas import RecetaIA, RespuestaRecetasIA

# Cambiarla cuando cambie el prompt o la forma de la entrada: hace parte de la clave
# del caché, así que invalida las recetas generadas con la versión anterior.
VERSION_PROMPT = "3"
NUMERO_RECETAS = 3
# Un ítem que vence en estos días o menos se considera "próximo a vencer".
DIAS_PROXIMO_A_VENCER = 3
# Tope de tokens de salida. Tres recetas ocupan ~1000-1700 tokens; el tope solo evita
# una respuesta desbocada (no acelera las normales). Si se alcanza, el JSON queda
# cortado y la llamada falla, así que debe quedar holgado.
MAX_TOKENS_SALIDA = 4096


@dataclass
class RecetasGeneradas:
    recetas: list[RecetaIA]
    # El modelo que respondió de verdad (puede ser el de respaldo). Va a la clave de la
    # caché y al registro de la recomendación.
    modelo: str


# Cualquier función texto → recetas. En producción es Gemini; en tests, un falso.
Generador = Callable[[str], RecetasGeneradas]


@dataclass
class ItemParaReceta:
    id_corto: str  # "p1", "p2"...: lo único que identifica al ítem ante Gemini
    nombre: str
    cantidad: float
    unidad: str
    dias_para_vencer: int | None


INSTRUCCIONES = f"""\
Eres un asistente de cocina para hogares colombianos. Tu objetivo es reducir el \
desperdicio de alimentos: propones recetas que aprovechan lo que el hogar ya tiene, \
sobre todo lo que está por vencerse.

Recibes la lista de alimentos disponibles (cada uno con un id como "p1", su cantidad \
y en cuántos días vence) y las preferencias del hogar. Propón exactamente \
{NUMERO_RECETAS} recetas.

Reglas:
- Prioriza los alimentos que vencen en {DIAS_PROXIMO_A_VENCER} días o menos: cada \
receta debería usar al menos uno si existe.
- Respeta estrictamente la dieta y las alergias: ningún ingrediente puede contener un \
alérgeno declarado, ni siquiera como derivado (por ejemplo, con alergia a lácteos no \
uses leche, queso, mantequilla, crema ni yogur).
- Dietas: vegetariana es sin carnes (res, cerdo, pollo, embutidos), sin pescado y sin \
mariscos; pescetariana es sin carnes, pero con pescado y mariscos; vegana es como \
vegetariana y además sin lácteos, huevo ni miel de abejas (la miel de panela sí).
- No uses los ingredientes que al hogar no le gustan.
- Si hay un tiempo máximo, tiempo_minutos no puede superarlo.
- Las porciones deben ser las que pide el hogar.
- Prefiere cocina casera colombiana cuando tenga sentido (arepas, sudados, calentado, \
caldos, arroces, ensaladas, jugos naturales), con ingredientes fáciles de conseguir.
- Agua, sal, aceite, azúcar y pimienta (en cualquier variante: agua sin gas, aceite \
vegetal, sal marina...) se consideran siempre disponibles: úsalos libremente, con \
item_id null, aunque no estén en la lista.
- Las {NUMERO_RECETAS} recetas deben ser distintas entre sí: no repitas la misma base \
principal con la misma proteína, y varía la técnica (sopa, salteado, horneado, \
ensalada, guiso, arroz, tortilla...).
- Usa solo alimentos. Nunca uses productos de aseo, cuidado personal ni para mascotas \
como ingrediente, aunque aparezcan en la lista.

Para cada receta:
- titulo y descripcion (una frase), en español.
- tiempo_minutos y porciones.
- ingredientes: de más a menos importante (primero la base y la proteína), con \
nombre, cantidad y unidad (null si es "al gusto"). En item_id pon el id del alimento \
de la lista que usa ("p1"), o null si hay que comprarlo o es un básico. Usa solo ids \
que estén en la lista.
- pasos: como máximo 6, cortos y en orden.
- por_que: en una frase, qué productos próximos a vencer aprovecha y por qué la \
receta es una buena forma de usarlos.\
"""


def _describir_vencimiento(dias: int | None) -> str:
    if dias is None:
        return "sin fecha de vencimiento"
    if dias == 0:
        return "vence hoy"
    return f"vence en {dias} día{'s' if dias != 1 else ''}"


def armar_entrada(
    items: list[ItemParaReceta],
    preferencias: Preferencias,
    *,
    evitar: list[str] | None = None,
    incumplidas: list[str] | None = None,
) -> str:
    """Texto que se le envía a Gemini. Solo ítems (con id corto), preferencias y,
    opcionalmente, títulos de recetas a evitar y por qué se rechazó un intento anterior.
    Nunca datos del hogar."""
    lineas = ["Alimentos disponibles:"]
    lineas += [
        f"- {item.id_corto}: {item.nombre}, {item.cantidad:g} {item.unidad}, "
        f"{_describir_vencimiento(item.dias_para_vencer)}"
        for item in items
    ]
    lineas += [
        "",
        "Preferencias del hogar:",
        f"- Dieta: {preferencias.dieta.value}",
        f"- Alergias: {', '.join(preferencias.alergias) or 'ninguna'}",
        f"- No le gusta: {', '.join(preferencias.no_le_gusta) or 'nada en particular'}",
        f"- Porciones: {preferencias.porciones}",
        "- Tiempo máximo: "
        + (
            f"{preferencias.tiempo_max_minutos} minutos"
            if preferencias.tiempo_max_minutos
            else "sin límite"
        ),
    ]
    if evitar:
        lineas += ["", "Ya se le propusieron estas recetas; propón otras distintas:"]
        lineas += [f"- {titulo}" for titulo in evitar]
    if incumplidas:
        lineas += [
            "",
            "IMPORTANTE: tus recetas anteriores no cumplían las restricciones del hogar y "
            "se descartaron. Propón otras que las cumplan estrictamente:",
        ]
        lineas += [f"- {motivo}" for motivo in incumplidas]
    return "\n".join(lineas)


def generar_recetas(
    texto: str,
    cliente: genai.Client,
    modelo: str,
    *,
    modelo_respaldo: str | None = None,
    timeout_segundos: float | None = None,
) -> RecetasGeneradas:
    """Sin timeout_segundos usa el interactivo (el usuario está esperando)."""
    resultado = generar_contenido(
        cliente,
        "recetas",
        modelo=modelo,
        modelo_respaldo=modelo_respaldo,
        contenido=texto,
        timeout_segundos=timeout_segundos or get_settings().gemini_timeout_interactivo,
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCCIONES,
            temperature=0.7,  # aquí sí queremos algo de variedad, a diferencia de facturas
            response_mime_type="application/json",
            response_schema=RespuestaRecetasIA,
            max_output_tokens=MAX_TOKENS_SALIDA,
            thinking_config=THINKING_MINIMO,
        ),
    )
    if not resultado.respuesta.text:
        raise ValueError("Gemini no devolvió contenido")
    return RecetasGeneradas(
        recetas=RespuestaRecetasIA.model_validate_json(resultado.respuesta.text).recetas,
        modelo=resultado.modelo,
    )


def generar_con_gemini(texto: str) -> RecetasGeneradas:
    """Generador real para el POST de recetas: timeout interactivo."""
    settings = get_settings()
    return generar_recetas(
        texto,
        cliente_gemini(),
        settings.gemini_model_recetas,
        modelo_respaldo=settings.gemini_model_recetas_respaldo,
    )


def generar_con_gemini_en_fondo(texto: str) -> RecetasGeneradas:
    """Generador real para el precálculo: nadie lo espera, así que tiene un timeout más
    largo y aguanta mejor los picos de latencia de Gemini."""
    settings = get_settings()
    return generar_recetas(
        texto,
        cliente_gemini(),
        settings.gemini_model_recetas,
        modelo_respaldo=settings.gemini_model_recetas_respaldo,
        timeout_segundos=settings.gemini_timeout_fondo,
    )
