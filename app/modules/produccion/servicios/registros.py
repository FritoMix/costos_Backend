"""Bloqueo y recarga de la orden antes de cualquier validación de escritura."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errores import RecursoNoEncontrado
from app.modules.produccion.models import OrdenProduccion


def bloquear_orden(db: Session, orden_id: int) -> OrdenProduccion:
    orden = db.scalar(
        select(OrdenProduccion)
        .where(OrdenProduccion.id == orden_id, OrdenProduccion.eliminado.is_(False))
        .with_for_update(of=OrdenProduccion)
        .execution_options(populate_existing=True)
    )
    if orden is None:
        raise RecursoNoEncontrado("Esa orden no existe o fue eliminada.")
    return orden
