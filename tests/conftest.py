import cv2
import fakeredis
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.auth.dependencies import get_usuario_actual
from app.catalog.models import Producto
from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.db import DbSession, SessionLocal
from app.core.storage import AlmacenamientoLocal, get_storage
from app.governance.models import Consentimiento, RegistroAuditoria
from app.governance.service import VERSION_POLITICA_VIGENTE, hash_sub
from app.inventory.models import ItemInventario
from app.invoices.models import Factura
from app.invoices.router import get_normalizador
from app.main import app
from app.ocr.normalizacion import ItemDetectado
from app.preferences.models import PreferenciasHogar
from app.recommendations.generacion import RecetasGeneradas
from app.recommendations.models import Recomendacion
from app.recommendations.router import get_generador, get_generador_fondo
from app.recommendations.schemas import IngredienteIA, RecetaIA
from app.users.models import Hogar, Usuario
from app.users.service import buscar_por_sub

HOGAR_TEST = 9001
OTRO_HOGAR = 9002
# Usuarios de prueba (uno por hogar), con consentimiento. El cliente de pruebas actúa
# como SUB_TEST salvo que un test cambie con actuar_como().
SUB_TEST = "auth0|pytest-hogar-9001"
SUB_OTRO = "auth0|pytest-hogar-9002"
# Otros subs que crean los tests (p. ej. un segundo miembro del hogar). La limpieza
# borra todo lo de estos subs, incluidos sus registros de auditoría.
SUB_SEGUNDO_MIEMBRO = "auth0|pytest-segundo-miembro"
SUBS_DE_PRUEBA = (SUB_TEST, SUB_OTRO, SUB_SEGUNDO_MIEMBRO)
# El catálogo es global (no tiene hogar_id): los tests usan códigos con este
# prefijo para poder borrar solo lo que crearon.
PREFIJO_CODIGO_TEST = "9990"
# EAN-13 con dígito de control válido: el catálogo solo aprende códigos GTIN válidos.
CODIGO_LECHE = PREFIJO_CODIGO_TEST + "000000012"


def item_detectado(**cambios) -> ItemDetectado:
    datos = {
        "codigo": None,
        # Lo impreso tiene que estar en el texto que "leyó" el OCR del test: si no, el
        # anclaje (app/ocr/anclaje.py) descarta el ítem. "LECHE ENTERA" está en la imagen
        # sintética y en TEXTO_FACTURA_VERIFICADA.
        "descripcion_impresa": "LECHE ENTERA",
        "nombre": "Leche entera 1.1 L",
        "cantidad": 2,
        "unidad": "unidad",
        "precio_unitario": 4500,
        "precio_total": 9000,
        "categoria": "lacteos",
        "nombre_incierto": False,
    }
    return ItemDetectado(**(datos | cambios))


ITEMS_FALSOS = [
    item_detectado(codigo=CODIGO_LECHE),
    item_detectado(
        descripcion_impresa="PAN TAJADO",
        nombre="Pan tajado",
        cantidad=1,
        precio_unitario=6200,
        precio_total=6200,
        categoria="panaderia",
    ),
]


def normalizador_falso(texto: str) -> list[ItemDetectado]:
    """Reemplaza a Gemini en los tests: siempre devuelve los mismos ítems."""
    return ITEMS_FALSOS


# Texto OCR de una factura cuyo TOTAL (9,000 + 6,200) cuadra con ITEMS_FALSOS. Con él,
# la factura queda con el total verificado y el catálogo puede aprender sus códigos.
TEXTO_FACTURA_VERIFICADA = f"""\
SUPERMERCADO DE PRUEBA
DESCRIPCION CANT VALOR
{CODIGO_LECHE} LECHE ENTERA 1100ML 2 9.000
PAN TAJADO 1 6.200
TOTAL 15.200
"""


