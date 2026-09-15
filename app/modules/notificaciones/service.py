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


def _destinatarios_operarios(db: Session) -> list[Usuario]:
    """Operarios de horno y saborizado activos: son quienes trabajan la orden."""
    return list(
        db.scalars(
            select(Usuario)
            .join(Rol)
            .where(
                Usuario.eliminado == False,
                Usuario.activo == True,
                Rol.codigo.in_([RolCodigo.OPERARIO_HORNO, RolCodigo.OPERARIO_SABORIZADO]),
            )
        ).all()
    )


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
        db.add(notificacion)
        try:
            # Cada aviso se guarda por separado: si uno choca con el indice
            # unico, no se pierden los demas.
            db.flush()
            creados += 1
        except IntegrityError:
            db.rollback()
    return creados


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
