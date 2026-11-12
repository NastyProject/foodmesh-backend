"""Métricas del pipeline de facturas contra una verdad etiquetada a mano (CSV).

Lo usa scripts/evaluar_ocr.py. Va aquí, y no en el script, para poder probarlo sin
llamar a Gemini. El formato del CSV está en scripts/README.md.
"""

import csv
import re
import statistics
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from app.ocr.normalizacion import TOLERANCIA_PESOS, ItemPropuesto
from app.ocr.recorte import normalizar

COLUMNAS = ("factura", "nombre", "cantidad", "precio_unitario", "precio_total")
# Columna opcional: si la foto se usó tal cual o se mejoró con IA antes de evaluarla.
# Las métricas se reportan por separado. Sin la columna, todas cuentan como originales.
ORIGENES_IMAGEN = ("original", "mejorada_ia")
# Un ítem detectado corresponde a uno real si sus nombres se parecen al menos esto,
# o si cobran lo mismo y los nombres se parecen al menos UMBRAL_NOMBRE_CON_PRECIO.
# Los nombres que propone Gemini son más largos que los de la factura ("Lonchitas de
# queso amarillo" por "LONCHITA AMAR"), así que el parecido es aproximado.
UMBRAL_NOMBRE = 0.5
UMBRAL_NOMBRE_CON_PRECIO = 0.25
_LARGO_RAIZ = 4  # se comparan las palabras por sus primeras letras: "lonchitas" ~ "lonchita"


@dataclass
class ItemVerdad:
    factura: str
    nombre: str
    cantidad: float
    precio_unitario: float | None
    precio_total: float
    origen_imagen: str = "original"


@dataclass
class ResultadoFactura:
    """Lo que devolvió el pipeline para una factura, en un modo."""

    factura: str
    items: list[ItemPropuesto]
    requiere_revision: bool
    latencia_ms: int
    error: str | None = None


@dataclass
class Metricas:
    facturas: int
    items_reales: int
    items_detectados: int
    emparejados: int
    precios_correctos: int
    facturas_verificadas: int
    latencias_ms: list[int] = field(default_factory=list)

    @property
    def precision(self) -> float:
        return self.emparejados / self.items_detectados if self.items_detectados else 0.0

    @property
    def recall(self) -> float:
        return self.emparejados / self.items_reales if self.items_reales else 0.0

    @property
    def f1(self) -> float:
        suma = self.precision + self.recall
        return 2 * self.precision * self.recall / suma if suma else 0.0

    @property
    def porcentaje_precios_correctos(self) -> float:
        """Sobre los ítems emparejados: cantidad, precio unitario y total correctos."""
        return self.precios_correctos / self.emparejados if self.emparejados else 0.0

    @property
    def porcentaje_facturas_verificadas(self) -> float:
        """Facturas cuyo total calculado cuadró con el impreso (sin requiere_revision)."""
        return self.facturas_verificadas / self.facturas if self.facturas else 0.0


def _pesos(valor: str) -> float | None:
    """'6,550', '6.550', '$6550' -> 6550. Vacío -> None. Los precios en COP son enteros."""
    limpio = re.sub(r"[\s$.,]", "", valor)
    return float(limpio) if limpio else None


def leer_verdad(ruta: Path) -> dict[str, list[ItemVerdad]]:
    """CSV de verdad -> ítems reales por factura (la columna factura es el nombre del
    archivo de la imagen sin extensión)."""
    with ruta.open(newline="", encoding="utf-8") as archivo:
        lector = csv.DictReader(archivo)
        faltan = set(COLUMNAS) - set(lector.fieldnames or [])
        if faltan:
            raise ValueError(f"Al CSV le faltan columnas: {', '.join(sorted(faltan))}")
        verdad: dict[str, list[ItemVerdad]] = {}
        for numero, fila in enumerate(lector, start=2):  # la 1 es el encabezado
            total = _pesos(fila["precio_total"])
            if total is None:
                raise ValueError(f"Fila {numero}: falta precio_total")
            origen = (fila.get("origen_imagen") or "original").strip()
            if origen not in ORIGENES_IMAGEN:
                raise ValueError(
                    f"Fila {numero}: origen_imagen debe ser {' o '.join(ORIGENES_IMAGEN)}"
                )
            item = ItemVerdad(
                factura=fila["factura"].strip(),
                nombre=fila["nombre"].strip(),
                # La cantidad puede tener decimales (kg): con punto o con coma.
                cantidad=float(fila["cantidad"].replace(",", ".")),
                precio_unitario=_pesos(fila["precio_unitario"]),
                precio_total=total,
                origen_imagen=origen,
            )
            otros = verdad.get(item.factura)
            if otros and otros[0].origen_imagen != origen:
                raise ValueError(
                    f"Fila {numero}: la factura {item.factura!r} tiene renglones con "
                    "distinto origen_imagen"
                )
            verdad.setdefault(item.factura, []).append(item)
    return verdad


