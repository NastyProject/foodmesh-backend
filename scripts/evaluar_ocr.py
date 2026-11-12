"""Evalúa el pipeline de facturas contra una verdad etiquetada a mano.

Corre cada imagen de la carpeta por el pipeline (en uno o varios modos), compara
los ítems detectados con los del CSV y calcula, por modo: ítems detectados,
precisión, recall, F1, % de precios correctos, % de facturas con el total
verificado y latencia. El formato del CSV está en scripts/README.md.

Llama a Gemini de verdad: cada factura, en cada modo, es una llamada a la API. En
modo visión, la foto completa se envía a Google.

Uso (desde la raíz del proyecto, con el .env configurado):
    python scripts/evaluar_ocr.py ~/facturas-prueba verdad.csv
    python scripts/evaluar_ocr.py ~/facturas-prueba verdad.csv --modos texto vision
    python scripts/evaluar_ocr.py ~/facturas-prueba verdad.csv --json resultados.json
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Permite importar `app` al correr el script directamente con `python scripts/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ocr.evaluacion import (  # noqa: E402
    ORIGENES_IMAGEN,
    Metricas,
    ResultadoFactura,
    calcular_metricas,
    emparejar,
    leer_verdad,
    origen_imagen,
    resumen_latencia,
)
from app.ocr.normalizacion import (  # noqa: E402
    normalizar_con_gemini,
    normalizar_imagen_con_gemini,
)
from app.ocr.pipeline import procesar_factura, procesar_factura_con_imagen  # noqa: E402

EXTENSIONES = {".jpg", ".jpeg", ".png", ".webp"}


def procesar(modo: str, datos: bytes):
    if modo == "vision":
        return procesar_factura_con_imagen(datos, normalizar_imagen_con_gemini)
    return procesar_factura(datos, normalizar_con_gemini)


def imprimir(titulo: str, metricas: Metricas) -> None:
    print(
        f"\n{titulo}\n"
        f"Facturas: {metricas.facturas} · ítems reales: {metricas.items_reales} · "
        f"detectados: {metricas.items_detectados} · emparejados: {metricas.emparejados}\n"
        f"Precisión: {metricas.precision:.1%} · Recall: {metricas.recall:.1%} · "
        f"F1: {metricas.f1:.1%}\n"
        f"Precios correctos: {metricas.porcentaje_precios_correctos:.1%} · "
        f"Facturas con total verificado: {metricas.porcentaje_facturas_verificadas:.1%}\n"
        f"Latencia por factura: {resumen_latencia(metricas.latencias_ms)}"
    )


def como_dict(metricas: Metricas) -> dict:
    return {
        **asdict(metricas),
        "precision": metricas.precision,
        "recall": metricas.recall,
        "f1": metricas.f1,
        "porcentaje_precios_correctos": metricas.porcentaje_precios_correctos,
        "porcentaje_facturas_verificadas": metricas.porcentaje_facturas_verificadas,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("carpeta", type=Path, help="carpeta con las fotos de las facturas")
    parser.add_argument("verdad", type=Path, help="CSV con los productos reales de cada factura")
    parser.add_argument(
        "--modos", nargs="+", choices=["texto", "vision"], default=["texto"], help="modos a evaluar"
    )
    parser.add_argument("--json", type=Path, metavar="RUTA", help="guardar el detalle en JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="  %(message)s")

    verdad = leer_verdad(args.verdad)
    imagenes = {
        ruta.stem: ruta
        for ruta in sorted(args.carpeta.iterdir())
        if ruta.suffix.lower() in EXTENSIONES and ruta.stem in verdad
    }
    for factura in sorted(set(verdad) - set(imagenes)):
        print(f"Aviso: la factura {factura!r} está en el CSV pero no hay imagen con ese nombre")
    if not imagenes:
        print("No hay imágenes que coincidan con la columna factura del CSV.")
        return 1

    detalle = {}
    for modo in args.modos:
        print(f"\n=== Modo {modo} ===")
        resultados = []
        for factura, ruta in imagenes.items():
            inicio = time.perf_counter()
            resultado = procesar(modo, ruta.read_bytes())
            latencia_ms = round((time.perf_counter() - inicio) * 1000)
            resultados.append(
                ResultadoFactura(
                    factura=factura,
                    items=resultado.items,
                    requiere_revision=resultado.requiere_revision,
                    latencia_ms=latencia_ms,
                    error=resultado.error,
                )
            )
            parejas = emparejar(resultado.items, verdad[factura])
            estado = "total ✓" if not resultado.requiere_revision else "total ✗"
            error = f" · ERROR: {resultado.error}" if resultado.error else ""
            print(
                f"- {factura} ({origen_imagen(verdad, factura)}): "
                f"{len(parejas)}/{len(verdad[factura])} reales detectados, "
                f"{len(resultado.items)} detectados, {estado}, {latencia_ms / 1000:.1f} s{error}"
            )

        metricas = calcular_metricas(resultados, verdad)
        imprimir("Todas las facturas", metricas)
        por_origen = {}
        for origen in ORIGENES_IMAGEN:
            grupo = [r for r in resultados if origen_imagen(verdad, r.factura) == origen]
            if grupo:
                por_origen[origen] = calcular_metricas(grupo, verdad)
                imprimir(f"Solo imágenes {origen}", por_origen[origen])
        detalle[modo] = {
            "metricas": como_dict(metricas),
            "metricas_por_origen": {o: como_dict(m) for o, m in por_origen.items()},
            "facturas": [
                {
                    **asdict(r),
                    "origen_imagen": origen_imagen(verdad, r.factura),
                    "items": [item.model_dump() for item in r.items],
                }
                for r in resultados
            ],
        }

    if args.json:
        args.json.write_text(json.dumps(detalle, ensure_ascii=False, indent=2, default=str))
        print(f"\nDetalle guardado en {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
