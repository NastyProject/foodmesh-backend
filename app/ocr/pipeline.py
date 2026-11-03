"""Orquesta las etapas: imagen → preprocesamiento → OCR → recorte → anonimización →
normalización."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from app.ocr import anonimizacion, encabezado, extraccion, preprocesamiento, recorte
from app.ocr.normalizacion import ItemDetectado, ItemPropuesto, a_propuesto, cuadran

logger = logging.getLogger(__name__)

# Cualquier función texto → ítems. En producción es Gemini; en tests, un falso.
Normalizador = Callable[[str], list[ItemDetectado]]


@dataclass
class ResultadoPipeline:
    texto_ocr: str | None  # texto completo, ya anonimizado
    # Lo que realmente se le envía al normalizador (anonimizado; recortado si se pudo).
    texto_enviado: str | None = None
    # True si se encontró el bloque de productos y solo se envió ese.
    recortada: bool = False
    supermercado: str | None = None
    fecha_compra: date | None = None
    # TOTAL que trae la factura y suma de precio_total de los ítems detectados.
    total_impreso: float | None = None
    total_calculado: float | None = None
    items: list[ItemPropuesto] = field(default_factory=list)
    error: str | None = None

    @property
    def requiere_revision(self) -> bool:
        """True si la suma de los ítems no coincide con el TOTAL impreso, o si no se
        pudo comparar (no se encontró el TOTAL o no hubo ítems): lo que no se puede
        verificar, se revisa."""
        if self.total_impreso is None or self.total_calculado is None:
            return True
        return not cuadran(self.total_calculado, self.total_impreso)


def procesar_factura(imagen: bytes, normalizar: Normalizador) -> ResultadoPipeline:
    """Corre todo el pipeline. Nunca lanza excepción: si una etapa falla, lo
    indica en `error` y devuelve lo que alcanzó a obtener."""
    try:
        procesada = preprocesamiento.preprocesar(preprocesamiento.decodificar(imagen))
        texto_crudo = extraccion.extraer_texto(procesada)
    except Exception:
        logger.exception("Falló el OCR de la factura")
        return ResultadoPipeline(texto_ocr=None, error="No se pudo leer el texto de la imagen.")

    # El texto crudo (con posibles datos personales) no sale de esta función.
    # Supermercado y fecha se sacan aquí con reglas locales: el encabezado no se envía.
    datos_encabezado = encabezado.extraer_encabezado(texto_crudo)
    bloque = recorte.recortar_productos(texto_crudo)
    texto = anonimizacion.anonimizar(texto_crudo).strip()
    # La anonimización se aplica también al bloque, por si quedó algún dato personal.
    texto_enviado = anonimizacion.anonimizar(bloque).strip() if bloque else texto

    resultado = ResultadoPipeline(
        texto_ocr=texto,
        texto_enviado=texto_enviado,
        recortada=bloque is not None,
        supermercado=datos_encabezado.supermercado,
        fecha_compra=datos_encabezado.fecha_compra,
        total_impreso=recorte.extraer_total_impreso(texto_crudo),
    )
    if not texto:
        resultado.error = "No se detectó texto en la imagen."
        return resultado

    try:
        detectados = normalizar(texto_enviado)
    except Exception:
        logger.exception("Falló la normalización de la factura")
        resultado.error = "No se pudieron identificar los productos de la factura."
        return resultado
    resultado.items = [a_propuesto(item) for item in detectados]
    # Un ítem sin precio_total cuenta como 0: la suma no cuadrará y se pedirá revisión.
    resultado.total_calculado = sum(item.precio_total or 0 for item in resultado.items)
    return resultado
