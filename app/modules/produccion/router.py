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
Ver las ordenes lo puede hacer cualquier usuario conectado: los operarios
necesitan ver cuales estan En produccion.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.errores import PermisoDenegado
from app.db.session import get_db
from app.modules.identidad.dependencias import UsuarioAutenticado, requiere_roles
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.produccion.schemas import (
    OrdenDetalle,
    OrdenGuardar,
    OrdenSalida,
    RecepcionGuardar,
    RecepcionSalida,
    RegistroHornoGuardar,
    RegistroHornoSalida,
)
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

router = APIRouter(prefix="/ordenes", tags=["Órdenes de producción"])


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
    usuario: UsuarioAutenticado,
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
def detalle(orden_id: int, db: BD, _: UsuarioAutenticado):
    orden = servicio_ordenes.obtener_orden(db, orden_id)
    return OrdenDetalle(
        orden=OrdenSalida.model_validate(orden),
        totales=servicio_totales.calcular_totales(db, orden),
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


# --- Registros de horno ----------------------------------------------------


@router.get("/{orden_id}/registros-horno", response_model=list[RegistroHornoSalida])
def listar_registros_horno(orden_id: int, db: BD, _: UsuarioAutenticado):
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
def listar_recepciones(orden_id: int, db: BD, _: UsuarioAutenticado):
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
