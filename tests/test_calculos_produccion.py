"""Pruebas de las formulas productivas y del reparto por mayores restos."""

from decimal import Decimal

import pytest

from app.core.errores import ErrorDeValidacion
from app.modules.produccion.dominio.calculos import (
    Participacion,
    calcular_bultos_estimados,
    calcular_kg_crudos,
    calcular_kg_fritos_estimados,
    distribuir_bultos,
    validar_participaciones,
)


def test_kg_crudos_y_fritos_usan_decimal_y_redondean_a_centavos():
    assert calcular_kg_crudos(Decimal("40"), Decimal("50.00")) == Decimal("2000.00")
    assert calcular_kg_fritos_estimados(Decimal("2000.00"), Decimal("25")) == Decimal(
        "500.00"
    )
    # 1,005 kg se redondea a 1,01 (no se trunca).
    assert calcular_kg_fritos_estimados(Decimal("4.02"), Decimal("25")) == Decimal(
        "1.01"
    )


def test_bultos_estimados_no_redondea_el_porcentaje():
    assert calcular_bultos_estimados(Decimal("50"), Decimal("66.67")) == Decimal(
        "33.3350"
    )
    assert calcular_bultos_estimados(Decimal("50"), Decimal("33.33")) == Decimal(
        "16.6650"
    )


def test_distribucion_50_bultos_66_67_y_33_33_da_33_y_17():
    participaciones = [
        Participacion(referencia_id=1, porcentaje=Decimal("66.67")),
        Participacion(referencia_id=2, porcentaje=Decimal("33.33")),
    ]
    resultado = distribuir_bultos(50, participaciones)
    assert resultado == {1: 33, 2: 17}
    assert sum(resultado.values()) == 50


def test_distribucion_reparte_los_restos_y_no_pierde_bultos():
    participaciones = [
        Participacion(referencia_id=1, porcentaje=Decimal("33.33")),
        Participacion(referencia_id=2, porcentaje=Decimal("33.33")),
        Participacion(referencia_id=3, porcentaje=Decimal("33.34")),
    ]
    resultado = distribuir_bultos(50, participaciones)
    assert sum(resultado.values()) == 50
    assert sorted(resultado.values()) == [16, 17, 17]


def test_los_empates_son_estables_por_porcentaje_y_luego_por_id():
    participaciones = [
        Participacion(referencia_id=2, porcentaje=Decimal("50")),
        Participacion(referencia_id=1, porcentaje=Decimal("50")),
    ]
    # Con capacidad impar, el bulto sobrante va a la referencia de id menor.
    assert distribuir_bultos(3, participaciones) == {2: 1, 1: 2}


def test_validacion_de_participaciones_acepta_tolerancia_de_centesima():
    total = validar_participaciones(
        [
            Participacion(referencia_id=1, porcentaje=Decimal("33.335")),
            Participacion(referencia_id=2, porcentaje=Decimal("66.665")),
        ]
    )
    assert total == Decimal("100.000")


@pytest.mark.parametrize(
    "participaciones",
    [
        [],
        [Participacion(referencia_id=1, porcentaje=Decimal("99.98"))],
        [
            Participacion(referencia_id=1, porcentaje=Decimal("50")),
            Participacion(referencia_id=1, porcentaje=Decimal("50")),
        ],
        [Participacion(referencia_id=1, porcentaje=Decimal("-1"))],
        [Participacion(referencia_id=1, porcentaje=Decimal("101"))],
    ],
)
def test_validacion_de_participaciones_rechaza_configuraciones_invalidas(participaciones):
    with pytest.raises(ErrorDeValidacion):
        validar_participaciones(participaciones)


def test_las_formulas_rechazan_valores_invalidos():
    with pytest.raises(ErrorDeValidacion, match="negativa"):
        calcular_kg_crudos(Decimal("-1"), Decimal("50"))
    with pytest.raises(ErrorDeValidacion, match="mayor a cero"):
        calcular_kg_crudos(Decimal("1"), Decimal("0"))
    with pytest.raises(ErrorDeValidacion, match="rendimiento"):
        calcular_kg_fritos_estimados(Decimal("100"), Decimal("0"))
    with pytest.raises(ErrorDeValidacion, match="rendimiento"):
        calcular_kg_fritos_estimados(Decimal("100"), Decimal("100.01"))
    with pytest.raises(ErrorDeValidacion, match="capacidad"):
        calcular_bultos_estimados(Decimal("0"), Decimal("50"))
    with pytest.raises(ErrorDeValidacion, match="capacidad"):
        distribuir_bultos(0, [Participacion(1, Decimal("100"))])
