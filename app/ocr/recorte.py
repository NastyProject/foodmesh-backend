"""Etapa 3: recortar el bloque de productos antes de anonimizar y enviar a Gemini.

Una factura tiene encabezado (almacén, NIT, dirección, cliente), el bloque de
productos y un pie (totales, medios de pago, CUFE). A Gemini solo le sirve el
bloque de productos, así que enviamos solo ese: menos datos personales que
podrían escaparse a la anonimización y menos ruido para el modelo.

El bloque va desde la línea de encabezado de columnas (DESCRIPCION / VALOR)
hasta la primera línea que empieza por TOTAL (o por TOTAL ITEMS, ver abajo). Los
nombres se comparan de forma aproximada para tolerar errores de OCR ("DESCRIPC1ON",
"T0TAL").

Dos formatos conocidos:
- Una línea por producto (D1): "1 1UN 6,550 7702603019160 LONCHITA AMAR 6,550".
- Multilínea (Surtimax aliado, operado por Merkamax): el EAN va en la línea de arriba
  de la descripción, la descripción ocupa varias líneas y el encabezado de columnas
  se repite a mitad del bloque. Después de los productos viene "TOTAL ITEMS:", luego
  SUBTOTAL, medios de pago y la tabla de IVA, y al final el TOTAL. El bloque se corta
  en "TOTAL ITEMS" (lo de abajo no son productos: solo sería ruido para Gemini), pero
  el TOTAL impreso se sigue buscando más abajo, en la línea del TOTAL de verdad.
- Alkosto: la descripción va en la línea de ARRIBA del código y el precio, y el
  encabezado de columnas dice "Articulo" en vez de "Descripción".

El bloque también termina en las líneas de pago ("Pagos:", "Forma de pago",
"Detalle de pago"), por si no hay una línea de TOTAL antes.

Si no se encuentra el bloque, NO se envía el texto completo (ahí se filtraban
nombres, emails y tarjetas): lineas_de_productos() deja solo las líneas que parecen
de un producto y sus vecinas.
"""

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

# Palabras que identifican la línea de encabezado de columnas, con el parecido
# mínimo (0 a 1) que debe tener una palabra del OCR para contar como esa palabra.
_PALABRAS_ENCABEZADO = {"DESCRIPCION": 0.75, "VALOR": 0.8, "ARTICULO": 0.75}
_PARECIDO_TOTAL = 0.8
# Líneas que empiezan por TOTAL pero no son el total a pagar: cuentan productos
# ("TOTAL ITEMS: 18", "TOTAL DE ARTICULOS", "Total Lineas factura: 5") o son otro
# total ("TOTAL DESCUENTOS"). El OCR las lee mal ("TOTAL XTEMS"): se comparan
# aproximado. Igual cierran el bloque de productos: después ya no hay productos.
_NO_ES_EL_TOTAL = {
    "ITEMS": 0.6,
    "ARTICULOS": 0.7,
    "LINEAS": 0.7,
    "DESCUENTOS": 0.75,
    "DESCUENTO": 0.75,
}
# Filas de la tabla de resumen de IVA ("TOTAL BASE IVA"): no son el total a pagar
# aunque empiecen por TOTAL.
_TABLA_IVA = re.compile(r"\b(?:IVA|BASE|EXENTO|EXCLUIDO)\b")
# Líneas de pago: después ya no hay productos.
_LINEA_DE_PAGO = re.compile(
    r"\bPAGOS?[ \t]*:|\bDETALLE[ \t]+DE[ \t]+PAGO|\bFORMA[ \t]+DE[ \t]+PAGO"
)
# El OCR suele leer bordes y sombras del papel como basura al inicio de la línea
# ("4 TOTAL o 130,690"): se ignoran hasta este número de palabras cortas antes de TOTAL.
_BASURA_INICIAL = 3
_LARGO_BASURA = 2
# Un valor en pesos: con separador de miles ("130,690", "18.625") o sin él ("4500").
# Los lookarounds evitan tomar los centavos de "130.690,00" como otro número.
_VALOR = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d{3})+|\d+)(?![\d])")


def normalizar(texto: str) -> str:
    """Mayúsculas y sin tildes: "Descripción" -> "DESCRIPCION"."""
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.upper()