def origen_imagen(verdad: dict[str, list[ItemVerdad]], factura: str) -> str:
    return verdad[factura][0].origen_imagen


def _raices(nombre: str) -> set[str]:
    return {p[:_LARGO_RAIZ] for p in re.findall(r"[A-Z0-9]+", normalizar(nombre)) if len(p) >= 3}


def parecido_nombres(detectado: str, real: str) -> float:
    """0 a 1. El mayor entre el parecido de los textos completos y la fracción de
    palabras del nombre real (por su raíz) que aparecen en el detectado."""
    texto = SequenceMatcher(None, normalizar(detectado), normalizar(real)).ratio()
    raices_reales = _raices(real)
    palabras = len(raices_reales & _raices(detectado)) / len(raices_reales) if raices_reales else 0
    return max(texto, palabras)


def _iguales(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= TOLERANCIA_PESOS


def emparejar(
    detectados: list[ItemPropuesto], reales: list[ItemVerdad]
) -> list[tuple[ItemPropuesto, ItemVerdad]]:
    """Empareja 1 a 1 los ítems detectados con los reales, de mejor a peor parecido.
    Un ítem detectado sin pareja es un falso positivo; uno real sin pareja, uno que
    no se detectó."""
    candidatos = []
    for i, detectado in enumerate(detectados):
        for j, real in enumerate(reales):
            parecido = parecido_nombres(detectado.nombre, real.nombre)
            mismo_precio = _iguales(detectado.precio_total, real.precio_total)
            if parecido >= UMBRAL_NOMBRE or (mismo_precio and parecido >= UMBRAL_NOMBRE_CON_PRECIO):
                candidatos.append((parecido + (0.5 if mismo_precio else 0), i, j))
    usados_i: set[int] = set()
    usados_j: set[int] = set()
    parejas = []
    for _, i, j in sorted(candidatos, reverse=True):
        if i not in usados_i and j not in usados_j:
            usados_i.add(i)
            usados_j.add(j)
            parejas.append((detectados[i], reales[j]))
    return parejas


def precio_correcto(detectado: ItemPropuesto, real: ItemVerdad) -> bool:
    """Cantidad, precio unitario (si la verdad lo trae) y precio total correctos."""
    if abs(detectado.cantidad - real.cantidad) > 0.001:
        return False
    if real.precio_unitario is not None and not _iguales(
        detectado.precio_unitario, real.precio_unitario
    ):
        return False
    return _iguales(detectado.precio_total, real.precio_total)


def calcular_metricas(
    resultados: list[ResultadoFactura], verdad: dict[str, list[ItemVerdad]]
) -> Metricas:
    metricas = Metricas(
        facturas=len(resultados),
        items_reales=0,
        items_detectados=0,
        emparejados=0,
        precios_correctos=0,
        facturas_verificadas=0,
    )
    for resultado in resultados:
        reales = verdad.get(resultado.factura, [])
        parejas = emparejar(resultado.items, reales)
        metricas.items_reales += len(reales)
        metricas.items_detectados += len(resultado.items)
        metricas.emparejados += len(parejas)
        metricas.precios_correctos += sum(precio_correcto(d, r) for d, r in parejas)
        metricas.facturas_verificadas += not resultado.requiere_revision
        metricas.latencias_ms.append(resultado.latencia_ms)
    return metricas


def resumen_latencia(latencias_ms: list[int]) -> str:
    if not latencias_ms:
        return "-"
    return (
        f"mediana {statistics.median(latencias_ms) / 1000:.1f} s, "
        f"máx {max(latencias_ms) / 1000:.1f} s"
    )
