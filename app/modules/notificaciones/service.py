"""
Logica del modulo Notificaciones.

Dos avisos, ambos pensados para que el operario no tenga que estar
mirando la pantalla:

  1) "Nueva orden": apenas el supervisor crea la orden, le llega a todo el
     personal (en la noche no hay Bodega que la reciba).
  2) "Faltan 15 minutos": cuando la orden entra en produccion se calcula
     el final (hora de inicio + horas programadas) y se deja el aviso
     guardado con fecha futura. La API lo entrega cuando llega su hora,
     sin necesidad de ningun proceso en segundo plano.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errores import RecursoNoEncontrado
from app.core.tiempo import ZONA_HORARIA_LOCAL
from app.db.transacciones import atomica
from app.modules.identidad.models import Rol, RolCodigo, Usuario
from app.modules.notificaciones.models import Notificacion, TipoNotificacion

logger = logging.getLogger("datacontrol")

# Cuanto antes del final se avisa que la produccion esta por terminar.
MINUTOS_DE_AVISO_PREVIO = 15
# Si nadie finaliza la orden, la app la cierra este tiempo despues del fin.
MINUTOS_PARA_CIERRE_AUTOMATICO = 30


def _destinatarios_por_rol(db: Session, codigos: list[str]) -> list[Usuario]:
    """Usuarios activos que tienen alguno de esos roles."""
    return list(
        db.scalars(
            select(Usuario)
            .join(Rol)
            .where(
                Usuario.eliminado == False,
                Usuario.activo == True,
                Rol.codigo.in_(codigos),
            )
        ).all()
    )


def _destinatarios_operarios(db: Session) -> list[Usuario]:
    """Operarios de horno y saborizado activos: son quienes trabajan la orden."""
    return _destinatarios_por_rol(
        db, [RolCodigo.OPERARIO_HORNO, RolCodigo.OPERARIO_SABORIZADO]
    )


def _destinatarios_jefes(db: Session) -> list[Usuario]:
    """Supervisores y administradores activos: quienes cierran las ordenes."""
    return _destinatarios_por_rol(db, [RolCodigo.SUPERVISOR, RolCodigo.ADMIN])


def _destinatarios_bodega(db: Session) -> list[Usuario]:
    """Bodegueros activos: ellos definen la formula de la orden."""
    return _destinatarios_por_rol(db, [RolCodigo.BODEGUERO])


def _crear_para(
    db: Session,
    *,
    usuarios: list[Usuario],
    tipo: str,
    titulo: str,
    mensaje: str,
    orden_id: int | None,
    fecha_programada: datetime | None = None,
) -> int:
    """
    Crea el aviso para cada destinatario. Devuelve cuantos se crearon.

    El indice unico de la tabla evita duplicar el mismo aviso para la misma
    orden y persona; si eso pasa (por ejemplo, una orden que se reinicia),
    simplemente no se vuelve a crear.
    """
    creados = 0
    for usuario in usuarios:
        notificacion = Notificacion(
            usuario_id=usuario.id,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            orden_id=orden_id,
            fecha_programada=fecha_programada or datetime.now(UTC),
        )
        try:
            # Savepoint por aviso: si este choca con el indice unico, solo
            # se descarta este. Un rollback normal revertiria tambien los
            # avisos ya preparados en la misma transaccion.
            with db.begin_nested():
                db.add(notificacion)
                db.flush()
            creados += 1
        except IntegrityError as exc:
            # No esconder violaciones de FK, NOT NULL o CHECK como duplicados.
            codigo = getattr(exc.orig, "sqlstate", None)
            sqlite_unique = getattr(exc.orig, "sqlite_errorname", "") == "SQLITE_CONSTRAINT_UNIQUE"
            restriccion = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            if not sqlite_unique and not (
                codigo == "23505" and restriccion == "ux_notificacion_unica_por_orden"
            ):
                raise
            continue
    return creados


def _crear_o_actualizar(
    db: Session,
    *,
    usuarios: list[Usuario],
    tipo: str,
    titulo: str,
    mensaje: str,
    orden_id: int,
) -> int:
    """
    Deja el aviso actualizado para cada destinatario.

    Si Bodega corrige la formula antes de iniciar, el aviso de la misma orden
    y persona se actualiza (texto, fecha y "no leida") en vez de duplicarse:
    el indice unico (usuario, orden, tipo) ya impide la segunda fila.
    """
    if not usuarios:
        return 0
    existentes = {
        notificacion.usuario_id: notificacion
        for notificacion in db.scalars(
            select(Notificacion).where(
                Notificacion.orden_id == orden_id,
                Notificacion.tipo == tipo,
                Notificacion.usuario_id.in_([usuario.id for usuario in usuarios]),
            )
        ).all()
    }
    cambiados = 0
    for usuario in usuarios:
        notificacion = existentes.get(usuario.id)
        if notificacion is None:
            continue
        notificacion.titulo = titulo
        notificacion.mensaje = mensaje
        notificacion.fecha_programada = datetime.now(UTC)
        notificacion.leida = False
        cambiados += 1
    creados = _crear_para(
        db,
        usuarios=[usuario for usuario in usuarios if usuario.id not in existentes],
        tipo=tipo,
        titulo=titulo,
        mensaje=mensaje,
        orden_id=orden_id,
    )
    return cambiados + creados


@atomica
def avisar_orden_para_bodega(db: Session, orden) -> None:
    """
    Aviso a Bodega: hay una orden nueva pendiente de formula.

    Las ordenes nuevas ya no avisan a los operarios al crearse: todavia no
    se pueden producir. Horno se enterara cuando la formula quede lista.
    """
    bodegueros = _destinatarios_bodega(db)
    if not bodegueros:
        return

    destino = (orden.destino or "").capitalize()
    horas = orden.horas_produccion
    duracion = f" · {horas} {'hora' if horas == 1 else 'horas'}" if horas else ""

    if getattr(orden, "formula_automatica", False):
        # La app le puso la formula de la noche: Bodega la confirma al llegar.
        titulo = f"Confirma la fórmula de la noche · {orden.numero_orden}"
        estado = "Tomó la fórmula de la noche del horno. Confírmala o corrígela."
    else:
        titulo = f"Orden pendiente de fórmula · {orden.numero_orden}"
        estado = "Pendiente de fórmula."
    _crear_para(
        db,
        usuarios=bodegueros,
        tipo=TipoNotificacion.ORDEN_PARA_BODEGA,
        titulo=titulo,
        mensaje=(
            f"Nueva orden {orden.numero_orden} de {orden.producto.nombre_comercial} "
            f"({destino}) · {orden.cantidad_programada} kg{duracion} · "
            f"{orden.horno.nombre}. {estado}"
        ),
        orden_id=orden.id,
    )
    db.flush()


@atomica
def avisar_formula_lista(db: Session, orden) -> None:
    """
    Aviso a horno y al supervisor: la formula quedo lista para producir.

    No se reutiliza `_destinatarios_operarios` porque saborizado no trabaja
    la mezcla de papa: solo avisa a horno y al supervisor de la orden.
    """
    destinatarios = _destinatarios_por_rol(db, [RolCodigo.OPERARIO_HORNO])
    supervisor = orden.supervisor
    if supervisor is not None and supervisor.eliminado is False and supervisor.activo:
        destinatarios.append(supervisor)
    if not destinatarios:
        return

    _crear_o_actualizar(
        db,
        usuarios=destinatarios,
        tipo=TipoNotificacion.FORMULA_LISTA,
        titulo=f"Fórmula lista · {orden.numero_orden}",
        mensaje=(
            f"Fórmula lista para {orden.numero_orden}: {orden.producto.nombre_comercial} "
            f"· {orden.horno.nombre}. Revisa la mezcla en la orden."
        ),
        orden_id=orden.id,
    )
    db.flush()


@atomica
def avisar_orden_creada(
    db: Session, orden, *, formula_lista: bool, bodega_avisada: bool | None = None
) -> int:
    """
    "Nueva orden" para todo el personal activo, cada rol con lo que le toca.

    En la noche no hay bodeguera: si el aviso solo le llegara a Bodega, nadie
    en planta se enteraria de la orden. No se repite el aviso a quien ya
    recibe el suyo por el flujo de la formula (Bodega cuando falta la
    formula; Horno y el supervisor de la orden cuando ya quedo lista), ni a
    quien creo la orden. Devuelve cuantos avisos se crearon.
    """
    if bodega_avisada is None:
        bodega_avisada = not formula_lista
    ya_avisados: set[int] = {orden.supervisor_id}
    if formula_lista:
        ya_avisados |= {u.id for u in _destinatarios_por_rol(db, [RolCodigo.OPERARIO_HORNO])}
    if bodega_avisada:
        ya_avisados |= {u.id for u in _destinatarios_bodega(db)}

    horas = orden.horas_produccion
    duracion = f" · {horas} {'hora' if horas == 1 else 'horas'}" if horas else ""
    base = (
        f"{orden.producto.nombre_comercial} en {orden.horno.nombre}{duracion}. "
        f"Meta: {orden.cantidad_programada} kg."
    )
    if formula_lista:
        estado = "La fórmula ya quedó lista: se puede producir."
    else:
        estado = "Pendiente de la fórmula de Bodega antes de producir."

    tareas = {
        RolCodigo.OPERARIO_HORNO: "Alista el horno.",
        RolCodigo.OPERARIO_SABORIZADO: "Alista el saborizado.",
        RolCodigo.BODEGUERO: "Revisa la papa para esta orden.",
        RolCodigo.SUPERVISOR: "Para tu seguimiento.",
        RolCodigo.ADMIN: "Para tu seguimiento.",
    }
    creados = 0
    for rol, tarea in tareas.items():
        usuarios = [u for u in _destinatarios_por_rol(db, [rol]) if u.id not in ya_avisados]
        if not usuarios:
            continue
        ya_avisados |= {u.id for u in usuarios}
        creados += _crear_para(
            db,
            usuarios=usuarios,
            tipo=TipoNotificacion.ORDEN_CREADA,
            titulo=f"Nueva orden {orden.numero_orden}",
            mensaje=f"{base} {estado} {tarea}",
            orden_id=orden.id,
        )
    db.flush()
    return creados


@atomica
def programar_aviso_fin_produccion(db: Session, orden) -> None:
    """
    Deja programados, al entrar la orden en produccion:
      * "faltan 15 minutos" para los operarios, y
      * "se acabo el tiempo" para supervisores y administradores (V19),
        que avisa ademas a que hora la cerrara la app si nadie lo hace.

    Si la orden no tiene horas programadas (las creadas antes de esa
    funcion), no hay nada que avisar.
    """
    if not orden.horas_produccion or orden.hora_inicio is None:
        return

    ahora = datetime.now(UTC)
    fin = orden.hora_inicio + timedelta(hours=int(orden.horas_produccion))
    # Si la produccion es tan corta que el aviso ya quedo en el pasado, se
    # entrega de inmediato en vez de perderse.
    momento_aviso = max(fin - timedelta(minutes=MINUTOS_DE_AVISO_PREVIO), ahora)
    # Hora de la planta, no la del servidor (en Render el servidor esta en UTC).
    hora_fin = fin.astimezone(ZONA_HORARIA_LOCAL).strftime("%H:%M")
    hora_cierre = (
        (fin + timedelta(minutes=MINUTOS_PARA_CIERRE_AUTOMATICO))
        .astimezone(ZONA_HORARIA_LOCAL)
        .strftime("%H:%M")
    )

    operarios = _destinatarios_operarios(db)
    if operarios:
        _crear_para(
            db,
            usuarios=operarios,
            tipo=TipoNotificacion.PRODUCCION_POR_TERMINAR,
            titulo=f"Faltan {MINUTOS_DE_AVISO_PREVIO} minutos · {orden.numero_orden}",
            mensaje=(
                f"La producción de {orden.producto.nombre_comercial} en {orden.horno.nombre} "
                f"termina a las {hora_fin}. Prepara el cierre."
            ),
            orden_id=orden.id,
            fecha_programada=momento_aviso,
        )

    jefes = _destinatarios_jefes(db)
    if jefes:
        _crear_para(
            db,
            usuarios=jefes,
            tipo=TipoNotificacion.PRODUCCION_TERMINADA,
            titulo=f"Se acabó el tiempo · cierra la orden {orden.numero_orden}",
            mensaje=(
                f"{orden.producto.nombre_comercial} en {orden.horno.nombre} terminó a las "
                f"{hora_fin}. Ábrela y finalízala. Si nadie la cierra, la app la cerrará "
                f"sola a las {hora_cierre}."
            ),
            orden_id=orden.id,
            fecha_programada=max(fin, ahora),
        )
    db.flush()


# --- Cierre automatico (V19) -------------------------------------------------

_ultima_revision: datetime | None = None


def revisar_ordenes_vencidas(db: Session) -> int:
    """
    Finaliza las ordenes que siguen En produccion 30 minutos despues de su
    hora de fin y avisa a supervisores y administradores.

    No hay procesos en segundo plano: se llama cuando alguien consulta sus
    avisos (la app lo hace cada pocos segundos) y corre como maximo una vez
    por minuto. Un error con una orden no afecta los avisos de nadie.
    Devuelve cuantas ordenes cerro.
    """
    global _ultima_revision
    ahora = datetime.now(UTC)
    if _ultima_revision is not None and ahora - _ultima_revision < timedelta(minutes=1):
        return 0
    _ultima_revision = ahora

    try:
        recordar_formula_noche(db)
    except Exception:  # noqa: BLE001
        db.rollback()
        logger.exception("No se pudo crear el recordatorio de la fórmula de la noche")

    from app.modules.produccion.models import EstadoOrden, OrdenProduccion
    from app.modules.produccion.servicios import ordenes as servicio_ordenes

    candidatas = db.scalars(
        select(OrdenProduccion).where(
            OrdenProduccion.estado == EstadoOrden.EN_PRODUCCION,
            OrdenProduccion.eliminado == False,  # noqa: E712
            OrdenProduccion.hora_inicio.is_not(None),
            OrdenProduccion.horas_produccion.is_not(None),
        )
    ).all()
    cerradas = 0
    for orden in candidatas:
        fin = orden.hora_inicio + timedelta(hours=int(orden.horas_produccion))
        if ahora < fin + timedelta(minutes=MINUTOS_PARA_CIERRE_AUTOMATICO):
            continue
        try:
            orden = servicio_ordenes.finalizar_orden(db, orden)
            orden.cerrada_automaticamente = True
            _crear_para(
                db,
                usuarios=_destinatarios_jefes(db),
                tipo=TipoNotificacion.ORDEN_CERRADA_SOLA,
                titulo=f"La app cerró la orden {orden.numero_orden}",
                mensaje=(
                    f"Nadie la cerró {MINUTOS_PARA_CIERRE_AUTOMATICO} minutos después de su hora "
                    "de fin, así que quedó Finalizada. Revisa que las tandas y recepciones estén "
                    "completas."
                ),
                orden_id=orden.id,
            )
            db.commit()
            cerradas += 1
        except Exception:  # noqa: BLE001
            db.rollback()
            logger.exception("No se pudo cerrar sola la orden %s", orden.numero_orden)
    return cerradas


# --- Recordatorio a Bodega (V20) ---------------------------------------------

# Bodega sale a las 5 pm: a las 4:45 se le recuerda dejar la formula de la noche.
HORA_RECORDATORIO_BODEGA = (16, 45)


def recordar_formula_noche(db: Session, ahora_local: datetime | None = None) -> int:
    """
    Una vez al dia, desde las 4:45 pm, le recuerda a cada bodeguero activo
    dejar la formula de la noche de cada horno. Devuelve cuantos creo.
    """
    ahora_local = ahora_local or datetime.now(ZONA_HORARIA_LOCAL)
    if (ahora_local.hour, ahora_local.minute) < HORA_RECORDATORIO_BODEGA:
        return 0
    inicio_dia = ahora_local.replace(hour=0, minute=0, second=0, microsecond=0)
    ya_recordados = set(
        db.scalars(
            select(Notificacion.usuario_id).where(
                Notificacion.tipo == TipoNotificacion.RECORDAR_FORMULA_NOCHE,
                Notificacion.fecha_programada >= inicio_dia,
            )
        ).all()
    )
    pendientes = [u for u in _destinatarios_bodega(db) if u.id not in ya_recordados]
    if not pendientes:
        return 0
    creados = _crear_para(
        db,
        usuarios=pendientes,
        tipo=TipoNotificacion.RECORDAR_FORMULA_NOCHE,
        titulo="Deja la fórmula de la noche",
        mensaje=(
            "Antes de irte, deja en cada horno la papa que despachaste para la noche. "
            "Las órdenes de la noche la toman solas y mañana las confirmas."
        ),
        orden_id=None,
        fecha_programada=ahora_local.astimezone(UTC),
    )
    db.commit()
    return creados


# --- Consulta y lectura ----------------------------------------------------


def pendientes(db: Session, usuario: Usuario) -> list[Notificacion]:
    """
    Avisos que ya cumplieron su hora y que esta persona no ha visto. Son los
    que el frontend muestra y con los que suena la alarma.

    Los avisos de reloj ("faltan 15 minutos", "se acabo el tiempo") de una
    orden que ya no esta en produccion se dan por vistos sin sonar.
    """
    lista = _pendientes(db, usuario)
    ids = {n.orden_id for n in lista if n.tipo in TipoNotificacion.DEL_RELOJ and n.orden_id}
    if not ids:
        return lista

    from app.modules.produccion.models import EstadoOrden, OrdenProduccion

    cerradas = set(
        db.scalars(
            select(OrdenProduccion.id).where(
                OrdenProduccion.id.in_(ids), OrdenProduccion.estado != EstadoOrden.EN_PRODUCCION
            )
        ).all()
    )
    if not cerradas:
        return lista
    vigentes = []
    for n in lista:
        if n.tipo in TipoNotificacion.DEL_RELOJ and n.orden_id in cerradas:
            n.leida = True
        else:
            vigentes.append(n)
    db.commit()
    return vigentes


def _pendientes(db: Session, usuario: Usuario) -> list[Notificacion]:
    return list(
        db.scalars(
            select(Notificacion)
            .where(
                Notificacion.usuario_id == usuario.id,
                Notificacion.leida == False,
                Notificacion.fecha_programada <= datetime.now(UTC),
            )
            .order_by(Notificacion.fecha_programada.desc())
            .limit(20)
        ).all()
    )


def historial(db: Session, usuario: Usuario) -> list[Notificacion]:
    """Ultimos avisos entregados (leidos o no), para la campana."""
    return list(
        db.scalars(
            select(Notificacion)
            .where(
                Notificacion.usuario_id == usuario.id,
                Notificacion.fecha_programada <= datetime.now(UTC),
            )
            .order_by(Notificacion.fecha_programada.desc())
            .limit(30)
        ).all()
    )


@atomica
def marcar_leida(db: Session, notificacion_id: int, usuario: Usuario) -> None:
    notificacion = db.get(Notificacion, notificacion_id)
    if notificacion is None or notificacion.usuario_id != usuario.id:
        raise RecursoNoEncontrado("Ese aviso no existe.")
    notificacion.leida = True
    db.flush()


@atomica
def marcar_todas_leidas(db: Session, usuario: Usuario) -> None:
    for notificacion in pendientes(db, usuario):
        notificacion.leida = True
    db.flush()
