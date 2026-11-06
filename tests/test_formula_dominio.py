"""
Pruebas unitarias del dominio de la fórmula de producción.

No tocan base de datos: comprueban las fórmulas puras que comparten Bodega,
Horno y la proyección, además de los límites de tandas.
"""

from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.errores import ErrorDeValidacion
from app.modules.produccion.dominio.calculos import (
    ReferenciaMezcla,
    calcular_porcentaje_desde_bultos,
    kg_fritos_por_bulto,
    sugerir_mezcla_por_tanda,
)
from app.modules.produccion.dominio.limites import (
    validar_conteo_tandas,
    validar_duracion_tanda,
)
from app.modules.produccion.servicios.formula import (
    _capacidad_maxima,
    _filas_desde_orden,
)

REFERENCIA = ReferenciaMezcla(
    referencia_id=1,
    peso_promedio_bulto_kg=Decimal("50"),
    rendimiento_fritura_pct=Decimal("25"),
    porcentaje_produccion_pct=Decimal("100"),
)


def test_porcentaje_desde_bultos():
    assert calcular_porcentaje_desde_bultos(30, 50) == Decimal("60.0000")
    assert calcular_porcentaje_desde_bultos(20, 50) == Decimal("40.0000")
    assert calcular_porcentaje_desde_bultos(1, 3) == Decimal("33.3333")


@pytest.mark.parametrize(
    ("bultos", "total", "mensaje"),
    [
        (-1, 10, "no pueden ser negativos"),
        (10, 0, "mayor a cero"),
        (10, -5, "mayor a cero"),
    ],
)
def test_porcentaje_desde_bultos_rechaza_datos_invalidos(bultos, total, mensaje):
    with pytest.raises(ErrorDeValidacion, match=mensaje):
        calcular_porcentaje_desde_bultos(bultos, total)


def test_kg_fritos_por_bulto():
    assert kg_fritos_por_bulto(Decimal("50"), Decimal("25")) == Decimal("12.5000")
    assert kg_fritos_por_bulto(Decimal("48.5"), Decimal("30")) == Decimal("14.5500")


@pytest.mark.parametrize(
    ("peso", "rendimiento", "mensaje"),
    [
        (0, 25, "peso promedio"),
        (50, 0, "rendimiento"),
        (50, 101, "rendimiento"),
    ],
)
def test_kg_fritos_por_bulto_rechaza_datos_invalidos(peso, rendimiento, mensaje):
    with pytest.raises(ErrorDeValidacion, match=mensaje):
        kg_fritos_por_bulto(peso, rendimiento)


def test_sugerencia_de_una_referencia_respeta_horas_y_cantidad():
    sugerencia = sugerir_mezcla_por_tanda(
        cantidad_programada=Decimal("100"),
        horas_produccion=2,
        capacidad_bultos_hora=50,
        referencias=[REFERENCIA],
    )

    # 100 kg / 12,5 kg por bulto = 8 bultos; 4 por cada una de las 2 tandas.
    assert [(fila.referencia_id, fila.bultos_por_tanda) for fila in sugerencia] == [(1, 4)]


def test_sugerencia_reparte_por_participacion_global():
    referencias = [
        ReferenciaMezcla(
            referencia_id=1,
            peso_promedio_bulto_kg=Decimal("50"),
            rendimiento_fritura_pct=Decimal("25"),
            porcentaje_produccion_pct=Decimal("60"),
        ),
        ReferenciaMezcla(
            referencia_id=2,
            peso_promedio_bulto_kg=Decimal("40"),
            rendimiento_fritura_pct=Decimal("30"),
            porcentaje_produccion_pct=Decimal("40"),
        ),
    ]

    sugerencia = sugerir_mezcla_por_tanda(
        cantidad_programada=Decimal("100"),
        horas_produccion=2,
        capacidad_bultos_hora=50,
        referencias=referencias,
    )

    # 8,13 bultos → 9 totales → 5 por tanda → 60/40 = 3 y 2.
    assert {fila.referencia_id: fila.bultos_por_tanda for fila in sugerencia} == {
        1: 3,
        2: 2,
    }


def test_sugerencia_usa_partes_iguales_si_la_global_no_suma_cien():
    referencias = [
        ReferenciaMezcla(
            referencia_id=1,
            peso_promedio_bulto_kg=Decimal("50"),
            rendimiento_fritura_pct=Decimal("25"),
            porcentaje_produccion_pct=Decimal("80"),
        ),
        ReferenciaMezcla(
            referencia_id=2,
            peso_promedio_bulto_kg=Decimal("50"),
            rendimiento_fritura_pct=Decimal("25"),
            porcentaje_produccion_pct=Decimal("80"),
        ),
    ]

    sugerencia = sugerir_mezcla_por_tanda(
        cantidad_programada=Decimal("100"),
        horas_produccion=2,
        capacidad_bultos_hora=50,
        referencias=referencias,
    )

    assert {fila.referencia_id: fila.bultos_por_tanda for fila in sugerencia} == {
        1: 2,
        2: 2,
    }


