"""
Rutas HTTP del modulo Identidad:
  /api/v1/auth/...      inicio de sesion y datos del usuario conectado
  /api/v1/usuarios/...  administracion de usuarios (solo Administrador)
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.limite import obtener_ip_cliente
from app.core.seguridad import borrar_cookie_sesion, poner_cookie_sesion
from app.db.session import get_db
from app.modules.identidad import correo, recuperacion, service, sesiones
from app.modules.identidad.dependencias import UsuarioAutenticado, requiere_roles
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.identidad.schemas import (
    CambiarPasswordPeticion,
    CodigosGeneradosSalida,
    EnvioCorreoGuardar,
    EnvioCorreoSalida,
    EstadoCodigosSalida,
    EstadoCorreoSalida,
    GenerarCodigosPeticion,
    LoginPeticion,
    OpcionesRecuperacionSalida,
    PasswordTemporalSalida,
    PruebaCorreoPeticion,
    QuitarCorreoPeticion,
    RecuperarConCodigoPeticion,
    RecuperarConCorreoPeticion,
    RegistrarCorreoPeticion,
    RolSalida,
    SesionSalida,
    SolicitarCodigoCorreoPeticion,
    SolicitudRecuperacion,
    UsuarioActualizar,
    UsuarioCrear,
    UsuarioSalida,
    VerificarCorreoPeticion,
)

BD = Annotated[Session, Depends(get_db)]
SoloAdmin = Annotated[Usuario, Depends(requiere_roles(RolCodigo.ADMIN))]
AdminOSupervisor = Annotated[Usuario, Depends(requiere_roles(RolCodigo.ADMIN, RolCodigo.SUPERVISOR))]

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


@router_auth.post("/olvide-password", status_code=status.HTTP_202_ACCEPTED)
def olvide_password(datos: SolicitudRecuperacion, db: BD) -> dict:
    """Pide una contraseña nueva: avisa al administrador y a los supervisores (V21).
    La respuesta es siempre la misma, exista o no el usuario."""
    service.solicitar_recuperacion(db, datos.nombre_usuario)
    return {
        "mensaje": "Solicitud recibida. Si tu cuenta está habilitada, un responsable de planta "
        "puede darte una contraseña temporal."
    }


@router_auth.get("/codigos-recuperacion", response_model=EstadoCodigosSalida)
def estado_codigos(usuario: SoloAdmin, db: BD) -> dict:
    """Cuantos codigos de recuperacion le quedan al administrador (V25)."""
    return recuperacion.estado(db, usuario)


@router_auth.post("/codigos-recuperacion", response_model=CodigosGeneradosSalida)
def generar_codigos(datos: GenerarCodigosPeticion, usuario: SoloAdmin, db: BD) -> CodigosGeneradosSalida:
    """Reemplaza los codigos anteriores por 8 nuevos. Exige la contraseña actual."""
    return CodigosGeneradosSalida(codigos=recuperacion.generar(db, usuario, datos.password_actual))


@router_auth.post("/recuperar-con-codigo")
def recuperar_con_codigo(datos: RecuperarConCodigoPeticion, db: BD, request: Request) -> dict:
    """Sin sesion: usuario + codigo de recuperacion + contraseña nueva."""
    quedan = recuperacion.recuperar(
        db, datos.nombre_usuario, datos.codigo, datos.password_nueva, obtener_ip_cliente(request)
    )
    return {"mensaje": "Listo. Ya puedes entrar con tu contraseña nueva.", "codigos_restantes": quedan}


# --- Correo de recuperacion (V29) ------------------------------------------


@router_auth.get("/recuperacion/opciones", response_model=OpcionesRecuperacionSalida)
def opciones_recuperacion(db: BD) -> dict:
    """Sin sesion: si la app puede enviar codigos por correo (no dice nada de ningun usuario)."""
    return {"correo": correo.envio_configurado(db)}


@router_auth.post("/recuperar-por-correo/solicitar", status_code=status.HTTP_202_ACCEPTED)
def solicitar_codigo_por_correo(
    datos: SolicitarCodigoCorreoPeticion, db: BD, tareas: BackgroundTasks
) -> dict:
    """Sin sesion. Responde siempre lo mismo; el correo sale en segundo plano."""
    tareas.add_task(correo.enviar_en_segundo_plano, correo.solicitar_recuperacion(db, datos.nombre_usuario))
    return {
        "mensaje": "Si tu usuario tiene un correo verificado, se solicitará un código de 6 dígitos. "
        "Revisa tu bandeja y la carpeta de spam."
    }


@router_auth.post("/recuperar-por-correo")
def recuperar_por_correo(
    datos: RecuperarConCorreoPeticion, db: BD, request: Request, tareas: BackgroundTasks
) -> dict:
    """Sin sesion: usuario + codigo del correo + contraseña nueva."""
    aviso = correo.recuperar(
        db, datos.nombre_usuario, datos.codigo, datos.password_nueva, obtener_ip_cliente(request)
    )
    tareas.add_task(correo.enviar_en_segundo_plano, aviso)
    return {"mensaje": "Listo. Ya puedes entrar con tu contraseña nueva."}


@router_auth.get("/correo", response_model=EstadoCorreoSalida)
def estado_correo(usuario: UsuarioAutenticado, db: BD) -> dict:
    return correo.estado(db, usuario)


@router_auth.post("/correo", response_model=EstadoCorreoSalida)
def registrar_correo(datos: RegistrarCorreoPeticion, usuario: UsuarioAutenticado, db: BD) -> dict:
    """Envia un codigo al correo nuevo; queda guardado al verificarlo."""
    return correo.iniciar_verificacion(db, usuario, datos.correo, datos.password_actual)


@router_auth.post("/correo/verificar", response_model=EstadoCorreoSalida)
def verificar_correo(datos: VerificarCorreoPeticion, usuario: UsuarioAutenticado, db: BD) -> dict:
    return correo.confirmar_verificacion(db, usuario, datos.codigo)


@router_auth.post("/correo/quitar", response_model=EstadoCorreoSalida)
def quitar_correo(datos: QuitarCorreoPeticion, usuario: UsuarioAutenticado, db: BD) -> dict:
    return correo.quitar(db, usuario, datos.password_actual)


def _envio_salida(cfg) -> dict:
    return {"url_envio": cfg.url_envio, "configurado": bool(cfg.url_envio), "script": correo.script(cfg)}


@router_auth.get("/envio-correo", response_model=EnvioCorreoSalida)
def ver_envio_correo(db: BD, _: SoloAdmin) -> dict:
    cfg = correo.configuracion(db)
    db.commit()
    return _envio_salida(cfg)


@router_auth.put("/envio-correo", response_model=EnvioCorreoSalida)
def guardar_envio_correo(datos: EnvioCorreoGuardar, db: BD, _: SoloAdmin) -> dict:
    return _envio_salida(correo.guardar_url(db, datos.url_envio))


@router_auth.post("/envio-correo/regenerar-secreto", response_model=EnvioCorreoSalida)
def regenerar_secreto_correo(db: BD, _: SoloAdmin) -> dict:
    return _envio_salida(correo.regenerar_secreto(db))


@router_auth.post("/envio-correo/prueba")
def probar_envio_correo(datos: PruebaCorreoPeticion, db: BD, _: SoloAdmin) -> dict:
    correo.probar(db, datos.para)
    return {"mensaje": "Correo de prueba enviado. Revisa la bandeja de entrada (y spam)."}


@router_usuarios.get("/para-recuperar", response_model=list[UsuarioSalida])
def usuarios_para_recuperar(db: BD, _: AdminOSupervisor) -> list[Usuario]:
    """Lista para que el supervisor busque a quien darle contraseña temporal."""
    return service.listar_usuarios(db)


@router_usuarios.post("/{usuario_id}/password-temporal", response_model=PasswordTemporalSalida)
def password_temporal(usuario_id: int, db: BD, quien: AdminOSupervisor) -> PasswordTemporalSalida:
    usuario = service.obtener_usuario(db, usuario_id)
    return PasswordTemporalSalida(password_temporal=service.dar_password_temporal(db, usuario, quien))


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
