import hashlib
import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import redis
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.gemini import ESPERA_REINTENTO_SEGUNDOS, INTENTOS_CON_RESPALDO
from app.inventory import service as inventory_service
from app.inventory.models import ItemInventario
from app.preferences import service as preferences_service
from app.preferences.schemas import Preferencias
from app.recommendations.basicos import es_basico
from app.recommendations.generacion import (
    DIAS_PROXIMO_A_VENCER,
    NUMERO_RECETAS,
    VERSION_PROMPT,
    Generador,
    ItemParaReceta,
    armar_entrada,
)
from app.recommendations.models import Recomendacion, TipoRecomendacion
from app.recommendations.restricciones import (
    alergenos_en,
    item_compatible,
    violaciones_de_dieta,
)
from app.recommendations.schemas import (
    IngredienteOut,
    ItemProximoAVencer,
    RecetaIA,
    RecetaOut,
    RespuestaRecomendacion,
)

logger = logging.getLogger(__name__)

AVISO = "Verifica siempre los ingredientes si tienes alergias: las recetas son generadas por IA."
SIN_RECETAS = (
    "No encontramos recetas que cumplan tus preferencias con lo que tienes en el inventario. "
    "Intenta pedir otras recetas, agrega productos o revisa tus preferencias."
)
# Una receta puede pasarse del tiempo máximo del hogar hasta en este porcentaje.
TOLERANCIA_TIEMPO = 0.20
# Para "otras recetas": se le piden a Gemini recetas distintas a las de estas últimas
# recomendaciones del hogar, sin pasar de este número de títulos.
RECOMENDACIONES_A_EVITAR = 5
MAXIMO_TITULOS_A_EVITAR = 15
# Rondas de validación: si ninguna receta pasa, se le pide a Gemini otra ronda con los
# motivos del descarte. Cada ronda es una llamada a generar(), que a su vez puede
# reintentar por error de red o timeout (app/core/gemini.py).
RONDAS_VALIDACION = 2
# Cada cuánto revisa la caché un POST que espera a que otro termine de generar.
INTERVALO_ESPERA_LOCK = 1.0  # segundos
# Colombia no tiene horario de verano: UTC-5 todo el año. Se usa para "hoy" y los días
# para vencer, así no depende de la zona horaria del servidor (en la nube suele ser UTC).
ZONA_COLOMBIA = timezone(timedelta(hours=-5))

_LISTA_RECETAS = TypeAdapter(list[RecetaOut])


class SinAlimentos(Exception):
    pass


class SinAlimentosCompatibles(Exception):
    """Hay alimentos, pero ninguno compatible con la dieta y las alergias del hogar."""


class GeneracionFallida(Exception):
    pass


class IndiceRecetaInvalido(Exception):
    pass


def hoy() -> date:
    return datetime.now(ZONA_COLOMBIA).date()


def _dias_para_vencer(item: ItemInventario, fecha: date) -> int | None:
    if item.fecha_vencimiento is None:
        return None
    return (item.fecha_vencimiento - fecha).days


def alimentos_disponibles(db: Session, hogar_id: int, fecha: date) -> list[ItemInventario]:
    """Alimentos del inventario que no han vencido y no son básicos de cocina. Los
    vencidos no se proponen para cocinar (no sería seguro); los básicos (sal, aceite...)
    se asumen siempre disponibles, así que no se le envían a Gemini ni cuentan para la
    caché."""
    items = inventory_service.listar_items(db, hogar_id, solo_alimentos=True)
    return [
        item
        for item in items
        if (_dias_para_vencer(item, fecha) or 0) >= 0 and not es_basico(item.nombre)
    ]


def alimentos_compatibles(
    items: list[ItemInventario], preferencias: Preferencias
) -> list[ItemInventario]:
    """Los que se le pueden enviar a Gemini: sin los que la dieta o las alergias del
    hogar prohíben. La validación de las recetas sigue revisando después, por si la IA
    agrega por su cuenta un ingrediente prohibido."""
    return [
        item
        for item in items
        if item_compatible(item.nombre, item.categoria, preferencias.dieta, preferencias.alergias)
    ]


# --- Caché ---


