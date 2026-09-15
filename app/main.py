"""
Punto de entrada de la API de DATACONTROL.

Esta capa hace solo tres cosas: configurar la aplicacion, enchufar los
routers de cada modulo y traducir errores. Toda la logica vive en
app/modules/<modulo>/service.py.
"""

import json
import logging
import os
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.exc import OperationalError

from app.api.manejadores import registrar_manejadores
from app.api.router import api_router
from app.core.config import settings
from app.core.limite import limiter
from app.db.bootstrap import crear_admin_inicial
from app.db.migraciones import aplicar_migraciones_pendientes
from app.db.session import SessionLocal, engine

# Limite generico: cuantas peticiones puede lanzar cada IP por minuto.
# Protege a la API de abuso (repeticion automatica, scraping) sin molestar
# al operario normal, que hace decenas de peticiones, no miles.


class FormatoJSON(logging.Formatter):
    """Logs en una sola linea JSON, para que un agregador los lea facil."""

    def format(self, record: logging.LogRecord) -> str:
        linea = {
            "hora": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "nivel": record.levelname,
            "logger": record.name,
            "mensaje": record.getMessage(),
        }
        if record.exc_info:
            linea["excepcion"] = self.formatException(record.exc_info)
        return json.dumps(linea, ensure_ascii=False)


def _configurar_logging() -> None:
    """En produccion los logs salen como JSON; en desarrollo, legibles."""
    nivel = logging.INFO
    formatter: logging.Formatter
    if settings.es_produccion:
        formatter = FormatoJSON()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    manejador = logging.StreamHandler(sys.stdout)
    manejador.setFormatter(formatter)

    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    raiz.handlers.clear()
    raiz.addHandler(manejador)

    # Que otras librerias no ensucien el log.
    for nombre in ("uvicorn", "uvicorn.error", "sqlalchemy"):
        log = logging.getLogger(nombre)
        log.setLevel(logging.WARNING)


_configurar_logging()

logger = logging.getLogger("datacontrol")


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI) -> AsyncIterator[None]:
    """Se ejecuta una vez al arrancar (y al apagar) el servidor."""
    # 1) Esquema de la base al dia.
    #
    # En local esto no hace nada: Flyway ya aplico las migraciones antes de
    # que la API arranque. Pero cuando el backend se despliega solo (Render,
    # Railway, un VPS) no hay contenedor de Flyway, y sin esto la base
    # quedaria vacia. Si falla, NO se arranca: es preferible un despliegue
    # caido y visible a una API respondiendo contra una base incompleta.
    if settings.migrar_al_arrancar:
        try:
            aplicar_migraciones_pendientes(engine)
        except OperationalError:
            # El traceback de SQLAlchemy no dice QUE falta configurar, asi que
            # se explica antes de dejarlo subir.
            logger.error(
                "No se pudo conectar a la base de datos en %s", settings.destino_base_datos
            )
            if settings.usa_host_de_compose:
                logger.error(
                    'El host "db" solo existe dentro de Docker Compose. Si esto corre en '
                    "Render, Railway o un servidor, falta la variable de entorno "
                    "DATABASE_URL con la cadena de conexión que entrega el proveedor."
                )
                # Se listan solo los NOMBRES (nunca los valores: llevan la
                # contrasena). Si aqui aparece algo parecido a DATABASE_URL
                # pero escrito distinto, ese es el error.
                relacionadas = sorted(
                    nombre
                    for nombre in os.environ
                    if "DATABASE" in nombre.upper() or "POSTGRES" in nombre.upper()
                )
                logger.error(
                    "Variables de entorno relacionadas que sí llegan a la app: %s",
                    ", ".join(relacionadas) if relacionadas else "NINGUNA",
                )
            raise

    # 2) Usuario administrador inicial (solo la primera vez).
    db = SessionLocal()
    try:
        crear_admin_inicial(db)
    except Exception:  # noqa: BLE001 - arrancar igual: la API sirve sin admin
        logger.exception("No se pudo verificar el usuario administrador inicial")
    finally:
        db.close()

    logger.info("%s listo (entorno: %s)", settings.app_name, settings.app_env)
    yield


app = FastAPI(
    title=f"{settings.app_name} API",
    version="2.0.0",
    description=(
        "API de recolección de datos de producción de Productos Alimenticios Fritomix SAS: "
        "órdenes, registro de horno, saborizado, catálogos y análisis."
    ),
    lifespan=ciclo_de_vida,
    # La documentacion interactiva queda fuera en produccion.
    docs_url=None if settings.es_produccion else "/docs",
    redoc_url=None,
    openapi_url=None if settings.es_produccion else "/openapi.json",
)

# El limite de peticiones se aplica a toda la app.
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# El frontend Angular corre en otro origen (otro puerto), asi que hay que
# autorizarlo explicitamente. La lista viene del .env.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origenes_cors,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Sin esto el navegador no deja leer el nombre del archivo exportado ni el ID de traza.
    expose_headers=["Content-Disposition", "X-Request-ID"],
)


@app.middleware("http")
async def middleware_trazabilidad(request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    inicio = time.perf_counter()
    respuesta = await call_next(request)
    duracion_ms = (time.perf_counter() - inicio) * 1000
    respuesta.headers["X-Request-ID"] = request_id

    # No ensuciar el log con las revisiones de salud de Docker
    if not request.url.path.endswith("/salud"):
        logger.info(
            "[%s] %s %s -> %d (%.1f ms)",
            request_id,
            request.method,
            request.url.path,
            respuesta.status_code,
            duracion_ms,
        )
    return respuesta


registrar_manejadores(app)
app.include_router(api_router)
