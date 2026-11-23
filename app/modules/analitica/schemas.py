"""
Contratos del modulo Analitica.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, Field, model_validator


class FiltrosAnalisis(BaseModel):
    """
    Filtros de la pantalla de Analisis. Todos son opcionales: lo que no se
    envia, no filtra.
    """

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    turno_id: int | None = Field(default=None, gt=0)
    horno_id: int | None = Field(default=None, gt=0)
    producto_id: int | None = Field(default=None, gt=0)
    categoria_id: int | None = Field(default=None, gt=0)
    supervisor_id: int | None = Field(default=None, gt=0)
    sabor_id: int | None = Field(default=None, gt=0)


    @model_validator(mode="after")
    def validar_rango(self) -> Self:
        if self.fecha_desde and self.fecha_hasta and self.fecha_desde > self.fecha_hasta:
            raise ValueError("La fecha inicial no puede ser posterior a la fecha final.")
        return self


class Desglose(BaseModel):
    """Una barra de una grafica: una etiqueta y su valor en kg.

    El campo ``meta`` es opcional: si está presente indica la cantidad
    programada para ese ítem, y el frontend lo usa para colorear la barra
    en verde (cumplió) o rojo (no cumplió).
    """

    etiqueta: str
    valor: Decimal
    meta: Decimal | None = None


class IndicadoresSalida(BaseModel):
    numero_ordenes: int
    kg_crudos: Decimal
    cantidad_bultos: Decimal
    kg_papa_frita: Decimal
    kg_sabor: Decimal
    kg_desperdicio: Decimal
    kg_aceite: Decimal

    # Formulas confirmadas por la planta:
    #   aceite por bulto      = kg aceite / bultos
    #   % rendimiento         = kg papa frita / kg crudos x 100
    #   % absorcion de aceite = kg aceite / kg papa frita x 100
    aceite_por_bulto: Decimal | None
    rendimiento_porcentaje: Decimal | None
    porcentaje_absorcion_aceite: Decimal | None

    por_horno: list[Desglose]
    por_producto: list[Desglose]
    por_turno: list[Desglose]
    por_tipo_desperdicio: list[Desglose]


class IndicadoresCategoriaSalida(BaseModel):
    """Los mismos indicadores, pero de una sola categoria."""

    categoria_id: int
    categoria_nombre: str
    numero_ordenes: int
    kg_crudos: Decimal
    cantidad_bultos: Decimal
    kg_papa_frita: Decimal
    kg_sabor: Decimal
    kg_desperdicio: Decimal
    kg_aceite: Decimal
    aceite_por_bulto: Decimal | None
    rendimiento_porcentaje: Decimal | None
    porcentaje_absorcion_aceite: Decimal | None
    sabores_usados: list[Desglose]


class TipoPapaTanda(BaseModel):
    """Bultos de un tipo de papa (A, B, C, D...) dentro de una tanda con formula."""

    tipo: str
    bultos: Decimal


class FilaBache(BaseModel):
    """Una tanda de horno con sus indicadores, para la tabla de detalle."""

    registro_id: int
    numero_orden: str
    # Linea de la orden y variedad de la materia prima (V21).
    linea: str | None = None
    variedad: str | None = None
    fecha: date
    hora_inicio: datetime
    hora_fin: datetime
    duracion_horas: Decimal
    horno: str
    producto: str
    categoria: str
    turno: str
    supervisor: str
    operario: str
    cantidad_bultos: Decimal
    kg_crudos: Decimal
    kg_papa_frita_orden: Decimal
    kg_aceite: Decimal | None
    temperatura_aceite_c: Decimal | None
    kg_desperdicio: Decimal
    aceite_por_bulto: Decimal | None
    rendimiento_porcentaje: Decimal | None
    porcentaje_absorcion_aceite: Decimal | None
    # Tipos de papa de la formula, cada uno con sus bultos. Vacio si la tanda
    # no uso formula (lineas sin Bodega o tandas viejas sin detalle).
    tipos_papa: list[TipoPapaTanda] = []
    # Rendimiento llevado a un bulto: kg crudos por bulto x rendimiento.
    kg_frito_por_bulto: Decimal | None = None
    # Sabor gastado en la orden y su porcentaje sobre los kg freidos.
    kg_sabor_orden: Decimal = Decimal("0")
    porcentaje_sabor: Decimal | None = None


class PaginaBaches(BaseModel):
    items: list[FilaBache]
    hay_siguiente: bool
