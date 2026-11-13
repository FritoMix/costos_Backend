"""
Logica de negocio del registro de saborizado (las recepciones).

Una orden puede tener varias recepciones. En cada una, el operario pesa
las canastillas UNA POR UNA: los kg recibidos son la suma de esos pesos
reales, nunca un estimado. El turno se detecta solo a partir de la hora.
"""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.borrado_suave import marcar_eliminado_por
from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.core.tiempo import combinar_fecha_y_hora
from app.db.auditoria import registrar, snapshot
from app.db.transacciones import atomica
from app.modules.catalogos.models import Sabor
from app.modules.catalogos.service import detectar_turno_por_hora
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.produccion.dominio.limites import validar_ventana_registro
from app.modules.produccion.models import (
    Canastilla,
    EstadoOrden,
    OrdenProduccion,
    RegistroSaborizado,
)
from app.modules.produccion.schemas import RecepcionGuardar
from app.modules.produccion.servicios.registros import bloquear_orden


def listar_recepciones(db: Session, orden_id: int) -> list[RegistroSaborizado]:
    return list(
        db.scalars(
            select(RegistroSaborizado)
            .where(
                RegistroSaborizado.orden_id == orden_id,
                RegistroSaborizado.eliminado == False,
            )
            .order_by(RegistroSaborizado.hora_inicio)
        )
        .unique()
        .all()
    )


def obtener_recepcion(db: Session, recepcion_id: int) -> RegistroSaborizado:
    recepcion = db.get(RegistroSaborizado, recepcion_id)
    if recepcion is None or recepcion.eliminado:
        raise RecursoNoEncontrado("Esa recepción no existe.")
    return recepcion


def _aplicar_datos(
    db: Session, recepcion: RegistroSaborizado, orden: OrdenProduccion, datos: RecepcionGuardar
) -> None:
    if db.get(Sabor, datos.sabor_id) is None:
        raise ErrorDeValidacion("El sabor seleccionado no es válido.")

    pesos = [peso for peso in datos.pesos_canastillas if peso is not None and peso > 0]
    if not pesos:
        raise ErrorDeValidacion("Debes registrar el peso real de al menos una canastilla.")

    turno = detectar_turno_por_hora(db, datos.hora_inicio)
    inicio, fin = combinar_fecha_y_hora(orden.fecha, datos.hora_inicio, datos.hora_fin)
    validar_ventana_registro(
        horas_produccion=orden.horas_produccion,
        inicio=inicio,
        fin=fin,
        registros=listar_recepciones(db, orden.id),
        tipo_registro="recepción de saborizado",
        excluir_id=recepcion.id,
    )

    recepcion.turno_id = turno.id
    recepcion.hora_inicio = inicio
    recepcion.hora_fin = fin
    recepcion.sabor_id = datos.sabor_id
    recepcion.cantidad_sabor_kg = datos.cantidad_sabor_kg
    recepcion.kg_recibidos = sum(pesos, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Las canastillas se reemplazan por completo con las nuevas.
    recepcion.canastillas.clear()
    for numero, peso in enumerate(pesos, start=1):
        recepcion.canastillas.append(Canastilla(numero=numero, peso_kg=peso))


@atomica
def crear_recepcion(
    db: Session, orden: OrdenProduccion, datos: RecepcionGuardar, usuario: Usuario
) -> RegistroSaborizado:
    orden = bloquear_orden(db, orden.id)
    if orden.estado != EstadoOrden.EN_PRODUCCION:
        raise ErrorDeValidacion("Solo se pueden registrar recepciones para una orden que esté En producción.")

    recepcion = RegistroSaborizado(orden_id=orden.id, usuario_id=usuario.id)
    recepcion.orden = orden
    _aplicar_datos(db, recepcion, orden, datos)
    db.add(recepcion)
    db.flush()
    db.refresh(recepcion)
    registrar(db, "saborizado", recepcion.id, "crear", usuario.id, None, snapshot(recepcion))
    return recepcion


@atomica
def editar_recepcion(
    db: Session, recepcion: RegistroSaborizado, datos: RecepcionGuardar, usuario: Usuario
) -> RegistroSaborizado:
    bloquear_orden(db, recepcion.orden_id)
    db.refresh(recepcion)
    antes = snapshot(recepcion)
    if recepcion.eliminado:
        raise RecursoNoEncontrado("Ese registro ya fue eliminado.")
    if recepcion.orden.estado != EstadoOrden.EN_PRODUCCION:
        raise ErrorDeValidacion("Solo se puede editar una recepción mientras la orden esté En producción.")
    if usuario.rol.codigo != RolCodigo.ADMIN and recepcion.usuario_id != usuario.id:
        raise ErrorDeValidacion("Solo puedes corregir las recepciones que tú mismo guardaste.")

    _aplicar_datos(db, recepcion, recepcion.orden, datos)
    db.flush()
    db.refresh(recepcion)
    registrar(db, "saborizado", recepcion.id, "editar", usuario.id, antes, snapshot(recepcion))
    return recepcion


@atomica
def eliminar_recepcion(db: Session, recepcion: RegistroSaborizado, usuario: Usuario) -> None:
    """Borrado suave (solo Administrador; ver el router)."""
    orden = bloquear_orden(db, recepcion.orden_id)
    db.refresh(recepcion)
    antes = snapshot(recepcion)
    if orden.estado != EstadoOrden.EN_PRODUCCION:
        raise ErrorDeValidacion("No se pueden borrar registros de una orden cerrada.")
    marcar_eliminado_por(db, recepcion, usuario)
    db.flush()
    registrar(db, "saborizado", recepcion.id, "eliminar", usuario.id, antes, snapshot(recepcion))
