"""Lecturas de órdenes: filtros por rol, paginación y disponibilidad del horno.

No confirma transacciones ni cambia entidades. Las escrituras bloquean la
orden antes de consultar disponibilidad y conservan el índice único final.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.produccion.models import EstadoOrden, OrdenProduccion
from app.modules.produccion.servicios.lectura import opciones_listado


def obtener_orden(db: Session, orden_id: int) -> OrdenProduccion:
    orden = db.get(OrdenProduccion, orden_id)
    if orden is None or orden.eliminado:
        raise RecursoNoEncontrado("Esa orden no existe.")
    return orden


def _consulta_ordenes(
    db: Session,
    *,
    usuario: Usuario,
    estado: str | None = None,
    solo_propias: bool | None = None,
) -> Select:
    """
    Lista de ordenes visibles.

    Un supervisor ve por defecto solo las suyas (es lo que gestiona);
    el administrador ve todas. Los operarios usan el filtro
    estado='en_produccion' para ver a que orden pueden registrarle datos.
    """
    consulta = select(OrdenProduccion).where(OrdenProduccion.eliminado == False)

    if estado is not None:
        consulta = consulta.where(OrdenProduccion.estado == estado)

    if solo_propias is None:
        solo_propias = usuario.rol.codigo == RolCodigo.SUPERVISOR
    if solo_propias:
        consulta = consulta.where(OrdenProduccion.supervisor_id == usuario.id)

    return consulta.order_by(OrdenProduccion.fecha.desc(), OrdenProduccion.id.desc())


def listar_ordenes(
    db: Session, *, usuario: Usuario, estado: str | None = None, solo_propias: bool | None = None
) -> list[OrdenProduccion]:
    consulta = _consulta_ordenes(db, usuario=usuario, estado=estado, solo_propias=solo_propias)
    return list(db.scalars(consulta.options(*opciones_listado()).limit(500)).unique().all())


def pagina_ordenes(
    db: Session,
    *,
    usuario: Usuario,
    pagina: int = 1,
    tamano: int = 50,
    estado: str | None = None,
    solo_propias: bool | None = None,
) -> dict:
    if not 1 <= pagina <= 1_000_000 or not 1 <= tamano <= 100:
        raise ErrorDeValidacion("Página o tamaño de página fuera de rango.")
    consulta = _consulta_ordenes(db, usuario=usuario, estado=estado, solo_propias=solo_propias)
    total = db.scalar(select(func.count()).select_from(consulta.order_by(None).subquery()))
    filas = db.scalars(
        consulta.options(*opciones_listado()).limit(tamano).offset((pagina - 1) * tamano)
    ).unique().all()
    return {"items": list(filas), "total": total, "pagina": pagina, "tamano": tamano}



def buscar_orden_en_horno(
    db: Session, horno_id: int, *, excluir_id: int | None = None
) -> OrdenProduccion | None:
    """Orden no eliminada que ocupa un horno; no sustituye el índice de exclusividad."""
    consulta = select(OrdenProduccion).where(
        OrdenProduccion.horno_id == horno_id,
        OrdenProduccion.estado == EstadoOrden.EN_PRODUCCION,
        OrdenProduccion.eliminado.is_(False),
    )
    if excluir_id is not None:
        consulta = consulta.where(OrdenProduccion.id != excluir_id)
    return db.scalar(consulta)
