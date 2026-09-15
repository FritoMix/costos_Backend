"""
Contratos de entrada y salida del modulo Notificaciones.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificacionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo: str
    titulo: str
    mensaje: str
    orden_id: int | None
    fecha_programada: datetime
    leida: bool


class ResumenNotificaciones(BaseModel):
    """
    Lo que el frontend consulta cada pocos segundos.

    "pendientes" trae solo los avisos que ya cumplieron su hora y que la
    persona todavia no ha visto: son los que hacen sonar la alarma.
    """

    sin_leer: int
    pendientes: list[NotificacionSalida]
