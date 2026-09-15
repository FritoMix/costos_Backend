"""
Totales de UNA orden, para la pantalla de detalle.

Los indicadores de gestion (rendimiento, absorcion de aceite, etc.) viven
en el modulo Analitica; aqui solo se suma lo que lleva esta orden para que
el supervisor vea el avance.
"""

from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.produccion.models import (
    Desperdicio,
    OrdenProduccion,
    RegistroHorno,
    RegistroSaborizado,
)
from app.modules.produccion.schemas import TotalesOrden


def calcular_totales(db: Session, orden: OrdenProduccion) -> TotalesOrden:
    kg_crudos, bultos, kg_aceite = db.execute(
        select(
            func.coalesce(func.sum(RegistroHorno.kg_crudos_calculados), 0),
            func.coalesce(func.sum(RegistroHorno.cantidad_bultos), 0),
            func.coalesce(func.sum(RegistroHorno.kg_aceite_consumido), 0),
        ).where(RegistroHorno.orden_id == orden.id, RegistroHorno.eliminado == False)
    ).one()

    kg_desperdicio = db.scalar(
        select(func.coalesce(func.sum(Desperdicio.cantidad_kg), 0))
        .join(RegistroHorno, Desperdicio.registro_horno_id == RegistroHorno.id)
        .where(RegistroHorno.orden_id == orden.id, RegistroHorno.eliminado == False)
    ) or Decimal("0")

    kg_papa_frita = db.scalar(
        select(func.coalesce(func.sum(RegistroSaborizado.kg_recibidos), 0)).where(
            RegistroSaborizado.orden_id == orden.id, RegistroSaborizado.eliminado == False
        )
    ) or Decimal("0")

    avance = None
    if orden.cantidad_programada and orden.cantidad_programada > 0:
        avance = (kg_papa_frita / orden.cantidad_programada * 100).quantize(Decimal("0.01"))

    return TotalesOrden(
        kg_crudos=kg_crudos,
        cantidad_bultos=bultos,
        kg_papa_frita=kg_papa_frita,
        kg_aceite=kg_aceite,
        kg_desperdicio=kg_desperdicio,
        avance_porcentaje=avance,
    )
