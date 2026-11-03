import pytest

from app.core.storage import key_imagen_factura


def test_key_imagen_factura():
    assert key_imagen_factura(3, 15) == "facturas/3/15.jpg"


def test_guardar_leer_y_borrar(almacenamiento):
    key = key_imagen_factura(1, 2)
    almacenamiento.guardar(key, b"bytes de la imagen")
    assert almacenamiento.leer(key) == b"bytes de la imagen"

    almacenamiento.borrar(key)
    with pytest.raises(FileNotFoundError):
        almacenamiento.leer(key)


def test_borrar_algo_que_no_existe_no_falla(almacenamiento):
    almacenamiento.borrar("facturas/1/no-existe.jpg")