def ocr_falso(monkeypatch, texto: str, confianza: float = 90.0) -> None:
    """Reemplaza a Tesseract: devuelve `texto`, con esa confianza en todas sus palabras."""
    from app.ocr import extraccion

    lectura = extraccion.LecturaOCR(texto, [(p, confianza) for p in texto.split()])
    monkeypatch.setattr(extraccion, "leer", lambda imagen: lectura)


@pytest.fixture
def factura_verificada(monkeypatch):
    """Las facturas que se suban en el test tienen el total verificado (el OCR
    devuelve TEXTO_FACTURA_VERIFICADA y el normalizador falso cuadra con él)."""
    ocr_falso(monkeypatch, TEXTO_FACTURA_VERIFICADA)


def receta_falsa(titulo: str = "Calentado de arroz", **cambios) -> RecetaIA:
    """Receta como la devolvería Gemini. Usa el alimento "p1" y algo que hay que comprar."""
    datos = {
        "titulo": titulo,
        "descripcion": "Un desayuno rápido para aprovechar lo que sobró.",
        "tiempo_minutos": 20,
        "porciones": 2,
        "ingredientes": [
            IngredienteIA(nombre="Arroz", cantidad=2, unidad="taza", item_id="p1"),
            IngredienteIA(nombre="Cebolla larga", cantidad=1, unidad="unidad", item_id=None),
        ],
        "pasos": ["Picar la cebolla.", "Sofreír y agregar el arroz."],
        "por_que": "Usa el arroz antes de que se dañe.",
    }
    return RecetaIA(**(datos | cambios))


def generadas(recetas: list[RecetaIA], modelo: str | None = None) -> RecetasGeneradas:
    """Lo que devuelve un generador: las recetas y el modelo que respondió (por defecto,
    el principal de la configuración)."""
    return RecetasGeneradas(recetas=recetas, modelo=modelo or get_settings().gemini_model_recetas)


def generador_falso(texto: str) -> RecetasGeneradas:
    """Reemplaza a Gemini en las recetas: siempre devuelve las mismas tres."""
    return generadas(
        [receta_falsa(), receta_falsa("Sudado de papa"), receta_falsa("Arroz con verduras")]
    )


def imagen_factura(lineas: list[str] | None = None, extension: str = ".png") -> bytes:
    """Imagen sintética de una factura: texto negro sobre fondo blanco."""
    # Precios con separador de miles, como en las facturas reales: sin encabezado de
    # columnas, son lo que hace que una línea parezca de un producto.
    lineas = lineas or ["SUPERMERCADO EL ROBLE", "LECHE ENTERA 4.500", "PAN TAJADO 6.200"]
    imagen = np.full((60 * len(lineas) + 40, 900, 3), 255, np.uint8)
    for i, linea in enumerate(lineas):
        cv2.putText(
            imagen,
            linea,
            (20, 60 + 60 * i),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (0, 0, 0),
            2,
            cv2.LINE_AA,
        )
    _, datos = cv2.imencode(extension, imagen)
    return datos.tobytes()


@pytest.fixture
def almacenamiento(tmp_path):
    """Storage local en un directorio temporal que pytest borra solo."""
    return AlmacenamientoLocal(tmp_path)


@pytest.fixture(autouse=True)
def sin_precalculo(monkeypatch):
    """El precálculo de recetas queda apagado en todos los tests, sin importar el .env:
    si no, cada POST a /inventario generaría recetas y registros de más. Los tests de
    precálculo lo encienden con la fixture `precalculo_activo`."""
    monkeypatch.setattr(get_settings(), "precalcular_recetas", False)


@pytest.fixture
def precalculo_activo(monkeypatch):
    monkeypatch.setattr(get_settings(), "precalcular_recetas", True)


@pytest.fixture
def servidor_redis():
    """Redis en memoria (fakeredis). Con servidor_redis.connected = False simula que se cayó."""
    return fakeredis.FakeServer()


