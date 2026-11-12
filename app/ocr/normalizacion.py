"""Etapa 4: convertir el texto OCR (ya anonimizado) en ítems estructurados con Gemini.

Usamos structured output: le pasamos a Gemini un modelo Pydantic como esquema y
la API garantiza que la respuesta es un JSON con esa forma (categorías dentro de
la lista cerrada, números donde van números...). Así no hay que "parsear" texto libre.

Hay un respaldo con visión (normalizar_imagen_items): se le envía la foto completa,
con el mismo esquema de salida, para formatos que el texto del OCR no resuelve. Solo
se usa si el usuario lo autoriza, porque la foto lleva todos los datos de la factura.
"""

import re
from collections.abc import Callable
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, computed_field

from app.catalog.categorias import Categoria, es_alimento
from app.core.config import get_settings
from app.core.gemini import THINKING_MINIMO, cliente_gemini, generar_contenido


class ItemDetectado(BaseModel):
    """Lo que Gemini devuelve por cada producto (es el esquema de structured output)."""

    codigo: str | None
    # La descripción tal como está impresa, sin corregir ni completar. Va antes de
    # nombre a propósito: Gemini genera los campos en el orden del esquema, así que
    # primero transcribe y luego normaliza a partir de lo transcrito. Con la foto
    # (visión), sin este paso inventaba marcas plausibles que no estaban impresas.
    descripcion_impresa: str
    nombre: str
    cantidad: float
    unidad: str
    precio_unitario: float | None
    precio_total: float | None
    categoria: Categoria
    # True si una parte del nombre era ilegible o ambigua y no se completó con
    # seguridad ("HUEVO DE cooo" -> "Huevos de c…"): el usuario debe revisarlo.
    nombre_incierto: bool


class RespuestaNormalizacion(BaseModel):
    items: list[ItemDetectado]


class RespuestaVision(RespuestaNormalizacion):
    """Lo que devuelve Gemini en el modo visión: los ítems y, aparte, el TOTAL impreso.

    En el modo texto el total lo leen las reglas locales del OCR (extraer_total_impreso);
    con la foto, esa lectura puede ser justo la que falló (en la factura de Surtimax
    aliado, el OCR leyó 135,504 por 125,500), así que Gemini también lee el total.
    """

    # Leído de la línea TOTAL, nunca calculado: así la verificación sigue siendo una
    # comparación entre dos lecturas independientes.
    total_impreso: float | None


class ItemPropuesto(ItemDetectado):
    """Ítem que se le propone al usuario: lo de Gemini más lo que calculamos nosotros.

    Va aparte de ItemDetectado para que estos campos no formen parte del esquema
    que se le pide a Gemini. Los valores por defecto permiten leer facturas
    guardadas antes de que existieran estos campos.
    """

    codigo: str | None = None
    # None en las facturas guardadas antes de que existiera el campo.
    descripcion_impresa: str | None = None
    precio_unitario: float | None = None
    precio_total: float | None = None
    nombre_incierto: bool = False
    # "catalogo" si el nombre y la categoría salieron del catálogo por el código; "ia" si no.
    origen: Literal["catalogo", "ia"] = "ia"
    # True si los números no cuadran y conviene que el usuario revise el ítem.
    revisar: bool = False

    # computed_field: se calcula de la categoría (no se guarda aparte) y sale en el JSON.
    @computed_field
    @property
    def es_alimento(self) -> bool:
        return es_alimento(self.categoria)


# Diferencia máxima aceptada, en pesos, entre dos valores que deberían coincidir
# (cantidad × precio_unitario y precio_total; total impreso y suma de los ítems).
# Los precios en COP son enteros: la suma debe cuadrar exacto. El peso de margen es
# para los productos por peso (0.535 kg × 7,990 = 4,274.65, impreso 4,275). Antes era
# un 1 %, y en la factura 3 dejó pasar como bueno un arroz leído 3,905 en vez de 3,990.
TOLERANCIA_PESOS = 1
# Códigos válidos: PLU (4-5 dígitos) y EAN-8, UPC-12, EAN-13, GTIN-14.
_CODIGO_VALIDO = re.compile(r"\d{4,14}")


def limpiar_codigo(codigo: str | None) -> str | None:
    """Quita espacios y guiones; None si lo que queda no parece un código de producto."""
    if codigo is None:
        return None
    limpio = re.sub(r"[\s-]", "", codigo)
    return limpio if _CODIGO_VALIDO.fullmatch(limpio) else None


def cuadran(calculado: float | None, impreso: float | None) -> bool:
    """calculado ≈ impreso, con TOLERANCIA_PESOS. Si falta alguno de los dos no hay
    con qué comparar, y se da por bueno."""
    if calculado is None or impreso is None:
        return True
    return abs(calculado - impreso) <= TOLERANCIA_PESOS


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


