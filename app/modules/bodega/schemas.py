"""Contratos de entrada y salida del modulo Bodega."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReferenciaPapaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    # NULL solo en referencias historicas anteriores a la configuracion.
    tipo: str | None
    peso_promedio_bulto_kg: Decimal
    rendimiento_fritura_pct: Decimal | None
    porcentaje_produccion_pct: Decimal | None
    activo: bool
    fecha_creacion: datetime
    fecha_actualizacion: datetime


class ReferenciaPapaGuardar(BaseModel):
    """
    Datos que captura Bodega hoy: nombre, peso por bulto y estado.

    `tipo`, rendimiento y participacion ya no se piden en la pantalla; se
    aceptan opcionales para no romper integraciones ni datos historicos, y
    quedan en NULL en las referencias nuevas.
    """

    nombre: str = Field(min_length=1, max_length=120)
    tipo: str | None = Field(default=None, max_length=100)
    # Numeric(6, 2): hasta 9.999,99 kg por bulto.
    peso_promedio_bulto_kg: Decimal = Field(gt=0, le=Decimal("9999.99"))
    rendimiento_fritura_pct: Decimal | None = Field(default=None, gt=0, le=Decimal("100"))
    porcentaje_produccion_pct: Decimal | None = Field(default=None, ge=0, le=Decimal("100"))
    activo: bool = True

    @field_validator("nombre")
    @classmethod
    def _texto_no_vacio(cls, valor: str) -> str:
        limpio = valor.strip()
        if not limpio:
            raise ValueError("Este campo no puede estar vacío.")
        return limpio

    @field_validator("tipo")
    @classmethod
    def _tipo_opcional(cls, valor: str | None) -> str | None:
        if valor is None:
            return None
        limpio = valor.strip()
        return limpio or None


class ProyeccionReferenciaSalida(BaseModel):
    referencia_id: int
    nombre: str
    tipo: str | None
    porcentaje_produccion_pct: Decimal
    bultos: int
    peso_promedio_bulto_kg: Decimal
    rendimiento_fritura_pct: Decimal | None
    kg_crudos: Decimal
    kg_fritos_estimados: Decimal | None


class ProyeccionProduccionSalida(BaseModel):
    horno_id: int
    horno_nombre: str
    capacidad_bultos_hora: Decimal
    horas: int
    total_bultos: int
    total_kg_crudos: Decimal
    total_kg_fritos_estimados: Decimal | None
    referencias: list[ProyeccionReferenciaSalida]
