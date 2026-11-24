"""Lecturas de órdenes: filtros por rol, paginación y disponibilidad del horno.

No confirma transacciones ni cambia entidades. Las escrituras bloquean la
orden antes de consultar disponibilidad y conservan el índice único final.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.modules.catalogos.models import Horno, Producto
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.produccion.models import EstadoOrden, OrdenProduccion
from app.modules.produccion.servicios.lectura import opciones_listado

# Rendimiento: turno, horno, producto, categoria y personas de la orden en la
# misma consulta, y no una consulta por cada uno.
_OPCIONES_ORDEN = (
    joinedload(OrdenProduccion.supervisor),
    joinedload(OrdenProduccion.turno),
    joinedload(OrdenProduccion.horno).joinedload(Horno.linea),
    joinedload(OrdenProduccion.variedad),
    joinedload(OrdenProduccion.producto).joinedload(Producto.categoria),
    joinedload(OrdenProduccion.categoria),
    joinedload(OrdenProduccion.formula_actualizada_por),
)


def obtener_orden(db: Session, orden_id: int) -> OrdenProduccion:
    orden = db.get(OrdenProduccion, orden_id, options=_OPCIONES_ORDEN)
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

    # Cada operario (y Bodega) ve solo las ordenes de su linea (V21).
    if usuario.linea_id is not None:
        from app.modules.catalogos.models import Horno

        consulta = consulta.where(
            OrdenProduccion.horno_id.in_(select(Horno.id).where(Horno.linea_id == usuario.linea_id))
        )

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



def contar_pendientes_sin_formula(db: Session, usuario: Usuario) -> int | None:
    if usuario.rol.codigo not in (RolCodigo.ADMIN, RolCodigo.SUPERVISOR):
        return None
    pendientes = _consulta_ordenes(db, usuario=usuario, estado=EstadoOrden.PENDIENTE).where(
        OrdenProduccion.formula_obligatoria.is_(True),
        ~OrdenProduccion.referencias.any(),
    )
    return db.scalar(select(func.count()).select_from(pendientes.order_by(None).subquery())) or 0


def verificar_linea(usuario: Usuario, orden: OrdenProduccion) -> None:
    """Un operario solo trabaja las ordenes de su linea (V21)."""
    if usuario.linea_id is not None and orden.horno.linea_id != usuario.linea_id:
        raise ErrorDeValidacion(
            f"La orden {orden.numero_orden} es de la línea {orden.linea.nombre}; "
            f"tú trabajas en la línea {usuario.linea.nombre}."
        )