def test_sugerencia_nunca_supera_la_capacidad_del_horno():
    sugerencia = sugerir_mezcla_por_tanda(
        cantidad_programada=Decimal("100000"),
        horas_produccion=8,
        capacidad_bultos_hora=50,
        referencias=[REFERENCIA],
    )

    # Capacidad total 400 bultos; por tanda no más de 50.
    assert sugerencia[0].bultos_por_tanda == 50


@pytest.mark.parametrize(
    ("cambios", "mensaje"),
    [
        ({"horas_produccion": 0}, "al menos 1 hora"),
        ({"cantidad_programada": 0}, "mayor a cero"),
        ({"capacidad_bultos_hora": Decimal("50.5")}, "entero"),
        ({"referencias": []}, "No hay referencias"),
    ],
)
def test_sugerencia_rechaza_datos_invalidos(cambios, mensaje):
    datos = {
        "cantidad_programada": Decimal("100"),
        "horas_produccion": 2,
        "capacidad_bultos_hora": 50,
        "referencias": [REFERENCIA],
    }
    datos.update(cambios)

    with pytest.raises(ErrorDeValidacion, match=mensaje):
        sugerir_mezcla_por_tanda(**datos)


def _registro(identificador: int, inicio: datetime, fin: datetime):
    return SimpleNamespace(id=identificador, hora_inicio=inicio, hora_fin=fin)


def test_una_orden_de_n_horas_admite_maximo_n_tandas():
    primera = _registro(1, datetime(2026, 10, 29, 6), datetime(2026, 10, 29, 7))
    segunda = _registro(2, datetime(2026, 10, 29, 7), datetime(2026, 10, 29, 8))

    # Antes de crear la segunda tanda solo hay una activa: hay cupo.
    validar_conteo_tandas(horas_produccion=2, registros=[primera])

    with pytest.raises(ErrorDeValidacion, match="ya registró 2 tandas"):
        validar_conteo_tandas(horas_produccion=2, registros=[primera, segunda])


def test_corregir_una_tanda_no_cuenta_dos_veces():
    registros = [
        _registro(1, datetime(2026, 10, 29, 6), datetime(2026, 10, 29, 7)),
        _registro(2, datetime(2026, 10, 29, 7), datetime(2026, 10, 29, 8)),
    ]

    # Editando la tanda 2, solo queda activa la 1.
    validar_conteo_tandas(
        horas_produccion=2, registros=registros, excluir_id=2
    )


def test_al_editar_horas_se_permite_igual_al_numero_de_tandas():
    registros = [
        _registro(1, datetime(2026, 10, 29, 6), datetime(2026, 10, 29, 7)),
        _registro(2, datetime(2026, 10, 29, 7), datetime(2026, 10, 29, 8)),
    ]

    validar_conteo_tandas(
        horas_produccion=2, registros=registros, al_editar_horas=True
    )

    with pytest.raises(ErrorDeValidacion, match="No puedes reducir"):
        validar_conteo_tandas(
            horas_produccion=1, registros=registros, al_editar_horas=True
        )


def test_una_tanda_no_puede_durar_mas_de_sesenta_minutos():
    validar_duracion_tanda(
        inicio=datetime(2026, 10, 29, 6), fin=datetime(2026, 10, 29, 7)
    )

    with pytest.raises(ErrorDeValidacion, match="más de 60 minutos"):
        validar_duracion_tanda(
            inicio=datetime(2026, 10, 29, 6), fin=datetime(2026, 10, 29, 7, 1)
        )


def test_capacidad_maxima_es_capacidad_por_horas():
    horno = SimpleNamespace(capacidad_bultos_hora=Decimal("50.00"))

    assert _capacidad_maxima(horno, 3) == 150
    assert _capacidad_maxima(horno, None) is None

    horno.capacidad_bultos_hora = None
    assert _capacidad_maxima(horno, 3) is None


def test_filas_desde_orden_usan_los_valores_congelados():
    fila = SimpleNamespace(
        referencia_papa_id=7,
        referencia_papa=SimpleNamespace(nombre="Papa pareja", tipo="Papa pareja"),
        bultos_por_tanda=10,
        bultos_planificados=20,
        porcentaje_produccion_pct=Decimal("100.0000"),
        peso_promedio_bulto_kg=Decimal("48.00"),
        rendimiento_fritura_pct=Decimal("25.0000"),
        kg_crudos_por_tanda=Decimal("480.00"),
        kg_fritos_por_tanda=Decimal("120.00"),
        kg_crudos_planificados=Decimal("960.00"),
        kg_fritos_estimados=Decimal("240.00"),
    )
    orden = SimpleNamespace(referencias=[fila])

    salida = _filas_desde_orden(orden, {7: Decimal("4")})

    assert len(salida) == 1
    assert salida[0].nombre == "Papa pareja"
    assert salida[0].peso_promedio_bulto_kg == Decimal("48.00")
    assert salida[0].bultos_producidos == Decimal("4")
    assert salida[0].bultos_restantes == Decimal("16")
