"""
Modulo Bodega - catalogo de referencias de papa.

Una referencia describe la variedad o procedencia de la papa cruda que
compra bodega. Ademas del peso promedio por bulto, guarda los parametros
productivos que usa el horno: rendimiento de fritura y participacion en la
mezcla de produccion.

Los tres valores (peso, rendimiento y participacion) se copian al registro
de horno al crear la tanda. Si bodega los corrige despues, las tandas
historicas conservan los valores con los que realmente se calcularon.

Los campos nuevos son NULL para las referencias creadas antes de V9: no se
inventan parametros historicos. El operario no puede usar una referencia
incompleta hasta que Bodega la complete.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReferenciaPapa(Base):
    __tablename__ = "referencias_papa"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    tipo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    peso_promedio_bulto_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    # NULL solo en referencias historicas. Las nuevas exigen ambos valores.
    rendimiento_fritura_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    porcentaje_produccion_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    fecha_actualizacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ReferenciaPapa {self.nombre} {self.peso_promedio_bulto_kg} kg>"
