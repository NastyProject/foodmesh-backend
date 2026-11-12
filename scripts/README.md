# Scripts

Se corren desde la raíz del proyecto, con el `.env` configurado (`GEMINI_API_KEY`) y el entorno virtual activado. Ninguno toca la base de datos.

| Script | Para qué |
|---|---|
| `probar_factura.py` | Corre el pipeline de facturas sobre **una** imagen y muestra cada etapa |
| `evaluar_ocr.py` | Evalúa el pipeline sobre **varias** facturas contra una verdad etiquetada a mano |
| `medir_latencia_recetas.py` | Mide la latencia de Gemini al generar recetas |

Cada llamada a Gemini consume cuota de la API. En el **modo visión**, la foto completa de la factura (con todos sus datos) se envía a Google: úsalo solo con facturas propias o de prueba.

## `probar_factura.py`

```bash
python scripts/probar_factura.py ~/facturas-prueba/factura2.jpg               # modo texto (por defecto)
python scripts/probar_factura.py ~/facturas-prueba/factura2.jpg --modo vision # la foto a Gemini
python scripts/probar_factura.py ~/facturas-prueba/factura2.jpg --solo-ocr    # sin llamar a Gemini
python scripts/probar_factura.py ~/facturas-prueba/borrosa.jpg --sin-validar-calidad
```

Muestra:
- la **calidad de la foto**: el enfoque (varianza del laplaciano) y el tamaño, con los mínimos `QUALITY_MIN_ENFOQUE` y `QUALITY_MIN_LADO_PX`;
- la **legibilidad del OCR**, después de Tesseract y antes de Gemini: la confianza media de Tesseract y la proporción de tokens legibles, con los mínimos `QUALITY_MIN_CONFIANZA_OCR` y `QUALITY_MIN_TOKENS_LEGIBLES`. El enfoque solo filtra fotos muy desenfocadas; la legibilidad es la que separa una foto que se lee de una que no (en las fotos del compañero B, 3.jpeg y 4.jpeg tenían buen enfoque y el OCR leyó basura);
- si la foto no pasa alguna de las dos, se detiene, como haría la API con un `422`. Con `--sin-validar-calidad` la procesa igual: sirve para calibrar los umbrales, comparando las métricas de fotos que se leen bien con las de fotos que no;
- el texto OCR completo (anonimizado), que es solo para depurar y que la API **no guarda**;
- lo que se envió a Gemini;
- lo que se guarda en la factura (solo el bloque de productos);
- el encabezado (supermercado, fecha, total impreso);
- los ítems, marcando `⚠ REVISAR` y `⚠ NOMBRE INCIERTO`.

## `evaluar_ocr.py`

```bash
python scripts/evaluar_ocr.py ~/facturas-prueba verdad.csv                     # solo modo texto
python scripts/evaluar_ocr.py ~/facturas-prueba verdad.csv --modos texto vision
python scripts/evaluar_ocr.py ~/facturas-prueba verdad.csv --json resultados.json
```

Para cada modo calcula las métricas de todas las facturas y, por separado, las de las imágenes `original` y las `mejorada_ia` (columna `origen_imagen` del CSV). Así no se mezclan en el artículo los resultados de fotos reales con los de fotos retocadas. Las métricas son:

| Métrica | Qué es |
|---|---|
| Ítems detectados | Cuántos ítems devolvió el pipeline |
| Precisión | De los detectados, cuántos corresponden a un producto real |
| Recall | De los productos reales, cuántos se detectaron |
| F1 | Media armónica de precisión y recall |
| % precios correctos | De los ítems emparejados, cuántos tienen bien la cantidad, el precio unitario y el total |
| % facturas con total verificado | Facturas cuya suma de ítems cuadró exacto (±$1) con el TOTAL impreso |
| Latencia | Mediana y máximo por factura (OCR + Gemini) |

**Cómo se empareja** un ítem detectado con uno real: 1 a 1, de mejor a peor parecido. Una pareja cuenta si los nombres se parecen al menos 0.5, o si cobran lo mismo y los nombres se parecen al menos 0.25. El parecido es el mayor entre la similitud de los textos y la fracción de palabras del nombre real (por sus primeras 4 letras) que aparecen en el detectado. Es aproximado: para afirmar que un nombre es "correcto" (p. ej. "Huevos" contra "Huevos de codorniz"), revisa el JSON a mano.

### Formato del CSV de verdad

Un renglón por producto de cada factura, tal como está en la factura física, en UTF-8 y con encabezado:

```csv
factura,nombre,cantidad,precio_unitario,precio_total,origen_imagen
factura3,Azúcar blanca,1,3190,3190,original
factura3,Clavo entero,1,2200,2200,original
factura3,Arroz premium,1,3990,3990,original
factura5,Yogurt griego,1,17450,17450,original
factura5,Gelatina sabores,1,4450,4450,original
9gpt,Leche Alkosto entera 1100 ml x6,6,11300,67800,mejorada_ia
```

| Columna | Contenido |
|---|---|
| `factura` | Nombre del archivo de la imagen **sin extensión**: `factura3` para `factura3.JPG`. Debe coincidir exacto, con mayúsculas y minúsculas |
| `nombre` | Nombre del producto, legible (no hace falta copiar la abreviatura de la factura) |
| `cantidad` | Unidades, o kg para productos por peso. Decimales con punto o coma: `1.25` o `1,25` |
| `precio_unitario` | En pesos. Puede ir vacío si la factura no lo muestra |
| `precio_total` | En pesos, lo que se pagó por ese renglón. Obligatorio |
| `origen_imagen` | `original` (la foto tal como se tomó) o `mejorada_ia` (una foto que se mejoró con IA antes de evaluarla). Opcional: si falta la columna o la celda, cuenta como `original`. Debe ser igual en todos los renglones de una misma factura |

- Los precios van sin decimales; se aceptan con separador de miles (`3,990`, `3.990`) o sin él (`3990`). Si usas separador, pon el valor entre comillas, porque la coma también separa columnas: `"3,990"`.
- Un producto que aparece dos veces en la factura (dos renglones) va en dos renglones del CSV.
- Las bolsas que se cobran como renglón cuentan como producto.
- Las facturas del CSV sin imagen en la carpeta, y las imágenes sin renglones en el CSV, se ignoran (las primeras con un aviso).

## `medir_latencia_recetas.py`

```bash
python scripts/medir_latencia_recetas.py -n 30
python scripts/medir_latencia_recetas.py -n 10 --modelo gemini-3.1-flash-lite
```

Hace N llamadas reales sin caché con un inventario de ejemplo e imprime mínimo, mediana, p95 y máximo.
