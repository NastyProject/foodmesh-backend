"""Etapa 1: preparar la foto para que Tesseract la lea mejor.

Cada función recibe y devuelve una imagen (arreglo de numpy), sin efectos
secundarios, para poder probarlas y evaluarlas por separado.
"""

from dataclasses import dataclass

import cv2
import numpy as np

# El contorno del papel debe ocupar al menos esta fracción de la foto; así no
# confundimos un recuadro pequeño (un logo, una tabla) con la factura completa.
AREA_MINIMA_PAPEL = 0.25


def decodificar(datos: bytes) -> np.ndarray:
    """Bytes de un JPEG/PNG/WebP → imagen BGR. Aplica la orientación EXIF del celular."""
    imagen = cv2.imdecode(np.frombuffer(datos, np.uint8), cv2.IMREAD_COLOR)
    if imagen is None:
        raise ValueError("Los datos no son una imagen válida")
    return imagen


# --- Calidad de la foto (antes del OCR) ---

# El enfoque se mide sobre la imagen reducida a este lado mayor: así el puntaje no
# depende de la resolución de la cámara y un mismo umbral sirve para todas las fotos.
LADO_MEDICION_ENFOQUE = 1000


@dataclass
class Calidad:
    # Varianza del laplaciano: alta si hay bordes nítidos (texto enfocado), baja si la
    # foto está movida o desenfocada. Una foto nítida de una factura da cientos o miles.
    enfoque: float
    ancho: int
    alto: int


def medir_calidad(imagen: np.ndarray) -> Calidad:
    alto, ancho = imagen.shape[:2]
    grises = a_grises(imagen)
    escala = LADO_MEDICION_ENFOQUE / max(alto, ancho)
    if escala < 1:
        tamano = (round(ancho * escala), round(alto * escala))
        grises = cv2.resize(grises, tamano, interpolation=cv2.INTER_AREA)
    return Calidad(enfoque=float(cv2.Laplacian(grises, cv2.CV_64F).var()), ancho=ancho, alto=alto)


def problema_de_calidad(calidad: Calidad, min_enfoque: float, min_lado_px: int) -> str | None:
    """ "imagen_pequena", "imagen_borrosa" o None si la foto sirve para el OCR."""
    if max(calidad.ancho, calidad.alto) < min_lado_px:
        return "imagen_pequena"
    if calidad.enfoque < min_enfoque:
        return "imagen_borrosa"
    return None


def a_grises(imagen: np.ndarray) -> np.ndarray:
    if imagen.ndim == 2:
        return imagen
    return cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)


def _ordenar_esquinas(puntos: np.ndarray) -> np.ndarray:
    """Ordena 4 puntos como: arriba-izq, arriba-der, abajo-der, abajo-izq."""
    puntos = puntos.reshape(4, 2).astype("float32")
    suma = puntos.sum(axis=1)  # x + y: mínima arriba-izq, máxima abajo-der
    resta = np.diff(puntos, axis=1).ravel()  # y - x: mínima arriba-der, máxima abajo-izq
    return np.array(
        [
            puntos[np.argmin(suma)],
            puntos[np.argmin(resta)],
            puntos[np.argmax(suma)],
            puntos[np.argmax(resta)],
        ],
        dtype="float32",
    )


def detectar_contorno_papel(gris: np.ndarray) -> np.ndarray | None:
    """Busca el cuadrilátero más grande de la foto (el papel). None si no lo encuentra."""
    suavizada = cv2.GaussianBlur(gris, (5, 5), 0)
    bordes = cv2.Canny(suavizada, 50, 150)
    # Dilatar une bordes cortados (dobleces, sombras) para cerrar el contorno.
    bordes = cv2.dilate(bordes, np.ones((3, 3), np.uint8), iterations=2)
    contornos, _ = cv2.findContours(bordes, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    area_minima = AREA_MINIMA_PAPEL * gris.shape[0] * gris.shape[1]
    for contorno in sorted(contornos, key=cv2.contourArea, reverse=True)[:5]:
        if cv2.contourArea(contorno) < area_minima:
            break
        perimetro = cv2.arcLength(contorno, True)
        aproximado = cv2.approxPolyDP(contorno, 0.02 * perimetro, True)
        if len(aproximado) == 4:
            return _ordenar_esquinas(aproximado)
    return None


def corregir_perspectiva(gris: np.ndarray) -> np.ndarray:
    """Endereza el papel si encuentra su contorno; si no, devuelve la imagen igual."""
    esquinas = detectar_contorno_papel(gris)
    if esquinas is None:
        return gris

    arriba_izq, arriba_der, abajo_der, abajo_izq = esquinas
    ancho = int(max(np.linalg.norm(abajo_der - abajo_izq), np.linalg.norm(arriba_der - arriba_izq)))
    alto = int(max(np.linalg.norm(arriba_der - abajo_der), np.linalg.norm(arriba_izq - abajo_izq)))
    destino = np.array(
        [[0, 0], [ancho - 1, 0], [ancho - 1, alto - 1], [0, alto - 1]], dtype="float32"
    )
    matriz = cv2.getPerspectiveTransform(esquinas, destino)
    return cv2.warpPerspective(gris, matriz, (ancho, alto))


def binarizar(gris: np.ndarray) -> np.ndarray:
    """Blanco y negro con umbral adaptativo: tolera sombras e iluminación desigual."""
    suavizada = cv2.medianBlur(gris, 3)
    return cv2.adaptiveThreshold(
        suavizada,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,  # tamaño del vecindario (impar): con qué zona se compara cada píxel
        15,  # cuánto más oscuro que su vecindario debe ser un píxel para ser "tinta"
    )


def preprocesar(imagen: np.ndarray) -> np.ndarray:
    return binarizar(corregir_perspectiva(a_grises(imagen)))
