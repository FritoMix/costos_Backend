"""Contratos de entrada y salida del modulo Bodega."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReferenciaPapaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    peso_promedio_bulto_kg: Decimal
    activo: bool
    fecha_creacion: datetime


class ReferenciaPapaGuardar(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    # Numeric(6, 2): hasta 9.999,99 kg por bulto.
    peso_promedio_bulto_kg: Decimal = Field(gt=0, le=Decimal("9999.99"))
    activo: bool = True
