"""
Contratos de entrada y salida del modulo Produccion.
"""

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Referencias cortas a otros catalogos ---------------------------------


class Referencia(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str


class ProductoRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_comercial: str


class ReferenciaPapaRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre: str
    tipo: str | None
    peso_promedio_bulto_kg: Decimal
    rendimiento_fritura_pct: Decimal | None
    porcentaje_produccion_pct: Decimal | None


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
    formula_estado: str
    formula_obligatoria: bool
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


# --- Formula de produccion por orden --------------------------------------


class FormulaReferenciaGuardar(BaseModel):
    referencia_papa_id: int = Field(gt=0)
    bultos_por_tanda: int = Field(gt=0)


class FormulaGuardar(BaseModel):
    referencias: list[FormulaReferenciaGuardar] = Field(min_length=1)
    notas: str | None = Field(default=None, max_length=500)


class FormulaReferenciaSalida(BaseModel):
    referencia_id: int
    nombre: str
    tipo: str | None
    bultos_por_tanda: int
    bultos_planificados: int
    porcentaje_produccion_pct: Decimal
    peso_promedio_bulto_kg: Decimal
    rendimiento_fritura_pct: Decimal
    kg_crudos_por_tanda: Decimal
    kg_fritos_por_tanda: Decimal
    kg_crudos_planificados: Decimal
    kg_fritos_estimados: Decimal
    bultos_producidos: Decimal
    bultos_restantes: Decimal


class FormulaSalida(BaseModel):
    orden_id: int
    estado: str
    referencias: list[FormulaReferenciaSalida]
    notas: str | None
    capacidad_bultos_hora: Decimal | None
    capacidad_maxima_bultos: int | None
    total_bultos_por_tanda: int
    total_bultos_planificados: int
    total_kg_crudos: Decimal
    total_kg_fritos_estimados: Decimal
    total_bultos_producidos: Decimal
    avance_bultos_porcentaje: Decimal | None
    tandas_registradas: int
    tandas_programadas: int | None
    actualizada_por: UsuarioRef | None
    fecha_actualizacion: datetime | None
    advertencias: list[str] = []


class FormulaProyeccionGuardar(BaseModel):
    referencias: list[FormulaReferenciaGuardar] = Field(default_factory=list)
    usar_sugerencia: bool = False


class FormulaProyeccionReferencia(BaseModel):
    referencia_id: int
    nombre: str
    tipo: str | None
    bultos_por_tanda: int
    porcentaje_produccion_pct: Decimal
    peso_promedio_bulto_kg: Decimal
    rendimiento_fritura_pct: Decimal
    kg_crudos_por_tanda: Decimal
    kg_fritos_por_tanda: Decimal
    kg_crudos_planificados: Decimal
    kg_fritos_estimados: Decimal


class FormulaProyeccionSalida(BaseModel):
    origen: str
    capacidad_bultos_hora: Decimal | None
    capacidad_maxima_bultos: int | None
    total_bultos_por_tanda: int
    total_bultos_planificados: int
    kg_fritos_por_bulto_promedio: Decimal
    total_kg_crudos: Decimal
    total_kg_fritos_estimados: Decimal
    cantidad_programada: Decimal
    diferencia_kg: Decimal
    diferencia_pct: Decimal
    tandas_programadas: int
    factible: bool
    mensaje: str | None
    referencias: list[FormulaProyeccionReferencia]


class OrdenBodegaSalida(OrdenSalida):
    formula_notas: str | None
    total_bultos_planificados: int | None
    total_bultos_producidos: Decimal | None
    tandas_registradas: int
    tandas_programadas: int | None
    avance_bultos_porcentaje: Decimal | None


class OrdenBodegaDetalle(BaseModel):
    orden: OrdenBodegaSalida
    formula: FormulaSalida


# --- Registro de horno -----------------------------------------------------


class DesperdicioSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tipo_desperdicio_id: int
    cantidad_kg: Decimal
    observacion: str | None
    tipo_desperdicio: Referencia


class RegistroReferenciaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    referencia_papa_id: int
    nombre: str
    cantidad_bultos: Decimal
    peso_estandar_bulto_kg: Decimal
    rendimiento_fritura_pct: Decimal | None
    porcentaje_produccion_pct: Decimal | None
    kg_crudos_calculados: Decimal
    kg_fritos_estimados: Decimal | None


class RegistroHornoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    orden_id: int
    hora_inicio: datetime
    hora_fin: datetime
    referencia_papa: ReferenciaPapaRef | None
    referencias: list[RegistroReferenciaSalida] = []
    cantidad_bultos: Decimal
    peso_estandar_bulto_kg: Decimal | None
    rendimiento_fritura_pct: Decimal | None
    porcentaje_produccion_pct: Decimal | None
    kg_crudos_calculados: Decimal
    kg_fritos_estimados: Decimal | None
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


class RegistroReferenciaGuardar(BaseModel):
    referencia_papa_id: int = Field(gt=0)
    cantidad_bultos: Decimal = Field(gt=0)


class RegistroHornoGuardar(BaseModel):
    # Solo la hora del reloj: la fecha la pone la app (es la de la orden) y
    # el usuario sale del token. Al operario no se le pide ni una ni otro.
    hora_inicio: time
    hora_fin: time
    # Formato nuevo: una o varias referencias por tanda.
    referencias: list[RegistroReferenciaGuardar] | None = None
    # Compatibilidad: clientes viejos envían una sola referencia.
    referencia_papa_id: int | None = Field(default=None, gt=0)
    cantidad_bultos: Decimal | None = Field(default=None, gt=0)
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

    @model_validator(mode="after")
    def _nivel_final_no_supera_inicial(self) -> "RegistroHornoGuardar":
        """Primera barrera: el consumo de aceite no puede ser negativo."""
        if self.nivel_aceite_final_cm > self.nivel_aceite_inicial_cm:
            raise ValueError("El nivel final del aceite no puede ser mayor que el inicial.")
        return self

    @model_validator(mode="after")
    def _exigir_mezcla(self) -> "RegistroHornoGuardar":
        """Una tanda necesita el formato nuevo o los dos campos heredados."""
        if not self.referencias and (
            self.referencia_papa_id is None or self.cantidad_bultos is None
        ):
            raise ValueError("Debes indicar al menos una referencia para la tanda.")
        if self.referencias:
            ids = [fila.referencia_papa_id for fila in self.referencias]
            if len(ids) != len(set(ids)):
                raise ValueError("No puedes repetir una referencia en la misma tanda.")
        return self


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
    kg_fritos_estimados: Decimal
    kg_papa_frita: Decimal
    kg_aceite: Decimal
    kg_desperdicio: Decimal
    # Cuanto se lleva producido frente a lo programado.
    avance_porcentaje: Decimal | None


class OrdenDetalle(BaseModel):
    orden: OrdenSalida
    totales: TotalesOrden
    formula: FormulaSalida | None
    registros_horno: list[RegistroHornoSalida]
    recepciones: list[RecepcionSalida]