_INTRO_TEXTO = """\
Eres un asistente que lee facturas de supermercados colombianos. Recibes el texto \
extraído por OCR de una factura, que puede tener errores de lectura (letras \
confundidas, renglones partidos). Normalmente es solo el bloque de productos, \
desde el encabezado de columnas hasta antes del total. Devuelve solo los \
productos comprados.

Hay dos formatos de factura:
- Una línea por producto (por ejemplo D1): número de línea, cantidad con su \
unidad ("1UN", "5 UN"), precio unitario, código de barras, descripción abreviada \
y valor total, todo en el mismo renglón: \
"3 5 UN 1,650 7700304325207 ARROZ ESTANDA 8,250". Ojo: el número de línea puede \
quedar pegado a la cantidad ("773 UN" en la línea 7 es 3 unidades).
- Multilínea (por ejemplo, tiendas aliadas de Surtimax): cada producto ocupa varias \
líneas. El código de barras va solo, en la línea de ARRIBA de la descripción \
(pertenece al producto que sigue, no al anterior); la descripción sigue en las \
líneas de abajo ("TOALLAS" / "PEQUEÑIN" / "ALMENDRA X100" es un solo producto); la \
cantidad está en la columna CANT ("1 CANT", "cant 2"), y el número al inicio del \
renglón es el número de línea, no la cantidad. Junta todas las líneas de un producto \
antes de leerlo, y no partas un producto en dos ni juntes dos productos en uno.
"""

_INTRO_VISION = """\
Eres un asistente que lee facturas de supermercados colombianos. Recibes la FOTO \
de una factura. Lee solo la tabla de productos comprados, respetando las columnas \
(en algunos formatos el código de barras va en la línea de arriba de la \
descripción, y la descripción ocupa varias líneas). Devuelve solo los productos \
comprados. No transcribas datos personales (nombres, documentos, tarjetas).

Además de los productos, devuelve total_impreso: el valor de la línea TOTAL (el \
total a pagar), en pesos sin separadores de miles, tal como está impreso. Léelo \
de esa línea; no lo calcules sumando los productos, y nunca lo ajustes para que \
cuadre con ellos: si la suma de los productos no da el total, el sistema le pide \
al usuario que revise, y eso es lo correcto. No lo confundas con SUBTOTAL, \
"TOTAL ITEMS", la base gravable, el IVA, el valor pagado ni el cambio. null si la \
línea TOTAL no se ve o no se puede leer.

Muy importante con la foto: el nombre se deriva SOLO de descripcion_impresa. Puedes \
expandir abreviaturas y corregir errores de lectura evidentes, pero nunca agregues \
una marca, un sabor, un tamaño ni un tipo de producto que no esté impreso, aunque te \
parezca probable. Si no puedes leer bien la descripción, conserva lo legible y marca \
nombre_incierto=true. Errores reales que NO debes repetir:
- "BON YURT ZUCARITAS" -> "Kumis Alpina" (mal); lo correcto es "Bon Yurt con Zucaritas".
- "BIG COLA NARANJA" -> "Jugo Hit naranja" (mal); lo correcto es "Big Cola naranja".
- "TOALLAS PEQUEÑIN ALMENDRA" -> "Almendras" (mal); lo correcto es \
"Toallas Pequeñín almendra".
- "PARMESAANO ALPINA" -> "Arequipe Alpina" (mal); lo correcto es \
"Queso parmesano Alpina".
"""

_REGLAS = """\

Para cada producto:
- codigo: el código de barras (EAN) o PLU del producto, copiado tal cual, dígito por \
dígito. Si en la factura tiene letras mezcladas (un error de lectura, como \
"TIOAZE96300ZA"), está incompleto o no aparece, devuelve null: nunca lo completes, \
lo corrijas ni lo deduzcas.
- descripcion_impresa: la descripción del producto tal como aparece en la factura, \
sin corregir, completar ni traducir abreviaturas (si ocupa varias líneas, júntalas \
con un espacio). Ejemplo: "LECHE ALQ ENT 1100ML".
- nombre: nombre legible en español, derivado solo de descripcion_impresa: sin \
abreviaturas ni códigos, con el tamaño en unidades estándar. Ejemplo: \
"LECHE ALQ ENT 1100ML" -> "Leche entera 1.1 L".
- nombre_incierto: true si una parte del nombre es ilegible o ambigua y no la \
puedes completar con seguridad. En ese caso conserva lo legible y marca con "…" lo \
que falta, sin inventar ni simplificar: "HUEVO DE cooo" -> "Huevos de c…" (no \
"Huevos"). false si el nombre es claro.
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

\
Los precios están en pesos colombianos, sin centavos. Puedes usar la relación \
cantidad × precio_unitario = precio_total solo para interpretar caracteres que el \
OCR dañó DENTRO de un número: "6/500" es 6500 (la barra es un error de OCR); \
"7,3506" es 7350 seguido del código de IVA 6. Pero si los dos números se leen bien \
y aun así cantidad × precio_unitario no da precio_total (por ejemplo, 1 × 3,990 y \
un total de 3,905), NO cambies ninguno para que cuadre: devuelve los valores tal \
como los leíste. El sistema detecta la diferencia y le pide al usuario que la \
revise. Si un producto se compró una sola vez y no hay precio unitario aparte, usa \
el mismo valor en precio_unitario y precio_total. No inventes números que no estén \
en la factura.

Ignora todo lo que no sea un producto: "TOTAL ITEMS", subtotales, total, IVA y \
otros impuestos (y la tabla de resumen de impuestos), descuentos y promociones, \
impuesto a la bolsa, propinas, medios de pago, cambio, datos del almacén y del \
cliente. Las bolsas plásticas que se cobran como un renglón sí son un producto. \
Los datos personales vienen reemplazados por marcadores como [NIT] o [TELEFONO]; \
ignóralos. Si no hay productos, devuelve una lista vacía.\
"""

