"""Reglas de tiempo compartidas por horno y saborizado."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.errores import ErrorDeValidacion
from app.modules.produccion.dominio.limites import (
    validar_horas_de_orden,
    validar_ventana_registro,
)

BASE = datetime(2026, 10, 22, 6, 0)


def _registro(registro_id: int, inicio: datetime, fin: datetime):
    return SimpleNamespace(id=registro_id, hora_inicio=inicio, hora_fin=fin)


def _validar(
    *,
    horas: int | None,
    inicio: datetime,
    fin: datetime,
    registros=(),
    excluir_id: int | None = None,
    tipo: str = "tanda de horno",
):
    validar_ventana_registro(
        horas_produccion=horas,
        inicio=inicio,
        fin=fin,
        registros=list(registros),
        tipo_registro=tipo,
        excluir_id=excluir_id,
    )


def test_permite_la_primera_tanda_de_una_orden_de_una_hora():
    _validar(horas=1, inicio=BASE, fin=BASE + timedelta(hours=1))


def test_permite_la_segunda_tanda_cuando_la_orden_tiene_dos_horas():
    primera = _registro(1, BASE, BASE + timedelta(hours=1))

    _validar(
        horas=2,
        inicio=BASE + timedelta(hours=1),
        fin=BASE + timedelta(hours=2),
        registros=[primera],
    )


def test_rechaza_un_horario_cruzado_aunque_queden_horas():
    primera = _registro(1, BASE, BASE + timedelta(hours=1))

    with pytest.raises(ErrorDeValidacion, match="se cruza"):
        _validar(
            horas=4,
            inicio=BASE + timedelta(minutes=30),
            fin=BASE + timedelta(hours=1, minutes=30),
            registros=[primera],
        )


def test_rechaza_cuando_la_orden_ya_agoto_sus_horas():
    primera = _registro(1, BASE, BASE + timedelta(hours=1))

    with pytest.raises(ErrorDeValidacion, match="Solo quedan 0 min"):
        _validar(
            horas=1,
            inicio=BASE + timedelta(hours=1),
            fin=BASE + timedelta(hours=2),
            registros=[primera],
        )


def test_rechaza_una_recepcion_que_excede_el_tiempo_disponible():
    primera = _registro(1, BASE, BASE + timedelta(minutes=30))

    with pytest.raises(ErrorDeValidacion, match="Solo quedan 30 min"):
        _validar(
            horas=1,
            inicio=BASE + timedelta(minutes=30),
            fin=BASE + timedelta(hours=1, minutes=30),
            registros=[primera],
            tipo="recepción de saborizado",
        )


def test_permite_corregir_el_mismo_registro_sin_contarlo_dos_veces():
    primera = _registro(1, BASE, BASE + timedelta(hours=1))

    _validar(
        horas=1,
        inicio=BASE,
        fin=BASE + timedelta(hours=1),
        registros=[primera],
        excluir_id=1,
    )


def test_una_orden_historica_sin_horas_solo_valida_que_no_se_cruce():
    primera = _registro(1, BASE, BASE + timedelta(hours=1))

    _validar(
        horas=None,
        inicio=BASE + timedelta(hours=2),
        fin=BASE + timedelta(hours=3),
        registros=[primera],
    )

    with pytest.raises(ErrorDeValidacion, match="se cruza"):
        _validar(
            horas=None,
            inicio=BASE + timedelta(minutes=30),
            fin=BASE + timedelta(hours=1, minutes=30),
            registros=[primera],
        )


def test_rechaza_una_hora_final_anterior_o_igual():
    with pytest.raises(ErrorDeValidacion, match="posterior"):
        _validar(horas=1, inicio=BASE, fin=BASE)

    with pytest.raises(ErrorDeValidacion, match="posterior"):
        _validar(horas=1, inicio=BASE, fin=BASE - timedelta(minutes=1))


def test_no_permite_reducir_las_horas_por_debajo_de_lo_registrado():
    tanda = _registro(1, BASE, BASE + timedelta(hours=1, minutes=30))

    with pytest.raises(ErrorDeValidacion, match="No puedes dejar"):
        validar_horas_de_orden(
            horas_nuevas=1,
            registros_horno=[tanda],
            registros_saborizado=[],
        )

    # Con dos horas el registro de hora y media si cabe.
    validar_horas_de_orden(
        horas_nuevas=2,
        registros_horno=[tanda],
        registros_saborizado=[],
    )


def test_no_permite_reducir_las_horas_por_una_recepcion_de_saborizado():
    recepcion = _registro(1, BASE, BASE + timedelta(hours=2))

    with pytest.raises(ErrorDeValidacion, match="saborizado"):
        validar_horas_de_orden(
            horas_nuevas=1,
            registros_horno=[],
            registros_saborizado=[recepcion],
        )
