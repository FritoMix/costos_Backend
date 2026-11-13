"""Fallos provocados, idempotencia y estados frescos bajo bloqueo."""

from datetime import time
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errores import ConflictoDeDatos, ErrorDeValidacion
from app.db.auditoria import EventoOperacion
from app.db.idempotencia import OperacionIdempotente, ejecutar
from app.modules.notificaciones import service as notificaciones
from app.modules.produccion.models import OrdenProduccion, RegistroHorno
from app.modules.produccion.schemas import OrdenSalida, RegistroHornoGuardar
from app.modules.produccion.servicios import formula, formulas_papa, horno, ordenes


def test_creacion_se_revierte_si_falla_la_formula(db, datos_base, orden_guardar, monkeypatch):
    def fallar(*args):
        raise RuntimeError("fallo simulado de fórmula")

    cantidad = db.scalar(select(func.count()).select_from(OrdenProduccion))
    monkeypatch.setattr(formulas_papa, "aplicar_a_orden", fallar)
    with pytest.raises(RuntimeError, match="simulado"):
        ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    assert db.scalar(select(func.count()).select_from(OrdenProduccion)) == cantidad
    assert db.get(type(datos_base.supervisor), datos_base.supervisor.id) is not None


def test_no_confirma_orden_si_falla_el_aviso(db, datos_base, orden_guardar, monkeypatch):
    def fallar(*args):
        raise RuntimeError("fallo simulado de aviso")

    cantidad = db.scalar(select(func.count()).select_from(OrdenProduccion))
    monkeypatch.setattr(notificaciones, "avisar_orden_para_bodega", fallar)
    with pytest.raises(RuntimeError, match="aviso"):
        ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    assert db.scalar(select(func.count()).select_from(OrdenProduccion)) == cantidad


def test_edicion_y_totales_no_quedan_a_medias(db, datos_base, orden_guardar, guardar_formula, monkeypatch):
    orden = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    guardar_formula(orden)
    bultos = orden.referencias[0].bultos_planificados

    def fallar(*args):
        raise RuntimeError("fallo simulado de totales")

    monkeypatch.setattr(formula, "recalcular_totales", fallar)
    with pytest.raises(RuntimeError, match="totales"):
        ordenes.editar_orden(db, orden, orden_guardar(horas_produccion=3))
    db.refresh(orden)
    assert orden.horas_produccion == 2
    assert orden.referencias[0].bultos_planificados == bultos


def test_reintento_recupera_orden_y_rechaza_otro_cuerpo(db, datos_base, orden_guardar):
    datos = orden_guardar()

    def crear():
        return ordenes.crear_orden(db, datos, datos_base.supervisor)

    primera = ejecutar(
        db, datos_base.supervisor.id, "crear_orden", "clave-reintento-123", datos, crear, OrdenSalida
    )
    repetida = ejecutar(
        db, datos_base.supervisor.id, "crear_orden", "clave-reintento-123", datos, crear, OrdenSalida
    )
    assert repetida == primera
    assert db.scalar(select(func.count()).select_from(OrdenProduccion)) == 1
    with pytest.raises(ConflictoDeDatos):
        ejecutar(
            db,
            datos_base.supervisor.id,
            "crear_orden",
            "clave-reintento-123",
            orden_guardar(cantidad_kg=Decimal("101")),
            crear,
            OrdenSalida,
        )


def test_fallo_no_consume_clave_idempotente(db, datos_base, orden_guardar):
    datos = orden_guardar()

    def fallar():
        ordenes.crear_orden(db, datos, datos_base.supervisor)
        raise RuntimeError("se perdió el proceso antes de confirmar")

    with pytest.raises(RuntimeError):
        ejecutar(
            db, datos_base.supervisor.id, "crear_orden", "clave-tras-fallo-123", datos, fallar, OrdenSalida
        )
    assert db.scalar(select(func.count()).select_from(OperacionIdempotente)) == 0
    assert db.scalar(select(func.count()).select_from(OrdenProduccion)) == 0
    respuesta = ejecutar(
        db,
        datos_base.supervisor.id,
        "crear_orden",
        "clave-tras-fallo-123",
        datos,
        lambda: ordenes.crear_orden(db, datos, datos_base.supervisor),
        OrdenSalida,
    )
    assert respuesta["id"]


def test_transiciones_repetidas_conservan_horas_y_auditoria(db, datos_base, orden_guardar, guardar_formula):
    orden = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    guardar_formula(orden)
    ordenes.iniciar_orden(db, orden, datos_base.supervisor)
    inicio = orden.hora_inicio
    ordenes.iniciar_orden(db, orden, datos_base.supervisor)
    assert orden.hora_inicio == inicio
    ordenes.finalizar_orden(db, orden, datos_base.supervisor)
    fin = orden.hora_fin
    ordenes.finalizar_orden(db, orden, datos_base.supervisor)
    assert orden.hora_fin == fin
    with pytest.raises(ErrorDeValidacion):
        ordenes.cancelar_orden(db, orden)
    eventos = db.scalars(select(EventoOperacion).where(EventoOperacion.recurso == "orden")).all()
    assert [e.accion for e in eventos] == ["crear", "iniciar", "finalizar"]
    assert eventos[-1].antes["estado"] == "en_produccion"
    assert eventos[-1].despues["estado"] == "finalizada"


def test_recarga_estado_aunque_el_objeto_del_llamador_este_obsoleto(
    db, datos_base, orden_guardar, guardar_formula
):
    from sqlalchemy import update

    orden = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    guardar_formula(orden)
    ordenes.iniciar_orden(db, orden)
    db.execute(
        update(OrdenProduccion)
        .where(OrdenProduccion.id == orden.id)
        .values(estado="finalizada")
        .execution_options(synchronize_session=False)
    )
    # El llamador aún conserva 'en_produccion'; el lock debe recargar la fila.
    assert orden.estado == "en_produccion"
    datos = RegistroHornoGuardar(
        hora_inicio=time(6),
        hora_fin=time(7),
        referencia_papa_id=datos_base.referencia_papa.id,
        cantidad_bultos=Decimal("5"),
        operarios_seleccion=2,
        operarios_horno=1,
        nivel_aceite_inicial_cm=20,
        nivel_aceite_final_cm=18,
        temperatura_aceite_c=175,
    )
    with pytest.raises(ErrorDeValidacion):
        horno.crear_registro(db, orden, datos, datos_base.operario_horno)
    assert db.scalar(select(func.count()).select_from(RegistroHorno)) == 0


def test_base_rechaza_cantidad_negativa_sin_perder_la_orden(db, datos_base, orden_guardar):
    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    orden = ordenes.crear_orden(db, orden_guardar(), datos_base.supervisor)
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(
            update(OrdenProduccion).where(OrdenProduccion.id == orden.id).values(cantidad_programada=-1)
        )
    db.refresh(orden)
    assert orden.cantidad_programada == Decimal("100.00")
