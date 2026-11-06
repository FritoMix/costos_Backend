"""
Logica del modulo Notificaciones.

Dos avisos, ambos pensados para que el operario no tenga que estar
mirando la pantalla:

  1) "Nueva orden": apenas el supervisor crea la orden, les llega a los
     operarios de horno y saborizado.
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
from app.modules.identidad.models import Rol, RolCodigo, Usuario
from app.modules.notificaciones.models import Notificacion, TipoNotificacion

logger = logging.getLogger("datacontrol")

# Cuanto antes del final se avisa que la produccion esta por terminar.
MINUTOS_DE_AVISO_PREVIO = 15


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
        except IntegrityError:
            # El aviso ya existia (misma persona, orden y tipo).
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

    _crear_para(
        db,
        usuarios=bodegueros,
        tipo=TipoNotificacion.ORDEN_PARA_BODEGA,
        titulo=f"Orden pendiente de fórmula · {orden.numero_orden}",
        mensaje=(
            f"Nueva orden {orden.numero_orden} de {orden.producto.nombre_comercial} "
            f"({destino}) · {orden.cantidad_programada} kg{duracion} · "
            f"{orden.horno.nombre}. Pendiente de fórmula."
        ),
        orden_id=orden.id,
    )
    db.commit()


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
    db.commit()


def avisar_orden_creada(db: Session, orden) -> None:
    """Aviso inmediato a los operarios: hay una orden nueva que trabajar."""
    operarios = _destinatarios_operarios(db)
    if not operarios:
        return

    horas = orden.horas_produccion
    duracion = f" · {horas} {'hora' if horas == 1 else 'horas'} de producción" if horas else ""

    _crear_para(
        db,
        usuarios=operarios,
        tipo=TipoNotificacion.ORDEN_CREADA,
        titulo=f"Nueva orden {orden.numero_orden}",
        mensaje=(
            f"{orden.producto.nombre_comercial} en {orden.horno.nombre}{duracion}. "
            f"Meta: {orden.cantidad_programada} kg."
        ),
        orden_id=orden.id,
    )
    db.commit()


def programar_aviso_fin_produccion(db: Session, orden) -> None:
    """
    Deja programado el aviso de "faltan 15 minutos".

    Se llama cuando la orden entra en produccion, que es cuando de verdad
    empieza a correr el reloj. Si la orden no tiene horas programadas (las
    creadas antes de esa funcion), no hay nada que avisar.
    """
    if not orden.horas_produccion or orden.hora_inicio is None:
        return

    fin = orden.hora_inicio + timedelta(hours=int(orden.horas_produccion))
    momento_aviso = fin - timedelta(minutes=MINUTOS_DE_AVISO_PREVIO)

    # Si la produccion es tan corta que el aviso ya quedo en el pasado, se
    # entrega de inmediato en vez de perderse.
    if momento_aviso < datetime.now(UTC):
        momento_aviso = datetime.now(UTC)

    operarios = _destinatarios_operarios(db)
    if not operarios:
        return

    _crear_para(
        db,
        usuarios=operarios,
        tipo=TipoNotificacion.PRODUCCION_POR_TERMINAR,
        titulo=f"Faltan {MINUTOS_DE_AVISO_PREVIO} minutos · {orden.numero_orden}",
        mensaje=(
            f"La producción de {orden.producto.nombre_comercial} en {orden.horno.nombre} "
            f"termina a las {fin.astimezone().strftime('%H:%M')}. Prepara el cierre."
        ),
        orden_id=orden.id,
        fecha_programada=momento_aviso,
    )
    db.commit()


# --- Consulta y lectura ----------------------------------------------------


def pendientes(db: Session, usuario: Usuario) -> list[Notificacion]:
    """
    Avisos que ya cumplieron su hora y que esta persona no ha visto. Son los
    que el frontend muestra y con los que suena la alarma.
    """
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


def marcar_leida(db: Session, notificacion_id: int, usuario: Usuario) -> None:
    notificacion = db.get(Notificacion, notificacion_id)
    if notificacion is None or notificacion.usuario_id != usuario.id:
        raise RecursoNoEncontrado("Ese aviso no existe.")
    notificacion.leida = True
    db.commit()


def marcar_todas_leidas(db: Session, usuario: Usuario) -> None:
    for notificacion in pendientes(db, usuario):
        notificacion.leida = True
    db.commit()
