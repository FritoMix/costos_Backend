"""
Una tanda de horno y una recepcion de saborizado por hora programada (V17).

Cada hora que programa el supervisor es una tanda: la 1 arranca cuando se
inicio la orden y cada una dura una hora (la 2 de una orden iniciada a las
7:00 es de 8:00 a 9:00). La hora la pone la app, no el operario: asi no hay
datos atipicos por horas mal digitadas. Una hora ya registrada no se repite:
se corrige.

Las ordenes antiguas sin hora de inicio siguen pidiendo la hora a mano.

Tambien vive aqui la parada dentro de la hora: minutos (0-60) y causa.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion
from app.core.tiempo import ZONA_HORARIA_LOCAL, ahora_local, combinar_fecha_y_hora
from app.modules.produccion.models import OrdenProduccion

# Margen para registrar una tanda unos minutos antes de que empiece su hora.
MINUTOS_DE_MARGEN = 5


def tandas_ocupadas(db: Session, orden_id: int, modelo) -> set[int]:
    """Numeros de tanda ya registrados en la orden (horno o saborizado)."""
    return set(
        db.scalars(
            select(modelo.numero_tanda).where(
                modelo.orden_id == orden_id,
                modelo.eliminado == False,  # noqa: E712
                modelo.numero_tanda.is_not(None),
            )
        ).all()
    )


def elegir_numero_tanda(
    db: Session,
    orden: OrdenProduccion,
    pedido: int | None,
    modelo,
    nombre: str = "tanda",
    nombres: str = "tandas",
) -> int:
    """
    La hora que falta (o la que se escoge). No se pasa de las horas de la
    orden ni se repite una ya registrada: esa se corrige.
    """
    horas = orden.horas_produccion
    ocupadas = tandas_ocupadas(db, orden.id, modelo)
    texto_horas = f"{horas} {'hora programada' if horas == 1 else 'horas programadas'}"
    if pedido is None:
        tope = horas if horas else max(ocupadas, default=0) + 1
        libres = [n for n in range(1, tope + 1) if n not in ocupadas]
        if not libres:
            raise ErrorDeValidacion(
                f"La orden {orden.numero_orden} tiene {texto_horas} y "
                + (
                    f"ya está registrada su {nombre}. Puedes corregirla"
                    if horas == 1
                    else f"ya están registradas sus {horas} {nombres}. Puedes corregirlas"
                )
                + "; si se necesita más tiempo, el supervisor debe aumentar las horas de la orden."
            )
        return libres[0]
    if horas and pedido > horas:
        raise ErrorDeValidacion(
            f"La orden {orden.numero_orden} solo tiene {texto_horas}: no existe la {nombre} {pedido}."
        )
    if pedido in ocupadas:
        raise ErrorDeValidacion(
            f"La {nombre} {pedido} ya está registrada: corrígela en lugar de registrarla otra vez."
        )
    return pedido


def franja_de_tanda(orden: OrdenProduccion, numero: int | None) -> tuple[datetime, datetime] | None:
    """Inicio y fin de la hora n de la orden. None en ordenes sin hora de inicio."""
    if orden.hora_inicio is None or numero is None:
        return None
    inicio = orden.hora_inicio + timedelta(hours=numero - 1)
    return inicio, inicio + timedelta(hours=1)


def exigir_hora_empezada(franja: tuple[datetime, datetime] | None, nombre: str, numero: int | None) -> None:
    """No se registra una tanda cuya hora todavia no ha empezado."""
    if franja is None:
        return
    inicio, fin = franja
    if ahora_local() < inicio - timedelta(minutes=MINUTOS_DE_MARGEN):
        raise ErrorDeValidacion(
            f"La {nombre} {numero} es de {inicio.astimezone(ZONA_HORARIA_LOCAL):%H:%M} a "
            f"{fin.astimezone(ZONA_HORARIA_LOCAL):%H:%M}: se registra cuando empiece esa hora."
        )


def horario_del_registro(
    orden: OrdenProduccion, franja: tuple[datetime, datetime] | None, datos
) -> tuple[datetime, datetime]:
    """La franja de la tanda; si la orden no tiene hora de inicio, la que se digito."""
    if franja is not None:
        return franja
    if datos.hora_inicio is None or datos.hora_fin is None:
        raise ErrorDeValidacion("La orden no tiene hora de inicio: indica la hora del registro.")
    return combinar_fecha_y_hora(orden.fecha, datos.hora_inicio, datos.hora_fin)


def aplicar_parada(registro, datos) -> None:
    """Minutos y causa de la parada dentro de la hora."""
    minutos = datos.minutos_parada or 0
    if minutos and not datos.causa_parada:
        raise ErrorDeValidacion("Si la línea estuvo parada, indica la causa de la parada.")
    if minutos and datos.causa_parada == "otro" and not (datos.nota_parada or "").strip():
        raise ErrorDeValidacion("Escribe cuál fue la causa de la parada.")
    registro.minutos_parada = minutos
    registro.causa_parada = datos.causa_parada if minutos else None
    registro.nota_parada = ((datos.nota_parada or "").strip() or None) if minutos else None
