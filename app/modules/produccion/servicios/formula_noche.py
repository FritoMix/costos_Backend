"""
Formula de la noche por horno (V20).

La bodeguera trabaja de dia. Antes de irse deja, por cada horno, la mezcla
de papa que despacho (referencias y bultos por tanda). Si en la noche se
crea o se inicia una orden en ese horno y su producto no tiene una formula
activa que sirva, la orden toma esa mezcla sola y queda marcada como
automatica. Al otro dia Bodega la confirma o la corrige.

La formula activa del producto (la de Emmanuel) siempre tiene prioridad.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.db.auditoria import registrar
from app.db.transacciones import atomica
from app.modules.catalogos.models import Horno
from app.modules.identidad.models import Usuario
from app.modules.produccion.models import FormulaNocheHorno, OrdenProduccion
from app.modules.produccion.schemas import (
    FormulaNocheFilaSalida,
    FormulaNocheGuardar,
    FormulaNocheSalida,
)
from app.modules.produccion.servicios.formula import (
    _capacidad,
    filas_de_mezcla,
    resolver_mezcla,
    validar_mezcla_en_horno,
)

logger = logging.getLogger("datacontrol")


def _filas(db: Session, horno_id: int) -> list[FormulaNocheHorno]:
    return list(
        db.scalars(
            select(FormulaNocheHorno)
            .where(FormulaNocheHorno.horno_id == horno_id)
            .order_by(FormulaNocheHorno.id)
        ).all()
    )


def _salida(horno: Horno, filas: list[FormulaNocheHorno]) -> FormulaNocheSalida:
    ultima = max(filas, key=lambda f: f.fecha_actualizacion) if filas else None
    return FormulaNocheSalida(
        horno_id=horno.id,
        horno=horno.nombre,
        filas=[
            FormulaNocheFilaSalida(
                referencia_papa_id=f.referencia_papa_id,
                nombre=f.referencia_papa.nombre,
                bultos_por_tanda=f.bultos_por_tanda,
            )
            for f in filas
        ],
        total_bultos_por_tanda=sum(f.bultos_por_tanda for f in filas),
        actualizado_por=(
            ultima.actualizado_por.nombre_completo if ultima and ultima.actualizado_por else None
        ),
        fecha_actualizacion=ultima.fecha_actualizacion if ultima else None,
    )


def listar(db: Session) -> list[FormulaNocheSalida]:
    """La formula de la noche de cada horno activo (vacia si no la han dejado)."""
    hornos = db.scalars(select(Horno).where(Horno.activo == True).order_by(Horno.nombre)).all()  # noqa: E712
    return [_salida(horno, _filas(db, horno.id)) for horno in hornos]


@atomica
def guardar(db: Session, horno_id: int, datos: FormulaNocheGuardar, usuario: Usuario) -> FormulaNocheSalida:
    """Reemplaza la formula de la noche del horno. Una lista vacia la borra."""
    horno = db.get(Horno, horno_id)
    if horno is None or not horno.activo:
        raise RecursoNoEncontrado("Ese horno no existe o está inactivo.")
    mezcla = resolver_mezcla(db, datos.referencias) if datos.referencias else []
    if mezcla:
        if horno.capacidad_bultos_hora is None:
            raise ErrorDeValidacion(
                f"El {horno.nombre} no tiene configurada su capacidad de bultos por hora. "
                "Configúrala en Hornos antes de dejar la fórmula."
            )
        total = sum(bultos for _, bultos in mezcla)
        capacidad = _capacidad(horno)
        if total > capacidad:
            raise ErrorDeValidacion(
                f"La mezcla carga {total} bultos por tanda y el {horno.nombre} admite máximo "
                f"{capacidad}. Ajusta los bultos."
            )

    anterior = _salida(horno, _filas(db, horno.id)).model_dump(mode="json")
    db.execute(delete(FormulaNocheHorno).where(FormulaNocheHorno.horno_id == horno.id))
    ahora = datetime.now(UTC)
    for referencia, bultos in mezcla:
        db.add(
            FormulaNocheHorno(
                horno_id=horno.id,
                referencia_papa_id=referencia.id,
                bultos_por_tanda=bultos,
                actualizado_por_id=usuario.id,
                fecha_actualizacion=ahora,
            )
        )
    db.flush()
    nueva = _salida(horno, _filas(db, horno.id))
    registrar(db, "formula_noche", horno.id, "guardar", usuario.id, anterior, nueva.model_dump(mode="json"))
    return nueva


def aplicar_a_orden(db: Session, orden: OrdenProduccion) -> bool:
    """
    Copia la formula de la noche del horno a una orden que no tiene mezcla.
    Devuelve False sin tocar la orden si el horno no tiene formula de la
    noche o si no sirve para esta orden (capacidad o cantidad pedida).
    """
    if orden.referencias:
        return True
    filas = _filas(db, orden.horno_id)
    if not filas:
        return False
    try:
        mezcla = resolver_mezcla(db, filas)
        validar_mezcla_en_horno(
            mezcla,
            horno=orden.horno,
            horas_produccion=orden.horas_produccion,
            cantidad_programada=orden.cantidad_programada,
        )
    except ErrorDeValidacion as exc:
        logger.warning("Fórmula de la noche no aplicable a %s: %s", orden.numero_orden, exc)
        return False

    autor = filas[0].actualizado_por_id or orden.supervisor_id
    orden.referencias.clear()
    db.flush()
    orden.referencias.extend(filas_de_mezcla(orden, mezcla, autor))
    orden.formula_notas = f"Fórmula de la noche del {orden.horno.nombre}. Bodega debe confirmarla."
    orden.formula_actualizada_por_id = autor
    orden.formula_fecha_actualizacion = datetime.now(UTC)
    orden.formula_automatica = True
    db.flush()
    db.refresh(orden)
    return True


@atomica
def confirmar(db: Session, orden: OrdenProduccion, usuario: Usuario) -> OrdenProduccion:
    """Bodega revisa la formula que puso la app y la da por buena."""
    if not orden.formula_automatica:
        return orden
    orden.formula_automatica = False
    if orden.formula_notas and orden.formula_notas.startswith("Fórmula de la noche"):
        orden.formula_notas = f"Fórmula de la noche del {orden.horno.nombre}, confirmada por Bodega."
    db.flush()
    registrar(db, "formula_orden", orden.id, "confirmar_formula_noche", usuario.id, None, None)
    db.refresh(orden)
    return orden