def clave_cache(
    hogar_id: int,
    items: list[ItemInventario],
    preferencias: Preferencias,
    fecha: date,
    modelo: str,
) -> str:
    """Hash de todo lo que, si cambia, debe dar recetas distintas.

    - hogar_id: dos hogares con el mismo inventario no comparten recetas (los
      item_id de la respuesta son de un hogar).
    - inventario: id, nombre, cantidad y fecha de vencimiento de cada alimento,
      ordenados por id para que el orden de la consulta no cambie la clave. El nombre
      va porque es lo que lee Gemini: renombrar un ítem debe dar recetas nuevas.
    - preferencias completas, con las listas ordenadas.
    - fecha de hoy: los días para vencer cambian cada día.
    - modelo y versión del prompt: cambiar cualquiera de los dos da recetas distintas.
    """
    preferencias_json = preferencias.model_dump(mode="json")
    for lista in ("alergias", "no_le_gusta"):
        preferencias_json[lista] = sorted(preferencias_json[lista], key=str.lower)
    contenido = {
        "hogar_id": hogar_id,
        "inventario": sorted(
            [
                item.id,
                item.nombre,
                item.cantidad,
                item.fecha_vencimiento.isoformat() if item.fecha_vencimiento else None,
            ]
            for item in items
        ),
        "preferencias": preferencias_json,
        "fecha": fecha.isoformat(),
        "modelo": modelo,
        "version_prompt": VERSION_PROMPT,
    }
    # sort_keys: el mismo contenido siempre produce el mismo JSON, y por tanto el mismo hash.
    serializado = json.dumps(contenido, sort_keys=True, separators=(",", ":"))
    return "recetas:" + hashlib.sha256(serializado.encode()).hexdigest()


def _leer_cache(cache: redis.Redis | None, clave: str) -> list[RecetaOut] | None:
    """Recetas guardadas con esa clave, o None si no hay (o si Redis no responde)."""
    if cache is None:
        return None
    try:
        guardado = cache.get(clave)
    except redis.RedisError as error:
        # Sin traceback: si Redis se cae, saldría uno en cada petición.
        logger.warning("Redis no disponible, se generan las recetas sin caché: %s", error)
        return None
    if guardado is None:
        return None
    try:
        return _LISTA_RECETAS.validate_json(guardado)
    except ValidationError:
        # Algo viejo o corrupto en la caché: se ignora y se genera de nuevo.
        logger.warning("Valor inválido en caché para %s: se ignora", clave)
        return None


def modelos_recetas() -> list[str]:
    """Los modelos que pueden haber generado recetas: el principal y, si hay, el de
    respaldo. En ese orden se busca en la caché."""
    settings = get_settings()
    modelos = [settings.gemini_model_recetas]
    respaldo = settings.gemini_model_recetas_respaldo
    if respaldo and respaldo != modelos[0]:
        modelos.append(respaldo)
    return modelos


def _claves_por_modelo(
    hogar_id: int, items: list[ItemInventario], preferencias: Preferencias, fecha: date
) -> dict[str, str]:
    return {
        modelo: clave_cache(hogar_id, items, preferencias, fecha, modelo)
        for modelo in modelos_recetas()
    }


@dataclass
class EnCache:
    recetas: list[RecetaOut]
    modelo: str  # el que las generó: sale de con qué clave se encontraron


def _buscar_en_cache(cache: redis.Redis | None, claves: dict[str, str]) -> EnCache | None:
    """Las recetas de la primera clave que tenga algo, en el orden de modelos_recetas().
    Si el principal estaba saturado y respondió el de respaldo, sus recetas quedaron
    con la clave del respaldo: buscar en las dos evita volver a generarlas."""
    for modelo, clave in claves.items():
        recetas = _leer_cache(cache, clave)
        if recetas is not None:
            return EnCache(recetas=recetas, modelo=modelo)
    return None


def _guardar_cache(cache: redis.Redis | None, clave: str, recetas: list[RecetaOut]) -> None:
    if cache is None:
        return
    try:
        cache.set(clave, _LISTA_RECETAS.dump_json(recetas), ex=get_settings().recetas_cache_ttl)
    except redis.RedisError as error:
        logger.warning("Redis no disponible, no se guardaron las recetas en caché: %s", error)


# --- Lock de generación por hogar ---
#
# Mientras alguien (el POST o el precálculo) genera recetas para un hogar, tiene este
# lock en Redis. Sin él, un PATCH al inventario seguido de un POST de recetas terminaba
# en dos generaciones a la vez para lo mismo. El valor es un token al azar: así cada
# uno solo borra su propio lock.


