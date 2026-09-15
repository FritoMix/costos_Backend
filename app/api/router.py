"""
Une los routers de todos los modulos bajo /api/v1.

Es el unico punto donde se ve el mapa completo de la API: cada modulo
aporta sus rutas y nada mas.
"""

import time
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine, get_db
from app.modules.analitica.router import router as router_analitica
from app.modules.catalogos.router import router as router_catalogos
from app.modules.identidad.router import router_auth, router_usuarios
from app.modules.notificaciones.router import router as router_notificaciones
from app.modules.produccion.router import router as router_produccion

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(router_auth)
api_router.include_router(router_usuarios)
api_router.include_router(router_catalogos)
api_router.include_router(router_produccion)
api_router.include_router(router_analitica)
api_router.include_router(router_notificaciones)

# Para reportar cuanto lleva la app corriendo desde el arranque.
_inicio_proceso = time.monotonic()


@api_router.get("/salud", tags=["Estado"])
def salud(db: Annotated[Session, Depends(get_db)]) -> dict:
    """
    Confirma que el servidor responde Y que la conexion a PostgreSQL
    funciona de verdad. Docker lo usa como healthcheck.
    """
    db.execute(text("SELECT 1"))

    info_pool = {}
    try:
        pool = engine.pool
        info_pool = {
            "conexiones_activas": pool.checkedout(),
            "conexiones_abiertas": pool.checkedin() + pool.checkedout(),
            "capacidad_maxima": pool.size(),
            "colas": pool.overflow(),
        }
    except Exception:  # noqa: BLE001 - si no se puede leer el pool, no es critico
        info_pool = {"detalle": "no_disponible"}

    return {
        "estado": "ok",
        "app": settings.app_name,
        "entorno": settings.app_env,
        "base_de_datos": "conectada",
        "version": "2.0.0",
        "tiempo_activo_segundos": int(time.monotonic() - _inicio_proceso),
        "pool": info_pool,
    }
