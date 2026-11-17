"""Coordinación de operaciones de órdenes y fachada estable para los routers.

Cada escritura mantiene un único límite @atomica: validación, fórmula,
notificaciones y auditoría se confirman juntas. Las funciones de lectura y
numeración se reexportan para conservar los puntos de entrada existentes.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.borrado_suave import marcar_eliminado_por
from app.core.errores import ErrorDeValidacion
from app.core.tiempo import hoy_local
from app.db.auditoria import estado_orden, registrar
from app.db.transacciones import atomica
from app.modules.identidad.models import Usuario
from app.modules.notificaciones import service as notificaciones
from app.modules.produccion.dominio.estados import requiere_transicion
from app.modules.produccion.dominio.limites import validar_conteo_tandas, validar_horas_de_orden
from app.modules.produccion.models import EstadoOrden, OrdenProduccion, RegistroHorno, RegistroSaborizado
from app.modules.produccion.schemas import OrdenGuardar
from app.modules.produccion.servicios import formula as servicio_formula
from app.modules.produccion.servicios import formulas_papa as servicio_formulas_papa
from app.modules.produccion.servicios.cantidades_ordenes import calcular_cantidad_programada
from app.modules.produccion.servicios.consultas_ordenes import (
    buscar_orden_en_horno,
    listar_ordenes,
    obtener_orden,
    pagina_ordenes,
)
from app.modules.produccion.servicios.numeracion_ordenes import generar_numero_orden
from app.modules.produccion.servicios.registros import bloquear_orden
from app.modules.produccion.servicios.validaciones_ordenes import validar_catalogos

__all__ = [
    "obtener_orden", "listar_ordenes", "pagina_ordenes", "generar_numero_orden",
    "calcular_cantidad_programada", "crear_orden", "editar_orden", "iniciar_orden",
    "finalizar_orden", "cancelar_orden", "eliminar_orden",
]


def _guardar_cambio_de_horno(db: Session, orden: OrdenProduccion) -> None:
    """Flush y recarga sin commit; @atomica sigue siendo el dueño de la transacción."""
    try:
        db.flush()
    except IntegrityError as exc:
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) != "ux_un_horno_en_produccion":
            raise
        # Defensa final si dos operaciones observaron el mismo horno libre.
        raise ErrorDeValidacion(
            "Ese horno acaba de quedar ocupado por otra orden. Intenta de nuevo."
        ) from exc
    db.refresh(orden)


@atomica
def crear_orden(db: Session, datos: OrdenGuardar, supervisor: Usuario) -> OrdenProduccion:
    _horno, producto = validar_catalogos(db, datos)
    cantidad_kg, canastillas = calcular_cantidad_programada(db, datos, producto)

    fecha = hoy_local()
    orden = OrdenProduccion(
        numero_orden=generar_numero_orden(db, fecha),
        fecha=fecha,
        supervisor_id=supervisor.id,
        turno_id=datos.turno_id,
        horno_id=datos.horno_id,
        producto_id=datos.producto_id,
        categoria_id=datos.categoria_id,
        cantidad_programada=cantidad_kg,
        unidad_solicitada=datos.unidad_solicitada,
        cantidad_canastillas_solicitadas=canastillas,
        horas_produccion=datos.horas_produccion,
        destino=datos.destino,
        estado=EstadoOrden.PENDIENTE,
        # Las ordenes nuevas exigen que Bodega defina la mezcla antes de
        # producir. Las historicas conservan formula_obligatoria = FALSE.
        formula_obligatoria=True,
    )
    db.add(orden)
    db.flush()
    aplicada = servicio_formulas_papa.aplicar_a_orden(db, orden)
    if aplicada:
        notificaciones.avisar_formula_lista(db, orden)
    else:
        notificaciones.avisar_orden_para_bodega(db, orden)
    db.flush()
    db.refresh(orden)

    registrar(db, "orden", orden.id, "crear", supervisor.id, None, estado_orden(orden))
    return orden


@atomica
def editar_orden(
    db: Session, orden: OrdenProduccion, datos: OrdenGuardar, usuario: Usuario | None = None
) -> OrdenProduccion:
    """
    Corrige una orden ya creada, por si el supervisor se equivoco. Solo
    mientras sigue activa: una vez Finalizada o Cancelada no se toca.
    """
    orden = bloquear_orden(db, orden.id)
    antes = estado_orden(orden)
    if orden.estado not in EstadoOrden.ACTIVOS:
        raise ErrorDeValidacion("Esta orden ya no se puede editar porque está Finalizada o Cancelada.")

    cambia_producto = datos.producto_id != orden.producto_id or datos.categoria_id != orden.categoria_id
    if cambia_producto and orden.estado == EstadoOrden.EN_PRODUCCION:
        raise ErrorDeValidacion("No puedes cambiar el producto de una orden que ya está en producción.")
    anterior_formula = None
    if cambia_producto and orden.referencias:
        anterior_formula = servicio_formula.obtener(db, orden).model_dump(mode="json")
        orden.referencias.clear()
        orden.formula_papa_id = None
        orden.formula_notas = None
        orden.formula_actualizada_por_id = None
        orden.formula_fecha_actualizacion = None
        db.flush()
    horno, producto = validar_catalogos(db, datos, turno_actual_id=orden.turno_id)

    if datos.horas_produccion is not None:
        registros_horno = db.scalars(
            select(RegistroHorno).where(
                RegistroHorno.orden_id == orden.id,
                RegistroHorno.eliminado.is_(False),
            )
        ).all()
        registros_saborizado = db.scalars(
            select(RegistroSaborizado).where(
                RegistroSaborizado.orden_id == orden.id,
                RegistroSaborizado.eliminado.is_(False),
            )
        ).all()
        validar_horas_de_orden(
            horas_nuevas=datos.horas_produccion,
            registros_horno=registros_horno,
            registros_saborizado=registros_saborizado,
        )
        # Una orden de N horas acepta maximo N tandas de horno.
        validar_conteo_tandas(
            horas_produccion=datos.horas_produccion,
            registros=registros_horno,
            al_editar_horas=True,
        )

    if orden.estado == EstadoOrden.EN_PRODUCCION and datos.horno_id != orden.horno_id:
        # Cambiar de horno con la orden ya en produccion vuelve a chocar
        # con la regla de "un horno, una orden a la vez".
        ocupado = buscar_orden_en_horno(db, datos.horno_id, excluir_id=orden.id)
        if ocupado is not None:
            raise ErrorDeValidacion(f"Ese horno ya tiene la orden {ocupado.numero_orden} en producción.")

    cantidad_kg, canastillas = calcular_cantidad_programada(db, datos, producto)

    # Si la orden ya tiene formula (Pendiente y sin tandas), el cambio de
    # horas, horno o cantidad debe seguir cabiendo en la capacidad fisica.
    # Si la formula quedo congelada (En produccion o con tandas), no se toca.
    servicio_formula.validar_cambio_orden(
        db,
        orden,
        horno=horno,
        horas_produccion=datos.horas_produccion,
        cantidad_programada=cantidad_kg,
    )

    orden.turno_id = datos.turno_id
    orden.horno_id = datos.horno_id
    orden.producto_id = datos.producto_id
    orden.categoria_id = datos.categoria_id
    orden.unidad_solicitada = datos.unidad_solicitada
    orden.cantidad_canastillas_solicitadas = canastillas
    orden.horas_produccion = datos.horas_produccion
    orden.cantidad_programada = cantidad_kg
    orden.destino = datos.destino

    _guardar_cambio_de_horno(db, orden)

    # Con las horas nuevas, los totales planificados de la formula se
    # recalculan (la mezcla por tanda no cambia).
    if orden.referencias and orden.estado == EstadoOrden.PENDIENTE:
        servicio_formula.recalcular_totales(db, orden)
        db.flush()
        db.refresh(orden)
    if cambia_producto:
        aplicada = servicio_formulas_papa.aplicar_a_orden(db, orden)
        if aplicada:
            notificaciones.avisar_formula_lista(db, orden)
        else:
            notificaciones.avisar_orden_para_bodega(db, orden)
        registrar(
            db,
            "formula_orden",
            orden.id,
            "cambiar_producto",
            usuario.id if usuario else None,
            anterior_formula,
            servicio_formula.obtener(db, orden).model_dump(mode="json"),
        )
    registrar(db, "orden", orden.id, "editar", usuario.id if usuario else None, antes, estado_orden(orden))
    return orden


@atomica
def iniciar_orden(db: Session, orden: OrdenProduccion, usuario: Usuario | None = None) -> OrdenProduccion:
    orden = bloquear_orden(db, orden.id)
    antes = estado_orden(orden)
    if not requiere_transicion(orden.estado, "iniciar"):
        return orden

    ocupado = buscar_orden_en_horno(db, orden.horno_id)
    if ocupado is not None:
        raise ErrorDeValidacion(
            f'El horno "{orden.horno.nombre}" ya tiene la orden {ocupado.numero_orden} en '
            "producción. Debes finalizarla antes de iniciar otra."
        )

    # Una plantilla puede activarse o corregirse despues de crear la orden.
    # Solo se recuperan pendientes sin copia; nunca se reemplaza una mezcla guardada.
    if orden.formula_obligatoria and not orden.referencias:
        servicio_formulas_papa.aplicar_a_orden(db, orden, exigir_valida=True)
        registrar(
            db, "formula_orden", orden.id, "aplicar_activa_al_iniciar",
            usuario.id if usuario else None, None,
            servicio_formula.obtener(db, orden).model_dump(mode="json"),
        )
        notificaciones.avisar_formula_lista(db, orden)

    orden.estado = EstadoOrden.EN_PRODUCCION
    orden.hora_inicio = datetime.now(UTC)
    _guardar_cambio_de_horno(db, orden)

    # El aviso se guarda en la misma transacción que el cambio de estado.
    notificaciones.programar_aviso_fin_produccion(db, orden)

    registrar(db, "orden", orden.id, "iniciar", usuario.id if usuario else None, antes, estado_orden(orden))
    return orden


@atomica
def finalizar_orden(db: Session, orden: OrdenProduccion, usuario: Usuario | None = None) -> OrdenProduccion:
    orden = bloquear_orden(db, orden.id)
    antes = estado_orden(orden)
    if not requiere_transicion(orden.estado, "finalizar"):
        return orden
    orden.estado = EstadoOrden.FINALIZADA
    orden.hora_fin = datetime.now(UTC)
    db.flush()
    db.refresh(orden)
    registrar(db, "orden", orden.id, "finalizar", usuario.id if usuario else None, antes, estado_orden(orden))
    return orden


@atomica
def cancelar_orden(db: Session, orden: OrdenProduccion, usuario: Usuario | None = None) -> OrdenProduccion:
    orden = bloquear_orden(db, orden.id)
    antes = estado_orden(orden)
    if not requiere_transicion(orden.estado, "cancelar"):
        return orden
    orden.estado = EstadoOrden.CANCELADA
    db.flush()
    db.refresh(orden)
    registrar(db, "orden", orden.id, "cancelar", usuario.id if usuario else None, antes, estado_orden(orden))
    return orden


@atomica
def eliminar_orden(db: Session, orden: OrdenProduccion, usuario: Usuario) -> int:
    """
    Borrado suave CON CASCADA: si el administrador elimina una orden es
    porque vio algo raro y quiere borrarla completa de un solo clic. La
    orden y todos sus registros activos quedan marcados como eliminados:
    desaparecen de listas, Analisis y exportaciones, pero siguen en la base
    de datos para poder auditar.

    Devuelve cuantos registros de horno/saborizado se llevo consigo.
    """
    orden = bloquear_orden(db, orden.id)
    antes = estado_orden(orden)
    arrastrados = 0

    registros_horno = (
        db.scalars(
            select(RegistroHorno).where(RegistroHorno.orden_id == orden.id, RegistroHorno.eliminado == False)
        )
        .unique()
        .all()
    )
    registros_saborizado = (
        db.scalars(
            select(RegistroSaborizado).where(
                RegistroSaborizado.orden_id == orden.id, RegistroSaborizado.eliminado == False
            )
        )
        .unique()
        .all()
    )

    for registro in registros_horno:
        if not registro.eliminado:
            registro.eliminado = True
            registro.eliminado_por_id = usuario.id
            registro.fecha_eliminacion = datetime.now(UTC)
            arrastrados += 1

    for recepcion in registros_saborizado:
        if not recepcion.eliminado:
            recepcion.eliminado = True
            recepcion.eliminado_por_id = usuario.id
            recepcion.fecha_eliminacion = datetime.now(UTC)
            arrastrados += 1

    # Una orden borrada deja de existir para el negocio. Si estaba Pendiente o
    # En produccion se cierra como Cancelada: asi libera el horno y no bloquea
    # la siguiente orden (el indice unico parcial solo mira el estado).
    if orden.estado in EstadoOrden.ACTIVOS:
        orden.estado = EstadoOrden.CANCELADA

    marcar_eliminado_por(db, orden, usuario)
    registrar(db, "orden", orden.id, "eliminar", usuario.id, antes, estado_orden(orden))
    db.flush()
    return arrastrados