def _palabras(linea: str) -> list[str]:
    return re.findall(r"[A-Z0-9]+", normalizar(linea))


def _se_parece(palabra: str, objetivo: str, minimo: float) -> bool:
    return SequenceMatcher(None, palabra, objetivo).ratio() >= minimo


def _tipo_total(linea: str) -> str | None:
    """Clasifica una línea de totales:
    - "total": el total a pagar (TOTAL, VALOR TOTAL, TOTAL COMPRA, TOTAL A PAGAR).
    - "otro": empieza por TOTAL pero no es el total a pagar (TOTAL ITEMS, TOTAL DE
      ARTICULOS, TOTAL LINEAS, TOTAL DESCUENTOS, filas de la tabla de IVA).
    - None: no es una línea de totales (SUBTOTAL tampoco lo es).
    """
    palabras = _palabras(linea)
    for i, palabra in enumerate(palabras[: _BASURA_INICIAL + 1]):
        # "TOTAL DE ARTICULOS": se mira la palabra después del "DE".
        siguientes = [p for p in palabras[i + 1 : i + 4] if p != "DE"]
        if _se_parece(palabra, "VALOR", 0.8) and siguientes:
            if not _se_parece(siguientes[0], "TOTAL", _PARECIDO_TOTAL):
                return None  # "VALOR IVA", "VALOR PAGADO"
            siguientes = siguientes[1:]  # "VALOR TOTAL": se sigue como si fuera TOTAL
        elif not _se_parece(palabra, "TOTAL", _PARECIDO_TOTAL):
            if len(palabra) > _LARGO_BASURA:  # una palabra de verdad que no es TOTAL
                return None
            continue
        siguiente = siguientes[0] if siguientes else ""
        no_es = any(
            _se_parece(siguiente, objetivo, minimo) for objetivo, minimo in _NO_ES_EL_TOTAL.items()
        )
        return "otro" if no_es or _TABLA_IVA.search(normalizar(linea)) else "total"
    return None


def _es_total(linea: str) -> bool:
    return _tipo_total(linea) == "total"


def _cierra_productos(linea: str) -> bool:
    """Una línea de totales (el TOTAL, "TOTAL ITEMS"…) o de pago: después ya no hay
    productos."""
    return _tipo_total(linea) is not None or bool(_LINEA_DE_PAGO.search(normalizar(linea)))


def es_encabezado_columnas(linea: str) -> bool:
    # "TOTAL VALOR ...", "TOTAL DE ARTICULOS" son el pie, no el encabezado.
    if _tipo_total(linea) is not None:
        return False
    return any(
        _se_parece(palabra, objetivo, minimo)
        for palabra in _palabras(linea)
        for objetivo, minimo in _PALABRAS_ENCABEZADO.items()
    )


def indice_encabezado(lineas: list[str]) -> int | None:
    """Posición de la línea de encabezado de columnas, o None si no aparece."""
    return next((i for i, linea in enumerate(lineas) if es_encabezado_columnas(linea)), None)


def indice_total(lineas: list[str], desde: int = 0) -> int | None:
    """Posición de la primera línea de TOTAL a partir de `desde`, o None."""
    return next((i for i in range(desde, len(lineas)) if _es_total(lineas[i])), None)


def recortar_productos(texto: str) -> str | None:
    """Devuelve el encabezado de columnas y los renglones de productos, sin la línea
    que los cierra (TOTAL o TOTAL ITEMS). None si no encuentra los dos marcadores."""
    lineas = texto.splitlines()
    inicio = indice_encabezado(lineas)
    if inicio is None:
        return None
    fin = next((i for i in range(inicio + 1, len(lineas)) if _cierra_productos(lineas[i])), None)
    if fin is None:
        return None
    # El encabezado de columnas que se repite a mitad del bloque (formato multilínea,
    # al pasar de una "página" a otra del rollo) es ruido: se queda solo el primero.
    productos = [linea for linea in lineas[inicio + 1 : fin] if not es_encabezado_columnas(linea)]
    # Si solo quedó el encabezado de columnas, no hay productos que recortar.
    if not any(linea.strip() for linea in productos):
        return None
    return "\n".join([lineas[inicio], *productos]).strip()