def _clave_lock(hogar_id: int) -> str:
    return f"lock_recetas:{hogar_id}"


def _ttl_lock() -> int:
    """Lo máximo que puede durar una generación: RONDAS_VALIDACION llamadas, cada una con
    hasta INTENTOS_CON_RESPALDO peticiones (principal, reintento y respaldo) de hasta el
    timeout de fondo, más la espera entre ellas. Si el proceso muere con el lock tomado,
    el TTL lo libera."""
    por_ronda = (
        INTENTOS_CON_RESPALDO * get_settings().gemini_timeout_fondo + ESPERA_REINTENTO_SEGUNDOS[1]
    )
    return math.ceil(RONDAS_VALIDACION * por_ronda)


def _tomar_lock(cache: redis.Redis, hogar_id: int) -> str | None:
    """El token del lock si se pudo tomar; None si lo tiene otro. Lanza RedisError si
    Redis no responde."""
    token = uuid.uuid4().hex
    # nx=True: solo se escribe si no existe.
    if cache.set(_clave_lock(hogar_id), token, nx=True, ex=_ttl_lock()):
        return token
    return None


def _soltar_lock(cache: redis.Redis | None, hogar_id: int, token: str | None) -> None:
    if cache is None or token is None:
        return
    try:
        # Leer y borrar no es atómico, pero basta: el lock solo cambia de dueño si el
        # TTL venció, y el TTL cubre la generación más lenta posible.
        if cache.get(_clave_lock(hogar_id)) == token:
            cache.delete(_clave_lock(hogar_id))
    except redis.RedisError:
        pass  # el TTL lo borra de todos modos


def _esperar(segundos: float) -> None:
    # Función aparte para que los tests la reemplacen y no esperen de verdad.
    time.sleep(segundos)


def _turno_para_generar(
    cache: redis.Redis | None, hogar_id: int, claves: dict[str, str]
) -> tuple[str | None, EnCache | None]:
    """Antes de generar en el POST: (token, None) si hay que generar (token None si se
    genera sin lock), o (None, recetas) si otro las generó mientras se esperaba.

    Si el lock lo tiene otro, revisa la caché cada INTERVALO_ESPERA_LOCK hasta el timeout
    interactivo. Deja de esperar antes si el otro suelta el lock sin dejar recetas para
    estas claves (falló, no quedó ninguna, o generó con otro inventario).
    """
    if cache is None:
        return None, None
    try:
        token = _tomar_lock(cache, hogar_id)
        if token is not None:
            return token, None
        logger.info("Hogar %d: otro ya está generando recetas, se espera su resultado", hogar_id)
        revisiones = math.ceil(get_settings().gemini_timeout_interactivo / INTERVALO_ESPERA_LOCK)
        for _ in range(revisiones):
            _esperar(INTERVALO_ESPERA_LOCK)
            encontradas = _buscar_en_cache(cache, claves)
            if encontradas is not None:
                logger.info("Hogar %d: recetas tomadas de la generación en curso", hogar_id)
                return None, encontradas
            if not cache.exists(_clave_lock(hogar_id)):
                break
        logger.info("Hogar %d: no aparecieron recetas esperando, se generan aquí", hogar_id)
        return _tomar_lock(cache, hogar_id), None
    except redis.RedisError as error:
        logger.warning("Redis no disponible, se generan las recetas sin lock: %s", error)
        return None, None


def _turno_sin_espera(cache: redis.Redis | None, hogar_id: int) -> tuple[str | None, bool]:
    """Intenta tomar el lock sin esperar. Devuelve (token o None, si Redis respondió)."""
    if cache is None:
        return None, False
    try:
        return _tomar_lock(cache, hogar_id), True
    except redis.RedisError as error:
        logger.warning("Redis no disponible, se sigue sin lock: %s", error)
        return None, False


# --- Validación de lo que devolvió la IA ---


@dataclass
class Validacion:
    recetas: list[RecetaOut] = field(default_factory=list)
    # Por qué se descartó cada receta ("Arepa con queso: alergia a lacteos"). Se usa
    # para explicarle a Gemini qué corregir en el reintento.
    descartes: list[str] = field(default_factory=list)


