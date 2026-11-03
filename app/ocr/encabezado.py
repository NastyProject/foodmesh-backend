"""Supermercado y fecha de compra, con reglas locales.

Se hace aquí y no con Gemini para no enviarle el encabezado de la factura, que
es donde están el NIT, la dirección y los datos del cliente.
"""

import re
from dataclasses import dataclass
from datetime import date

from app.ocr.recorte import indice_encabezado, normalizar

# Variantes que el OCR produce y que no se pueden escribir como una palabra fija.
# "D1 SAS" sale como "DI SAS" o "Dl SAS"; se exige el SAS para no tomar cualquier "DI".
_SUPERMERCADOS_OCR = {r"\bD[1IL][ \t]*S\.?[ \t]*A\.?[ \t]*S\b": "D1"}
# Nombre que aparece en la factura (sin tildes, mayúsculas) -> nombre que guardamos.
# Incluye la razón social, que a veces es lo único legible (D1 es Koba Colombia).
_SUPERMERCADOS = {
    "D1": "D1",
    "KOBA": "D1",
    "ARA": "Ara",
    "JERONIMO MARTINS": "Ara",
    "EXITO": "Éxito",
    "CARULLA": "Carulla",
    "SURTIMAX": "Surtimax",
    "OLIMPICA": "Olímpica",
    "JUMBO": "Jumbo",
    "METRO": "Metro",
    "CENCOSUD": "Jumbo",
    "ALKOSTO": "Alkosto",
    "MAKRO": "Makro",
    "COLSUBSIDIO": "Colsubsidio",
    "ISIMO": "Isimo",
    "ZAPATOCA": "Zapatoca",
}
# Si no hay encabezado de columnas, el nombre del almacén se busca en estas primeras líneas.
_LINEAS_ENCABEZADO = 10

# 30/10/2026, 30-10-26, 30.10.2026 (día primero, como en Colombia) y 2026/10/30, 2026-10-30.
_FECHA_DMA = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})(?!\d)")
_FECHA_AMD = re.compile(r"(?<!\d)(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})(?!\d)")


@dataclass
class Encabezado:
    supermercado: str | None
    fecha_compra: date | None


def detectar_supermercado(texto: str) -> str | None:
    lineas = texto.splitlines()
    fin = indice_encabezado(lineas)
    zona = normalizar("\n".join(lineas[: fin if fin is not None else _LINEAS_ENCABEZADO]))
    patrones = _SUPERMERCADOS_OCR | {
        rf"\b{re.escape(nombre)}\b": canonico for nombre, canonico in _SUPERMERCADOS.items()
    }
    for patron, canonico in patrones.items():
        if re.search(patron, zona):
            return canonico
    return None


def _fecha_valida(anio: int, mes: int, dia: int) -> date | None:
    if anio < 100:
        anio += 2000
    try:
        fecha = date(anio, mes, dia)
    except ValueError:
        return None
    # Descarta lecturas absurdas (fechas de vencimiento de resoluciones, errores de OCR).
    return fecha if 2000 <= fecha.year <= date.today().year + 1 else None


def detectar_fecha(texto: str) -> date | None:
    """Primera fecha válida del texto, en orden de aparición."""
    candidatas = [(m.start(), int(m[3]), int(m[2]), int(m[1])) for m in _FECHA_DMA.finditer(texto)]
    candidatas += [(m.start(), int(m[1]), int(m[2]), int(m[3])) for m in _FECHA_AMD.finditer(texto)]
    for _, anio, mes, dia in sorted(candidatas):
        if fecha := _fecha_valida(anio, mes, dia):
            return fecha
    return None


def extraer_encabezado(texto: str) -> Encabezado:
    return Encabezado(supermercado=detectar_supermercado(texto), fecha_compra=detectar_fecha(texto))
