"""
Zona horaria de la fabrica: Colombia (America/Bogota, UTC-5, sin horario
de verano).

Por que existe este archivo:
- PostgreSQL guarda internamente todo en UTC, que es la forma correcta.
  Pero cuando un operario escribe "06:00" en un formulario esta pensando
  en hora de Colombia. Si guardaramos ese valor como si fuera UTC,
  quedaria cinco horas corrido.
- Aqui se centraliza esa conversion para que ningun servicio la repita.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.config import settings

ZONA_HORARIA_LOCAL = ZoneInfo(settings.tz)


def ahora_local() -> datetime:
    """Fecha y hora actuales en la zona horaria de la planta."""
    return datetime.now(ZONA_HORARIA_LOCAL)


def hoy_local() -> date:
    """Fecha de hoy segun el reloj de la planta (no el del servidor)."""
    return ahora_local().date()


def combinar_fecha_y_hora(
    fecha_base: date, hora_inicio: time, hora_fin: time
) -> tuple[datetime, datetime]:
    """
    Convierte dos horas de reloj (ej: 23:30 y 01:15) en fecha+hora reales,
    detectando si el turno cruzo la medianoche: si la hora final es menor
    que la inicial, se asume que ocurrio al dia siguiente.

    Las horas se interpretan como hora local de la planta.
    """
    inicio = datetime.combine(fecha_base, hora_inicio, tzinfo=ZONA_HORARIA_LOCAL)
    fin = datetime.combine(fecha_base, hora_fin, tzinfo=ZONA_HORARIA_LOCAL)
    if hora_fin < hora_inicio:
        fin += timedelta(days=1)
    return inicio, fin
