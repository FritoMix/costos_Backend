"""
Pruebas de revocacion de sesiones.

Un token deja de servir cuando cambia la contrasena o se desactiva la
cuenta, sin guardar sesiones en la base: el JWT lleva la version de sesion
del usuario y la API la compara contra la fila actual.
"""

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.errores import CredencialesInvalidas
from app.core.seguridad import crear_token_acceso, hash_password
from app.modules.identidad import service
from app.modules.identidad.dependencias import usuario_actual
from app.modules.identidad.schemas import UsuarioActualizar


def _peticion_con(token: str) -> SimpleNamespace:
    # usuario_actual solo usa request.cookies; no hace falta una Request real.
    return SimpleNamespace(cookies={settings.cookie_nombre: token})


def test_cambiar_password_revoca_los_tokens_anteriores(db, datos_base):
    usuario = datos_base.admin
    usuario.password_hash = hash_password("clave-actual")
    db.flush()

    token_viejo, _ = crear_token_acceso(
        usuario.id, usuario.rol.codigo, usuario.token_version
    )

    service.cambiar_password_propia(db, usuario, "clave-actual", "clave-nueva")

    assert usuario.token_version == 1
    with pytest.raises(CredencialesInvalidas):
        usuario_actual(_peticion_con(token_viejo), db)

    token_nuevo, _ = crear_token_acceso(
        usuario.id, usuario.rol.codigo, usuario.token_version
    )
    assert usuario_actual(_peticion_con(token_nuevo), db).id == usuario.id


def test_desactivar_y_reactivar_la_cuenta_no_resucita_la_sesion_vieja(db, datos_base):
    usuario = datos_base.admin
    token_viejo, _ = crear_token_acceso(
        usuario.id, usuario.rol.codigo, usuario.token_version
    )

    def actualizar(activo: bool) -> None:
        service.actualizar_usuario(
            db,
            usuario.id,
            UsuarioActualizar(
                nombre_completo=usuario.nombre_completo,
                nombre_usuario=usuario.nombre_usuario,
                rol_id=usuario.rol_id,
                activo=activo,
            ),
        )

    actualizar(activo=False)
    actualizar(activo=True)

    assert usuario.token_version == 1
    with pytest.raises(CredencialesInvalidas):
        usuario_actual(_peticion_con(token_viejo), db)
