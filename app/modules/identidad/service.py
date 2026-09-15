"""
Logica del modulo Identidad: autenticacion y gestion de usuarios.

Esta capa no sabe nada de HTTP: recibe datos y lanza los errores de
app/core/errores.py. Eso permite probarla sin levantar el servidor y
reutilizarla desde otros modulos.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.borrado_suave import marcar_eliminado_por
from app.core.errores import (
    ConflictoDeDatos,
    CredencialesInvalidas,
    ErrorDeValidacion,
    RecursoNoEncontrado,
)
from app.core.seguridad import hash_password, verificar_password
from app.modules.identidad.models import Rol, Usuario
from app.modules.identidad.schemas import UsuarioActualizar, UsuarioCrear

# --- Consultas basicas -----------------------------------------------------


def obtener_usuario(db: Session, usuario_id: int) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
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


def crear_usuario(db: Session, datos: UsuarioCrear) -> Usuario:
    _validar_nombre_libre(db, datos.nombre_usuario)
    _validar_rol(db, datos.rol_id)

    usuario = Usuario(
        nombre_completo=datos.nombre_completo.strip(),
        nombre_usuario=datos.nombre_usuario.strip().lower(),
        password_hash=hash_password(datos.password),
        rol_id=datos.rol_id,
        activo=datos.activo,
    )
    db.add(usuario)
    db.commit()
    db.refresh(usuario)
    return usuario


def actualizar_usuario(db: Session, usuario_id: int, datos: UsuarioActualizar) -> Usuario:
    usuario = obtener_usuario(db, usuario_id)
    _validar_nombre_libre(db, datos.nombre_usuario, excepto_id=usuario.id)
    _validar_rol(db, datos.rol_id)

    usuario.nombre_completo = datos.nombre_completo.strip()
    usuario.nombre_usuario = datos.nombre_usuario.strip().lower()
    usuario.rol_id = datos.rol_id
    usuario.activo = datos.activo
    if datos.password:
        usuario.password_hash = hash_password(datos.password)

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
    marcar_eliminado_por(db, usuario, eliminado_por)
    db.commit()
