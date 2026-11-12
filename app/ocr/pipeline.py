"""Orquesta las etapas: imagen → preprocesamiento → OCR → legibilidad → recorte →
anonimización → normalización → anclaje."""

import logging
from dataclasses import dataclass, field
from datetime import date

from app.core.config import get_settings
from app.ocr import anclaje, anonimizacion, encabezado, extraccion, preprocesamiento, recorte
from app.ocr.legibilidad import Legibilidad, es_legible, medir_legibilidad
from app.ocr.normalizacion import (
    ItemPropuesto,
    Normalizador,
    NormalizadorImagen,
    a_propuesto,
    cuadran,
)

logger = logging.getLogger(__name__)


ILEGIBLE = "El texto de la foto no se pudo leer."
SIN_PRODUCTOS_EN_EL_TEXTO = (
    "No encontramos los productos en el texto de la factura. Puedes reintentar "
    "leyéndola con la imagen."
)


def requiere_revision(total_impreso: float | None, total_calculado: float | None) -> bool:
    """True si la suma de los ítems no coincide con el TOTAL impreso, o si no se
    pudo comparar (no se encontró el TOTAL o no hubo ítems): lo que no se puede
    verificar, se revisa."""
    if total_impreso is None or total_calculado is None:
        return True
    return not cuadran(total_calculado, total_impreso)


def total_de(items: list[ItemPropuesto]) -> float:
    # Un ítem sin precio_total cuenta como 0: la suma no cuadrará y se pedirá revisión.
    return sum(item.precio_total or 0 for item in items)


@dataclass
class ResultadoPipeline:
    # Texto completo, ya anonimizado. Solo vive en memoria (lo muestra el script de
    # pruebas): NO se guarda, porque la anonimización puede dejar escapar algún dato.
    texto_completo: str | None
    # Lo que realmente se le envía al normalizador, anonimizado: el bloque de productos
    # o, si no se encontró, solo las líneas que parecen de productos. Nunca el texto
    # completo. None si no hay nada que enviar (y entonces no se llama a Gemini).
    texto_enviado: str | None = None
    # True si se encontró el bloque de productos y solo se envió ese.
    recortada: bool = False
    supermercado: str | None = None
    fecha_compra: date | None = None
    # TOTAL que trae la factura y suma de precio_total de los ítems detectados.
    total_impreso: float | None = None
    total_calculado: float | None = None
    items: list[ItemPropuesto] = field(default_factory=list)
    # Ítems que devolvió Gemini pero cuya descripción no aparece en el texto enviado.
    items_descartados: int = 0
    # Lo que leyó el OCR: confianza de Tesseract y proporción de tokens legibles.
    legibilidad: Legibilidad | None = None
    # "imagen_ilegible" si el OCR leyó basura: no se llamó a Gemini y la API responde 422.
    problema_calidad: str | None = None
    error: str | None = None

    @property
    def requiere_revision(self) -> bool:
        return requiere_revision(self.total_impreso, self.total_calculado)

    @property
    def texto_guardado(self) -> str | None:
        """Lo único del texto que se guarda en la factura (minimización de datos): lo
        que se le envió a Gemini (el bloque de productos, o las líneas de productos).
        El texto completo nunca se guarda."""
        return self.texto_enviado


