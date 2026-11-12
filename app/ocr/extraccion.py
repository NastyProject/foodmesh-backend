"""Etapa 2: extraer el texto de la imagen preprocesada con Tesseract."""

from dataclasses import dataclass, field

import numpy as np
import pytesseract

# --psm 6: tratar la imagen como un único bloque de texto. Una factura es una
# columna de renglones; el modo automático tiende a partirla en bloques sueltos.
CONFIG_TESSERACT = "--psm 6"


@dataclass
class LecturaOCR:
    texto: str
    # (palabra, confianza de Tesseract de 0 a 100), en orden. Para medir la
    # legibilidad (app/ocr/legibilidad.py) antes de enviar nada a Gemini.
    palabras: list[tuple[str, float]] = field(default_factory=list)


def leer(imagen: np.ndarray, lang: str = "spa") -> LecturaOCR:
    """Texto y confianza por palabra, en UNA pasada de Tesseract (image_to_data).

    El texto se arma con las palabras de cada renglón separadas por un espacio y un
    renglón por línea, como lo devuelve image_to_string.
    """
    datos = pytesseract.image_to_data(
        imagen, lang=lang, config=CONFIG_TESSERACT, output_type=pytesseract.Output.DICT
    )
    renglones: dict[tuple[int, int, int], list[str]] = {}
    palabras = []
    for i, palabra in enumerate(datos["text"]):
        palabra = palabra.strip()
        if not palabra:
            continue
        clave = (datos["block_num"][i], datos["par_num"][i], datos["line_num"][i])
        renglones.setdefault(clave, []).append(palabra)
        confianza = float(datos["conf"][i])
        if confianza >= 0:  # -1: no es una palabra (bloques, renglones vacíos)
            palabras.append((palabra, confianza))
    texto = "\n".join(" ".join(renglon) for renglon in renglones.values())
    return LecturaOCR(texto=texto, palabras=palabras)


def extraer_texto(imagen: np.ndarray, lang: str = "spa") -> str:
    return leer(imagen, lang).texto