def _ingredientes_principales(receta: RecetaOut) -> frozenset[int] | None:
    """Los 2 primeros ingredientes de la receta que salen del inventario (el prompt pide
    listarlos de más a menos importante), o None si usa menos de 2."""
    ids = [i.item_id for i in receta.ingredientes if i.item_id is not None][:2]
    return frozenset(ids) if len(ids) == 2 else None


def _quitar_repetidas(recetas: list[RecetaOut]) -> tuple[list[RecetaOut], list[str]]:
    """Si varias recetas comparten los mismos 2 ingredientes principales, deja la que
    aprovecha más productos próximos a vencer (en empate, la primera). Devuelve las
    que quedan, en su orden original, y el motivo de cada descarte."""
    mejor: dict[frozenset[int], RecetaOut] = {}
    for receta in recetas:
        clave = _ingredientes_principales(receta)
        if clave is None:
            continue
        actual = mejor.get(clave)
        if actual is None or len(receta.usa_proximos_a_vencer) > len(actual.usa_proximos_a_vencer):
            mejor[clave] = receta

    quedan, descartes = [], []
    for receta in recetas:
        clave = _ingredientes_principales(receta)
        if clave is None or mejor[clave] is receta:
            quedan.append(receta)
        else:
            motivo = f"repite los ingredientes principales de {mejor[clave].titulo!r}"
            logger.info("Receta %r descartada: %s", receta.titulo, motivo)
            descartes.append(f"{receta.titulo}: {motivo}")
    return quedan, descartes


def _motivo_descarte(receta: RecetaIA, textos: list[str], preferencias: Preferencias) -> str | None:
    """Por qué la receta no cumple las preferencias del hogar, o None si las cumple."""
    if alergenos := alergenos_en(textos, preferencias.alergias):
        return f"contiene alérgenos declarados ({', '.join(sorted(alergenos))})"
    if prohibidos := violaciones_de_dieta(textos, preferencias.dieta):
        return f"no es {preferencias.dieta.value} (contiene {', '.join(sorted(prohibidos))})"
    tiempo_max = preferencias.tiempo_max_minutos
    if tiempo_max and receta.tiempo_minutos > tiempo_max * (1 + TOLERANCIA_TIEMPO):
        return f"tarda {receta.tiempo_minutos} minutos y el máximo es {tiempo_max}"
    return None


def validar_recetas(
    recetas_ia: list[RecetaIA],
    items: dict[str, ItemInventario],
    preferencias: Preferencias,
    fecha: date,
) -> Validacion:
    """Convierte las recetas de la IA en las de la API, sin confiar en la IA:

    1. Traduce los ids cortos a ids reales. Un id que no está en `items` (inventado, o
       de otro hogar) se vuelve null: ese ingrediente queda como "a comprar".
       Los básicos de cocina (sal, aceite...) quedan con item_id null y no cuentan
       como faltantes, aunque la IA los haya asociado a un ítem del inventario.
    2. Descarta las recetas con un alérgeno declarado, las que no cumplen la dieta y
       las que se pasan del tiempo máximo en más de TOLERANCIA_TIEMPO.
    3. Calcula usa_proximos_a_vencer e ingredientes_faltantes con los ids ya revisados.
    4. Descarta las repetidas: mismos 2 ingredientes principales del inventario.
    5. Devuelve como máximo NUMERO_RECETAS (pueden ser menos si se descartaron).
    """
    resultado = Validacion()
    for receta in recetas_ia:
        ingredientes = []
        basicos = []
        usados: dict[int, ItemInventario] = {}
        for ingrediente in receta.ingredientes:
            item = items.get(ingrediente.item_id) if ingrediente.item_id else None
            if es_basico(ingrediente.nombre) or (item is not None and es_basico(item.nombre)):
                item = None
                basicos.append(ingrediente.nombre)
            if item is not None:
                usados[item.id] = item
            ingredientes.append(
                IngredienteOut(
                    nombre=ingrediente.nombre,
                    cantidad=ingrediente.cantidad,
                    unidad=ingrediente.unidad,
                    item_id=item.id if item else None,
                )
            )

        # Se revisan también los nombres del inventario: un ingrediente "p3" llamado
        # "lo que sobró" puede ser, en el inventario, "Queso campesino".
        textos = [receta.titulo, *receta.pasos]
        textos += [i.nombre for i in receta.ingredientes] + [i.nombre for i in usados.values()]
        if motivo := _motivo_descarte(receta, textos, preferencias):
            logger.info("Receta %r descartada: %s", receta.titulo, motivo)
            resultado.descartes.append(f"{receta.titulo}: {motivo}")
            continue

        proximos = []
        for item in usados.values():
            dias = _dias_para_vencer(item, fecha)
            if dias is not None and dias <= DIAS_PROXIMO_A_VENCER:
                proximos.append(
                    ItemProximoAVencer(item_id=item.id, nombre=item.nombre, dias_para_vencer=dias)
                )
        resultado.recetas.append(
            RecetaOut(
                titulo=receta.titulo,
                descripcion=receta.descripcion,
                tiempo_minutos=receta.tiempo_minutos,
                porciones=receta.porciones,
                ingredientes=ingredientes,
                pasos=receta.pasos,
                por_que=receta.por_que,
                usa_proximos_a_vencer=sorted(proximos, key=lambda p: p.dias_para_vencer),
                ingredientes_faltantes=[
                    i.nombre for i in ingredientes if i.item_id is None and i.nombre not in basicos
                ],
            )
        )
    resultado.recetas, repetidas = _quitar_repetidas(resultado.recetas)
    resultado.descartes += repetidas
    resultado.recetas = resultado.recetas[:NUMERO_RECETAS]
    return resultado


