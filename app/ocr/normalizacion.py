"""Etapa 4: convertir el texto OCR (ya anonimizado) en ítems estructurados con Gemini.

Usamos structured output: le pasamos a Gemini un modelo Pydantic como esquema y
la API garantiza que la respuesta es un JSON con esa forma (categorías dentro de
la lista cerrada, números donde van números...). Así no hay que "parsear" texto libre.
"""

import re
from functools import lru_cache
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, computed_field

from app.catalog.categorias import Categoria, es_alimento
from app.core.config import get_settings


class ItemDetectado(BaseModel):
    """Lo que Gemini devuelve por cada producto (es el esquema de structured output)."""

    codigo: str | None
    nombre: str
    cantidad: float
    unidad: str
    precio_unitario: float | None
    precio_total: float | None
    categoria: Categoria


class RespuestaNormalizacion(BaseModel):
    items: list[ItemDetectado]


class ItemPropuesto(ItemDetectado):
    """Ítem que se le propone al usuario: lo de Gemini más lo que calculamos nosotros.

    Va aparte de ItemDetectado para que estos campos no formen parte del esquema
    que se le pide a Gemini. Los valores por defecto permiten leer facturas
    guardadas antes de que existieran estos campos.
    """

    codigo: str | None = None
    precio_unitario: float | None = None
    precio_total: float | None = None
    # "catalogo" si el nombre y la categoría salieron del catálogo por el código; "ia" si no.
    origen: Literal["catalogo", "ia"] = "ia"
    # True si los números no cuadran y conviene que el usuario revise el ítem.
    revisar: bool = False

    # computed_field: se calcula de la categoría (no se guarda aparte) y sale en el JSON.
    @computed_field
    @property
    def es_alimento(self) -> bool:
        return es_alimento(self.categoria)


# Diferencia máxima aceptada entre dos valores que deberían coincidir
# (cantidad × precio_unitario y precio_total; total impreso y suma de los ítems).
TOLERANCIA_PRECIO = 0.01
# Códigos válidos: PLU (4-5 dígitos) y EAN-8, UPC-12, EAN-13, GTIN-14.
_CODIGO_VALIDO = re.compile(r"\d{4,14}")


def limpiar_codigo(codigo: str | None) -> str | None:
    """Quita espacios y guiones; None si lo que queda no parece un código de producto."""
    if codigo is None:
        return None
    limpio = re.sub(r"[\s-]", "", codigo)
    return limpio if _CODIGO_VALIDO.fullmatch(limpio) else None


def cuadran(calculado: float | None, impreso: float | None) -> bool:
    """calculado ≈ impreso, con TOLERANCIA_PRECIO. Si falta alguno de los dos no hay
    con qué comparar, y se da por bueno."""
    if calculado is None or impreso is None:
        return True
    return abs(calculado - impreso) <= TOLERANCIA_PRECIO * max(impreso, 1)


def precios_cuadran(item: ItemDetectado) -> bool:
    """cantidad × precio_unitario ≈ precio_total."""
    if item.precio_unitario is None:
        return True
    return cuadran(item.cantidad * item.precio_unitario, item.precio_total)


def a_propuesto(item: ItemDetectado) -> ItemPropuesto:
    return ItemPropuesto(
        **item.model_dump(exclude={"codigo"}),
        codigo=limpiar_codigo(item.codigo),
        revisar=not precios_cuadran(item),
    )


