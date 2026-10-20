"""
Idempotencia de las notificaciones contra PostgreSQL real.

El indice unico (usuario, orden, tipo) es la garantia de que un reintento
no duplique avisos. El savepoint evita que un choque descarte los avisos
de los demas destinatarios.
"""

from sqlalchemy import func, select

from app.modules.notificaciones import service as servicio_notificaciones
from app.modules.notificaciones.models import Notificacion, TipoNotificacion
from app.modules.produccion.servicios import ordenes as servicio_ordenes


def _contar(db, orden_id: int, tipo: str) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Notificacion)
        .where(Notificacion.orden_id == orden_id, Notificacion.tipo == tipo)
    ) or 0


def test_avisar_dos_veces_no_duplica_ni_pierde(db, datos_base, orden_guardar):
    orden = servicio_ordenes.crear_orden(
        db, orden_guardar(), datos_base.supervisor
    )

    # Un aviso por cada operario activo (horno y saborizado).
    assert _contar(db, orden.id, TipoNotificacion.ORDEN_CREADA) == 2

    servicio_notificaciones.avisar_orden_creada(db, orden)

    assert _contar(db, orden.id, TipoNotificacion.ORDEN_CREADA) == 2

    servicio_ordenes.iniciar_orden(db, orden)

    assert _contar(db, orden.id, TipoNotificacion.PRODUCCION_POR_TERMINAR) == 2

    servicio_notificaciones.programar_aviso_fin_produccion(db, orden)

    assert _contar(db, orden.id, TipoNotificacion.PRODUCCION_POR_TERMINAR) == 2
