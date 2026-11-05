"""Mide la latencia real de Gemini al generar recetas, sin caché ni BD.

Hace N llamadas con un inventario de ejemplo fijo y las preferencias por defecto, e
imprime el tiempo de cada una (con sus tokens) y el mínimo, la mediana y el p95.
Llama a Gemini de verdad: cada llamada consume cuota de la API.

Uso (desde la raíz del proyecto, con el .env configurado):
    python scripts/medir_latencia_recetas.py            # 10 llamadas
    python scripts/medir_latencia_recetas.py -n 30
    python scripts/medir_latencia_recetas.py --modelo gemini-3.6-flash
"""

import argparse
import logging
import statistics
import sys
import time
from pathlib import Path

# Permite importar `app` al correr el script directamente con `python scripts/...`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.core.gemini import cliente_gemini  # noqa: E402
from app.preferences.schemas import Preferencias  # noqa: E402
from app.recommendations.generacion import (  # noqa: E402
    ItemParaReceta,
    armar_entrada,
    generar_recetas,
)

# Un inventario típico: algunos productos próximos a vencer y otros sin fecha.
INVENTARIO = [
    ("Pechuga de pollo", 0.8, "kg", 1),
    ("Espinaca", 1, "unidad", 1),
    ("Tomate chonto", 6, "unidad", 2),
    ("Leche entera 1.1 L", 1, "unidad", 2),
    ("Zanahoria", 4, "unidad", 3),
    ("Papa pastusa", 2, "kg", 7),
    ("Cebolla cabezona", 3, "unidad", 10),
    ("Huevos AA x12", 1, "unidad", 12),
    ("Arroz blanco 1 kg", 1, "unidad", None),
    ("Fríjol rojo 500 g", 1, "unidad", None),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", type=int, default=10, help="número de llamadas (mínimo 2)")
    parser.add_argument("--modelo", help="modelo a medir (por defecto, GEMINI_MODEL_RECETAS)")
    args = parser.parse_args()
    if args.n < 2:
        parser.error("se necesitan al menos 2 llamadas para calcular percentiles")

    # Muestra el log de cada llamada (modelo, ms y tokens de entrada, thinking y salida).
    logging.basicConfig(level=logging.INFO, format="  %(message)s", stream=sys.stdout)
    for ruidoso in ("httpx", "google_genai"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)

    modelo = args.modelo or get_settings().gemini_model_recetas
    items = [
        ItemParaReceta(f"p{i}", nombre, cantidad, unidad, dias)
        for i, (nombre, cantidad, unidad, dias) in enumerate(INVENTARIO, start=1)
    ]
    texto = armar_entrada(items, Preferencias())
    cliente = cliente_gemini()

    print(f"Modelo: {modelo} | {args.n} llamadas | entrada de {len(texto)} caracteres\n")
    tiempos: list[int] = []
    fallidas = 0
    for i in range(1, args.n + 1):
        inicio = time.perf_counter()
        try:
            # Sin modelo de respaldo: se mide solo el modelo pedido.
            recetas = generar_recetas(texto, cliente, modelo).recetas
        except Exception as error:  # una falla no detiene la medición
            fallidas += 1
            print(f"[{i}/{args.n}] falló: {error}")
            continue
        ms = round((time.perf_counter() - inicio) * 1000)
        tiempos.append(ms)
        print(f"[{i}/{args.n}] {ms} ms, {len(recetas)} recetas")

    if len(tiempos) < 2:
        print("\nMuy pocas llamadas exitosas para calcular estadísticas.")
        return 1
    # quantiles(n=20) parte los datos en 20 grupos; el corte 19 (índice 18) es el p95.
    p95 = statistics.quantiles(tiempos, n=20, method="inclusive")[18]
    print(f"\nExitosas: {len(tiempos)} | fallidas: {fallidas}")
    print(f"Mínimo:  {min(tiempos)} ms")
    print(f"Mediana: {statistics.median(tiempos):.0f} ms")
    print(f"p95:     {p95:.0f} ms")
    print(f"Máximo:  {max(tiempos)} ms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