INSTRUCCIONES = """\
Eres un asistente que lee facturas de supermercados colombianos. Recibes el texto \
extraído por OCR de una factura, que puede tener errores de lectura (letras \
confundidas, renglones partidos). Normalmente es solo el bloque de productos, \
desde el encabezado de columnas hasta antes del total. Devuelve solo los \
productos comprados.

Para cada producto:
- codigo: el código de barras (EAN) o PLU que aparece en el renglón, solo dígitos. \
null si no aparece o no se puede leer.
- nombre: nombre legible en español, sin abreviaturas ni códigos, con el tamaño en \
unidades estándar. Ejemplo: "LECHE ALQ ENT 1100ML" -> "Leche entera 1.1 L".
- cantidad: cuántas unidades se compraron; para productos pesados, el peso.
- unidad: "unidad" para productos empacados; "kg" para productos vendidos por peso.
- precio_unitario: precio de una unidad (o de un kg) en pesos, sin separadores de \
miles. null si no se puede leer.
- precio_total: valor total pagado por ese renglón en pesos, sin separadores de \
miles. null si no se puede leer.
- categoria: la que mejor corresponda; "otros" si ninguna aplica. Ejemplos de \
productos colombianos:
  - lacteos: leche, yogur, kumis, queso campesino, mantequilla.
  - carnes_pescados: pollo, carne de res, cerdo, salchichas, mortadela, jamón, \
lonjas de jamón, pescado, huevos.
  - frutas_verduras: banano, arándanos, tomate, papa, cebolla, aguacate.
  - frutos_secos: maní, almendras, nueces, marañones, uvas pasas, mezcla de frutos secos.
  - granos_cereales: arroz, fríjol, lenteja, avena, pasta, harina, maíz pira.
  - enlatados_conservas: atún en lata, sardinas, maíz tierno enlatado, salsa de tomate.
  - panaderia: pan tajado, arepas, tostadas, mogolla.
  - bebidas: agua, gaseosa, jugo, té, café, chocolate de mesa.
  - condimentos_especias: sal, azúcar, canela, comino, pimienta, color, aceite, \
vinagre, caldo en cubos.
  - snacks_dulces: compotas, galletas, papas fritas de paquete, chocolatinas, \
bocadillo, gomas.
  - congelados: helado, verduras congeladas, productos precocidos congelados.
  - aseo_hogar: Varsol, detergente, suavizante, lavaloza, cloro, limpiador, toallas \
de cocina, papel higiénico, bolsas de basura.
  - cuidado_personal: jabón de baño, champú, crema dental, enjuague bucal, \
desodorante, pañitos húmedos, toallas higiénicas.
  - mascotas: alimento para perro o gato, arena para gato.

Usa la relación cantidad × precio_unitario = precio_total para corregir lecturas \
dudosas de los números. Ejemplos: "6/500" probablemente es 6500 (la barra es un \
error de OCR); "7,3506" probablemente es 7350 seguido del código de IVA 6. Si un \
producto se compró una sola vez y no hay precio unitario aparte, usa el mismo \
valor en precio_unitario y precio_total. No inventes números que no estén en el texto.

Ignora todo lo que no sea un producto: subtotales, total, IVA y otros impuestos, \
descuentos y promociones, bolsas e impuesto a la bolsa, propinas, medios de pago, \
cambio, datos del almacén y del cliente. Los datos personales vienen reemplazados \
por marcadores como [NIT] o [TELEFONO]; ignóralos. Si no hay productos, devuelve \
una lista vacía.\
"""


def normalizar_items(texto: str, cliente: genai.Client, modelo: str) -> list[ItemDetectado]:
    respuesta = cliente.models.generate_content(
        model=modelo,
        contents=texto,
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCCIONES,
            temperature=0,  # extracción de datos: la respuesta más probable, sin creatividad
            response_mime_type="application/json",
            response_schema=RespuestaNormalizacion,
        ),
    )
    if not respuesta.text:
        raise ValueError("Gemini no devolvió contenido")
    # Validamos con Pydantic nosotros mismos: si la respuesta no cumple el esquema,
    # falla aquí con un error claro en vez de más adelante.
    return RespuestaNormalizacion.model_validate_json(respuesta.text).items


@lru_cache
def _cliente_gemini() -> genai.Client:
    api_key = get_settings().gemini_api_key
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY no está configurada")
    return genai.Client(api_key=api_key)


def normalizar_con_gemini(texto: str) -> list[ItemDetectado]:
    """Normalizador real, con el cliente y modelo de la configuración."""
    return normalizar_items(texto, _cliente_gemini(), get_settings().gemini_model)
