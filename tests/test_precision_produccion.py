"""No calcular con una precisión que PostgreSQL descartará al guardar."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.produccion.schemas import (
    OrdenGuardar,
    RecepcionGuardar,
    RegistroHornoGuardar,
    RegistroReferenciaGuardar,
)

ORDEN = dict(turno_id=1, horno_id=1, categoria_id=1, producto_id=1, horas_produccion=1)
TANDA = dict(hora_inicio="06:00", hora_fin="07:00", referencia_papa_id=1,
             cantidad_bultos="5", operarios_seleccion=1, operarios_horno=1,
             nivel_aceite_inicial_cm="20", nivel_aceite_final_cm="18", temperatura_aceite_c="175")
RECEPCION = dict(hora_inicio="06:00", hora_fin="07:00", sabor_id=1,
                 cantidad_sabor_kg="1", pesos_canastillas=["6.00"])


@pytest.mark.parametrize("modelo,base,campo", [
    (OrdenGuardar, ORDEN, "cantidad_kg"),
    (OrdenGuardar, ORDEN, "cantidad_canastillas"),
    (RegistroReferenciaGuardar, {"referencia_papa_id": 1}, "cantidad_bultos"),
    (RegistroHornoGuardar, TANDA, "cantidad_bultos"),
    (RegistroHornoGuardar, TANDA, "nivel_aceite_inicial_cm"),
    (RegistroHornoGuardar, TANDA, "nivel_aceite_final_cm"),
    (RegistroHornoGuardar, TANDA, "temperatura_aceite_c"),
    (RegistroHornoGuardar, TANDA, "cantidad_desperdicio_kg"),
    (RecepcionGuardar, RECEPCION, "cantidad_sabor_kg"),
])
def test_rechaza_decimales_que_se_perderian_en_bd(modelo, base, campo):
    with pytest.raises(ValidationError):
        modelo(**(base | {campo: "20.001"}))


@pytest.mark.parametrize("modelo,base,campo,valor", [
    (OrdenGuardar, ORDEN, "cantidad_kg", "100000000"),
    (RegistroReferenciaGuardar, {"referencia_papa_id": 1}, "cantidad_bultos", "10000"),
    (RecepcionGuardar, RECEPCION, "cantidad_sabor_kg", "1000000"),
])
def test_rechaza_valores_fuera_de_la_columna(modelo, base, campo, valor):
    with pytest.raises(ValidationError):
        modelo(**(base | {campo: valor}))


def test_conserva_decimales_validos_sin_redondear_entradas():
    fila = RegistroReferenciaGuardar(referencia_papa_id=1, cantidad_bultos="0.01")
    assert fila.cantidad_bultos == Decimal("0.01")
    recepcion = RecepcionGuardar(
        **(RECEPCION | {"cantidad_sabor_kg": "0.01", "pesos_canastillas": ["6.55", "5.45"]})
    )
    assert sum(recepcion.pesos_canastillas) == Decimal("12.00")


def test_suma_de_referencias_tampoco_desborda_la_cabecera():
    with pytest.raises(ValidationError, match="suma de bultos"):
        RegistroHornoGuardar(**(TANDA | {"referencias": [
            {"referencia_papa_id": 1, "cantidad_bultos": "6000"},
            {"referencia_papa_id": 2, "cantidad_bultos": "6000"},
        ]}))
