"""
Logica de negocio del registro de saborizado (las recepciones).

Una orden puede tener varias recepciones. En cada una, el operario pesa
las canastillas UNA POR UNA: los kg recibidos son la suma de esos pesos
reales, nunca un estimado. El turno se detecta solo a partir de la hora.
"""

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.borrado_suave import marcar_eliminado_por
from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.core.tiempo import combinar_fecha_y_hora
from app.modules.catalogos.models import Sabor
from app.modules.catalogos.service import detectar_turno_por_hora
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.produccion.models import (
    Canastilla,
    EstadoOrden,
    OrdenProduccion,
    RegistroSaborizado,
)
from app.modules.produccion.schemas import RecepcionGuardar


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

    recepcion.turno_id = turno.id
    recepcion.hora_inicio = inicio
    recepcion.hora_fin = fin
    recepcion.sabor_id = datos.sabor_id
    recepcion.cantidad_sabor_kg = datos.cantidad_sabor_kg
    recepcion.kg_recibidos = sum(pesos, Decimal("0")).quantize(Decimal("0.01"))

    # Las canastillas se reemplazan por completo con las nuevas.
    recepcion.canastillas.clear()
    for numero, peso in enumerate(pesos, start=1):
        recepcion.canastillas.append(Canastilla(numero=numero, peso_kg=peso))


def crear_recepcion(
    db: Session, orden: OrdenProduccion, datos: RecepcionGuardar, usuario: Usuario
) -> RegistroSaborizado:
    if orden.estado != EstadoOrden.EN_PRODUCCION:
        raise ErrorDeValidacion(
            "Solo se pueden registrar recepciones para una orden que esté En producción."
        )

    recepcion = RegistroSaborizado(orden_id=orden.id, usuario_id=usuario.id)
    recepcion.orden = orden
    _aplicar_datos(db, recepcion, orden, datos)
    db.add(recepcion)
    db.commit()
    db.refresh(recepcion)
    return recepcion


def editar_recepcion(
    db: Session, recepcion: RegistroSaborizado, datos: RecepcionGuardar, usuario: Usuario
) -> RegistroSaborizado:
    if recepcion.orden.estado != EstadoOrden.EN_PRODUCCION:
        raise ErrorDeValidacion(
            "Solo se puede editar una recepción mientras la orden esté En producción."
        )
    if usuario.rol.codigo != RolCodigo.ADMIN and recepcion.usuario_id != usuario.id:
        raise ErrorDeValidacion("Solo puedes corregir las recepciones que tú mismo guardaste.")

    _aplicar_datos(db, recepcion, recepcion.orden, datos)
    db.commit()
    db.refresh(recepcion)
    return recepcion


def eliminar_recepcion(db: Session, recepcion: RegistroSaborizado, usuario: Usuario) -> None:
    """Borrado suave (solo Administrador; ver el router)."""
    marcar_eliminado_por(db, recepcion, usuario)
    db.commit()
