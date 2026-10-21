"""
Arranque inicial: crear el usuario administrador la primera vez.

Los datos de catalogo (roles, turnos, hornos...) los carga Flyway en
backend/migraciones/V2__datos_iniciales.sql. El administrador no puede ir
ahi porque su contrasena tiene que quedar cifrada con bcrypt, asi que se
crea desde Python al arrancar la API, leyendo ADMIN_USERNAME y
ADMIN_PASSWORD del archivo .env.

Es seguro que esto corra en cada arranque: si el usuario ya existe, no
hace nada y no toca su contrasena, SALVO que se active expresamente
ADMIN_RESET_PASSWORD=true (interruptor de recuperacion, ver mas abajo).
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.seguridad import hash_password
from app.modules.identidad.models import Rol, RolCodigo, Usuario

logger = logging.getLogger("datacontrol")


def crear_admin_inicial(db: Session) -> None:
    ya_existe = db.scalar(
        select(Usuario).where(Usuario.nombre_usuario == settings.admin_username)
    )
    if ya_existe is not None:
        _tal_vez_restablecer_password(db, ya_existe)
        return

    if not settings.admin_password:
        logger.warning(
            "No hay ADMIN_PASSWORD en el .env: no se creó el usuario administrador inicial. "
            "Defínela y reinicia la API."
        )
        return

    rol_admin = db.scalar(select(Rol).where(Rol.codigo == RolCodigo.ADMIN))
    if rol_admin is None:
        logger.error(
            "No existe el rol '%s'. ¿Se aplicaron las migraciones de Flyway?", RolCodigo.ADMIN
        )
        return

    db.add(
        Usuario(
            nombre_completo=settings.admin_nombre_completo,
            nombre_usuario=settings.admin_username,
            password_hash=hash_password(settings.admin_password),
            rol_id=rol_admin.id,
            activo=True,
        )
    )
    db.commit()
    logger.info(
        'Usuario administrador "%s" creado. Cambia su contraseña desde la pantalla de Usuarios.',
        settings.admin_username,
    )


def _tal_vez_restablecer_password(db: Session, usuario: Usuario) -> None:
    """
    Restablece la contrasena del administrador SOLO si se activo el
    interruptor de recuperacion (ADMIN_RESET_PASSWORD=true).

    Sirve para recuperar el acceso a un despliegue donde el admin ya existia
    con una contrasena distinta a la de ADMIN_PASSWORD. Es un interruptor de
    un solo uso: despues de entrar, se quita la variable para que la API no
    vuelva a pisar la contrasena en cada arranque.
    """
    if not settings.admin_reset_password:
        return

    if not settings.admin_password:
        logger.warning(
            "ADMIN_RESET_PASSWORD=true pero no hay ADMIN_PASSWORD: "
            "no se pudo restablecer la contraseña del administrador."
        )
        return

    cambios: list[str] = []
    usuario.password_hash = hash_password(settings.admin_password)
    usuario.token_version += 1
    cambios.append("contraseña")
    if not usuario.activo:
        usuario.activo = True
        cambios.append("activo=True")
    if usuario.eliminado:
        usuario.eliminado = False
        usuario.eliminado_por_id = None
        usuario.fecha_eliminacion = None
        cambios.append("reactivado")

    db.commit()
    logger.warning(
        'Contraseña del administrador "%s" restablecida por ADMIN_RESET_PASSWORD (%s). '
        "Quita esa variable del entorno para no repetirlo en el próximo arranque.",
        settings.admin_username,
        ", ".join(cambios),
    )