def procesar_factura(
    imagen: bytes, normalizar: Normalizador, *, validar_legibilidad: bool = True
) -> ResultadoPipeline:
    """Corre todo el pipeline. Nunca lanza excepción: si una etapa falla, lo
    indica en `error` y devuelve lo que alcanzó a obtener.

    Si el OCR leyó basura (validar_legibilidad), se detiene antes de Gemini y deja
    problema_calidad = "imagen_ilegible".
    """
    try:
        procesada = preprocesamiento.preprocesar(preprocesamiento.decodificar(imagen))
        lectura = extraccion.leer(procesada)
    except Exception:
        logger.exception("Falló el OCR de la factura")
        return ResultadoPipeline(
            texto_completo=None, error="No se pudo leer el texto de la imagen."
        )

    texto_crudo = lectura.texto
    legibilidad = medir_legibilidad(lectura)
    # El texto crudo (con posibles datos personales) no sale de esta función.
    # Supermercado y fecha se sacan aquí con reglas locales: el encabezado no se envía.
    datos_encabezado = encabezado.extraer_encabezado(texto_crudo)
    bloque = recorte.recortar_productos(texto_crudo)
    texto = anonimizacion.anonimizar(texto_crudo).strip()
    if bloque:
        # La anonimización se aplica también al bloque, por si quedó algún dato personal.
        texto_enviado = anonimizacion.anonimizar(bloque).strip()
    else:
        # Sin bloque, el texto completo NO se envía: en facturas reales se filtraban
        # nombres, barrios, emails y dígitos de tarjeta que la anonimización no
        # reconoció. Solo las líneas que parecen de productos (del texto ya anonimizado).
        texto_enviado = recorte.lineas_de_productos(texto)

    resultado = ResultadoPipeline(
        texto_completo=texto,
        texto_enviado=texto_enviado,
        recortada=bloque is not None,
        supermercado=datos_encabezado.supermercado,
        fecha_compra=datos_encabezado.fecha_compra,
        total_impreso=recorte.extraer_total_impreso(texto_crudo),
        legibilidad=legibilidad,
    )
    if not texto:
        resultado.error = "No se detectó texto en la imagen."
        return resultado
    settings = get_settings()
    if validar_legibilidad and not es_legible(
        legibilidad, settings.quality_min_confianza_ocr, settings.quality_min_tokens_legibles
    ):
        # El enfoque de la foto puede ser bueno y el OCR igual leer basura (fotos 3 y 4
        # del compañero B). De esa basura, Gemini "rescataba" productos inventados.
        resultado.problema_calidad = "imagen_ilegible"
        resultado.error = ILEGIBLE
        return resultado
    if not texto_enviado:
        # Nada que parezca un producto: no se llama a Gemini con el texto. Queda el
        # reproceso con la imagen, si el usuario lo autoriza.
        resultado.error = SIN_PRODUCTOS_EN_EL_TEXTO
        return resultado

    try:
        detectados = normalizar(texto_enviado)
    except Exception:
        logger.exception("Falló la normalización de la factura")
        resultado.error = "No se pudieron identificar los productos de la factura."
        return resultado
    # Lo que devolvió Gemini se ancla al texto que se le envió (códigos, precios y
    # descripciones que de verdad están ahí): ver app/ocr/anclaje.py.
    anclados = anclaje.anclar(detectados, texto_enviado)
    resultado.items = anclados.items
    resultado.items_descartados = anclados.descartados
    resultado.total_calculado = total_de(resultado.items)
    return resultado


@dataclass
class LecturaConImagen:
    items: list[ItemPropuesto]
    # El TOTAL leído de la foto por Gemini. En el modo visión se verifica contra este,
    # no contra el que leyó el OCR (que puede ser justo el que falló).
    total_impreso: float | None


def leer_con_imagen(imagen: bytes, normalizar_imagen: NormalizadorImagen) -> LecturaConImagen:
    """Respaldo con visión: la foto completa al normalizador multimodal. A diferencia
    de procesar_factura, sí lanza la excepción si falla: quien la llama decide."""
    respuesta = normalizar_imagen(imagen)
    return LecturaConImagen(
        items=[a_propuesto(item) for item in respuesta.items],
        total_impreso=respuesta.total_impreso,
    )


def procesar_factura_con_imagen(
    imagen: bytes, normalizar_imagen: NormalizadorImagen
) -> ResultadoPipeline:
    """Como procesar_factura, pero los ítems salen de la foto (visión) y no del texto.

    El OCR local corre igual: de ahí salen el supermercado y la fecha. Los ítems y el
    total impreso (con el que se verifica la suma) salen de la visión. Para el script
    de pruebas y la evaluación; en la API, el reproceso parte de la factura guardada.
    """
    # Sin validar la legibilidad: la visión puede leer fotos que el OCR no entiende.
    resultado = procesar_factura(imagen, lambda texto: [], validar_legibilidad=False)
    if resultado.error and resultado.texto_completo is None:
        return resultado  # ni siquiera se pudo leer la imagen
    try:
        lectura = leer_con_imagen(imagen, normalizar_imagen)
    except Exception:
        logger.exception("Falló la normalización con visión de la factura")
        resultado.items = []
        resultado.total_calculado = None
        resultado.error = "No se pudieron identificar los productos de la factura."
        return resultado
    resultado.items = lectura.items
    resultado.total_impreso = lectura.total_impreso
    resultado.total_calculado = total_de(resultado.items)
    resultado.error = None
    return resultado