# --- Flujo completo ---


def titulos_recientes(db: Session, hogar_id: int) -> list[str]:
    """Títulos de las últimas recetas que se le propusieron al hogar, sin repetir."""
    consulta = (
        select(Recomendacion.recetas)
        .where(Recomendacion.hogar_id == hogar_id)
        .order_by(Recomendacion.id.desc())
        .limit(RECOMENDACIONES_A_EVITAR)
    )
    titulos: list[str] = []
    for recetas in db.scalars(consulta):
        for receta in recetas:
            if receta["titulo"] not in titulos:
                titulos.append(receta["titulo"])
    return titulos[:MAXIMO_TITULOS_A_EVITAR]


@dataclass
class Generacion:
    recetas: list[RecetaOut]
    intentos: int  # rondas de validación: 1, o 2 si ninguna receta pasó la primera
    descartadas: int  # recetas que no pasaron la validación, sumando los intentos
    latencia_gemini_ms: int  # tiempo esperando a Gemini, sumando los intentos
    modelo: str  # el que respondió en la última ronda (la de las recetas que quedaron)


def _generar_y_validar(
    generar: Generador,
    items: list[ItemInventario],
    preferencias: Preferencias,
    fecha: date,
    evitar: list[str],
) -> Generacion:
    """Pide recetas a Gemini y las valida. Si ninguna pasa la validación, hace UNA ronda
    más explicándole a Gemini qué restricciones incumplió. `items` son solo los
    compatibles con las preferencias: lo único que ve Gemini."""
    # Ids cortos en orden: p1, p2... Gemini nunca ve los ids reales.
    por_id_corto = {f"p{i}": item for i, item in enumerate(items, start=1)}
    para_receta = [
        ItemParaReceta(
            id_corto=id_corto,
            nombre=item.nombre,
            cantidad=item.cantidad,
            unidad=item.unidad,
            dias_para_vencer=_dias_para_vencer(item, fecha),
        )
        for id_corto, item in por_id_corto.items()
    ]

    validacion = Validacion()
    descartadas = latencia_gemini_ms = 0
    for ronda in range(1, RONDAS_VALIDACION + 1):
        entrada = armar_entrada(
            para_receta, preferencias, evitar=evitar, incumplidas=validacion.descartes
        )
        inicio = time.perf_counter()
        try:
            resultado = generar(entrada)
        except Exception as error:
            logger.exception(
                "Ronda de validación %d/%d: falló la llamada a Gemini", ronda, RONDAS_VALIDACION
            )
            raise GeneracionFallida from error
        latencia_llamada = round((time.perf_counter() - inicio) * 1000)
        latencia_gemini_ms += latencia_llamada
        validacion = validar_recetas(resultado.recetas, por_id_corto, preferencias, fecha)
        descartadas += len(validacion.descartes)
        logger.info(
            "Ronda de validación %d/%d: %s respondió en %d ms (con reintentos de red), "
            "%d recetas propuestas, %d válidas",
            ronda,
            RONDAS_VALIDACION,
            resultado.modelo,
            latencia_llamada,
            len(resultado.recetas),
            len(validacion.recetas),
        )
        if validacion.recetas:
            break
        if ronda < RONDAS_VALIDACION:
            logger.info("Ninguna receta pasó: se pide otra ronda con los motivos del descarte")
        if not validacion.descartes:
            # Gemini no devolvió recetas: no hay nada que corregirle, se reintenta igual.
            validacion.descartes = ["no propusiste ninguna receta"]
    return Generacion(
        recetas=validacion.recetas,
        intentos=ronda,
        descartadas=descartadas,
        latencia_gemini_ms=latencia_gemini_ms,
        modelo=resultado.modelo,
    )


