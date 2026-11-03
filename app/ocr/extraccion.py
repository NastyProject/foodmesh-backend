"""Etapa 2: extraer el texto de la imagen preprocesada con Tesseract."""

import numpy as np
import pytesseract

# --psm 6: tratar la imagen como un único bloque de texto. Una factura es una
# columna de renglones; el modo automático tiende a partirla en bloques sueltos.
CONFIG_TESSERACT = "--psm 6"


def extraer_texto(imagen: np.ndarray, lang: str = "spa") -> str:
    return pytesseract.image_to_string(imagen, lang=lang, config=CONFIG_TESSERACT)
