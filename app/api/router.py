"""
Une los routers de todos los modulos bajo /api/v1.

Es el unico punto donde se ve el mapa completo de la API: cada modulo
aporta sus rutas y nada mas.
"""

import logging
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.limite import limiter
from app.db.session import engine, get_db
from app.modules.analitica.router import router as router_analitica
from app.modules.bodega.router import router as router_bodega
from app.modules.bodega.router import router_proyeccion as router_bodega_proyeccion
from app.modules.catalogos.router import router as router_catalogos
from app.modules.identidad.dependencias import UsuarioAutenticado
from app.modules.identidad.router import router_auth, router_usuarios
from app.modules.notificaciones.router import router as router_notificaciones
from app.modules.produccion.router import router as router_produccion
from app.modules.produccion.router import router_bodega_formulas, router_bodega_noche, router_bodega_ordenes

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(router_auth)
api_router.include_router(router_usuarios)
api_router.include_router(router_bodega)
api_router.include_router(router_bodega_proyeccion)
api_router.include_router(router_catalogos)
# Antes de las rutas /ordenes/{orden_id}: /bodega/ordenes es la bandeja
# restringida de Bodega y /bodega/formulas-papa su catalogo de formulas.
api_router.include_router(router_bodega_ordenes)
api_router.include_router(router_bodega_formulas)
api_router.include_router(router_bodega_noche)
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


@api_router.get("/vivo", tags=["Estado"])
def vivo() -> dict:
    """El proceso responde, sin consumir conexiones PostgreSQL."""
    return {"estado": "ok"}


@api_router.get("/listo", tags=["Estado"])
def listo():
    """Admite tráfico únicamente si puede obtener y usar una conexión."""
    try:
        with engine.connect() as conexion:
            conexion.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(
            status_code=503, content={"estado": "no_disponible"}, headers={"Cache-Control": "no-store"}
        )
    return JSONResponse(content={"estado": "ok"}, headers={"Cache-Control": "no-store"})


class MedicionTurno(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operacion_id: str = Field(pattern=r"^[a-f0-9]{32}$", min_length=32, max_length=32)
    accion: Literal["abrir_kpi", "abrir_nueva_orden", "guardar_tanda", "guardar_recepcion"]
    resultado: Literal["ok", "error"]
    primera: bool
    duracion_ms: int = Field(ge=0, le=86_400_000)


@api_router.post("/mediciones/turno", status_code=204, tags=["Operación"])
@limiter.limit("30/minute")
def medir_turno(request: Request, datos: MedicionTurno, _: UsuarioAutenticado) -> Response:
    logging.getLogger("datacontrol.turno").info(
        "medicion_turno %s", datos.model_dump_json()
    )
    return Response(status_code=204)
