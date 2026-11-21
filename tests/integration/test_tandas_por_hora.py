"""
Una tanda y una recepcion por hora programada, con la hora puesta por la
app, y paradas dentro de la hora (V17).
"""

from datetime import time, timedelta
from decimal import Decimal

import pytest

from app.core.errores import ErrorDeValidacion
from app.modules.produccion.schemas import RecepcionGuardar, RegistroHornoGuardar
from app.modules.produccion.servicios import horno as servicio_horno
from app.modules.produccion.servicios import ordenes as servicio_ordenes
from app.modules.produccion.servicios import saborizado as servicio_saborizado


def _tanda(datos_base, **cambios) -> RegistroHornoGuardar:
    base = dict(
        referencia_papa_id=datos_base.referencia_papa.id,
        cantidad_bultos=Decimal("10"),
        operarios_seleccion=2,
        operarios_horno=1,
        nivel_aceite_inicial_cm=Decimal("20"),
        nivel_aceite_final_cm=Decimal("18"),
        temperatura_aceite_c=Decimal("175"),
    )
    base.update(cambios)
    return RegistroHornoGuardar(**base)


def _recepcion(datos_base, **cambios) -> RecepcionGuardar:
    base = dict(
        sabor_id=datos_base.sabor.id,
        cantidad_sabor_kg=Decimal("1.00"),
        pesos_canastillas=[Decimal("6.00"), Decimal("5.50")],
    )
    base.update(cambios)
    return RecepcionGuardar(**base)


def _orden_iniciada(db, datos_base, orden_guardar, guardar_formula, horas: int, hace_horas: int):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(horas_produccion=horas), datos_base.supervisor)
    guardar_formula(orden)
    servicio_ordenes.iniciar_orden(db, orden)
    orden.hora_inicio -= timedelta(hours=hace_horas)
    db.flush()
    return orden


def test_la_app_pone_la_hora_de_cada_tanda(db, datos_base, orden_guardar, guardar_formula):
    orden = _orden_iniciada(db, datos_base, orden_guardar, guardar_formula, horas=2, hace_horas=2)

    # Aunque el operario mande otra hora, la tanda toma la de su numero.
    primera = servicio_horno.crear_registro(
        db, orden, _tanda(datos_base, hora_inicio=time(3, 0), hora_fin=time(3, 20)), datos_base.operario_horno
    )
    segunda = servicio_horno.crear_registro(db, orden, _tanda(datos_base), datos_base.operario_horno)

    assert (primera.numero_tanda, segunda.numero_tanda) == (1, 2)
    assert primera.hora_inicio == orden.hora_inicio
    assert primera.hora_fin == orden.hora_inicio + timedelta(hours=1)
    assert segunda.hora_inicio == orden.hora_inicio + timedelta(hours=1)

    # Corregir no cambia la hora de la tanda.
    corregida = servicio_horno.editar_registro(
        db, primera, _tanda(datos_base, cantidad_bultos=Decimal("9")), datos_base.operario_horno
    )
    assert corregida.numero_tanda == 1
    assert corregida.hora_inicio == orden.hora_inicio


def test_no_se_registra_una_hora_que_no_ha_empezado(db, datos_base, orden_guardar, guardar_formula):
    orden = _orden_iniciada(db, datos_base, orden_guardar, guardar_formula, horas=2, hace_horas=0)
    servicio_horno.crear_registro(db, orden, _tanda(datos_base), datos_base.operario_horno)

    with pytest.raises(ErrorDeValidacion, match="se registra cuando empiece esa hora"):
        servicio_horno.crear_registro(db, orden, _tanda(datos_base), datos_base.operario_horno)


def test_una_hora_registrada_no_se_repite(db, datos_base, orden_guardar, guardar_formula):
    orden = _orden_iniciada(db, datos_base, orden_guardar, guardar_formula, horas=2, hace_horas=2)
    servicio_horno.crear_registro(db, orden, _tanda(datos_base, numero_tanda=1), datos_base.operario_horno)

    with pytest.raises(ErrorDeValidacion, match="ya está registrada: corrígela"):
        servicio_horno.crear_registro(
            db, orden, _tanda(datos_base, numero_tanda=1), datos_base.operario_horno
        )
    with pytest.raises(ErrorDeValidacion, match="no existe la tanda 3"):
        servicio_horno.crear_registro(
            db, orden, _tanda(datos_base, numero_tanda=3), datos_base.operario_horno
        )


def test_la_parada_exige_causa_y_queda_como_alerta(db, datos_base, orden_guardar, guardar_formula):
    orden = _orden_iniciada(db, datos_base, orden_guardar, guardar_formula, horas=2, hace_horas=2)

    with pytest.raises(ErrorDeValidacion, match="indica la causa"):
        servicio_horno.crear_registro(
            db, orden, _tanda(datos_base, minutos_parada=20), datos_base.operario_horno
        )
    with pytest.raises(ErrorDeValidacion, match="Escribe cuál fue la causa"):
        servicio_horno.crear_registro(
            db, orden, _tanda(datos_base, minutos_parada=20, causa_parada="otro"), datos_base.operario_horno
        )

    con_parada = servicio_horno.crear_registro(
        db, orden, _tanda(datos_base, minutos_parada=20, causa_parada="falta_papa"), datos_base.operario_horno
    )
    assert con_parada.minutos_parada == 20
    assert "Parada 20 min · Falta de papa" in con_parada.alertas

    # Pocos bultos sin parada anotada: alerta para el supervisor.
    sin_parada = servicio_horno.crear_registro(db, orden, _tanda(datos_base), datos_base.operario_horno)
    assert any("no se anotó parada" in alerta for alerta in sin_parada.alertas)


def test_saborizado_tambien_va_por_hora(db, datos_base, orden_guardar, guardar_formula):
    orden = _orden_iniciada(db, datos_base, orden_guardar, guardar_formula, horas=1, hace_horas=1)
    recepcion = servicio_saborizado.crear_recepcion(
        db, orden, _recepcion(datos_base), datos_base.operario_saborizado
    )
    assert recepcion.numero_tanda == 1
    assert recepcion.hora_inicio == orden.hora_inicio

    with pytest.raises(ErrorDeValidacion, match="ya está registrada su recepción"):
        servicio_saborizado.crear_recepcion(db, orden, _recepcion(datos_base), datos_base.operario_saborizado)
