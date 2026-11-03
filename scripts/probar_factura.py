"""Corre el pipeline OCR sobre una imagen, sin levantar la API ni tocar la BD.

Uso (desde la raíz del proyecto, con el .env configurado):
    python scripts/probar_factura.py ruta/a/factura.jpg
    # Sin llamar a Gemini:
    python scripts/probar_factura.py factura.jpg --solo-ocr
    # Guardar la imagen binarizada, para ver lo mismo que ve Tesseract:
    python scripts/probar_factura.py factura.jpg --guardar-preprocesada binarizada.png

Como no toca la BD, no consulta el catálogo de productos: todos los ítems salen
con origen "ia" (en la API, los que tengan código conocido saldrán como "catalogo").
"""

import argparse
import sys
from pathlib import Path

# Permite importar `app` al correr el script directamente con `python scripts/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from app.ocr import preprocesamiento  # noqa: E402
from app.ocr.normalizacion import normalizar_con_gemini  # noqa: E402
from app.ocr.pipeline import procesar_factura  # noqa: E402


def _pesos(valor: float | None) -> str:
    return f"${valor:,.0f}" if valor is not None else "?"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("imagen", type=Path, help="ruta de la foto de la factura")
    parser.add_argument("--solo-ocr", action="store_true", help="no llamar a Gemini")
    parser.add_argument(
        "--guardar-preprocesada", type=Path, metavar="RUTA", help="guardar la imagen binarizada"
    )
    args = parser.parse_args()

    datos = args.imagen.read_bytes()

    if args.guardar_preprocesada:
        procesada = preprocesamiento.preprocesar(preprocesamiento.decodificar(datos))
        cv2.imwrite(str(args.guardar_preprocesada), procesada)
        print(f"Imagen preprocesada guardada en {args.guardar_preprocesada}")

    normalizar = (lambda texto: []) if args.solo_ocr else normalizar_con_gemini
    resultado = procesar_factura(datos, normalizar)

    print("=== Texto OCR (anonimizado) ===")
    print(resultado.texto_ocr or "(vacío)")
    recorte = "solo el bloque de productos" if resultado.recortada else "texto completo"
    print(f"\n=== Texto enviado a Gemini ({recorte}) ===")
    print(resultado.texto_enviado or "(vacío)")
    print("\n=== Encabezado (reglas locales) ===")
    print(f"Supermercado: {resultado.supermercado or '(no detectado)'}")
    print(f"Fecha de compra: {resultado.fecha_compra or '(no detectada)'}")
    print(f"Total impreso: {_pesos(resultado.total_impreso)}")
    if not args.solo_ocr:
        print(f"\n=== Ítems normalizados ({len(resultado.items)}) ===")
        for item in resultado.items:
            marca = " ⚠ REVISAR" if item.revisar else ""
            alimento = "" if item.es_alimento else " (no alimento)"
            print(
                f"- [{item.codigo or 'sin código'}] {item.nombre}: {item.cantidad:g} {item.unidad}"
                f" × {_pesos(item.precio_unitario)} = {_pesos(item.precio_total)}"
                f" · {item.categoria}{alimento} · origen={item.origen}{marca}"
            )
        verificacion = "✗ REVISAR" if resultado.requiere_revision else "✓"
        if resultado.total_impreso is None:
            verificacion = "? (no se encontró el TOTAL impreso)"
        print(
            f"\nTotal impreso vs calculado: {_pesos(resultado.total_impreso)}"
            f" vs {_pesos(resultado.total_calculado)} {verificacion}"
        )

    if resultado.error:
        # El detalle de la excepción ya lo imprimió el logging del pipeline.
        print(f"\nERROR: {resultado.error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
