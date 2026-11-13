"""Sesiones revocables y protección de acceso compartidas por todas las instancias."""

import hashlib
import hmac
import logging
import math
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import CredencialesInvalidas, ErrorDeAplicacion
from app.core.seguridad import crear_token_acceso, hash_password, verificar_password
from app.modules.identidad.models import IntentoLogin, SesionUsuario, Usuario

logger = logging.getLogger("datacontrol.auth")
# Igualar el trabajo de bcrypt cuando la cuenta no existe/no está habilitada.
_HASH_FICTICIO = hash_password("verificacion-interna-no-es-una-credencial")


def ahora() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _clave(tipo: str, valor: str) -> str:
    return hmac.new(settings.jwt_secret_key.encode(), f"{tipo}:{valor}".encode(), hashlib.sha256).hexdigest()


class AccesoTemporalmenteLimitado(ErrorDeAplicacion):
    codigo_http = 429

    def __init__(self, segundos: int):
        super().__init__("Demasiados intentos de acceso. Espera un momento y vuelve a intentar.")
        self.retry_after = segundos


def autenticar_protegido(db: Session, nombre: str, password: str, ip: str) -> Usuario:
    """Bloqueos de fila evitan perder incrementos ante intentos concurrentes.

    La misma política se aplica a cuentas existentes e inexistentes. La espera
    progresa desde 30 s hasta 15 min, y se reinicia tras 15 min sin intentos.
    """
    momento = ahora()
    cuenta = _clave("cuenta", nombre)
    direccion = _clave("ip", ip)
    limites = {cuenta: settings.login_account_attempts, direccion: settings.login_ip_attempts}
    filas = []
    # Orden fijo para no provocar deadlocks entre dos peticiones.
    for clave in sorted(limites):
        db.execute(
            insert(IntentoLogin)
            .values(
                clave=clave,
                fallos=0,
                ultimo_intento=momento,
            )
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
        logger.warning("auth.login_limitado cuenta=%s origen=%s", cuenta[:16], direccion[:16])
        raise AccesoTemporalmenteLimitado(max(esperas))

    usuario = db.scalar(select(Usuario).where(Usuario.nombre_usuario == nombre))
    habilitado = usuario is not None and usuario.puede_entrar
    valido = verificar_password(password, usuario.password_hash if habilitado else _HASH_FICTICIO)
    if not habilitado or not valido:
        for fila in filas:
            fila.fallos += 1
            fila.ultimo_intento = momento
            if fila.fallos >= limites[fila.clave]:
                espera = min(900, 30 * 2 ** min(fila.fallos - limites[fila.clave], 5))
                fila.bloqueado_hasta = momento + timedelta(seconds=espera)
        db.commit()  # Los fallos deben persistir también cuando se devuelve 401.
        logger.warning("auth.login_fallido cuenta=%s origen=%s", cuenta[:16], direccion[:16])
        raise CredencialesInvalidas("Usuario o contraseña incorrectos.")

    for fila in filas:
        if fila.clave == cuenta:
            fila.fallos = 0
            fila.bloqueado_hasta = None
        fila.ultimo_intento = momento
    db.commit()
    logger.info("auth.login_correcto usuario_id=%d origen=%s", usuario.id, direccion[:16])
    return usuario


def emitir_sesion(db: Session, usuario: Usuario) -> tuple[str, int]:
    momento = ahora()
    token, segundos = crear_token_acceso(usuario.id, usuario.rol.codigo, usuario.token_version)
    db.execute(delete(SesionUsuario).where(SesionUsuario.expira_en <= momento))
    db.execute(delete(IntentoLogin).where(IntentoLogin.ultimo_intento < momento - timedelta(days=1)))
    db.add(
        SesionUsuario(
            token_hash=hash_token(token),
            usuario_id=usuario.id,
            expira_en=momento + timedelta(seconds=segundos),
            ultima_actividad=momento,
        )
    )
    db.commit()
    return token, segundos


def validar_sesion(db: Session, token: str, usuario_id: int) -> SesionUsuario:
    sesion = db.get(SesionUsuario, hash_token(token))
    momento = ahora()
    if (
        sesion is None
        or sesion.usuario_id != usuario_id
        or sesion.expira_en <= momento
        or sesion.ultima_actividad <= momento - timedelta(minutes=settings.session_idle_minutes)
    ):
        raise CredencialesInvalidas("Tu sesión expiró o fue cerrada. Vuelve a iniciar sesión.")
    return sesion


def registrar_actividad(db: Session, token: str) -> None:
    momento = ahora()
    resultado = db.execute(
        update(SesionUsuario)
        .where(
            SesionUsuario.token_hash == hash_token(token),
            SesionUsuario.expira_en > momento,
            SesionUsuario.ultima_actividad > momento - timedelta(minutes=settings.session_idle_minutes),
        )
        .values(ultima_actividad=momento)
    )
    db.commit()
    if resultado.rowcount != 1:
        raise CredencialesInvalidas("Tu sesión expiró. Vuelve a iniciar sesión.")


def revocar_sesion(db: Session, token: str | None) -> None:
    if not token:
        return
    # El logout es idempotente, incluso con cookie corrupta o vencida.
    resultado = db.execute(delete(SesionUsuario).where(SesionUsuario.token_hash == hash_token(token)))
    db.commit()
    if resultado.rowcount:
        logger.info("auth.logout")


def revocar_sesiones_usuario(db: Session, usuario_id: int) -> None:
    db.execute(delete(SesionUsuario).where(SesionUsuario.usuario_id == usuario_id))
    logger.info("auth.sesiones_revocadas usuario_id=%d", usuario_id)