def recomendar_recetas(
    db: Session,
    hogar_id: int,
    cache: redis.Redis | None,
    generar: Generador,
    *,
    nuevas: bool = False,
) -> RespuestaRecomendacion:
    """Recetas para el hogar. Con nuevas=True no se lee la caché y se le pide a Gemini
    que no repita las últimas recetas que ya vio el hogar ("otras recetas")."""
    inicio = time.perf_counter()
    fecha = hoy()

    items = alimentos_disponibles(db, hogar_id, fecha)
    if not items:
        raise SinAlimentos
    preferencias = preferences_service.obtener_preferencias(db, hogar_id)
    compatibles = alimentos_compatibles(items, preferencias)
    if not compatibles:
        raise SinAlimentosCompatibles
    evitar = titulos_recientes(db, hogar_id) if nuevas else []
    # Cerramos la transacción de lectura antes de llamar a Gemini (tarda segundos):
    # así no queda una transacción abierta mientras tanto.
    db.commit()

    # La clave usa el inventario completo, no solo lo compatible: si cambia el pollo
    # de un hogar vegetariano, igual se invalida (un cambio de dieta lo vuelve visible).
    # Hay una clave por modelo (principal y respaldo): se busca en ambas.
    claves = _claves_por_modelo(hogar_id, items, preferencias, fecha)
    encontradas = None
    token = None
    if nuevas:
        # "Otras recetas" no espera a nadie (pide recetas distintas a propósito), pero
        # toma el lock si está libre para que un precálculo no arranque a la vez.
        token, _ = _turno_sin_espera(cache, hogar_id)
    else:
        encontradas = _buscar_en_cache(cache, claves)
        if encontradas is None:
            token, encontradas = _turno_para_generar(cache, hogar_id, claves)

    generacion = None
    if encontradas is not None:
        recetas, modelo = encontradas.recetas, encontradas.modelo
    else:
        try:
            generacion = _generar_y_validar(generar, compatibles, preferencias, fecha, evitar)
            recetas, modelo = generacion.recetas, generacion.modelo
            # Con "otras recetas" también se guarda: reemplaza lo que había para esta
            # clave. Una lista vacía no se guarda, para que la próxima vez se intente de
            # nuevo. Se guarda antes de soltar el lock: quien espera la encuentra. La
            # clave es la del modelo que respondió, no la del configurado.
            if recetas:
                clave = clave_cache(hogar_id, items, preferencias, fecha, modelo)
                _guardar_cache(cache, clave, recetas)
        finally:
            _soltar_lock(cache, hogar_id, token)

    latencia_ms = round((time.perf_counter() - inicio) * 1000)
    cache_hit = generacion is None
    registro = _registrar(
        db,
        hogar_id,
        TipoRecomendacion.nuevas if nuevas else TipoRecomendacion.normal,
        generacion=generacion,
        recetas=recetas,
        latencia_ms=latencia_ms,
        modelo=modelo,
    )

    return RespuestaRecomendacion(
        recomendacion_id=registro.id,
        recetas=recetas,
        aviso=AVISO,
        mensaje=None if recetas else SIN_RECETAS,
        cache="hit" if cache_hit else "miss",
        latencia_ms=latencia_ms,
        modelo=modelo,
    )


