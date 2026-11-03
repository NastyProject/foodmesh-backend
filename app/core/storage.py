from functools import lru_cache
from pathlib import Path
from typing import Annotated, Protocol

import boto3
from fastapi import Depends

from app.core.config import get_settings


class Almacenamiento(Protocol):
    """Interfaz común: el resto del código no sabe si guarda en disco o en S3."""

    def guardar(self, key: str, datos: bytes) -> None: ...

    def leer(self, key: str) -> bytes: ...

    def borrar(self, key: str) -> None: ...


def key_imagen_factura(hogar_id: int, factura_id: int) -> str:
    return f"facturas/{hogar_id}/{factura_id}.jpg"


class AlmacenamientoLocal:
    """Guarda los archivos en disco, bajo un directorio base. Para desarrollo y tests."""

    def __init__(self, directorio: Path) -> None:
        self.directorio = directorio

    def _ruta(self, key: str) -> Path:
        return self.directorio / key

    def guardar(self, key: str, datos: bytes) -> None:
        ruta = self._ruta(key)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)

    def leer(self, key: str) -> bytes:
        return self._ruta(key).read_bytes()

    def borrar(self, key: str) -> None:
        # Borrar algo que ya no existe no es un error (igual que en S3).
        self._ruta(key).unlink(missing_ok=True)


class AlmacenamientoS3:
    """Guarda los archivos en un bucket de S3. boto3 toma las credenciales del entorno."""

    def __init__(self, bucket: str, cliente=None) -> None:
        self.bucket = bucket
        self.cliente = cliente or boto3.client("s3")

    def guardar(self, key: str, datos: bytes) -> None:
        self.cliente.put_object(Bucket=self.bucket, Key=key, Body=datos)

    def leer(self, key: str) -> bytes:
        return self.cliente.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def borrar(self, key: str) -> None:
        self.cliente.delete_object(Bucket=self.bucket, Key=key)


@lru_cache
def get_storage() -> Almacenamiento:
    """Almacenamiento según STORAGE_BACKEND. Se crea una sola vez por proceso."""
    settings = get_settings()
    if settings.storage_backend == "s3":
        if not settings.s3_bucket:
            raise RuntimeError("STORAGE_BACKEND=s3 requiere S3_BUCKET")
        return AlmacenamientoS3(settings.s3_bucket)
    return AlmacenamientoLocal(Path(settings.local_storage_dir))


Storage = Annotated[Almacenamiento, Depends(get_storage)]
