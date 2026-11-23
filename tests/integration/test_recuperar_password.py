"""Recuperar la contraseña sin correo y línea de los usuarios (V21)."""

import pytest
from sqlalchemy import func, select

from app.core.errores import ErrorDeValidacion
from app.core.seguridad import verificar_password
from app.modules.catalogos.models import Linea
from app.modules.identidad import service
from app.modules.identidad.models import Rol, RolCodigo
from app.modules.identidad.schemas import UsuarioCrear
from app.modules.notificaciones.models import Notificacion, TipoNotificacion


def _avisos(db) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Notificacion)
            .where(Notificacion.tipo == TipoNotificacion.RECUPERAR_PASSWORD)
        )
        or 0
    )


def test_solicitud_avisa_a_admin_y_supervisor_una_vez(db, datos_base):
    service.solicitar_recuperacion(db, "no_existe")
    assert _avisos(db) == 0  # misma respuesta, sin aviso

    service.solicitar_recuperacion(db, datos_base.operario_horno.nombre_usuario.upper())
    assert _avisos(db) == 2  # administrador y supervisor
    service.solicitar_recuperacion(db, datos_base.operario_horno.nombre_usuario)
    assert _avisos(db) == 2  # una sola cada 15 minutos


def test_password_temporal_obliga_a_cambiarla(db, datos_base):
    operario = datos_base.operario_horno
    temporal = service.dar_password_temporal(db, operario, datos_base.supervisor)
    assert len(temporal) == 8 and temporal.isdigit()
    assert operario.debe_cambiar_password is True
    assert verificar_password(temporal, operario.password_hash)

    service.cambiar_password_propia(db, operario, temporal, "Clave-Nueva-2026!")
    assert operario.debe_cambiar_password is False

    with pytest.raises(ErrorDeValidacion, match="Solo el administrador"):
        service.dar_password_temporal(db, datos_base.admin, datos_base.supervisor)


def test_linea_del_usuario(db):
    roles = {r.codigo: r for r in db.scalars(select(Rol)).all()}
    papa = db.scalar(select(Linea).where(Linea.codigo == "papa"))
    platano = db.scalar(select(Linea).where(Linea.codigo == "platano"))

    sin_linea = service.crear_usuario(
        db,
        UsuarioCrear(
            nombre_completo="Operario Nuevo",
            nombre_usuario="operario_nuevo",
            password="Clave-Segura-2026!",
            rol_id=roles[RolCodigo.OPERARIO_HORNO].id,
        ),
    )
    assert sin_linea.linea_id == papa.id  # un cliente viejo sigue funcionando

    with pytest.raises(ErrorDeValidacion, match="no tiene bodega"):
        service.crear_usuario(
            db,
            UsuarioCrear(
                nombre_completo="Bodega Plátano",
                nombre_usuario="bodega_platano",
                password="Clave-Segura-2026!",
                rol_id=roles[RolCodigo.BODEGUERO].id,
                linea_id=platano.id,
            ),
        )

    supervisor = service.crear_usuario(
        db,
        UsuarioCrear(
            nombre_completo="Supervisor Nuevo",
            nombre_usuario="supervisor_nuevo",
            password="Clave-Segura-2026!",
            rol_id=roles[RolCodigo.SUPERVISOR].id,
            linea_id=platano.id,
        ),
    )
    assert supervisor.linea_id is None  # ve todas las líneas
