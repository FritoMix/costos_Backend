"""Aviso de fin de producción, cierre automático y destino del producto (V19)."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.errores import ErrorDeValidacion
from app.modules.notificaciones import service as servicio_notificaciones
from app.modules.notificaciones.models import Notificacion, TipoNotificacion
from app.modules.produccion.models import EstadoOrden
from app.modules.produccion.servicios import ordenes as servicio_ordenes


def _contar(db, orden_id: int, tipo: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Notificacion)
            .where(Notificacion.orden_id == orden_id, Notificacion.tipo == tipo)
        )
        or 0
    )


def _orden_en_produccion(db, datos_base, orden_guardar, guardar_formula, horas=1):
    orden = servicio_ordenes.crear_orden(db, orden_guardar(horas_produccion=horas), datos_base.supervisor)
    guardar_formula(orden)
    return servicio_ordenes.iniciar_orden(db, orden)


def test_al_iniciar_se_programa_el_aviso_de_fin_a_los_jefes(db, datos_base, orden_guardar, guardar_formula):
    orden = _orden_en_produccion(db, datos_base, orden_guardar, guardar_formula)
    # Supervisor y administrador de prueba.
    assert _contar(db, orden.id, TipoNotificacion.PRODUCCION_TERMINADA) == 2


def test_no_cierra_antes_del_margen(db, datos_base, orden_guardar, guardar_formula, monkeypatch):
    orden = _orden_en_produccion(db, datos_base, orden_guardar, guardar_formula)
    # Terminó hace 20 minutos: todavía dentro del margen.
    orden.hora_inicio -= timedelta(hours=1, minutes=20)
    db.flush()
    monkeypatch.setattr(servicio_notificaciones, "_ultima_revision", None)
    assert servicio_notificaciones.revisar_ordenes_vencidas(db) == 0
    db.refresh(orden)
    assert orden.estado == EstadoOrden.EN_PRODUCCION


def test_la_app_cierra_la_orden_vencida_y_avisa(db, datos_base, orden_guardar, guardar_formula, monkeypatch):
    orden = _orden_en_produccion(db, datos_base, orden_guardar, guardar_formula)
    # Terminó hace 31 minutos: ya pasó el margen de 30.
    orden.hora_inicio -= timedelta(hours=1, minutes=31)
    db.flush()
    monkeypatch.setattr(servicio_notificaciones, "_ultima_revision", None)

    assert servicio_notificaciones.revisar_ordenes_vencidas(db) == 1
    db.refresh(orden)
    assert orden.estado == EstadoOrden.FINALIZADA
    assert orden.cerrada_automaticamente is True
    assert _contar(db, orden.id, TipoNotificacion.ORDEN_CERRADA_SOLA) == 2

    # Los avisos de reloj de la orden cerrada se dan por vistos sin sonar.
    pendientes = servicio_notificaciones.pendientes(db, datos_base.supervisor)
    assert not [n for n in pendientes if n.orden_id == orden.id and n.tipo in TipoNotificacion.DEL_RELOJ]
    # Corre como máximo una vez por minuto.
    assert servicio_notificaciones.revisar_ordenes_vencidas(db) == 0


def test_producto_solo_para_su_destino(db, datos_base, orden_guardar):
    datos_base.producto.destino = "nacional"
    db.flush()
    with pytest.raises(ErrorDeValidacion, match="no está marcado para exportación"):
        datos_base.horno.apto_exportacion = True
        db.flush()
        servicio_ordenes.crear_orden(db, orden_guardar(destino="exportacion"), datos_base.supervisor)

    datos_base.producto.destino = "ambos"
    db.flush()
    orden = servicio_ordenes.crear_orden(db, orden_guardar(destino="exportacion"), datos_base.supervisor)
    assert orden.destino == "exportacion"
