"""
Contratos del modulo Analitica.
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class FiltrosAnalisis(BaseModel):
    """
    Filtros de la pantalla de Analisis. Todos son opcionales: lo que no se
    envia, no filtra.
    """

    fecha_desde: date | None = None
    fecha_hasta: date | None = None
    turno_id: int | None = None
    horno_id: int | None = None
    producto_id: int | None = None
    categoria_id: int | None = None
    supervisor_id: int | None = None
    sabor_id: int | None = None


class Desglose(BaseModel):
    """Una barra de una grafica: una etiqueta y su valor en kg."""

    etiqueta: str
    valor: Decimal


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


class FilaBache(BaseModel):
    """Una tanda de horno con sus indicadores, para la tabla de detalle."""

    registro_id: int
    numero_orden: str
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
