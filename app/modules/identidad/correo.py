"""
Correo de recuperacion (V29).

Cada usuario puede registrar su correo en "Mi cuenta". Queda verificado
cuando escribe el codigo de 6 digitos que le llega. Con el correo verificado,
en "¿Olvidaste tu contraseña?" pide un codigo y crea una contraseña nueva sin
depender de nadie.

Envio: Render (plan gratis) bloquea el correo SMTP. Los correos salen por un
script de Google Apps Script publicado desde la cuenta de Gmail del
administrador: la app le hace un POST HTTPS con un secreto compartido y el
script envia el correo con MailApp. El enlace se guarda en
configuracion_correo; el secreto lo genera la app y va dentro del script.

Seguridad:
- Codigos de 6 digitos, de un solo uso, vencen en 15 minutos y se guardan
  cifrados con bcrypt. Cada codigo admite 5 intentos.
- Recuperar usa los mismos contadores de bloqueo que los codigos del
  administrador (por cuenta y por IP).
- Pedir un codigo de recuperacion siempre responde lo mismo: no revela que
  usuarios existen ni si tienen correo. El correo sale en segundo plano para
  que el tiempo de respuesta tampoco lo delate.
- Cambiar el correo exige la contraseña actual.
- Recuperar cierra todas las sesiones y avisa al correo que la contraseña
  cambio.
"""

import json
import logging
import re
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from html import escape

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.core.errores import CredencialesInvalidas, ErrorDeValidacion
from app.core.seguridad import hash_password, verificar_password
from app.db.session import SessionLocal
from app.modules.identidad import recuperacion
from app.modules.identidad.models import CodigoCorreo, ConfiguracionCorreo, Usuario
from app.modules.identidad.service import obtener_usuario
from app.modules.identidad.sesiones import _HASH_FICTICIO, ahora

logger = logging.getLogger("datacontrol.auth")

VERIFICAR = "verificar"
RECUPERAR = "recuperar"
MINUTOS_VIGENCIA = 15
MAX_INTENTOS = 5
SEGUNDOS_ENTRE_ENVIOS = 60
MAX_ENVIOS_POR_HORA = 5

