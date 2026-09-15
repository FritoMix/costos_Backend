"""
Rutas HTTP del modulo Analitica: /api/v1/analitica/...

Toda esta seccion es exclusiva del Administrador / Analista.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.limite import limiter
from app.db.session import get_db
from app.modules.analitica import exportacion, service
from app.modules.analitica.schemas import (
    FilaBache,
    FiltrosAnalisis,
    IndicadoresCategoriaSalida,
    IndicadoresSalida,
)
from app.modules.identidad.dependencias import requiere_roles
from app.modules.identidad.models import RolCodigo, Usuario

BD = Annotated[Session, Depends(get_db)]
SoloAdmin = Annotated[Usuario, Depends(requiere_roles(RolCodigo.ADMIN))]

router = APIRouter(prefix="/analitica", tags=["Análisis"])


def filtros_desde_query(
    fecha_desde: Annotated[str | None, Query()] = None,
    fecha_hasta: Annotated[str | None, Query()] = None,
    turno_id: int | None = None,
    horno_id: int | None = None,
    producto_id: int | None = None,
    categoria_id: int | None = None,
    supervisor_id: int | None = None,
    sabor_id: int | None = None,
) -> FiltrosAnalisis:
    """
    Convierte los parametros de la URL en un objeto de filtros. Las fechas
    llegan como texto para poder aceptar vacio ("") desde el formulario.
    """
    return FiltrosAnalisis(
        fecha_desde=fecha_desde or None,
        fecha_hasta=fecha_hasta or None,
        turno_id=turno_id,
        horno_id=horno_id,
        producto_id=producto_id,
        categoria_id=categoria_id,
        supervisor_id=supervisor_id,
        sabor_id=sabor_id,
    )


Filtros = Annotated[FiltrosAnalisis, Depends(filtros_desde_query)]


@router.get("/indicadores", response_model=IndicadoresSalida)
@limiter.limit("30/minute")
def indicadores(request: Request, db: BD, _: SoloAdmin, filtros: Filtros):
    return service.calcular_indicadores(db, filtros)


@router.get("/por-categoria", response_model=list[IndicadoresCategoriaSalida])
@limiter.limit("30/minute")
def por_categoria(request: Request, db: BD, _: SoloAdmin, filtros: Filtros):
    return service.calcular_indicadores_por_categoria(db, filtros)


@router.get("/baches", response_model=list[FilaBache])
@limiter.limit("30/minute")
def baches(request: Request, db: BD, _: SoloAdmin, filtros: Filtros):
    return service.obtener_detalle_baches(db, filtros)


@router.get("/exportar.csv")
@limiter.limit("10/minute")
def exportar_csv(request: Request, db: BD, _: SoloAdmin, filtros: Filtros) -> StreamingResponse:
    filas = exportacion.obtener_filas(db, filtros)
    nombre = exportacion.nombre_archivo("csv")
    return StreamingResponse(
        exportacion.generar_csv(filas),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@router.get("/exportar.xlsx")
@limiter.limit("10/minute")
def exportar_excel(request: Request, db: BD, _: SoloAdmin, filtros: Filtros) -> StreamingResponse:
    filas = exportacion.obtener_filas(db, filtros)
    nombre = exportacion.nombre_archivo("xlsx")
    return StreamingResponse(
        exportacion.generar_excel(filas),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )
