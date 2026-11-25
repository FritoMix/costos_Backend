"""
Codigos de recuperacion del administrador (V25).

El administrador genera 8 codigos de un solo uso y los guarda impresos. Si
olvida la contraseña, en "¿Olvidaste tu contraseña?" escribe su usuario, uno
de esos codigos y una contraseña nueva.

Seguridad:
- Formato ABCD-EFGH-JKLM (60 bits). Los 4 primeros caracteres identifican el
  codigo; los 8 restantes se guardan cifrados con bcrypt, como las contraseñas.
- Generarlos exige la contraseña actual: una sesion abierta y descuidada no
  basta para quedarse con la cuenta.
- Los intentos fallidos bloquean por tiempo creciente (misma politica que el
  inicio de sesion, con contadores propios).
- Usar un codigo cierra todas las sesiones de esa cuenta.
"""

import logging
import math
import secrets
from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import CredencialesInvalidas, ErrorDeValidacion
from app.core.seguridad import hash_password, verificar_password
from app.modules.identidad.models import CodigoRecuperacion, IntentoLogin, RolCodigo, Usuario
from app.modules.identidad.sesiones import (
    _HASH_FICTICIO,
    AccesoTemporalmenteLimitado,
    _clave,
    ahora,
    revocar_sesiones_usuario,
)

logger = logging.getLogger("datacontrol.auth")

CANTIDAD = 8
# Sin 0/O, 1/I/L ni U/V: no se confunden al leerlos de un papel.
_ALFABETO = "23456789ABCDEFGHJKMNPQRSTWXYZ"
_MENSAJE_FALLO = "Usuario o código de recuperación incorrectos."


def _normalizar(codigo: str) -> str:
    return "".join(c for c in codigo.upper() if c.isalnum())


def _nuevo_codigo() -> str:
    return "".join(secrets.choice(_ALFABETO) for _ in range(12))


def puede_usar_codigos(usuario: Usuario) -> bool:
    return usuario.rol.codigo == RolCodigo.ADMIN


def estado(db: Session, usuario: Usuario) -> dict:
    disponibles, generados_en = db.execute(
        select(
            func.count(CodigoRecuperacion.id).filter(CodigoRecuperacion.usado_en.is_(None)),
            func.max(CodigoRecuperacion.creado_en),
        ).where(CodigoRecuperacion.usuario_id == usuario.id)
    ).one()
    return {"disponibles": disponibles, "generados_en": generados_en}


def generar(db: Session, usuario: Usuario, password_actual: str) -> list[str]:
    """Reemplaza los codigos anteriores por 8 nuevos y los devuelve UNA vez."""
    if not puede_usar_codigos(usuario):
        raise ErrorDeValidacion("Solo el administrador usa códigos de recuperación.")
    if not verificar_password(password_actual, usuario.password_hash):
        raise ErrorDeValidacion("La contraseña actual no es correcta.")
    db.execute(delete(CodigoRecuperacion).where(CodigoRecuperacion.usuario_id == usuario.id))
    codigos = [_nuevo_codigo() for _ in range(CANTIDAD)]
    for codigo in codigos:
        db.add(
            CodigoRecuperacion(
                usuario_id=usuario.id,
                identificador=codigo[:4],
                codigo_hash=hash_password(codigo[4:]),
            )
        )
    db.commit()
    logger.warning("auth.codigos_generados usuario_id=%d", usuario.id)
    return [f"{c[:4]}-{c[4:8]}-{c[8:]}" for c in codigos]


def _filas_de_intento(db: Session, nombre: str, ip: str) -> tuple[list[IntentoLogin], dict, str]:
    momento = ahora()
    cuenta = _clave("recuperacion-cuenta", nombre)
    direccion = _clave("recuperacion-ip", ip)
    limites = {cuenta: settings.login_account_attempts, direccion: settings.login_ip_attempts}
    filas = []
    for clave in sorted(limites):  # Orden fijo: sin deadlocks.
        db.execute(
            insert(IntentoLogin)
            .values(clave=clave, fallos=0, ultimo_intento=momento)
            .on_conflict_do_nothing(index_elements=[IntentoLogin.clave])
        )
        fila = db.scalar(select(IntentoLogin).where(IntentoLogin.clave == clave).with_for_update())
        if momento - fila.ultimo_intento >= timedelta(minutes=15):
            fila.fallos = 0
            fila.bloqueado_hasta = None
        filas.append(fila)
    esperas = [
        math.ceil((f.bloqueado_hasta - momento).total_seconds())
        for f in filas
        if f.bloqueado_hasta and f.bloqueado_hasta > momento
    ]
    if esperas:
        db.commit()
        raise AccesoTemporalmenteLimitado(max(esperas))
    return filas, limites, cuenta


def recuperar(db: Session, nombre_usuario: str, codigo: str, password_nueva: str, ip: str) -> int:
    """Cambia la contraseña con un codigo valido. Devuelve cuantos quedan."""
    nombre = nombre_usuario.strip().lower()
    filas, limites, cuenta = _filas_de_intento(db, nombre, ip)
    momento = ahora()
    limpio = _normalizar(codigo)

    usuario = db.scalar(select(Usuario).where(Usuario.nombre_usuario == nombre))
    candidato = None
    if usuario is not None and usuario.puede_entrar and len(limpio) == 12:
        candidato = db.scalar(
            select(CodigoRecuperacion)
            .where(
                CodigoRecuperacion.usuario_id == usuario.id,
                CodigoRecuperacion.identificador == limpio[:4],
                CodigoRecuperacion.usado_en.is_(None),
            )
            .with_for_update()
        )
    # Siempre un bcrypt, exista o no el codigo: el tiempo no delata nada.
    valido = verificar_password(limpio[4:], candidato.codigo_hash if candidato else _HASH_FICTICIO)

    if candidato is None or not valido:
        for fila in filas:
            fila.fallos += 1
            fila.ultimo_intento = momento
            if fila.fallos >= limites[fila.clave]:
                espera = min(900, 30 * 2 ** min(fila.fallos - limites[fila.clave], 5))
                fila.bloqueado_hasta = momento + timedelta(seconds=espera)
        db.commit()
        logger.warning("auth.recuperacion_fallida cuenta=%s", cuenta[:16])
        raise CredencialesInvalidas(_MENSAJE_FALLO)

    candidato.usado_en = momento
    usuario.password_hash = hash_password(password_nueva)
    usuario.debe_cambiar_password = False
    usuario.token_version += 1
    revocar_sesiones_usuario(db, usuario.id)
    for fila in filas:
        if fila.clave == cuenta:
            fila.fallos = 0
            fila.bloqueado_hasta = None
        fila.ultimo_intento = momento
    db.commit()
    logger.warning("auth.recuperacion_con_codigo usuario_id=%d", usuario.id)
    return estado(db, usuario)["disponibles"]
