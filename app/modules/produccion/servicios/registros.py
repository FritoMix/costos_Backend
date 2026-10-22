"""
Utilidades compartidas por los registros de horno y saborizado.

El bloqueo de la orden serializa dos guardados simultaneos. Sin el, dos
peticiones podrian leer "todavia no hay tanda" al mismo tiempo y ambas
crear un registro que excede las horas programadas.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.produccion.models import OrdenProduccion


def bloquear_orden(db: Session, orden_id: int) -> None:
    """Toma el lock de la orden hasta que termine la transaccion actual."""
    db.execute(
        select(OrdenProduccion.id)
        .where(OrdenProduccion.id == orden_id)
        .with_for_update()
    )