def _registrar(
    db: Session,
    hogar_id: int,
    tipo: TipoRecomendacion,
    *,
    generacion: Generacion | None,
    recetas: list[RecetaOut],
    latencia_ms: int,
    modelo: str,
) -> Recomendacion:
    """Guarda la fila de métricas. generacion=None significa que salió de la caché."""
    registro = Recomendacion(
        hogar_id=hogar_id,
        tipo=tipo,
        cache_hit=generacion is None,
        intentos=generacion.intentos if generacion else 0,
        recetas_descartadas=generacion.descartadas if generacion else 0,
        latencia_ms=latencia_ms,
        latencia_gemini_ms=generacion.latencia_gemini_ms if generacion else None,
        modelo=modelo,
        recetas=[receta.model_dump(mode="json") for receta in recetas],
    )
    db.add(registro)
    db.commit()
    return registro


# --- Precálculo en segundo plano ---


def precalcular_recetas(hogar_id: int, cache: redis.Redis | None, generar: Generador) -> None:
    """Genera las recetas del hogar y las deja en caché, para que su próxima petición
    sea un hit. Corre con BackgroundTasks después de responder el request que la
    programó, así que usa su propia sesión de BD (la del request ya se cerró) y nunca
    lanza excepciones: si algo falla, solo queda en el log."""
    if cache is None:
        return  # sin Redis no hay dónde dejar las recetas
    token, redis_ok = _turno_sin_espera(cache, hogar_id)
    if token is None:
        if redis_ok:
            # Lo tiene otro precálculo o un POST: ese ya va a dejar las recetas en caché.
            logger.info("Precálculo del hogar %d: ya hay una generación en curso", hogar_id)
        return

    try:
        with SessionLocal() as db:
            _precalcular(db, hogar_id, cache, generar)
    except Exception:
        logger.exception("Falló el precálculo de recetas del hogar %d", hogar_id)
    finally:
        _soltar_lock(cache, hogar_id, token)


def _precalcular(db: Session, hogar_id: int, cache: redis.Redis, generar: Generador) -> None:
    inicio = time.perf_counter()
    fecha = hoy()

    items = alimentos_disponibles(db, hogar_id, fecha)
    if not items:
        return
    preferencias = preferences_service.obtener_preferencias(db, hogar_id)
    compatibles = alimentos_compatibles(items, preferencias)
    if not compatibles:
        logger.info("Precálculo del hogar %d: ningún alimento compatible", hogar_id)
        return
    db.commit()  # como en recomendar_recetas: sin transacción abierta durante Gemini

    claves = _claves_por_modelo(hogar_id, items, preferencias, fecha)
    if _buscar_en_cache(cache, claves) is not None:
        # Ya están en caché (p. ej. el cambio fue en un campo que no afecta la clave):
        # no se llama a Gemini ni se registra nada.
        logger.info("Precálculo del hogar %d: las recetas ya estaban en caché", hogar_id)
        return

    generacion = _generar_y_validar(generar, compatibles, preferencias, fecha, evitar=[])
    if generacion.recetas:
        clave = clave_cache(hogar_id, items, preferencias, fecha, generacion.modelo)
        _guardar_cache(cache, clave, generacion.recetas)
    _registrar(
        db,
        hogar_id,
        TipoRecomendacion.precalculo,
        generacion=generacion,
        recetas=generacion.recetas,
        latencia_ms=round((time.perf_counter() - inicio) * 1000),
        modelo=generacion.modelo,
    )
    if generacion.recetas:
        logger.info(
            "Precálculo del hogar %d: %d recetas guardadas en caché",
            hogar_id,
            len(generacion.recetas),
        )
    else:
        logger.info(
            "Precálculo del hogar %d: ninguna receta pasó la validación, no se guarda nada "
            "en caché (el POST lo intentará de nuevo)",
            hogar_id,
        )


def obtener_recomendacion(
    db: Session, hogar_id: int, recomendacion_id: int
) -> Recomendacion | None:
    consulta = select(Recomendacion).where(
        Recomendacion.id == recomendacion_id, Recomendacion.hogar_id == hogar_id
    )
    return db.scalar(consulta)


def guardar_feedback(db: Session, recomendacion: Recomendacion, indice: int, util: bool) -> None:
    if indice >= len(recomendacion.recetas):
        raise IndiceRecetaInvalido
    # Se asigna un diccionario nuevo: SQLAlchemy no detecta cambios dentro de un JSONB.
    recomendacion.feedback = {**recomendacion.feedback, str(indice): util}
    db.commit()
