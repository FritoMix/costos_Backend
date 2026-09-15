"""
Arranque inicial: crear el usuario administrador la primera vez.

Los datos de catalogo (roles, turnos, hornos...) los carga Flyway en
backend/migraciones/V2__datos_iniciales.sql. El administrador no puede ir
ahi porque su contrasena tiene que quedar cifrada con bcrypt, asi que se
crea desde Python al arrancar la API, leyendo ADMIN_USERNAME y
ADMIN_PASSWORD del archivo .env.

Es seguro que esto corra en cada arranque: si el usuario ya existe, no
hace nada y no toca su contrasena.
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
