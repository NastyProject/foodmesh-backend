from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.auth.dependencies import HogarId
from app.core.db import DbSession
from app.core.storage import Storage
from app.inventory.schemas import ItemOut
from app.invoices import service
from app.invoices.models import Factura
from app.invoices.schemas import FacturaOut, ItemFactura
from app.ocr import preprocesamiento
from app.ocr.normalizacion import normalizar_con_gemini
from app.ocr.pipeline import Normalizador

router = APIRouter(prefix="/facturas", tags=["facturas"])

TIPOS_PERMITIDOS = {"image/jpeg", "image/png", "image/webp"}
TAMANO_MAXIMO = 10 * 1024 * 1024  # 10 MB


def get_normalizador() -> Normalizador:
    """Dependencia para poder reemplazar Gemini por un falso en los tests."""
    return normalizar_con_gemini


NormalizadorDep = Annotated[Normalizador, Depends(get_normalizador)]


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
        preprocesamiento.decodificar(imagen)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="El archivo no es una imagen válida",
        ) from None

    return service.crear_factura(db, hogar_id, imagen, almacenamiento, normalizar)


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
):
    factura = _buscar_o_404(db, hogar_id, factura_id, bloquear=True)
    try:
        return service.confirmar_factura(db, factura, items, almacenamiento)
    except service.FacturaYaConfirmada:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="La factura ya fue confirmada"
        ) from None