def _valor(linea: str) -> int | None:
    """El número más grande de la línea, en pesos.

    Acepta "32,760", "32.760" (punto de miles), "29500.00" y "$ 29.500,00": los
    centavos se ignoran (los lookarounds de _VALOR no los toman como otro número).
    La línea puede traer basura del OCR ("4 TOTAL o 130,690 1"): el total siempre es
    mayor que esa basura.
    """
    valores = [int(re.sub(r"[.,]", "", m[1])) for m in _VALOR.finditer(linea)]
    return max(valores) if valores else None


def extraer_total_impreso(texto: str) -> float | None:
    """El TOTAL a pagar. Se buscan las líneas de total válidas (TOTAL, VALOR TOTAL,
    TOTAL COMPRA, TOTAL A PAGAR) después del encabezado de columnas; nunca SUBTOTAL,
    TOTAL ITEMS ni la tabla de IVA. Si hay varias con valores distintos, se toma el
    valor que más se repite (el total suele salir dos veces: "TOTAL" y "TOTAL A
    PAGAR"); en un empate, el de la primera.
    """
    lineas = texto.splitlines()
    inicio = indice_encabezado(lineas)
    desde = inicio + 1 if inicio is not None else 0
    valores = [
        valor
        for linea in lineas[desde:]
        if _es_total(linea) and (valor := _valor(linea)) is not None
    ]
    if not valores:
        return None
    conteo = Counter(valores)
    mas_repetido = max(conteo.values())
    return float(next(v for v in valores if conteo[v] == mas_repetido))


# --- Respaldo cuando no hay bloque de productos ---

# Un código de barras (8 a 14 dígitos seguidos) o un precio con separador de miles o
# con centavos ("67.800", "14,900", "29500.00"). Un número suelto sin separador no
# cuenta: puede ser el número de pedido, de caja o de resolución.
# El código no puede ir pegado a una letra: "X6601009349" es el número de la factura
# electrónica (prefijo + consecutivo), no un EAN.
_CODIGO = re.compile(r"(?<![\dA-Za-z])\d{8,14}(?!\d)")
# Renglones con números largos que no son productos: la resolución de la DIAN
# ("Resolucion DIAN 18764094754937"), el número de factura o de pedido.
_NO_ES_PRODUCTO = re.compile(r"RESOLU|FACTURA|PREFIJO|AUTORIZ|PEDIDO|\bNIT\b|\bRES\b")
_PRECIO = re.compile(r"(?<![\d.,])(?:\d{1,3}(?:[.,]\d{3})+|\d+[.,]\d{2})(?![\d])")
# Una línea vecina que trae un marcador de la anonimización o una etiqueta de datos
# personales no se envía, aunque esté junto a un producto.
_VECINA_PERSONAL = re.compile(
    r"\[|\b(?:CLIENTE|CLANTE|NOMBRE|BARRIO|DIRECCION|DIR|EMAIL|E-MAIL|CORREO"
    r"|TEL[A-Z]*|CELULAR|NIT|CC|CEDULA)\b"
)


def _parece_producto(linea: str) -> bool:
    if _NO_ES_PRODUCTO.search(normalizar(linea)):
        return False
    return bool(_CODIGO.search(linea) or _PRECIO.search(linea))


def lineas_de_productos(texto: str) -> str | None:
    """Para cuando no se encontró el bloque de productos: solo las líneas que parecen
    de un producto (traen un código de barras o un precio) y sus vecinas, la de arriba
    y la de abajo, porque la descripción puede ir en otra línea (en Alkosto va arriba;
    en el formato multilínea, abajo del código). None si no hay ninguna.

    Debe recibir el texto YA anonimizado: así los teléfonos o cédulas, que también
    son números largos, llegan como marcadores y no parecen productos.
    """
    lineas = texto.splitlines()
    elegidas: set[int] = set()
    for i, linea in enumerate(lineas):
        if not _parece_producto(linea):
            continue
        elegidas.add(i)
        for vecina in (i - 1, i + 1):
            if 0 <= vecina < len(lineas) and not _VECINA_PERSONAL.search(
                normalizar(lineas[vecina])
            ):
                elegidas.add(vecina)
    seleccion = [lineas[i] for i in sorted(elegidas) if lineas[i].strip()]
    return "\n".join(seleccion).strip() or None
