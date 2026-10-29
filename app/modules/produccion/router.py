"""
Rutas HTTP del modulo Produccion: /api/v1/ordenes/...

Quien puede hacer que:
  * Crear / finalizar / cancelar / editar ordenes: Supervisor
    (el Administrador tambien, para poder ayudar desde la oficina).
  * INICIAR la produccion: ademas de ellos, los operarios de horno y
    saborizado. Son quienes estan en la maquina y toman la orden que van a
    trabajar, sin tener que esperar a que el supervisor la arranque.
  * Registrar tandas de horno: Operario de Horno.
  * Registrar recepciones de saborizado: Operario de Saborizado.
  * Eliminar (borrado suave): solo Administrador.
Ver las ordenes lo pueden hacer los roles de produccion: administrador,
supervisor y operarios. Bodega no consulta ordenes ni sus registros.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.errores import PermisoDenegado
from app.db.session import get_db
from app.modules.identidad.dependencias import requiere_roles
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.produccion.schemas import (
    FormulaGuardar,
    FormulaProyeccionGuardar,
    FormulaProyeccionSalida,
    FormulaSalida,
    OrdenBodegaDetalle,
    OrdenBodegaSalida,
    OrdenDetalle,
    OrdenGuardar,
    OrdenSalida,
    RecepcionGuardar,
    RecepcionSalida,
    RegistroHornoGuardar,
    RegistroHornoSalida,
)
from app.modules.produccion.servicios import formula as servicio_formula
from app.modules.produccion.servicios import horno as servicio_horno
from app.modules.produccion.servicios import ordenes as servicio_ordenes
from app.modules.produccion.servicios import saborizado as servicio_saborizado
from app.modules.produccion.servicios import totales as servicio_totales

BD = Annotated[Session, Depends(get_db)]
SoloAdmin = Annotated[Usuario, Depends(requiere_roles(RolCodigo.ADMIN))]
Supervisa = Annotated[Usuario, Depends(requiere_roles(RolCodigo.ADMIN, RolCodigo.SUPERVISOR))]
OperarioHorno = Annotated[Usuario, Depends(requiere_roles(RolCodigo.ADMIN, RolCodigo.OPERARIO_HORNO))]
OperarioSaborizado = Annotated[
    Usuario, Depends(requiere_roles(RolCodigo.ADMIN, RolCodigo.OPERARIO_SABORIZADO))
]
# Consultar ordenes, tandas y recepciones. Bodega queda fuera: su unica
# pantalla operativa es el catalogo de referencias de papa.
VeOrdenes = Annotated[
    Usuario,
    Depends(
        requiere_roles(
            RolCodigo.ADMIN,
            RolCodigo.SUPERVISOR,
            RolCodigo.OPERARIO_HORNO,
            RolCodigo.OPERARIO_SABORIZADO,
        )
    ),
]

# Tomar una orden y arrancar la produccion tambien es trabajo de planta: el
# operario que va a trabajarla la inicia sin esperar al supervisor.
TomaOrdenes = Annotated[
    Usuario,
    Depends(
        requiere_roles(
            RolCodigo.ADMIN,
            RolCodigo.SUPERVISOR,
            RolCodigo.OPERARIO_HORNO,
            RolCodigo.OPERARIO_SABORIZADO,
        )
    ),
]

# Bodega define la formula de la orden. No ve registros, aceite, desperdicios
# ni costos: solo el encabezado, la formula y el avance.
BodegaFormula = Annotated[
    Usuario,
    Depends(requiere_roles(RolCodigo.ADMIN, RolCodigo.BODEGUERO)),
]

router = APIRouter(prefix="/ordenes", tags=["Órdenes de producción"])
router_bodega_ordenes = APIRouter(
    prefix="/bodega/ordenes", tags=["Bodega · Fórmula de producción"]
)


@router_bodega_ordenes.get("", response_model=list[OrdenBodegaSalida])
def listar_ordenes_bodega(
    db: BD,
    _: BodegaFormula,
    fecha_desde: Annotated[date | None, Query()] = None,
    fecha_hasta: Annotated[date | None, Query()] = None,
    estado: Annotated[str | None, Query()] = None,
    producto_id: Annotated[int | None, Query(gt=0)] = None,
    destino: Annotated[str | None, Query()] = None,
    solo_sin_formula: Annotated[bool, Query()] = False,
):
    """Bandeja de Bodega: ordenes con el estado de su formula y el avance."""
    return servicio_formula.listar_ordenes_bodega(
        db,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta,
        estado=estado,
        producto_id=producto_id,
        destino=destino,
        solo_sin_formula=solo_sin_formula,
    )


@router_bodega_ordenes.get("/{orden_id}", response_model=OrdenBodegaDetalle)
def detalle_orden_bodega(orden_id: int, db: BD, _: BodegaFormula):
    """Detalle restringido: encabezado, formula y avance, sin registros."""
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    return servicio_formula.detalle_bodega(db, orden)


def _verificar_puede_gestionar(orden, usuario: Usuario) -> None:
    """Un supervisor solo gestiona sus propias ordenes; el admin, todas."""
    if usuario.rol.codigo == RolCodigo.ADMIN:
        return
    if orden.supervisor_id != usuario.id:
        raise PermisoDenegado("Esta orden es de otro supervisor.")


def _verificar_puede_iniciar(orden, usuario: Usuario) -> None:
    """
    Quien puede arrancar la produccion de una orden.

    Los operarios pueden tomar cualquier orden pendiente: son ellos quienes
    la van a trabajar en el horno o en saborizado. El supervisor sigue
    limitado a las suyas y el administrador puede con todas.
    """
    if usuario.rol.codigo in (
        RolCodigo.ADMIN,
        RolCodigo.OPERARIO_HORNO,
        RolCodigo.OPERARIO_SABORIZADO,
    ):
        return
    if orden.supervisor_id != usuario.id:
        raise PermisoDenegado("Esta orden es de otro supervisor.")


# --- Ordenes ---------------------------------------------------------------


@router.get("", response_model=list[OrdenSalida])
def listar(
    db: BD,
    usuario: VeOrdenes,
    estado: str | None = None,
    solo_propias: bool | None = None,
):
    return servicio_ordenes.listar_ordenes(
        db, usuario=usuario, estado=estado, solo_propias=solo_propias
    )


@router.post("", response_model=OrdenSalida, status_code=status.HTTP_201_CREATED)
def crear(datos: OrdenGuardar, db: BD, usuario: Supervisa):
    return servicio_ordenes.crear_orden(db, datos, usuario)


@router.get("/{orden_id}", response_model=OrdenDetalle)
def detalle(orden_id: int, db: BD, _: VeOrdenes):
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    return OrdenDetalle(
        orden=OrdenSalida.model_validate(orden),
        totales=servicio_totales.calcular_totales(db, orden),
        formula=servicio_formula.obtener(db, orden),
        registros_horno=[
            RegistroHornoSalida.model_validate(r) for r in servicio_horno.listar_registros(db, orden.id)
        ],
        recepciones=[
            RecepcionSalida.model_validate(r)
            for r in servicio_saborizado.listar_recepciones(db, orden.id)
        ],
    )


@router.put("/{orden_id}", response_model=OrdenSalida)
def editar(orden_id: int, datos: OrdenGuardar, db: BD, usuario: Supervisa):
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    _verificar_puede_gestionar(orden, usuario)
    return servicio_ordenes.editar_orden(db, orden, datos)


@router.post("/{orden_id}/iniciar", response_model=OrdenSalida)
def iniciar(orden_id: int, db: BD, usuario: TomaOrdenes):
    """El operario toma la orden que va a trabajar y arranca la producción."""
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    _verificar_puede_iniciar(orden, usuario)
    return servicio_ordenes.iniciar_orden(db, orden)


@router.post("/{orden_id}/finalizar", response_model=OrdenSalida)
def finalizar(orden_id: int, db: BD, usuario: Supervisa):
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    _verificar_puede_gestionar(orden, usuario)
    return servicio_ordenes.finalizar_orden(db, orden)


@router.post("/{orden_id}/cancelar", response_model=OrdenSalida)
def cancelar(orden_id: int, db: BD, usuario: Supervisa):
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    _verificar_puede_gestionar(orden, usuario)
    return servicio_ordenes.cancelar_orden(db, orden)


@router.delete("/{orden_id}")
def eliminar(orden_id: int, db: BD, admin: SoloAdmin) -> dict:
    """
    Borrado suave con cascada. Devuelve cuantos registros de horno y
    saborizado se eliminaron junto con la orden, para poder avisarlo.
    """
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    arrastrados = servicio_ordenes.eliminar_orden(db, orden, admin)
    return {"registros_eliminados": arrastrados}


# --- Formula de produccion por orden --------------------------------------


@router.get("/{orden_id}/formula", response_model=FormulaSalida)
def obtener_formula(orden_id: int, db: BD, _: VeOrdenes):
    """Formula vigente de la orden y avance por referencia."""
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    return servicio_formula.obtener(db, orden)


@router.put("/{orden_id}/formula", response_model=FormulaSalida)
def guardar_formula(orden_id: int, datos: FormulaGuardar, db: BD, usuario: BodegaFormula):
    """Bodega guarda (o reemplaza) la mezcla de ESA orden."""
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    return servicio_formula.guardar(db, orden, datos, usuario)


@router.post("/{orden_id}/formula/proyeccion", response_model=FormulaProyeccionSalida)
def proyectar_formula(
    orden_id: int, datos: FormulaProyeccionGuardar, db: BD, _: BodegaFormula
):
    """Vista previa de la mezcla o sugerencia; no guarda nada."""
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    return servicio_formula.proyectar(db, orden, datos)


# --- Registros de horno ----------------------------------------------------


@router.get("/{orden_id}/registros-horno", response_model=list[RegistroHornoSalida])
def listar_registros_horno(orden_id: int, db: BD, _: VeOrdenes):
    servicio_ordenes.obtener_orden(db, orden_id)
    return servicio_horno.listar_registros(db, orden_id)


@router.post(
    "/{orden_id}/registros-horno",
    response_model=RegistroHornoSalida,
    status_code=status.HTTP_201_CREATED,
)
def crear_registro_horno(
    orden_id: int, datos: RegistroHornoGuardar, db: BD, usuario: OperarioHorno
):
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    return servicio_horno.crear_registro(db, orden, datos, usuario)


@router.put("/{orden_id}/registros-horno/{registro_id}", response_model=RegistroHornoSalida)
def editar_registro_horno(
    orden_id: int, registro_id: int, datos: RegistroHornoGuardar, db: BD, usuario: OperarioHorno
):
    registro = servicio_horno.obtener_registro(db, registro_id)
    return servicio_horno.editar_registro(db, registro, datos, usuario)


@router.delete(
    "/{orden_id}/registros-horno/{registro_id}", status_code=status.HTTP_204_NO_CONTENT
)
def eliminar_registro_horno(orden_id: int, registro_id: int, db: BD, admin: SoloAdmin) -> None:
    registro = servicio_horno.obtener_registro(db, registro_id)
    servicio_horno.eliminar_registro(db, registro, admin)


# --- Recepciones de saborizado --------------------------------------------


@router.get("/{orden_id}/recepciones", response_model=list[RecepcionSalida])
def listar_recepciones(orden_id: int, db: BD, _: VeOrdenes):
    servicio_ordenes.obtener_orden(db, orden_id)
    return servicio_saborizado.listar_recepciones(db, orden_id)


@router.post(
    "/{orden_id}/recepciones", response_model=RecepcionSalida, status_code=status.HTTP_201_CREATED
)
def crear_recepcion(
    orden_id: int, datos: RecepcionGuardar, db: BD, usuario: OperarioSaborizado
):
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    return servicio_saborizado.crear_recepcion(db, orden, datos, usuario)


@router.put("/{orden_id}/recepciones/{recepcion_id}", response_model=RecepcionSalida)
def editar_recepcion(
    orden_id: int, recepcion_id: int, datos: RecepcionGuardar, db: BD, usuario: OperarioSaborizado
):
    recepcion = servicio_saborizado.obtener_recepcion(db, recepcion_id)
    return servicio_saborizado.editar_recepcion(db, recepcion, datos, usuario)


@router.delete("/{orden_id}/recepciones/{recepcion_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_recepcion(orden_id: int, recepcion_id: int, db: BD, admin: SoloAdmin) -> None:
    recepcion = servicio_saborizado.obtener_recepcion(db, recepcion_id)
    servicio_saborizado.eliminar_recepcion(db, recepcion, admin)
