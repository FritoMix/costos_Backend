"""
Logica del modulo Identidad: autenticacion y gestion de usuarios.

Esta capa no sabe nada de HTTP: recibe datos y lanza los errores de
app/core/errores.py. Eso permite probarla sin levantar el servidor y
reutilizarla desde otros modulos.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.borrado_suave import marcar_eliminado_por
from app.core.errores import (
    ConflictoDeDatos,
    CredencialesInvalidas,
    ErrorDeValidacion,
    RecursoNoEncontrado,
)
from app.core.seguridad import hash_password, verificar_password
from app.modules.identidad.models import CodigoRecuperacion, Rol, RolCodigo, Usuario
from app.modules.identidad.schemas import UsuarioActualizar, UsuarioCrear
from app.modules.identidad.sesiones import revocar_sesiones_usuario

# --- Consultas basicas -----------------------------------------------------


def obtener_usuario(db: Session, usuario_id: int, *, bloquear: bool = False) -> Usuario:
    usuario = db.get(
        Usuario,
        usuario_id,
        populate_existing=bloquear,
        with_for_update={"of": Usuario} if bloquear else None,
        options=[selectinload(Usuario.rol)] if bloquear else None,
    )
    if usuario is None or usuario.eliminado:
        raise RecursoNoEncontrado("Ese usuario no existe.")
    return usuario


def listar_usuarios(db: Session) -> list[Usuario]:
    return list(
        db.scalars(
            select(Usuario)
            .where(Usuario.eliminado == False)
            .order_by(Usuario.nombre_completo)
        ).all()
    )


def listar_roles(db: Session) -> list[Rol]:
    return list(db.scalars(select(Rol).order_by(Rol.id)).all())


def listar_supervisores(db: Session) -> list[Usuario]:
    """Usuarios que pueden aparecer como supervisor en los filtros de Analisis."""
    return list(
        db.scalars(
            select(Usuario)
            .join(Rol)
            .where(Usuario.eliminado == False, Rol.codigo == "supervisor")
            .order_by(Usuario.nombre_completo)
        ).all()
    )


# --- Autenticacion ---------------------------------------------------------


def autenticar(db: Session, nombre_usuario: str, password: str) -> Usuario:
    """
    Devuelve el usuario si las credenciales son correctas y la cuenta esta
    habilitada. El mensaje de error es igual en todos los casos a
    proposito: no le decimos a nadie si un usuario existe o no.
    """
    usuario = db.scalar(select(Usuario).where(Usuario.nombre_usuario == nombre_usuario))
    if usuario is None or not usuario.puede_entrar:
        raise CredencialesInvalidas("Usuario o contraseña incorrectos.")
    if not verificar_password(password, usuario.password_hash):
        raise CredencialesInvalidas("Usuario o contraseña incorrectos.")
    return usuario


def cambiar_password_propia(db: Session, usuario: Usuario, actual: str, nueva: str) -> None:
    if not verificar_password(actual, usuario.password_hash):
        raise ErrorDeValidacion("La contraseña actual no es correcta.")
    if actual == nueva:
        raise ErrorDeValidacion("La contraseña nueva debe ser diferente a la actual.")
    usuario.password_hash = hash_password(nueva)
    # Ya creo su contraseña propia (V21).
    usuario.debe_cambiar_password = False
    # Invalida cualquier token emitido antes de este cambio. El router
    # reemite uno nuevo para que la sesion actual siga funcionando.
    usuario.token_version += 1
    revocar_sesiones_usuario(db, usuario.id)
    db.commit()


# --- Administracion de usuarios -------------------------------------------


def _validar_nombre_libre(db: Session, nombre_usuario: str, excepto_id: int | None = None) -> None:
    consulta = select(Usuario).where(Usuario.nombre_usuario == nombre_usuario)
    if excepto_id is not None:
        consulta = consulta.where(Usuario.id != excepto_id)
    if db.scalar(consulta) is not None:
        raise ConflictoDeDatos(f'El nombre de usuario "{nombre_usuario}" ya está en uso.')


def _validar_rol(db: Session, rol_id: int) -> Rol:
    rol = db.get(Rol, rol_id)
    if rol is None:
        raise ErrorDeValidacion("El rol seleccionado no es válido.")
    return rol


# Roles que trabajan en UNA linea de produccion (V21).
ROLES_DE_LINEA = (RolCodigo.OPERARIO_HORNO, RolCodigo.OPERARIO_SABORIZADO, RolCodigo.BODEGUERO)


def _linea_del_usuario(db: Session, rol: Rol, linea_id: int | None, actual: int | None) -> int | None:
    """
    Operarios y Bodega trabajan en una linea; admin y supervisor no (ven
    todas). Si no se indica, se conserva la que tenia o queda en papa, para
    que un cliente viejo siga funcionando igual.
    """
    from app.modules.catalogos.models import Linea
    from app.modules.catalogos.service import linea_por_codigo

    if rol.codigo not in ROLES_DE_LINEA:
        return None
    if linea_id is None:
        linea_id = actual or linea_por_codigo(db, "papa").id
    linea = db.get(Linea, linea_id)
    if linea is None or not linea.activo:
        raise ErrorDeValidacion("La línea seleccionada no es válida.")
    if rol.codigo == RolCodigo.BODEGUERO and not linea.usa_bodega:
        raise ErrorDeValidacion(f"La línea {linea.nombre} no tiene bodega.")
    return linea.id


def crear_usuario(db: Session, datos: UsuarioCrear) -> Usuario:
    _validar_nombre_libre(db, datos.nombre_usuario)
    rol = _validar_rol(db, datos.rol_id)
    linea_id = _linea_del_usuario(db, rol, datos.linea_id, None)

    usuario = Usuario(
        nombre_completo=datos.nombre_completo.strip(),
        nombre_usuario=datos.nombre_usuario.strip().lower(),
        password_hash=hash_password(datos.password),
        rol_id=datos.rol_id,
        linea_id=linea_id,
        activo=datos.activo,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def actualizar_usuario(db: Session, usuario_id: int, datos: UsuarioActualizar) -> Usuario:
    usuario = obtener_usuario(db, usuario_id, bloquear=True)
    _validar_nombre_libre(db, datos.nombre_usuario, excepto_id=usuario.id)
    rol = _validar_rol(db, datos.rol_id)
    linea_id = _linea_del_usuario(db, rol, datos.linea_id, usuario.linea_id)

    usuario.nombre_completo = datos.nombre_completo.strip()
    usuario.nombre_usuario = datos.nombre_usuario.strip().lower()
    if usuario.rol_id != rol.id:
        db.execute(delete(CodigoRecuperacion).where(CodigoRecuperacion.usuario_id == usuario.id))
    usuario.rol_id = datos.rol_id
    usuario.linea_id = linea_id

    desactivando = usuario.activo and not datos.activo
    cambio_password = bool(datos.password)
    usuario.activo = datos.activo
    if cambio_password:
        usuario.password_hash = hash_password(datos.password)
    if cambio_password or desactivando:
        # Cualquier cambio de credenciales o una desactivacion cierra las
        # sesiones abiertas de ese usuario.
        usuario.token_version += 1
        revocar_sesiones_usuario(db, usuario.id)

    db.commit()
    db.refresh(usuario)
    return usuario


def eliminar_usuario(db: Session, usuario_id: int, eliminado_por: Usuario) -> None:
    """
    Borrado suave. El usuario deja de aparecer y de poder entrar, pero sus
    ordenes y registros historicos conservan su firma.
    """
    usuario = obtener_usuario(db, usuario_id)
    if usuario.id == eliminado_por.id:
        raise ErrorDeValidacion("No puedes eliminar tu propio usuario.")

    usuario.activo = False
    usuario.token_version += 1
    revocar_sesiones_usuario(db, usuario.id)
    marcar_eliminado_por(db, usuario, eliminado_por)
    db.commit()


# --- Recuperar la contraseña sin correo (V21) --------------------------------

MINUTOS_ENTRE_SOLICITUDES = 15


def solicitar_recuperacion(db: Session, nombre_usuario: str) -> None:
    """
    Quien olvido su contraseña la pide desde el inicio de sesion. Se avisa
    (con alarma) al administrador y a los supervisores para que le den una
    temporal. Si el usuario no existe no pasa nada, pero la respuesta es la
    misma: no le decimos a nadie que usuarios existen. Una sola solicitud
    cada 15 minutos por persona.
    """
    from datetime import UTC, datetime, timedelta

    from app.modules.notificaciones.models import Notificacion, TipoNotificacion
    from app.modules.notificaciones.service import _crear_para, _destinatarios_por_rol

    usuario = db.scalar(
        select(Usuario)
        .where(func.lower(Usuario.nombre_usuario) == nombre_usuario.strip().lower())
        .with_for_update(of=Usuario)
    )
    if usuario is None or not usuario.puede_entrar:
        return
    hace_poco = datetime.now(UTC) - timedelta(minutes=MINUTOS_ENTRE_SOLICITUDES)
    if db.scalar(
        select(Notificacion.id)
        .where(
            Notificacion.tipo == TipoNotificacion.RECUPERAR_PASSWORD,
            Notificacion.mensaje.contains(f"({usuario.nombre_usuario})", autoescape=True),
            Notificacion.fecha_creacion >= hace_poco,
        )
        .limit(1)
    ):
        return
    # Los supervisores atienden a los de planta; al administrador le llegan todos.
    roles = [RolCodigo.ADMIN]
    if usuario.rol.codigo not in (RolCodigo.ADMIN, RolCodigo.SUPERVISOR):
        roles.append(RolCodigo.SUPERVISOR)
    destinatarios = [u for u in _destinatarios_por_rol(db, roles) if u.id != usuario.id]
    if not destinatarios:
        return
    _crear_para(
        db,
        usuarios=destinatarios,
        tipo=TipoNotificacion.RECUPERAR_PASSWORD,
        titulo=f"Contraseña temporal para {usuario.nombre_usuario}",
        mensaje=(
            f"{usuario.nombre_completo} ({usuario.nombre_usuario}), {usuario.rol.nombre}, pidió una "
            "contraseña temporal. Abre este aviso para gestionar la solicitud."
        ),
        orden_id=None,
    )
    db.commit()


def dar_password_temporal(db: Session, usuario: Usuario, quien: Usuario) -> str:
    """
    Genera una contraseña temporal de 8 numeros (facil de dictar). La persona
    entra con ella y la app le pide crear una nueva antes de seguir. Un
    supervisor solo puede hacerlo con usuarios de planta. Cierra las sesiones
    abiertas de esa persona.
    """
    import secrets

    if usuario.eliminado:
        raise RecursoNoEncontrado("Ese usuario no existe.")
    if quien.rol.codigo != RolCodigo.ADMIN and usuario.rol.codigo in (
        RolCodigo.ADMIN,
        RolCodigo.SUPERVISOR,
    ):
        raise ErrorDeValidacion("Solo el administrador puede cambiar esta contraseña.")
    temporal = "".join(secrets.choice("0123456789") for _ in range(8))
    usuario.password_hash = hash_password(temporal)
    usuario.debe_cambiar_password = True
    usuario.token_version += 1
    revocar_sesiones_usuario(db, usuario.id)
    db.commit()
    return temporal
