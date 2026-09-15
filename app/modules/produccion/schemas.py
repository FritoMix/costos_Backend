"""
Contratos de entrada y salida del modulo Produccion.
"""

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

# --- Referencias cortas a otros catalogos ---------------------------------


class Referencia(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str


class ProductoRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_comercial: str


class UsuarioRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_completo: str


# --- Ordenes ---------------------------------------------------------------


class OrdenSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    numero_orden: str
    fecha: date
    estado: str
    estado_etiqueta: str
    destino: str
    destino_etiqueta: str
    cantidad_programada: Decimal
    unidad_solicitada: str
    cantidad_canastillas_solicitadas: Decimal | None
    horas_produccion: int | None
    hora_inicio: datetime | None
    hora_fin: datetime | None
    supervisor: UsuarioRef
    turno: Referencia
    horno: Referencia
    producto: ProductoRef
    categoria: Referencia


class OrdenGuardar(BaseModel):
    turno_id: int
    horno_id: int
    categoria_id: int
    producto_id: int
    destino: str = "nacional"
    unidad_solicitada: str = "kg"
    # Se envia uno u otro segun la unidad: kg directo, o cantidad de
    # canastillas (que la app convierte a kg con el peso estandar).
    cantidad_kg: Decimal | None = Field(default=None, gt=0)
    cantidad_canastillas: Decimal | None = Field(default=None, gt=0)
    # Horas COMPLETAS que se va a mandar la orden a produccion. Es un entero
    # a proposito: en la planta no se programan medias horas, y el minimo es
    # una hora.
    horas_produccion: int | None = Field(default=None, ge=1)


# --- Registro de horno -----------------------------------------------------


class DesperdicioSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo_desperdicio_id: int
    cantidad_kg: Decimal
    observacion: str | None
    tipo_desperdicio: Referencia


class RegistroHornoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    orden_id: int
    hora_inicio: datetime
    hora_fin: datetime
    cantidad_bultos: Decimal
    peso_estandar_bulto_kg: Decimal
    kg_crudos_calculados: Decimal
    operarios_seleccion: int
    operarios_horno: int
    nivel_aceite_inicial_cm: Decimal
    nivel_aceite_final_cm: Decimal
    diferencia_aceite_cm: Decimal
    temperatura_aceite_c: Decimal | None
    litros_por_cm_usado: Decimal | None
    volumen_aceite_litros: Decimal | None
    densidad_aceite_usada: Decimal | None
    kg_aceite_consumido: Decimal | None
    observaciones: str | None
    fecha_creacion: datetime
    usuario: UsuarioRef
    desperdicios: list[DesperdicioSalida]


class RegistroHornoGuardar(BaseModel):
    # Solo la hora del reloj: la fecha la pone la app (es la de la orden) y
    # el usuario sale del token. Al operario no se le pide ni una ni otro.
    hora_inicio: time
    hora_fin: time
    cantidad_bultos: Decimal = Field(gt=0)
    operarios_seleccion: int = Field(ge=0, le=999)
    operarios_horno: int = Field(ge=0, le=999)
    nivel_aceite_inicial_cm: Decimal = Field(ge=0)
    nivel_aceite_final_cm: Decimal = Field(ge=0)
    temperatura_aceite_c: Decimal = Field(gt=0, le=400)
    observaciones: str | None = None
    # Desperdicio de la tanda (opcional).
    tipo_desperdicio_id: int | None = None
    cantidad_desperdicio_kg: Decimal | None = Field(default=None, ge=0)
    observacion_desperdicio: str | None = None


# --- Registro de saborizado (recepciones) ---------------------------------


class CanastillaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    numero: int
    peso_kg: Decimal


class RecepcionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    orden_id: int
    hora_inicio: datetime
    hora_fin: datetime
    cantidad_sabor_kg: Decimal
    kg_recibidos: Decimal
    fecha_creacion: datetime
    sabor: Referencia
    turno: Referencia
    usuario: UsuarioRef
    canastillas: list[CanastillaSalida]


class RecepcionGuardar(BaseModel):
    hora_inicio: time
    hora_fin: time
    sabor_id: int
    cantidad_sabor_kg: Decimal = Field(gt=0)
    # Peso REAL de cada canastilla, una por una. Nunca un valor asumido.
    pesos_canastillas: list[Decimal] = Field(min_length=1)


# --- Detalle completo de una orden ----------------------------------------


class TotalesOrden(BaseModel):
    kg_crudos: Decimal
    cantidad_bultos: Decimal
    kg_papa_frita: Decimal
    kg_aceite: Decimal
    kg_desperdicio: Decimal
    # Cuanto se lleva producido frente a lo programado.
    avance_porcentaje: Decimal | None


class OrdenDetalle(BaseModel):
    orden: OrdenSalida
    totales: TotalesOrden
    registros_horno: list[RegistroHornoSalida]
    recepciones: list[RecepcionSalida]