# Solo enlaces de Google Apps Script publicados como aplicacion web: la app
# nunca hace peticiones a otro sitio con el secreto.
_URL_VALIDA = re.compile(r"^https://script\.google\.com/macros/s/[A-Za-z0-9_-]{10,200}/exec$")
_CORREO_VALIDO = re.compile(r"^[^@\s<>\"',;]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
_MENSAJE_FALLO = "Usuario o código incorrectos, o el código ya venció."

SCRIPT_PLANTILLA = """// DATACONTROL · envío de correos desde esta cuenta de Gmail.
// 1) En script.google.com crea un Proyecto nuevo, borra lo que trae, pega
//    todo este código y guarda.
// 2) Implementar > Nueva implementación > Tipo: Aplicación web.
//    Ejecutar como: Yo. Quién tiene acceso: Cualquier usuario.
// 3) Autoriza el permiso para enviar correos y copia la URL de la
//    aplicación web (termina en /exec) en DATACONTROL > Mi cuenta.
// No compartas este código: el secreto de abajo permite enviar correos.
const SECRETO = '__SECRETO__';

function doPost(e) {
  let datos;
  try {
    datos = JSON.parse(e.postData.contents);
  } catch (error) {
    return responder({ ok: false, error: 'json' });
  }
  if (datos.secreto !== SECRETO) return responder({ ok: false, error: 'secreto' });
  MailApp.sendEmail({
    to: datos.para,
    subject: datos.asunto,
    body: datos.texto,
    htmlBody: datos.html,
    name: 'DATACONTROL · Fritomix',
  });
  return responder({ ok: true, restantes: MailApp.getRemainingDailyQuota() });
}

function responder(objeto) {
  return ContentService.createTextOutput(JSON.stringify(objeto)).setMimeType(
    ContentService.MimeType.JSON,
  );
}
"""


@dataclass(frozen=True)
class Mensaje:
    para: str
    asunto: str
    texto: str
    html: str


@dataclass(frozen=True)
class Envio:
    """Todo lo necesario para enviar un correo despues de cerrar la transaccion."""

    url: str
    secreto: str
    mensaje: Mensaje
    codigo_id: int | None = None


# --- Configuracion del envio ------------------------------------------------


def configuracion(db: Session) -> ConfiguracionCorreo:
    """La fila unica de configuracion; la crea con un secreto nuevo si no existe."""
    cfg = db.get(ConfiguracionCorreo, 1)
    if cfg is None:
        cfg = ConfiguracionCorreo(id=1, secreto=secrets.token_urlsafe(32))
        db.add(cfg)
        db.flush()
    return cfg


def envio_configurado(db: Session) -> bool:
    cfg = db.get(ConfiguracionCorreo, 1)
    return cfg is not None and bool(cfg.url_envio)


def script(cfg: ConfiguracionCorreo) -> str:
    return SCRIPT_PLANTILLA.replace("__SECRETO__", cfg.secreto)


def guardar_url(db: Session, url: str | None) -> ConfiguracionCorreo:
    limpia = (url or "").strip() or None
    if limpia is not None and not _URL_VALIDA.match(limpia):
        raise ErrorDeValidacion(
            "Pega la URL de la aplicación web de Google Apps Script: empieza por "
            "https://script.google.com/macros/s/ y termina en /exec."
        )
    cfg = configuracion(db)
    cfg.url_envio = limpia
    db.commit()
    return cfg


def regenerar_secreto(db: Session) -> ConfiguracionCorreo:
    """Secreto nuevo: hay que pegar el script otra vez en Google."""
    cfg = configuracion(db)
    cfg.secreto = secrets.token_urlsafe(32)
    db.commit()
    return cfg


def _envio(db: Session, mensaje: Mensaje, codigo_id: int | None = None) -> Envio | None:
    cfg = db.get(ConfiguracionCorreo, 1)
    if cfg is None or not cfg.url_envio:
        return None
    return Envio(url=cfg.url_envio, secreto=cfg.secreto, mensaje=mensaje, codigo_id=codigo_id)


def enviar(envio: Envio) -> None:
    """POST al script de Google. Lanza ErrorDeValidacion si no se pudo enviar."""
    cuerpo = json.dumps(
        {
            "secreto": envio.secreto,
            "para": envio.mensaje.para,
            "asunto": envio.mensaje.asunto,
            "texto": envio.mensaje.texto,
            "html": envio.mensaje.html,
        }
    ).encode("utf-8")
    peticion = urllib.request.Request(
        envio.url, data=cuerpo, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        # Google responde 302 a script.googleusercontent.com con el resultado.
        with urllib.request.urlopen(peticion, timeout=20) as respuesta:  # noqa: S310 (URL validada)
            datos = respuesta.read(20_000)
        resultado = json.loads(datos)
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        logger.error("correo.envio_fallido %s", type(error).__name__)
        raise ErrorDeValidacion(
            "No se pudo enviar el correo. Revisa que la aplicación web de Google esté "
            "implementada con acceso para «Cualquier usuario»."
        ) from error
    if not isinstance(resultado, dict) or resultado.get("ok") is not True:
        motivo = resultado.get("error") if isinstance(resultado, dict) else None
        logger.error("correo.envio_rechazado")
        if motivo == "secreto":
            raise ErrorDeValidacion(
                "Google rechazó el envío: el script no tiene el secreto actual. "
                "Copia el script de nuevo y vuelve a implementarlo."
            )
        raise ErrorDeValidacion("Google no pudo enviar el correo. Revisa la dirección y el script.")


def enviar_en_segundo_plano(envio: Envio | None) -> None:
    """Registra el resultado de Google sin conservar el contenido del mensaje."""
    if envio is None:
        return
    try:
        enviar(envio)
    except Exception as error:
        logger.warning("correo.envio_fallido codigo_id=%s tipo=%s", envio.codigo_id, type(error).__name__)
        aceptado = False
    else:
        logger.info("correo.envio_aceptado codigo_id=%s", envio.codigo_id)
        aceptado = True
    if envio.codigo_id is not None:
        # La sesión del request puede haberse cerrado al ejecutar esta tarea.
        with SessionLocal.begin() as db:
            _registrar_entrega(db, envio.codigo_id, aceptado)


def _registrar_entrega(db: Session, codigo_id: int, aceptado: bool) -> None:
    # Mismo orden de bloqueo que al verificar el buzón o consumir el código.
    usuario_id = db.scalar(
        select(Usuario.id).join(CodigoCorreo).where(CodigoCorreo.id == codigo_id).with_for_update(of=Usuario)
    )
    if usuario_id is None:
        return
    fila = db.execute(
        update(CodigoCorreo)
        .where(CodigoCorreo.id == codigo_id, CodigoCorreo.estado_envio == "pendiente")
        .values(estado_envio="aceptado" if aceptado else "fallido")
        .returning(CodigoCorreo.expira_en, CodigoCorreo.usado_en)
    ).one_or_none()
    if aceptado and fila is not None and fila.usado_en is None and fila.expira_en > ahora():
        # Una respuesta tardía solo puede retirar solicitudes anteriores a la suya.
        db.execute(
            update(CodigoCorreo)
            .where(
                CodigoCorreo.usuario_id == usuario_id,
                CodigoCorreo.proposito == RECUPERAR,
                CodigoCorreo.id < codigo_id,
                CodigoCorreo.usado_en.is_(None),
                CodigoCorreo.expira_en > ahora(),
            )
            .values(expira_en=ahora())
        )


def probar(db: Session, para: str) -> None:
    destino = _normalizar_correo(para)
    envio = _envio(
        db,
        _plantilla(
            destino,
            "Prueba de envío",
            "Si lees esto, DATACONTROL ya puede enviar correos de recuperación.",
            None,
            "Correo de prueba enviado por el administrador.",
        ),
    )
    if envio is None:
        raise ErrorDeValidacion("Primero guarda la URL de la aplicación web de Google.")
    enviar(envio)


# --- Plantillas ---------------------------------------------------------------


_PIE_CODIGO = "Si no fuiste tú, ignora este correo. Nadie de Fritomix te pedirá este código."


def _plantilla(para: str, asunto: str, parrafo: str, codigo: str | None, pie: str = _PIE_CODIGO) -> Mensaje:
    texto = f"{parrafo}\n\n"
    bloque = ""
    if codigo is not None:
        texto += f"Código: {codigo}\nVence en {MINUTOS_VIGENCIA} minutos.\n\n"
        bloque = (
            '<p style="margin:24px 0;text-align:center">'
            '<span style="display:inline-block;padding:14px 22px;border-radius:12px;'
            "background:#f1f5f9;border:1px solid #cbd5e1;font:700 32px/1 monospace;"
            f'letter-spacing:8px;color:#0f172a">{escape(codigo)}</span></p>'
            f'<p style="color:#475569;font-size:14px">Vence en {MINUTOS_VIGENCIA} minutos.</p>'
        )
    texto += pie
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:480px;margin:auto;'
        'border:1px solid #e2e8f0;border-radius:16px;overflow:hidden">'
        '<div style="background:#0b2545;color:#fff;padding:16px 24px;font-weight:700;'
        'font-size:18px">DATACONTROL · Fritomix</div>'
        f'<div style="padding:24px;color:#0f172a;font-size:16px"><p>{escape(parrafo)}</p>{bloque}'
        f'<p style="color:#64748b;font-size:13px;margin-top:24px">{escape(pie)}</p></div></div>'
    )
    return Mensaje(para=para, asunto=f"DATACONTROL · {asunto}", texto=texto, html=html)


# --- Codigos -------------------------------------------------------------------


def _normalizar_correo(correo: str) -> str:
    limpio = correo.strip().lower()
    if len(limpio) > 254 or not _CORREO_VALIDO.match(limpio):
        raise ErrorDeValidacion("Escribe un correo válido, por ejemplo nombre@gmail.com.")
    return limpio


def _nuevo_codigo() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _solo_digitos(codigo: str) -> str:
    return "".join(c for c in codigo if c.isdigit())


def _envios_recientes(db: Session, usuario_id: int, proposito: str) -> list:
    momento = ahora()
    return list(
        db.scalars(
            select(CodigoCorreo.creado_en).where(
                CodigoCorreo.usuario_id == usuario_id,
                CodigoCorreo.proposito == proposito,
                CodigoCorreo.creado_en >= momento - timedelta(hours=1),
            )
        )
    )


def _demasiados_envios(db: Session, usuario_id: int, proposito: str) -> str | None:
    recientes = _envios_recientes(db, usuario_id, proposito)
    momento = ahora()
    if any(momento - creado < timedelta(seconds=SEGUNDOS_ENTRE_ENVIOS) for creado in recientes):
        return "Ya te enviamos un código hace un momento. Espera un minuto y revisa también spam."
    if len(recientes) >= MAX_ENVIOS_POR_HORA:
        return "Pediste muchos códigos en la última hora. Intenta más tarde."
    return None


def _anular_pendientes(db: Session, usuario_id: int, proposito: str) -> None:
    db.execute(
        update(CodigoCorreo)
        .where(
            CodigoCorreo.usuario_id == usuario_id,
            CodigoCorreo.proposito == proposito,
            CodigoCorreo.usado_en.is_(None),
        )
        .values(expira_en=ahora())
    )


def _guardar_codigo(db: Session, usuario: Usuario, proposito: str, correo: str, codigo: str) -> int:
    if proposito == VERIFICAR:
        _anular_pendientes(db, usuario.id, VERIFICAR)
    momento = ahora()
    fila = CodigoCorreo(
        usuario_id=usuario.id,
        proposito=proposito,
        correo=correo,
        codigo_hash=hash_password(codigo),
        creado_en=momento,
        expira_en=momento + timedelta(minutes=MINUTOS_VIGENCIA),
        estado_envio="aceptado" if proposito == VERIFICAR else "pendiente",
    )
    db.add(fila)
    db.flush()
    return fila.id


def _pendiente(
    db: Session, usuario_id: int, proposito: str, bloquear: bool = True, destino: str | None = None
) -> CodigoCorreo | None:
    consulta = (
        select(CodigoCorreo)
        .where(
            CodigoCorreo.usuario_id == usuario_id,
            CodigoCorreo.proposito == proposito,
            CodigoCorreo.usado_en.is_(None),
            CodigoCorreo.expira_en > ahora(),
            CodigoCorreo.intentos < MAX_INTENTOS,
        )
        .order_by(CodigoCorreo.creado_en.desc())
        .limit(1)
    )
    if destino is not None:
        consulta = consulta.where(
            CodigoCorreo.correo == destino,
            or_(CodigoCorreo.estado_envio.is_(None), CodigoCorreo.estado_envio == "aceptado"),
        )
    return db.scalar(consulta.with_for_update() if bloquear else consulta)


# --- Verificar el correo (con sesion) ------------------------------------------


def estado(db: Session, usuario: Usuario) -> dict:
    pendiente = _pendiente(db, usuario.id, VERIFICAR, bloquear=False)
    return {
        "correo": usuario.correo,
        "verificado": usuario.correo_verificado,
        "pendiente": pendiente.correo if pendiente else None,
        "envio_configurado": envio_configurado(db),
    }


def iniciar_verificacion(db: Session, usuario: Usuario, correo: str, password_actual: str) -> dict:
    """Envia un codigo al correo nuevo. El correo solo cambia al verificarlo."""
    destino = _normalizar_correo(correo)
    usuario = obtener_usuario(db, usuario.id, bloquear=True)
    if not verificar_password(password_actual, usuario.password_hash):
        raise ErrorDeValidacion("La contraseña actual no es correcta.")
    if not envio_configurado(db):
        raise ErrorDeValidacion(
            "El envío de correos aún no está configurado. Pídele al administrador que lo active."
        )
    if (motivo := _demasiados_envios(db, usuario.id, VERIFICAR)) is not None:
        raise ErrorDeValidacion(motivo)
    codigo = _nuevo_codigo()
    # Primero se envia: si Google falla, no queda un codigo que nunca llego.
    enviar(
        _envio(
            db,
            _plantilla(
                destino,
                "Verifica tu correo",
                f"Hola {usuario.nombre_completo}: escribe este código en Mi cuenta para "
                "verificar tu correo de recuperación.",
                codigo,
            ),
        )
    )
    _guardar_codigo(db, usuario, VERIFICAR, destino, codigo)
    db.commit()
    logger.info("auth.correo_verificacion_enviada usuario_id=%d", usuario.id)
    return estado(db, usuario)


def confirmar_verificacion(db: Session, usuario: Usuario, codigo: str) -> dict:
    usuario = obtener_usuario(db, usuario.id, bloquear=True)
    pendiente = _pendiente(db, usuario.id, VERIFICAR)
    if pendiente is None:
        raise ErrorDeValidacion("El código venció o ya no es válido. Pide uno nuevo.")
    if not verificar_password(_solo_digitos(codigo), pendiente.codigo_hash):
        pendiente.intentos += 1
        quedan = MAX_INTENTOS - pendiente.intentos
        db.commit()
        if quedan <= 0:
            raise ErrorDeValidacion("Código incorrecto. Ya no quedan intentos: pide uno nuevo.")
        raise ErrorDeValidacion(f"Código incorrecto. Te quedan {quedan} intentos.")
    pendiente.usado_en = ahora()
    if usuario.correo != pendiente.correo or not usuario.correo_verificado:
        _anular_pendientes(db, usuario.id, RECUPERAR)
    usuario.correo = pendiente.correo
    usuario.correo_verificado_en = ahora()
    db.commit()
    logger.warning("auth.correo_verificado usuario_id=%d", usuario.id)
    return estado(db, usuario)


def quitar(db: Session, usuario: Usuario, password_actual: str) -> dict:
    usuario = obtener_usuario(db, usuario.id, bloquear=True)
    if not verificar_password(password_actual, usuario.password_hash):
        raise ErrorDeValidacion("La contraseña actual no es correcta.")
    usuario.correo = None
    usuario.correo_verificado_en = None
    _anular_pendientes(db, usuario.id, VERIFICAR)
    _anular_pendientes(db, usuario.id, RECUPERAR)
    db.commit()
    logger.warning("auth.correo_quitado usuario_id=%d", usuario.id)
    return estado(db, usuario)


# --- Recuperar la contraseña (sin sesion) --------------------------------------


def _usuario_por_nombre(db: Session, nombre: str) -> Usuario | None:
    return db.scalar(
        select(Usuario)
        .where(Usuario.nombre_usuario == nombre)
        .options(selectinload(Usuario.rol))
        .with_for_update(of=Usuario)
        .execution_options(populate_existing=True)
    )


def solicitar_recuperacion(db: Session, nombre_usuario: str) -> Envio | None:
    """
    Si el usuario existe, puede entrar y tiene correo verificado, crea un
    codigo y devuelve el correo por enviar. Si no, None: quien llama responde
    lo mismo en ambos casos.
    """
    usuario = _usuario_por_nombre(db, nombre_usuario.strip().lower())
    if usuario is None or not usuario.puede_entrar or not usuario.correo_verificado:
        return None
    if not envio_configurado(db) or _demasiados_envios(db, usuario.id, RECUPERAR):
        return None
    codigo = _nuevo_codigo()
    codigo_id = _guardar_codigo(db, usuario, RECUPERAR, usuario.correo, codigo)
    envio = _envio(
        db,
        _plantilla(
            usuario.correo,
            "Código para recuperar tu contraseña",
            f"Hola {usuario.nombre_completo}: pediste recuperar la contraseña del usuario "
            f"«{usuario.nombre_usuario}». Escribe este código en DATACONTROL para crear una nueva.",
            codigo,
        ),
        codigo_id=codigo_id,
    )
    db.commit()
    logger.info("auth.correo_recuperacion_solicitada codigo_id=%d", codigo_id)
    return envio


def recuperar(db: Session, nombre_usuario: str, codigo: str, password_nueva: str, ip: str) -> Envio | None:
    """Cambia la contraseña con el codigo del correo. Devuelve el aviso por enviar."""
    nombre = nombre_usuario.strip().lower()
    filas, limites, cuenta = recuperacion._filas_de_intento(db, nombre, ip)
    momento = ahora()
    limpio = _solo_digitos(codigo)

    usuario = _usuario_por_nombre(db, nombre)
    candidato = None
    if usuario is not None and usuario.puede_entrar and usuario.correo_verificado:
        candidato = _pendiente(db, usuario.id, RECUPERAR, destino=usuario.correo)
    # Siempre un bcrypt, exista o no el codigo: el tiempo no delata nada.
    valido = verificar_password(
        limpio if len(limpio) == 6 else "------",
        candidato.codigo_hash if candidato else _HASH_FICTICIO,
    )

    if candidato is None or not valido:
        if candidato is not None:
            candidato.intentos += 1
        recuperacion._registrar_fallo(db, filas, limites, momento)
        db.commit()
        logger.warning("auth.recuperacion_correo_fallida cuenta=%s", cuenta[:16])
        raise CredencialesInvalidas(_MENSAJE_FALLO)

    candidato.usado_en = momento
    _anular_pendientes(db, usuario.id, RECUPERAR)
    recuperacion.poner_password_recuperada(db, usuario, password_nueva)
    recuperacion._registrar_exito(filas, cuenta, momento)
    aviso = _envio(
        db,
        _plantilla(
            usuario.correo,
            "Tu contraseña cambió",
            f"Hola {usuario.nombre_completo}: la contraseña del usuario «{usuario.nombre_usuario}» "
            "se cambió con un código enviado a este correo y se cerraron todas las sesiones.",
            None,
            "Si no fuiste tú, avisa de inmediato al administrador de DATACONTROL.",
        ),
    )
    db.commit()
    logger.warning("auth.recuperacion_con_correo usuario_id=%d", usuario.id)
    return aviso
