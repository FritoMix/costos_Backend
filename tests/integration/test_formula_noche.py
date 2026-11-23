"""Fórmula de la noche por horno (V20)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app.core.errores import ErrorDeValidacion
from app.modules.notificaciones import service as servicio_notificaciones
from app.modules.notificaciones.models import Notificacion, TipoNotificacion
from app.modules.produccion.schemas import FormulaNocheGuardar, FormulaReferenciaGuardar
from app.modules.produccion.servicios import formula_noche as servicio_noche
from app.modules.produccion.servicios import ordenes as servicio_ordenes


def _dejar(db, datos_base, bultos=10):
    return servicio_noche.guardar(
        db,
        datos_base.horno.id,
        FormulaNocheGuardar(
            referencias=[
                FormulaReferenciaGuardar(
                    referencia_papa_id=datos_base.referencia_papa.id, bultos_por_tanda=bultos
                )
            ]
        ),
        datos_base.bodeguero,
    )


def _contar(db, orden_id, tipo):
    return (
        db.scalar(
            select(func.count())
            .select_from(Notificacion)
            .where(Notificacion.orden_id == orden_id, Notificacion.tipo == tipo)
        )
        or 0
    )


def test_bodega_deja_y_borra_la_formula_de_la_noche(db, datos_base):
    salida = _dejar(db, datos_base)
    assert salida.total_bultos_por_tanda == 10
    assert salida.actualizado_por == datos_base.bodeguero.nombre_completo
    listado = {f.horno_id: f for f in servicio_noche.listar(db)}
    assert listado[datos_base.horno.id].filas[0].bultos_por_tanda == 10

    with pytest.raises(ErrorDeValidacion, match="admite máximo"):
        _dejar(db, datos_base, bultos=999)

    vacia = servicio_noche.guardar(db, datos_base.horno.id, FormulaNocheGuardar(), datos_base.bodeguero)
    assert vacia.filas == []


def test_orden_sin_formula_toma_la_de_la_noche_y_bodega_la_confirma(db, datos_base, orden_guardar):
    _dejar(db, datos_base)
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)

    assert orden.formula_automatica is True
    assert [f.bultos_por_tanda for f in orden.referencias] == [10]
    # Horno y el supervisor: fórmula lista. Bodega: confirmar. Resto: nueva orden.
    assert _contar(db, orden.id, TipoNotificacion.FORMULA_LISTA) == 2
    assert _contar(db, orden.id, TipoNotificacion.ORDEN_PARA_BODEGA) == 1
    assert _contar(db, orden.id, TipoNotificacion.ORDEN_CREADA) == 2

    # Ya se puede producir de noche.
    orden = servicio_ordenes.iniciar_orden(db, orden)
    orden = servicio_noche.confirmar(db, orden, datos_base.bodeguero)
    assert orden.formula_automatica is False
    assert "confirmada" in orden.formula_notas


def test_sin_formula_de_la_noche_sigue_esperando_a_bodega(db, datos_base, orden_guardar):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    assert orden.formula_automatica is False
    assert not orden.referencias
    with pytest.raises(ErrorDeValidacion, match="no tiene una fórmula activa"):
        servicio_ordenes.iniciar_orden(db, orden)


def test_al_iniciar_toma_la_formula_de_la_noche(db, datos_base, orden_guardar):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    _dejar(db, datos_base)
    orden = servicio_ordenes.iniciar_orden(db, orden)
    assert orden.formula_automatica is True
    assert orden.referencias


def test_recordatorio_a_bodega_una_vez_al_dia(db, datos_base):
    zona = ZoneInfo("America/Bogota")
    antes = datetime(2026, 11, 23, 16, 30, tzinfo=zona)
    despues = datetime(2026, 11, 23, 16, 50, tzinfo=zona)
    assert servicio_notificaciones.recordar_formula_noche(db, antes) == 0
    assert servicio_notificaciones.recordar_formula_noche(db, despues) >= 1
    assert servicio_notificaciones.recordar_formula_noche(db, despues) == 0