INSTRUCCIONES = _INTRO_TEXTO + _REGLAS
INSTRUCCIONES_VISION = _INTRO_VISION + _REGLAS


# Función texto → ítems (Gemini en producción, un falso en tests).
Normalizador = Callable[[str], list[ItemDetectado]]
# Función imagen → ítems y total impreso: el respaldo con visión.
NormalizadorImagen = Callable[[bytes], RespuestaVision]


def _pedir[Respuesta: RespuestaNormalizacion](
    contenido: types.ContentListUnion,
    instrucciones: str,
    esquema: type[Respuesta],
    cliente: genai.Client,
    modelo: str,
    modelo_respaldo: str | None,
) -> Respuesta:
    # El modelo que respondió queda en el log (generar_contenido); la factura no lo guarda.
    respuesta = generar_contenido(
        cliente,
        "facturas",
        modelo=modelo,
        modelo_respaldo=modelo_respaldo,
        contenido=contenido,
        timeout_segundos=get_settings().gemini_timeout_interactivo,
        config=types.GenerateContentConfig(
            system_instruction=instrucciones,
            temperature=0,  # extracción de datos: la respuesta más probable, sin creatividad
            response_mime_type="application/json",
            response_schema=esquema,
            # Sin max_output_tokens: una factura larga puede tener muchos ítems, y una
            # respuesta cortada sería un JSON inválido.
            thinking_config=THINKING_MINIMO,
        ),
    ).respuesta
    if not respuesta.text:
        raise ValueError("Gemini no devolvió contenido")
    # Validamos con Pydantic nosotros mismos: si la respuesta no cumple el esquema,
    # falla aquí con un error claro en vez de más adelante.
    return esquema.model_validate_json(respuesta.text)


def normalizar_items(
    texto: str, cliente: genai.Client, modelo: str, modelo_respaldo: str | None = None
) -> list[ItemDetectado]:
    respuesta = _pedir(
        texto, INSTRUCCIONES, RespuestaNormalizacion, cliente, modelo, modelo_respaldo
    )
    return respuesta.items


def tipo_de_imagen(datos: bytes) -> str:
    """MIME de la imagen según sus primeros bytes. La key del storage siempre termina en
    .jpg, pero el usuario pudo subir un PNG o un WebP."""
    if datos.startswith(b"\x89PNG"):
        return "image/png"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def normalizar_imagen_items(
    imagen: bytes, cliente: genai.Client, modelo: str, modelo_respaldo: str | None = None
) -> RespuestaVision:
    """Respaldo con visión: la foto completa a Gemini multimodal. Mismos ítems que el
    modo texto, más el TOTAL impreso leído de la foto."""
    contenido = [
        types.Part.from_bytes(data=imagen, mime_type=tipo_de_imagen(imagen)),
        "Extrae los productos y el total de esta factura.",
    ]
    return _pedir(
        contenido, INSTRUCCIONES_VISION, RespuestaVision, cliente, modelo, modelo_respaldo
    )


def normalizar_con_gemini(texto: str) -> list[ItemDetectado]:
    """Normalizador real, con el cliente y modelo de la configuración."""
    settings = get_settings()
    return normalizar_items(
        texto, cliente_gemini(), settings.gemini_model, settings.gemini_model_respaldo
    )


def normalizar_imagen_con_gemini(imagen: bytes) -> RespuestaVision:
    """Normalizador con visión real, con el cliente y modelo de la configuración."""
    settings = get_settings()
    return normalizar_imagen_items(
        imagen, cliente_gemini(), settings.gemini_model, settings.gemini_model_respaldo
    )
