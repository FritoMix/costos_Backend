"""
Modulo Bodega - catalogo de referencias de papa.

Una referencia describe la variedad o procedencia de la papa cruda que
compra bodega. El peso promedio por bulto es el dato operativo: con el se
calculan los kilos crudos de cada tanda de horno.

El peso se copia al registro de horno en el momento de crear la tanda. Si
bodega corrige el promedio despues, las ordenes historicas conservan el
peso con el que realmente se calculo su produccion.
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
    peso_promedio_bulto_kg: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    activo: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    fecha_creacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<ReferenciaPapa {self.nombre} {self.peso_promedio_bulto_kg} kg>"
