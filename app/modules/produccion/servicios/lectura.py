"""Relaciones necesarias para las filas de órdenes, sin recorrer otros catálogos."""

from sqlalchemy.orm import joinedload, lazyload, selectinload

from app.modules.produccion.models import OrdenProduccion, OrdenReferencia


def opciones_listado():
    # Evita cargas automáticas de otros catálogos; las pruebas vigilan el número de consultas.
    return (
        lazyload("*"),
        joinedload(OrdenProduccion.supervisor),
        joinedload(OrdenProduccion.turno),
        joinedload(OrdenProduccion.horno),
        joinedload(OrdenProduccion.producto),
        joinedload(OrdenProduccion.categoria),
        selectinload(OrdenProduccion.referencias).load_only(
            OrdenReferencia.id, OrdenReferencia.orden_id, OrdenReferencia.bultos_planificados,
        ),
    )
