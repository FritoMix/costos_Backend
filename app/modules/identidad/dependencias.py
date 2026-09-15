"""
Dependencias de sesion y permisos, reutilizables por todos los modulos.

- usuario_actual: quien esta conectado, leido del token JWT. Gracias a
  esto la app sabe sola quien hace cada registro y nunca hay que
  preguntarselo al operario en un formulario.
- requiere_roles(...): exige ademas que el rol alcance para esa accion.
"""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import CredencialesInvalidas, PermisoDenegado
from app.core.seguridad import leer_token_acceso
from app.db.session import get_db
from app.modules.identidad.models import Usuario


def usuario_actual(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Usuario:
    # El token viaja en una cookie HttpOnly puesta por /auth/login: el
    # navegador la envia sola, el JavaScript nunca la ve.
    token = request.cookies.get(settings.cookie_nombre)
    if not token:
        raise CredencialesInvalidas("Necesitas iniciar sesión.")

    contenido = leer_token_acceso(token)
    usuario_id = contenido.get("sub")
    if usuario_id is None:
        raise CredencialesInvalidas("Tu sesión no es válida. Vuelve a iniciar sesión.")

    usuario = db.get(Usuario, int(usuario_id))
    if usuario is None or not usuario.puede_entrar:
        # La cuenta fue desactivada o eliminada despues de iniciar sesion.
        raise CredencialesInvalidas("Tu cuenta ya no está habilitada.")
    return usuario


UsuarioAutenticado = Annotated[Usuario, Depends(usuario_actual)]


def requiere_roles(*roles_permitidos: str):
    """
    Uso:

        @router.get("", dependencies=[Depends(requiere_roles(RolCodigo.ADMIN))])

    o, si necesitas el usuario dentro de la funcion:

        usuario: Usuario = Depends(requiere_roles(RolCodigo.ADMIN))
    """

    def verificar(usuario: UsuarioAutenticado) -> Usuario:
        if usuario.rol.codigo not in roles_permitidos:
            raise PermisoDenegado("No tienes permiso para esta sección.")
        return usuario

    return verificar
