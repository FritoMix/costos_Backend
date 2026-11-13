"""
Rutas HTTP del modulo Identidad:
  /api/v1/auth/...      inicio de sesion y datos del usuario conectado
  /api/v1/usuarios/...  administracion de usuarios (solo Administrador)
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.limite import obtener_ip_cliente
from app.core.seguridad import borrar_cookie_sesion, poner_cookie_sesion
from app.db.session import get_db
from app.modules.identidad import service, sesiones
from app.modules.identidad.dependencias import UsuarioAutenticado, requiere_roles
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.identidad.schemas import (
    CambiarPasswordPeticion,
    LoginPeticion,
    RolSalida,
    SesionSalida,
    UsuarioActualizar,
    UsuarioCrear,
    UsuarioSalida,
)

BD = Annotated[Session, Depends(get_db)]
SoloAdmin = Annotated[Usuario, Depends(requiere_roles(RolCodigo.ADMIN))]

router_auth = APIRouter(prefix="/auth", tags=["Autenticación"])
router_usuarios = APIRouter(prefix="/usuarios", tags=["Usuarios"])


# --- Autenticacion ---------------------------------------------------------


@router_auth.post("/login", response_model=SesionSalida)
def iniciar_sesion(datos: LoginPeticion, db: BD, response: Response, request: Request) -> SesionSalida:
    usuario = sesiones.autenticar_protegido(
        db, datos.nombre_usuario.strip().lower(), datos.password, obtener_ip_cliente(request)
    )
    token, segundos = sesiones.emitir_sesion(db, usuario)
    # El token se entrega SOLO como cookie HttpOnly: no vuelve en el cuerpo,
    # asi que el JavaScript del navegador nunca llega a verlo.
    poner_cookie_sesion(response, token, segundos)
    return SesionSalida(
        expira_en_segundos=segundos,
        inactividad_segundos=settings.session_idle_minutes * 60,
        usuario=UsuarioSalida.model_validate(usuario),
    )


@router_auth.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def cerrar_sesion(response: Response, request: Request, db: BD) -> None:
    """Borra la cookie de sesion. No exige estar autenticado: si ya no hay
    sesion valida, igual limpia cualquier cookie residual."""
    sesiones.revocar_sesion(db, request.cookies.get(settings.cookie_nombre))
    borrar_cookie_sesion(response)


@router_auth.get("/yo", response_model=UsuarioSalida)
def usuario_conectado(usuario: UsuarioAutenticado, response: Response, request: Request, db: BD) -> Usuario:
    """Con quien esta trabajando la app ahora mismo (lo usa el frontend al abrir)."""
    sesiones.registrar_actividad(db, request.cookies[settings.cookie_nombre])
    response.headers["X-Sesion-Inactividad-Segundos"] = str(settings.session_idle_minutes * 60)
    return usuario


@router_auth.post("/actividad", status_code=status.HTTP_204_NO_CONTENT)
def actividad(request: Request, db: BD, _: UsuarioAutenticado) -> None:
    sesiones.registrar_actividad(db, request.cookies[settings.cookie_nombre])


@router_auth.post("/cambiar-password", status_code=status.HTTP_204_NO_CONTENT)
def cambiar_password(
    datos: CambiarPasswordPeticion,
    usuario: UsuarioAutenticado,
    db: BD,
    response: Response,
) -> None:
    service.cambiar_password_propia(db, usuario, datos.password_actual, datos.password_nueva)
    # La contrasena cambio y la version subio: se emite un token nuevo para
    # que esta sesion siga abierta, mientras las demas quedan revocadas.
    token, segundos = sesiones.emitir_sesion(db, usuario)
    poner_cookie_sesion(response, token, segundos)


# --- Usuarios (solo Administrador) ----------------------------------------


@router_usuarios.get("", response_model=list[UsuarioSalida])
def listar(db: BD, _: SoloAdmin) -> list[Usuario]:
    return service.listar_usuarios(db)


@router_usuarios.get("/roles", response_model=list[RolSalida])
def listar_roles(db: BD, _: SoloAdmin) -> list:
    return service.listar_roles(db)


@router_usuarios.get("/supervisores", response_model=list[UsuarioSalida])
def listar_supervisores(db: BD, _: SoloAdmin) -> list[Usuario]:
    """Para el filtro por supervisor de la pantalla de Análisis."""
    return service.listar_supervisores(db)


@router_usuarios.post("", response_model=UsuarioSalida, status_code=status.HTTP_201_CREATED)
def crear(datos: UsuarioCrear, db: BD, _: SoloAdmin) -> Usuario:
    return service.crear_usuario(db, datos)


@router_usuarios.get("/{usuario_id}", response_model=UsuarioSalida)
def detalle(usuario_id: int, db: BD, _: SoloAdmin) -> Usuario:
    return service.obtener_usuario(db, usuario_id)


@router_usuarios.put("/{usuario_id}", response_model=UsuarioSalida)
def actualizar(usuario_id: int, datos: UsuarioActualizar, db: BD, _: SoloAdmin) -> Usuario:
    return service.actualizar_usuario(db, usuario_id, datos)


@router_usuarios.delete("/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar(usuario_id: int, db: BD, admin: SoloAdmin) -> None:
    service.eliminar_usuario(db, usuario_id, admin)
