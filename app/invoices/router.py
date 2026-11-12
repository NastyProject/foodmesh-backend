from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.auth.dependencies import HogarId, UsuarioConConsentimiento
from app.core.config import get_settings
from app.core.db import DbSession
from app.core.storage import Storage
from app.inventory.schemas import ItemOut
from app.invoices import service
from app.invoices.models import Factura
from app.invoices.schemas import FacturaOut, ItemFactura, ReprocesoConImagen
from app.ocr import preprocesamiento
from app.ocr.normalizacion import normalizar_con_gemini, normalizar_imagen_con_gemini
from app.ocr.pipeline import Normalizador, NormalizadorImagen
from app.recommendations.precalculo import PrecalculoDep

router = APIRouter(prefix="/facturas", tags=["facturas"])

TIPOS_PERMITIDOS = {"image/jpeg", "image/png", "image/webp"}
TAMANO_MAXIMO = 10 * 1024 * 1024  # 10 MB

# Lo que se le responde al usuario cuando la foto no sirve, para que la repita.
MENSAJES_CALIDAD = {
    "imagen_borrosa": {
        "mensaje": "La foto está borrosa y no se puede leer bien.",
        "consejo": "Tómala de nuevo con buena luz, sin moverte y tocando la pantalla para "
        "enfocar. Acércate a la factura; si es muy larga, toma solo la parte de los "
        "productos.",
    },
    "imagen_ilegible": {
        "mensaje": "No pudimos leer el texto de la foto.",
        "consejo": "Tómala de nuevo de frente, con la factura plana y bien iluminada, sin "
        "sombras ni reflejos, y que el texto se vea nítido en la pantalla antes de "
        "tomarla. Si la factura es larga, toma solo la parte de los productos.",
    },
    "imagen_pequena": {
        "mensaje": "La foto tiene muy poca resolución.",
        "consejo": "Tómala con la cámara del celular, sin usar capturas de pantalla ni "
        "imágenes reenviadas por chat, que llegan comprimidas.",
    },
}


def get_normalizador() -> Normalizador:
    """Dependencia para poder reemplazar Gemini por un falso en los tests."""
    return normalizar_con_gemini


def get_normalizador_imagen() -> NormalizadorImagen:
    """El respaldo con visión, también reemplazable en los tests."""
    return normalizar_imagen_con_gemini


NormalizadorDep = Annotated[Normalizador, Depends(get_normalizador)]
NormalizadorImagenDep = Annotated[NormalizadorImagen, Depends(get_normalizador_imagen)]


def _buscar_o_404(
    db: DbSession, hogar_id: int, factura_id: int, *, bloquear: bool = False
) -> Factura:
    factura = service.obtener_factura(db, hogar_id, factura_id, bloquear=bloquear)
    if factura is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Factura no encontrada")
    return factura


# Los endpoints son `def` (no `async def`): el OCR y Gemini bloquean varios
# segundos, y FastAPI corre las funciones `def` en un hilo aparte para no
# congelar el servidor mientras tanto.
@router.post("", response_model=FacturaOut, status_code=status.HTTP_201_CREATED)
def subir(
    archivo: UploadFile,
    db: DbSession,
    hogar_id: HogarId,
    almacenamiento: Storage,
    normalizar: NormalizadorDep,
):
    if archivo.content_type not in TIPOS_PERMITIDOS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Solo se aceptan imágenes JPEG, PNG o WebP",
        )
    # Leemos un byte más del máximo: si llega, el archivo es demasiado grande
    # (sin cargar en memoria un archivo arbitrariamente grande).
    imagen = archivo.file.read(TAMANO_MAXIMO + 1)
    if len(imagen) > TAMANO_MAXIMO:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="La imagen no puede pesar más de 10 MB",
        )
    # El content_type lo declara el cliente; comprobamos que de verdad es una imagen.
    try:
        decodificada = preprocesamiento.decodificar(imagen)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="El archivo no es una imagen válida",
        ) from None
    # Antes del OCR y de Gemini: una foto borrosa solo daría un resultado malo (y
    # gastaría una llamada). Mejor pedirle al usuario que la repita.
    settings = get_settings()
    calidad = preprocesamiento.medir_calidad(decodificada)
    problema = preprocesamiento.problema_de_calidad(
        calidad, settings.quality_min_enfoque, settings.quality_min_lado_px
    )
    if problema:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"codigo": problema, **MENSAJES_CALIDAD[problema]},
        )

    try:
        return service.crear_factura(db, hogar_id, imagen, almacenamiento, normalizar)
    except service.ImagenIlegible:
        # Se detecta después del OCR y antes de Gemini: no se guardó nada.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"codigo": "imagen_ilegible", **MENSAJES_CALIDAD["imagen_ilegible"]},
        ) from None


@router.get("", response_model=list[FacturaOut])
def listar(db: DbSession, hogar_id: HogarId):
    return service.listar_facturas(db, hogar_id)


@router.get("/{factura_id}", response_model=FacturaOut)
def obtener(factura_id: int, db: DbSession, hogar_id: HogarId):
    return _buscar_o_404(db, hogar_id, factura_id)


@router.post(
    "/{factura_id}/confirmar",
    response_model=list[ItemOut],
    status_code=status.HTTP_201_CREATED,
)
def confirmar(
    factura_id: int,
    items: list[ItemFactura],
    db: DbSession,
    hogar_id: HogarId,
    almacenamiento: Storage,
    precalculo: PrecalculoDep,
):
    factura = _buscar_o_404(db, hogar_id, factura_id, bloquear=True)
    try:
        creados = service.confirmar_factura(db, factura, items, almacenamiento)
    except service.FacturaYaConfirmada:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="La factura ya fue confirmada"
        ) from None
    if any(item.es_alimento for item in creados):
        precalculo.programar(hogar_id)
    return creados


@router.post("/{factura_id}/reprocesar-con-imagen", response_model=FacturaOut)
def reprocesar_con_imagen(
    factura_id: int,
    autorizacion: ReprocesoConImagen,
    db: DbSession,
    hogar_id: HogarId,
    usuario: UsuarioConConsentimiento,
    almacenamiento: Storage,
    normalizar_imagen: NormalizadorImagenDep,
):
    """Respaldo con visión para formatos que el texto del OCR no resuelve. Body
    obligatorio: {"acepto_enviar_imagen": true}, porque la foto completa (con todos
    los datos de la factura) se envía a Google. Reemplaza los items_detectados."""
    # Sin bloquear aquí: la llamada a Gemini tarda segundos. El servicio bloquea la
    # fila justo antes de escribir.
    factura = _buscar_o_404(db, hogar_id, factura_id)
    try:
        return service.reprocesar_con_imagen(
            db, factura, usuario, almacenamiento, normalizar_imagen
        )
    except service.FacturaNoReprocesable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta factura ya no se puede reprocesar: ya fue confirmada o su imagen "
            "ya no está disponible.",
        ) from None
    except service.ReprocesoFallido:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de lectura de facturas no está disponible en este momento. "
            "Intenta de nuevo en unos minutos.",
        ) from None
