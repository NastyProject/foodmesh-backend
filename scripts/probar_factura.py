"""Corre el pipeline OCR sobre una imagen, sin levantar la API ni tocar la BD.

Uso (desde la raíz del proyecto, con el .env configurado):
    python scripts/probar_factura.py ruta/a/factura.jpg
    # Sin llamar a Gemini:
    python scripts/probar_factura.py factura.jpg --solo-ocr
    # Con el respaldo de visión: la FOTO completa se envía a Gemini
    python scripts/probar_factura.py factura.jpg --modo vision
    # Procesar aunque la foto no pase la validación de calidad (para calibrar)
    python scripts/probar_factura.py factura.jpg --sin-validar-calidad
    # Guardar la imagen binarizada, para ver lo mismo que ve Tesseract:
    python scripts/probar_factura.py factura.jpg --guardar-preprocesada binarizada.png

Como no toca la BD, no consulta el catálogo de productos: todos los ítems salen
con origen "ia" (en la API, los que tengan código conocido saldrán como "catalogo").

El texto OCR completo se muestra en pantalla para depurar, pero la API no lo guarda:
en la factura queda solo el bloque de productos.
"""

import argparse
import sys
from pathlib import Path

# Permite importar `app` al correr el script directamente con `python scripts/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.ocr import preprocesamiento  # noqa: E402
from app.ocr.normalizacion import (  # noqa: E402
    normalizar_con_gemini,
    normalizar_imagen_con_gemini,
)
from app.ocr.pipeline import procesar_factura, procesar_factura_con_imagen  # noqa: E402


def _pesos(valor: float | None) -> str:
    return f"${valor:,.0f}" if valor is not None else "?"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("imagen", type=Path, help="ruta de la foto de la factura")
    parser.add_argument("--solo-ocr", action="store_true", help="no llamar a Gemini")
    parser.add_argument(
        "--modo",
        choices=["texto", "vision"],
        default="texto",
        help="texto: OCR + texto anonimizado a Gemini (por defecto); "
        "vision: la foto completa a Gemini",
    )
    parser.add_argument(
        "--sin-validar-calidad",
        action="store_true",
        help="procesar aunque la foto esté borrosa, tenga poca resolución o el OCR sea ilegible",
    )
    parser.add_argument(
        "--guardar-preprocesada", type=Path, metavar="RUTA", help="guardar la imagen binarizada"
    )
    args = parser.parse_args()

    datos = args.imagen.read_bytes()

    # La misma validación que POST /facturas, antes del OCR.
    settings = get_settings()
    calidad = preprocesamiento.medir_calidad(preprocesamiento.decodificar(datos))
    problema = preprocesamiento.problema_de_calidad(
        calidad, settings.quality_min_enfoque, settings.quality_min_lado_px
    )
    print("=== Calidad de la foto ===")
    print(
        f"Enfoque (varianza del laplaciano): {calidad.enfoque:.1f}"
        f" (mínimo: {settings.quality_min_enfoque:g})"
    )
    print(
        f"Tamaño: {calidad.ancho} × {calidad.alto} px"
        f" (lado mayor mínimo: {settings.quality_min_lado_px})"
    )
    print(f"Resultado: {problema or 'aceptada'}\n")
    if problema and not args.sin_validar_calidad:
        print(
            "La API la rechazaría con 422. Usa --sin-validar-calidad para procesarla igual.",
            file=sys.stderr,
        )
        return 2

    if args.guardar_preprocesada:
        procesada = preprocesamiento.preprocesar(preprocesamiento.decodificar(datos))
        cv2.imwrite(str(args.guardar_preprocesada), procesada)
        print(f"Imagen preprocesada guardada en {args.guardar_preprocesada}")

    validar = not args.sin_validar_calidad
    if args.solo_ocr:
        resultado = procesar_factura(datos, lambda texto: [], validar_legibilidad=validar)
    elif args.modo == "vision":
        resultado = procesar_factura_con_imagen(datos, normalizar_imagen_con_gemini)
    else:
        resultado = procesar_factura(datos, normalizar_con_gemini, validar_legibilidad=validar)

    if resultado.legibilidad:
        legibilidad = resultado.legibilidad
        print("=== Legibilidad del OCR (después de Tesseract, antes de Gemini) ===")
        print(
            f"Confianza media de Tesseract: {legibilidad.confianza_media:.1f}"
            f" (mínimo: {settings.quality_min_confianza_ocr:g})"
        )
        print(
            f"Tokens legibles: {legibilidad.tokens_legibles:.2f} de {legibilidad.tokens} tokens"
            f" (mínimo: {settings.quality_min_tokens_legibles:g})"
        )
        print(f"Resultado: {resultado.problema_calidad or 'legible'}\n")
    if resultado.problema_calidad:
        print(
            "La API la rechazaría con 422 (imagen_ilegible), sin llamar a Gemini. Usa "
            "--sin-validar-calidad para procesarla igual.",
            file=sys.stderr,
        )
        return 2

    print("=== Texto OCR completo (anonimizado; solo en pantalla, NO se guarda) ===")
    print(resultado.texto_completo or "(vacío)")
    if args.modo == "vision" and not args.solo_ocr:
        print("\n=== A Gemini se envió la FOTO completa (modo visión) ===")
    else:
        recorte = (
            "solo el bloque de productos"
            if resultado.recortada
            else "solo las líneas que parecen de productos"
        )
        print(f"\n=== Texto enviado a Gemini ({recorte}) ===")
        print(resultado.texto_enviado or "(vacío)")
    print("\n=== Texto que se guarda en la factura ===")
    print(resultado.texto_guardado or "(nada: no se encontraron líneas de productos)")
    print("\n=== Encabezado (reglas locales) ===")
    print(f"Supermercado: {resultado.supermercado or '(no detectado)'}")
    print(f"Fecha de compra: {resultado.fecha_compra or '(no detectada)'}")
    print(f"Total impreso: {_pesos(resultado.total_impreso)}")
    if not args.solo_ocr:
        print(f"\n=== Ítems normalizados, modo {args.modo} ({len(resultado.items)}) ===")
        for item in resultado.items:
            marca = " ⚠ REVISAR" if item.revisar else ""
            marca += " ⚠ NOMBRE INCIERTO" if item.nombre_incierto else ""
            alimento = "" if item.es_alimento else " (no alimento)"
            print(
                f"- [{item.codigo or 'sin código'}] {item.nombre}"
                f" (impreso: {item.descripcion_impresa or '?'}): {item.cantidad:g} {item.unidad}"
                f" × {_pesos(item.precio_unitario)} = {_pesos(item.precio_total)}"
                f" · {item.categoria}{alimento} · origen={item.origen}{marca}"
            )
        if resultado.items_descartados:
            print(
                f"({resultado.items_descartados} ítems descartados: su descripción no está"
                " en el texto enviado)"
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
