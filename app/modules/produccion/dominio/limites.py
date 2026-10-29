"""
Limites de tiempo para los registros de produccion.

Una orden se programa por horas completas. El horno registra tandas de una
hora y saborizado recepciones de duracion variable; en ambos casos la suma
de los registros activos no puede superar las horas programadas en la orden.

Ademas, dos registros del mismo modulo no pueden cruzarse en el tiempo. Esa
segunda regla es la que evita cargar dos veces la misma tanda o recepcion
cuando el operario guarda repetido o corrige mal el horario.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from app.core.errores import ErrorDeValidacion


class RegistroConHorario(Protocol):
    """Lo minimo que necesita la validacion de cualquier registro."""

    id: int
    hora_inicio: datetime
    hora_fin: datetime


def _formatear_minutos(minutos: int) -> str:
    """Texto corto y legible para los mensajes de validacion."""
    minutos = max(0, minutos)
    horas, resto = divmod(minutos, 60)
    if horas and resto:
        return f"{horas} h {resto} min"
    if horas == 1:
        return "1 hora"
    if horas:
        return f"{horas} horas"
    return f"{resto} min"


def _minutos(inicio: datetime, fin: datetime) -> int:
    return int((fin - inicio).total_seconds() // 60)


def _segundos_registrados(registros: Sequence[RegistroConHorario]) -> float:
    return sum(
        (registro.hora_fin - registro.hora_inicio).total_seconds() for registro in registros
    )


def validar_horas_de_orden(
    *,
    horas_nuevas: int,
    registros_horno: Sequence[RegistroConHorario],
    registros_saborizado: Sequence[RegistroConHorario],
) -> None:
    """
    Impide reducir las horas de una orden por debajo de lo ya registrado.

    Si la orden ya tiene una hora y media de horno, no se puede bajar a una
    hora: los registros existentes quedarian fuera del limite. El usuario
    debe corregir o borrar primero esos registros.
    """
    limite_segundos = horas_nuevas * 60 * 60
    for tipo_registro, registros in (
        ("horno", registros_horno),
        ("saborizado", registros_saborizado),
    ):
        ocupado_segundos = _segundos_registrados(registros)
        if ocupado_segundos > limite_segundos:
            raise ErrorDeValidacion(
                f"No puedes dejar la orden en {_formatear_minutos(horas_nuevas * 60)} porque "
                f"ya hay {_formatear_minutos(int(ocupado_segundos // 60))} registrados en "
                f"{tipo_registro}. Borra o corrige esos registros primero."
            )


def validar_conteo_tandas(
    *,
    horas_produccion: int | None,
    registros: Sequence[RegistroConHorario],
    excluir_id: int | None = None,
    al_editar_horas: bool = False,
) -> None:
    """
    Una orden de N horas acepta como maximo N tandas.

    Al crear o corregir una tanda se exige que quede al menos un cupo libre
    (``tandas_activas < horas``). Al editar las horas de la orden se permite
    que las tandas ya registradas sean exactamente N.
    """
    if horas_produccion is None:
        return
    activos = [registro for registro in registros if registro.id != excluir_id]
    if al_editar_horas:
        if len(activos) > horas_produccion:
            raise ErrorDeValidacion(
                f"La orden tiene {horas_produccion} horas y ya registró "
                f"{len(activos)} tandas. No puedes reducir las horas por debajo de las tandas."
            )
        return
    if len(activos) >= horas_produccion:
        raise ErrorDeValidacion(
            f"La orden tiene {horas_produccion} horas y ya registró "
            f"{len(activos)} tandas. No se puede registrar otra."
        )


def validar_duracion_tanda(
    *,
    inicio: datetime,
    fin: datetime,
    max_minutos: int = 60,
) -> None:
    """Una tanda no puede durar mas de una hora."""
    if (fin - inicio).total_seconds() > max_minutos * 60:
        raise ErrorDeValidacion(
            f"Una tanda de horno no puede durar más de {max_minutos} minutos. "
            f"Esta tanda dura {_formatear_minutos(_minutos(inicio, fin))}."
        )


def validar_ventana_registro(
    *,
    horas_produccion: int | None,
    inicio: datetime,
    fin: datetime,
    registros: Sequence[RegistroConHorario],
    tipo_registro: str,
    excluir_id: int | None = None,
) -> None:
    """
    Valida una tanda de horno o una recepcion de saborizado.

    ``excluir_id`` permite corregir un registro existente sin que se cuente
    dos veces a si mismo. Las ordenes historicas sin horas configuradas
    siguen permitiendo registros, pero nunca aceptan horarios cruzados.
    """
    if fin <= inicio:
        raise ErrorDeValidacion(
            f"La hora de fin de la {tipo_registro} debe ser posterior a la hora de inicio."
        )

    otros = [registro for registro in registros if registro.id != excluir_id]

    for registro in otros:
        if inicio < registro.hora_fin and fin > registro.hora_inicio:
            raise ErrorDeValidacion(
                f"El horario de esta {tipo_registro} se cruza con otra registrada de "
                f"{registro.hora_inicio:%H:%M} a {registro.hora_fin:%H:%M}. "
                "Revisa los datos para no duplicar el registro."
            )

    if horas_produccion is None:
        return

    limite_segundos = horas_produccion * 60 * 60
    ocupado_segundos = _segundos_registrados(otros)
    nuevo_segundos = (fin - inicio).total_seconds()

    if ocupado_segundos + nuevo_segundos <= limite_segundos:
        return

    restante = int(max(0, limite_segundos - ocupado_segundos) // 60)
    raise ErrorDeValidacion(
        f"La orden tiene {_formatear_minutos(horas_produccion * 60)} de producción y "
        f"ya se registró {_formatear_minutos(int(ocupado_segundos // 60))} en "
        f"{tipo_registro}. Solo quedan {_formatear_minutos(restante)}; este registro "
        f"dura {_formatear_minutos(_minutos(inicio, fin))}. "
        "Ajusta el horario para no duplicar registros."
    )
