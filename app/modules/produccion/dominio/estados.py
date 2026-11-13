"""Máquina de estados de órdenes; los reintentos en el destino no repiten efectos."""

from app.core.errores import ErrorDeValidacion
from app.modules.produccion.models import EstadoOrden

TRANSICIONES = {
    "iniciar": (
        (EstadoOrden.PENDIENTE,),
        EstadoOrden.EN_PRODUCCION,
        "Solo se puede iniciar una orden que esté Pendiente.",
    ),
    "finalizar": (
        (EstadoOrden.EN_PRODUCCION,),
        EstadoOrden.FINALIZADA,
        "Solo se puede finalizar una orden que esté En producción.",
    ),
    "cancelar": (EstadoOrden.ACTIVOS, EstadoOrden.CANCELADA, "Esta orden ya no se puede cancelar."),
}


def requiere_transicion(estado: str, accion: str) -> bool:
    origenes, destino, mensaje = TRANSICIONES[accion]
    if estado == destino:
        return False
    if estado not in origenes:
        raise ErrorDeValidacion(mensaje)
    return True
