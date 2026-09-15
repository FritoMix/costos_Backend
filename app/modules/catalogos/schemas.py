"""
Contratos de entrada y salida del modulo Catalogos.
"""

from datetime import date, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

# --- Catalogos simples (solo nombre + activo) ------------------------------


class CatalogoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    activo: bool


class CatalogoGuardar(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    activo: bool = True


# --- Turnos ----------------------------------------------------------------


class TurnoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    hora_inicio: time
    hora_fin: time
    cruza_medianoche: bool
    activo: bool


class TurnoGuardar(BaseModel):
    nombre: str = Field(min_length=1, max_length=50)
    hora_inicio: time
    hora_fin: time
    activo: bool = True
    # No se pide al usuario: se deduce sola (si la hora de fin es menor
    # que la de inicio, el turno cruza la medianoche).


# --- Hornos ----------------------------------------------------------------


class HornoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    activo: bool
    tipo_aceite: str | None
    apto_exportacion: bool
    tanque_diametro_cm: Decimal | None
    litros_por_cm_manual: Decimal | None
    # Calculado: lo que la app realmente usa para convertir cm a litros.
    litros_por_cm: Decimal | None
    categorias: list[CatalogoSalida]


class HornoGuardar(BaseModel):
    nombre: str = Field(min_length=1, max_length=50)
    activo: bool = True
    tipo_aceite: str | None = Field(default=None, max_length=50)
    apto_exportacion: bool = False
    tanque_diametro_cm: Decimal | None = Field(default=None, ge=0)
    litros_por_cm_manual: Decimal | None = Field(default=None, ge=0)
    categoria_ids: list[int] = Field(default_factory=list)


# --- Productos -------------------------------------------------------------


class ProductoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_comercial: str
    activo: bool
    peso_estandar_canastilla_kg: Decimal | None
    categoria: CatalogoSalida


class ProductoGuardar(BaseModel):
    nombre_comercial: str = Field(min_length=1, max_length=150)
    categoria_id: int
    activo: bool = True
    peso_estandar_canastilla_kg: Decimal | None = Field(default=None, gt=0)


# --- Configuracion de planta ----------------------------------------------


class ConfiguracionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    peso_estandar_bulto_kg: Decimal | None
    peso_estandar_canastilla_kg: Decimal | None


class ConfiguracionGuardar(BaseModel):
    peso_estandar_bulto_kg: Decimal | None = Field(default=None, gt=0)
    peso_estandar_canastilla_kg: Decimal | None = Field(default=None, gt=0)


# --- Densidad del aceite ---------------------------------------------------


class MuestraDensidadSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    horno_id: int
    fecha: date
    densidad_kg_por_litro: Decimal


class MuestraDensidadCrear(BaseModel):
    horno_id: int
    fecha: date
    densidad_kg_por_litro: Decimal = Field(gt=0, le=2)


class DensidadVigenteSalida(BaseModel):
    """Ultima densidad conocida de un horno, para mostrarla en pantalla."""

    horno_id: int
    horno_nombre: str
    fecha: date | None
    densidad_kg_por_litro: Decimal | None
