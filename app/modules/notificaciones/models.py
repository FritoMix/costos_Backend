"""
Modulo Notificaciones - tabla: notificaciones.

Un aviso pertenece siempre a UNA persona (si hay que avisarle a cinco
operarios, se crean cinco filas). Asi cada quien marca como leidos los
suyos sin afectar a los demas.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TipoNotificacion:
    """Motivos por los que la app avisa. Deben coincidir con el CHECK de la tabla."""

    ORDEN_CREADA = "orden_creada"
    PRODUCCION_POR_TERMINAR = "produccion_por_terminar"


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id: Mapped[int] = mapped_column(primary_key=True)

    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"))

    tipo: Mapped[str] = mapped_column(String(40))
    titulo: Mapped[str] = mapped_column(String(150))
    mensaje: Mapped[str] = mapped_column(Text)

    orden_id: Mapped[int | None] = mapped_column(
        ForeignKey("ordenes_produccion.id"), nullable=True
    )

    # Desde cuando debe verse el aviso. En los inmediatos es "ahora"; en el
    # de "faltan 15 minutos" es un momento futuro calculado al iniciar la
    # produccion. La API solo entrega los que ya cumplieron su hora.
    fecha_programada: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    leida: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<Notificacion {self.tipo} usuario={self.usuario_id}>"