def crear_usuario(sub: str, hogar_id: int, *, consentimiento: bool = True) -> int:
    """Crea (si no existe) un usuario de prueba en ese hogar y, si se pide, con el
    tratamiento de datos aceptado. Devuelve su id."""
    with SessionLocal() as db:
        usuario = buscar_por_sub(db, sub)
        if usuario is None:
            usuario = Usuario(auth0_sub=sub, email=None, hogar_id=hogar_id)
            db.add(usuario)
            db.flush()
        if consentimiento:
            db.merge(
                Consentimiento(
                    usuario_id=usuario.id,
                    acepta_tratamiento=True,
                    version_politica=VERSION_POLITICA_VIGENTE,
                )
            )
        db.commit()
        return usuario.id


def actuar_como(sub: str) -> None:
    """Las siguientes peticiones del cliente son de este usuario (sin pasar por Auth0).
    Recorre la cadena real usuario -> consentimiento -> hogar_id."""

    def usuario_de_prueba(db: DbSession) -> Usuario:
        return buscar_por_sub(db, sub)

    app.dependency_overrides[get_usuario_actual] = usuario_de_prueba


def _limpiar_datos_de_prueba() -> None:
    """Borra lo que crearon los tests (en orden, por las FK), incluidos los hogares
    nuevos que se crean al volver a entrar con un sub de prueba."""
    with SessionLocal() as db:
        hogares = {HOGAR_TEST, OTRO_HOGAR}
        hogares |= set(
            db.scalars(select(Usuario.hogar_id).where(Usuario.auth0_sub.in_(SUBS_DE_PRUEBA)))
        )
        usuarios = select(Usuario.id).where(Usuario.hogar_id.in_(hogares))
        db.execute(delete(Recomendacion).where(Recomendacion.hogar_id.in_(hogares)))
        db.execute(delete(PreferenciasHogar).where(PreferenciasHogar.hogar_id.in_(hogares)))
        db.execute(delete(ItemInventario).where(ItemInventario.hogar_id.in_(hogares)))
        db.execute(delete(Factura).where(Factura.hogar_id.in_(hogares)))
        db.execute(delete(Producto).where(Producto.codigo.startswith(PREFIJO_CODIGO_TEST)))
        db.execute(delete(Consentimiento).where(Consentimiento.usuario_id.in_(usuarios)))
        db.execute(delete(Usuario).where(Usuario.hogar_id.in_(hogares)))
        db.execute(delete(Hogar).where(Hogar.id.in_(hogares)))
        # La auditoría es append-only para la app; los tests sí limpian sus propias filas.
        hashes = [hash_sub(sub) for sub in SUBS_DE_PRUEBA]
        db.execute(delete(RegistroAuditoria).where(RegistroAuditoria.usuario_sub_hash.in_(hashes)))
        db.commit()


@pytest.fixture
def client(almacenamiento, servidor_redis):
    """Cliente de pruebas que actúa como el usuario SUB_TEST, del hogar HOGAR_TEST, con
    el tratamiento de datos aceptado."""
    _limpiar_datos_de_prueba()  # por si quedó algo de una corrida interrumpida
    # items_inventario.hogar_id tiene FK a hogares: los hogares de prueba deben existir.
    with SessionLocal() as db:
        for hogar_id in (HOGAR_TEST, OTRO_HOGAR):
            db.add(Hogar(id=hogar_id, nombre=f"Hogar de prueba {hogar_id}"))
        db.commit()
    crear_usuario(SUB_TEST, HOGAR_TEST)
    crear_usuario(SUB_OTRO, OTRO_HOGAR)

    actuar_como(SUB_TEST)
    app.dependency_overrides[get_storage] = lambda: almacenamiento
    app.dependency_overrides[get_normalizador] = lambda: normalizador_falso
    cache = fakeredis.FakeRedis(server=servidor_redis, decode_responses=True)
    app.dependency_overrides[get_cache] = lambda: cache
    app.dependency_overrides[get_generador] = lambda: generador_falso
    app.dependency_overrides[get_generador_fondo] = lambda: generador_falso
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    _limpiar_datos_de_prueba()
