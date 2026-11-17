"""Conservar el límite transaccional y los efectos al extraer servicios de órdenes."""

from datetime import date

import pytest
from sqlalchemy import func, select

from app.db.auditoria import EventoOperacion
from app.modules.produccion.models import OrdenProduccion
from app.modules.produccion.schemas import FormulaPapaGuardar, FormulaPapaReferenciaGuardar
from app.modules.produccion.servicios import formulas_papa, ordenes


def _activar_plantilla(db, datos_base):
    creada = formulas_papa.crear(
        db,
        FormulaPapaGuardar(
            nombre="Plantilla de límite transaccional",
            producto_id=datos_base.producto.id,
            referencias=[FormulaPapaReferenciaGuardar(
                referencia_papa_id=datos_base.referencia_papa.id, bultos_por_tanda=10,
            )],
        ),
        datos_base.bodeguero,
    )
    formulas_papa.activar(db, formulas_papa.obtener(db, creada.id))
    return creada.id


@pytest.mark.parametrize("accion", ["crear", "editar", "iniciar", "finalizar", "cancelar", "eliminar"])
def test_una_confirmacion_por_operacion_incluso_con_servicios_anidados(
    db, datos_base, orden_guardar, guardar_formula, monkeypatch, accion,
):
    orden = None
    plantilla_id = None
    if accion != "crear":
        orden = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    if accion in {"crear", "iniciar"}:
        # Al crear o iniciar se copia realmente una fórmula dentro de la transacción.
        plantilla_id = _activar_plantilla(db, datos_base)
    else:
        guardar_formula(orden)
        if accion in {"finalizar", "cancelar", "eliminar"}:
            ordenes.iniciar_orden(db, orden, datos_base.admin)

    eventos_antes = db.scalar(select(func.count()).select_from(EventoOperacion))
    confirmar = db.commit
    confirmaciones = []

    def contar_confirmacion():
        confirmaciones.append(True)
        return confirmar()

    monkeypatch.setattr(db, "commit", contar_confirmacion)
    if accion == "crear":
        orden = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    elif accion == "editar":
        ordenes.editar_orden(db, orden, orden_guardar(horas_produccion=3), datos_base.admin)
        assert orden.referencias[0].bultos_planificados == 30
    elif accion == "iniciar":
        ordenes.iniciar_orden(db, orden, datos_base.admin)
    elif accion == "finalizar":
        ordenes.finalizar_orden(db, orden, datos_base.admin)
    elif accion == "cancelar":
        ordenes.cancelar_orden(db, orden, datos_base.admin)
    else:
        ordenes.eliminar_orden(db, orden, datos_base.admin)
        assert orden.eliminado is True

    assert len(confirmaciones) == 1
    eventos_despues = db.scalar(select(func.count()).select_from(EventoOperacion))
    assert eventos_despues - eventos_antes == (2 if accion == "iniciar" else 1)
    if plantilla_id is not None:
        assert orden.formula_papa_id == plantilla_id
        assert len(orden.referencias) == 1


def test_fallo_revierte_consecutivo_orden_y_auditoria_y_permite_reintento(
    db, datos_base, orden_guardar, monkeypatch,
):
    monkeypatch.setattr(ordenes, "hoy_local", lambda: date(2026, 1, 2))
    confirmar = db.commit
    confirmaciones = []

    def contar_confirmacion():
        confirmaciones.append(True)
        return confirmar()

    def fallar(*args):
        raise RuntimeError("aviso interrumpido tras asignar consecutivo")

    monkeypatch.setattr(db, "commit", contar_confirmacion)
    with monkeypatch.context() as contexto:
        contexto.setattr(ordenes.notificaciones, "avisar_orden_para_bodega", fallar)
        with pytest.raises(RuntimeError, match="aviso interrumpido"):
            ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    assert confirmaciones == []
    assert db.scalar(select(func.count()).select_from(OrdenProduccion)) == 0
    assert db.scalar(select(func.count()).select_from(EventoOperacion)) == 0

    nueva = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    assert nueva.numero_orden == "OP-20260102-0001"
    assert len(confirmaciones) == 1
