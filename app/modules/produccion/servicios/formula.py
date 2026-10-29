"""
Formula de produccion por orden.

La formula es de UNA orden y la define Bodega despues de que el supervisor
crea la orden. Se guarda por tanda (bultos por referencia); la misma mezcla
se repite en todas las tandas de la orden en esta fase.

Reglas:
  * Solo se guarda mientras la orden esta Pendiente y sin tandas.
  * No se admiten referencias repetidas, inactivas o incompletas.
  * La suma de bultos por tanda no puede superar la capacidad del horno.
  * Peso, rendimiento y porcentaje se congelan en la formula.
  * Al iniciar produccion la formula queda congelada.
"""

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.modules.bodega import service as servicio_bodega
from app.modules.bodega.models import ReferenciaPapa
from app.modules.catalogos.models import Horno
from app.modules.identidad.models import Usuario
from app.modules.notificaciones import service as notificaciones
from app.modules.produccion.dominio.calculos import (
    CIEN,
    MezclaSugerida,
    ReferenciaMezcla,
    calcular_kg_crudos,
    calcular_kg_fritos_estimados,
    calcular_porcentaje_desde_bultos,
    kg_fritos_por_bulto,
    sugerir_mezcla_por_tanda,
)
from app.modules.produccion.models import (
    EstadoOrden,
    OrdenProduccion,
    OrdenReferencia,
    RegistroHorno,
    RegistroHornoReferencia,
)
from app.modules.produccion.schemas import (
    FormulaGuardar,
    FormulaProyeccionGuardar,
    FormulaProyeccionReferencia,
    FormulaProyeccionSalida,
    FormulaReferenciaSalida,
    FormulaSalida,
    OrdenBodegaDetalle,
    OrdenBodegaSalida,
    OrdenSalida,
)
from app.modules.produccion.servicios.totales import producido_por_referencia

logger = logging.getLogger("datacontrol")

CENTAVOS = Decimal("0.01")
CUATRO_DECIMALES = Decimal("0.0001")
UMBRAL_DIFERENCIA_PCT = Decimal("5")


# --- Helpers -----------------------------------------------------------------


def _capacidad(horno: Horno) -> int:
    return servicio_bodega.capacidad_entera(horno)


def _capacidad_maxima(horno: Horno, horas: int | None) -> int | None:
    if horno.capacidad_bultos_hora is None or horas is None:
        return None
    return int(horno.capacidad_bultos_hora) * horas


def _validar_referencia_formula(referencia: ReferenciaPapa) -> None:
    if not referencia.activo:
        raise ErrorDeValidacion(
            f'La referencia "{referencia.nombre}" está inactiva. Actívala o elige otra.'
        )
    if (
        referencia.tipo is None
        or referencia.tipo.strip() == ""
        or referencia.rendimiento_fritura_pct is None
        or referencia.rendimiento_fritura_pct <= 0
        or referencia.peso_promedio_bulto_kg <= 0
    ):
        raise ErrorDeValidacion(
            f'La referencia "{referencia.nombre}" está incompleta: configura tipo, '
            "peso por bulto y rendimiento de fritura antes de usarla en una fórmula."
        )


def _referencias_de_formula(
    db: Session, datos: FormulaGuardar
) -> list[tuple[ReferenciaPapa, int]]:
    ids = [fila.referencia_papa_id for fila in datos.referencias]
    if len(ids) != len(set(ids)):
        raise ErrorDeValidacion("No puedes repetir una referencia en la misma fórmula.")

    encontradas = {
        referencia.id: referencia
        for referencia in db.scalars(
            select(ReferenciaPapa).where(ReferenciaPapa.id.in_(ids))
        ).all()
    }
    resultado: list[tuple[ReferenciaPapa, int]] = []
    for fila in datos.referencias:
        referencia = encontradas.get(fila.referencia_papa_id)
        if referencia is None:
            raise RecursoNoEncontrado("Esa referencia de papa no existe.")
        _validar_referencia_formula(referencia)
        resultado.append((referencia, fila.bultos_por_tanda))
    return resultado


def _filas_desde_orden(
    orden: OrdenProduccion,
    producido: dict[int, Decimal] | None = None,
) -> list[FormulaReferenciaSalida]:
    """
    Filas de la formula con los valores CONGELADOS al guardarla.

    No se recalculan desde el catalogo: si Bodega corrige el peso o el
    rendimiento despues, la formula y las tandas ya creadas no cambian.
    """
    producido = producido or {}
    filas: list[FormulaReferenciaSalida] = []
    for fila in orden.referencias:
        bultos_producidos = producido.get(fila.referencia_papa_id, Decimal("0"))
        filas.append(
            FormulaReferenciaSalida(
                referencia_id=fila.referencia_papa_id,
                nombre=fila.referencia_papa.nombre,
                tipo=fila.referencia_papa.tipo,
                bultos_por_tanda=fila.bultos_por_tanda,
                bultos_planificados=fila.bultos_planificados,
                porcentaje_produccion_pct=fila.porcentaje_produccion_pct,
                peso_promedio_bulto_kg=fila.peso_promedio_bulto_kg,
                rendimiento_fritura_pct=fila.rendimiento_fritura_pct,
                kg_crudos_por_tanda=fila.kg_crudos_por_tanda,
                kg_fritos_por_tanda=fila.kg_fritos_por_tanda,
                kg_crudos_planificados=fila.kg_crudos_planificados,
                kg_fritos_estimados=fila.kg_fritos_estimados,
                bultos_producidos=bultos_producidos,
                bultos_restantes=max(
                    Decimal("0"),
                    Decimal(fila.bultos_planificados) - bultos_producidos,
                ),
            )
        )
    return filas


def _advertencias(
    *,
    total_kg_fritos: Decimal,
    cantidad_programada: Decimal,
) -> list[str]:
    if cantidad_programada <= 0:
        return []
    diferencia = total_kg_fritos - cantidad_programada
    diferencia_pct = (diferencia / cantidad_programada * CIEN).quantize(CUATRO_DECIMALES)
    if abs(diferencia_pct) <= UMBRAL_DIFERENCIA_PCT:
        return []
    if diferencia > 0:
        return [
            f"La fórmula produce {diferencia.quantize(CENTAVOS)} kg fritos más de lo pedido "
            f"({diferencia_pct.quantize(Decimal('0.01'))} %). Revisa las horas o los bultos."
        ]
    return [
        f"La fórmula produce {abs(diferencia).quantize(CENTAVOS)} kg fritos menos de lo pedido "
        f"({abs(diferencia_pct).quantize(Decimal('0.01'))} %). Revisa la mezcla o pide más horas."
    ]


def _tandas_registradas(db: Session, orden_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(RegistroHorno)
            .where(
                RegistroHorno.orden_id == orden_id,
                RegistroHorno.eliminado == False,
            )
        )
        or 0
    )


# --- Lectura y guardado ------------------------------------------------------


def obtener(db: Session, orden: OrdenProduccion) -> FormulaSalida:
    producido = producido_por_referencia(db, orden.id)
    filas = _filas_desde_orden(orden, producido)
    total_por_tanda = sum(fila.bultos_por_tanda for fila in filas)
    total_planificados = sum(fila.bultos_planificados for fila in filas)
    total_producidos = sum((fila.bultos_producidos for fila in filas), Decimal("0"))
    total_crudos = sum((fila.kg_crudos_planificados for fila in filas), Decimal("0"))
    total_fritos = sum((fila.kg_fritos_estimados for fila in filas), Decimal("0"))
    avance = None
    if total_planificados > 0:
        avance = (total_producidos / Decimal(total_planificados) * CIEN).quantize(
            Decimal("0.01")
        )

    return FormulaSalida(
        orden_id=orden.id,
        estado=orden.formula_estado,
        referencias=filas,
        notas=orden.formula_notas,
        capacidad_bultos_hora=orden.horno.capacidad_bultos_hora,
        capacidad_maxima_bultos=_capacidad_maxima(orden.horno, orden.horas_produccion),
        total_bultos_por_tanda=total_por_tanda,
        total_bultos_planificados=total_planificados,
        total_kg_crudos=total_crudos,
        total_kg_fritos_estimados=total_fritos,
        total_bultos_producidos=total_producidos,
        avance_bultos_porcentaje=avance,
        tandas_registradas=_tandas_registradas(db, orden.id),
        tandas_programadas=orden.horas_produccion,
        actualizada_por=orden.formula_actualizada_por,
        fecha_actualizacion=orden.formula_fecha_actualizacion,
        advertencias=_advertencias(
            total_kg_fritos=total_fritos,
            cantidad_programada=orden.cantidad_programada,
        ),
    )


def guardar(
    db: Session,
    orden: OrdenProduccion,
    datos: FormulaGuardar,
    usuario: Usuario,
) -> FormulaSalida:
    if not orden.formula_obligatoria:
        raise ErrorDeValidacion(
            "Esta orden es histórica y no admite fórmula: se produce con el registro anterior."
        )
    if _tandas_registradas(db, orden.id) > 0:
        raise ErrorDeValidacion(
            "La fórmula ya está congelada porque la orden tiene tandas registradas."
        )
    if orden.estado != EstadoOrden.PENDIENTE:
        raise ErrorDeValidacion(
            "La fórmula solo se puede definir o corregir mientras la orden esté Pendiente."
        )
    if not orden.horas_produccion or orden.horas_produccion < 1:
        raise ErrorDeValidacion("La orden debe tener al menos una hora programada.")
    if orden.horno.capacidad_bultos_hora is None:
        raise ErrorDeValidacion(
            f'El {orden.horno.nombre} no tiene configurada su capacidad de bultos por hora. '
            "Configúrala en Hornos antes de guardar la fórmula."
        )

    mezcla = _referencias_de_formula(db, datos)
    total_por_tanda = sum(bultos for _, bultos in mezcla)
    capacidad = _capacidad(orden.horno)
    if total_por_tanda > capacidad:
        raise ErrorDeValidacion(
            f"La mezcla carga {total_por_tanda} bultos por tanda y el horno admite "
            f"máximo {capacidad}. Ajusta los bultos por referencia."
        )

    # Se reemplaza la formula completa: una sola formula vigente por orden.
    orden.referencias.clear()
    db.flush()
    for referencia, bultos in mezcla:
        rendimiento = referencia.rendimiento_fritura_pct
        if rendimiento is None:  # ya validado, pero deja el tipo claro
            continue
        kg_crudos = calcular_kg_crudos(bultos, referencia.peso_promedio_bulto_kg)
        kg_fritos = calcular_kg_fritos_estimados(kg_crudos, rendimiento)
        orden.referencias.append(
            OrdenReferencia(
                referencia_papa_id=referencia.id,
                bultos_por_tanda=bultos,
                bultos_planificados=bultos * orden.horas_produccion,
                porcentaje_produccion_pct=calcular_porcentaje_desde_bultos(
                    bultos, total_por_tanda
                ),
                peso_promedio_bulto_kg=referencia.peso_promedio_bulto_kg,
                rendimiento_fritura_pct=rendimiento,
                kg_crudos_por_tanda=kg_crudos,
                kg_fritos_por_tanda=kg_fritos,
                kg_crudos_planificados=(kg_crudos * orden.horas_produccion).quantize(
                    CENTAVOS
                ),
                kg_fritos_estimados=(kg_fritos * orden.horas_produccion).quantize(
                    CENTAVOS
                ),
                creado_por_id=usuario.id,
            )
        )

    orden.formula_notas = (datos.notas or "").strip() or None
    orden.formula_actualizada_por_id = usuario.id
    orden.formula_fecha_actualizacion = datetime.now(UTC)
    db.commit()
    db.refresh(orden)

    try:
        notificaciones.avisar_formula_lista(db, orden)
    except Exception:  # noqa: BLE001 - la formula ya quedo guardada
        logger.exception("No se pudo notificar la fórmula de %s", orden.numero_orden)

    return obtener(db, orden)


def recalcular_totales(db: Session, orden: OrdenProduccion) -> None:
    """Recalcula los totales planificados si cambian las horas de la orden."""
    if not orden.referencias:
        return
    horas = orden.horas_produccion or 0
    if horas < 1:
        raise ErrorDeValidacion("La orden debe tener al menos una hora programada.")
    for fila in orden.referencias:
        fila.bultos_planificados = fila.bultos_por_tanda * horas
        fila.kg_crudos_planificados = (
            fila.kg_crudos_por_tanda * horas
        ).quantize(CENTAVOS)
        fila.kg_fritos_estimados = (
            fila.kg_fritos_por_tanda * horas
        ).quantize(CENTAVOS)


def validar_cambio_orden(
    db: Session,
    orden: OrdenProduccion,
    *,
    horno: Horno,
    horas_produccion: int,
    cantidad_programada: Decimal,
) -> None:
    """
    Valida que la formula vigente siga cabiendo si el supervisor cambia
    horas, horno o cantidad antes de iniciar. No modifica nada.
    """
    if not orden.referencias:
        return
    if orden.estado != EstadoOrden.PENDIENTE:
        return
    if horno.capacidad_bultos_hora is None:
        raise ErrorDeValidacion(
            f'El {horno.nombre} no tiene configurada su capacidad de bultos por hora; '
            "Bodega no puede ajustar la fórmula."
        )
    capacidad = _capacidad(horno)
    total_por_tanda = sum(fila.bultos_por_tanda for fila in orden.referencias)
    if total_por_tanda > capacidad:
        raise ErrorDeValidacion(
            f"La fórmula actual carga {total_por_tanda} bultos por tanda y el nuevo horno "
            f"admite máximo {capacidad}. Bodega debe ajustarla."
        )
    max_kg_por_bulto = max(
        kg_fritos_por_bulto(
            fila.peso_promedio_bulto_kg, fila.rendimiento_fritura_pct
        )
        for fila in orden.referencias
    )
    capacidad_kg = Decimal(capacidad * horas_produccion) * max_kg_por_bulto
    if capacidad_kg < cantidad_programada:
        raise ErrorDeValidacion(
            "La capacidad del horno con las horas indicadas no alcanza para la cantidad "
            "pedida con el rendimiento de la fórmula actual. Bodega debe ajustarla o el "
            "supervisor debe ampliar las horas."
        )


# --- Proyeccion y sugerencia -------------------------------------------------


def _referencias_para_sugerencia(db: Session) -> list[ReferenciaPapa]:
    referencias = list(
        db.scalars(
            select(ReferenciaPapa)
            .where(ReferenciaPapa.activo.is_(True))
            .order_by(ReferenciaPapa.id)
        ).all()
    )
    if not referencias:
        raise ErrorDeValidacion(
            "No hay referencias de papa activas. Bodega debe registrar al menos una."
        )
    for referencia in referencias:
        _validar_referencia_formula(referencia)
    return referencias


def sugerir(db: Session, orden: OrdenProduccion) -> list[MezclaSugerida]:
    if not orden.horas_produccion or orden.horas_produccion < 1:
        raise ErrorDeValidacion("La orden debe tener al menos una hora programada.")
    capacidad = _capacidad(orden.horno)
    referencias = _referencias_para_sugerencia(db)
    return sugerir_mezcla_por_tanda(
        cantidad_programada=orden.cantidad_programada,
        horas_produccion=orden.horas_produccion,
        capacidad_bultos_hora=capacidad,
        referencias=[
            ReferenciaMezcla(
                referencia_id=referencia.id,
                peso_promedio_bulto_kg=referencia.peso_promedio_bulto_kg,
                rendimiento_fritura_pct=referencia.rendimiento_fritura_pct,
                porcentaje_produccion_pct=referencia.porcentaje_produccion_pct,
            )
            for referencia in referencias
            if referencia.rendimiento_fritura_pct is not None
        ],
    )


def _mezcla_para_proyeccion(
    db: Session, orden: OrdenProduccion, datos: FormulaProyeccionGuardar
) -> tuple[list[tuple[ReferenciaPapa, int]], str]:
    if datos.usar_sugerencia or not datos.referencias:
        sugerencia = sugerir(db, orden)
        referencias = {
            referencia.id: referencia
            for referencia in db.scalars(
                select(ReferenciaPapa).where(
                    ReferenciaPapa.id.in_([fila.referencia_id for fila in sugerencia])
                )
            ).all()
        }
        return [
            (referencias[fila.referencia_id], fila.bultos_por_tanda)
            for fila in sugerencia
        ], "sugerencia"
    return _referencias_de_formula(
        db, FormulaGuardar(referencias=datos.referencias, notas=None)
    ), "manual"


def proyectar(
    db: Session,
    orden: OrdenProduccion,
    datos: FormulaProyeccionGuardar,
) -> FormulaProyeccionSalida:
    if not orden.horas_produccion or orden.horas_produccion < 1:
        raise ErrorDeValidacion("La orden debe tener al menos una hora programada.")
    if orden.horno.capacidad_bultos_hora is None:
        raise ErrorDeValidacion(
            f'El {orden.horno.nombre} no tiene configurada su capacidad de bultos por hora. '
            "Configúrala en Hornos antes de proyectar la fórmula."
        )
    mezcla, origen = _mezcla_para_proyeccion(db, orden, datos)
    capacidad = _capacidad(orden.horno)
    total_por_tanda = sum(bultos for _, bultos in mezcla)
    if total_por_tanda > capacidad:
        raise ErrorDeValidacion(
            f"La mezcla carga {total_por_tanda} bultos por tanda y el horno admite "
            f"máximo {capacidad}. Ajusta los bultos por referencia."
        )

    filas: list[FormulaProyeccionReferencia] = []
    total_crudos = Decimal("0")
    total_fritos = Decimal("0")
    for referencia, bultos in mezcla:
        rendimiento = referencia.rendimiento_fritura_pct
        if rendimiento is None:
            continue
        kg_crudos = calcular_kg_crudos(bultos, referencia.peso_promedio_bulto_kg)
        kg_fritos = calcular_kg_fritos_estimados(kg_crudos, rendimiento)
        total_crudos += (kg_crudos * orden.horas_produccion).quantize(CENTAVOS)
        total_fritos += (kg_fritos * orden.horas_produccion).quantize(CENTAVOS)
        filas.append(
            FormulaProyeccionReferencia(
                referencia_id=referencia.id,
                nombre=referencia.nombre,
                tipo=referencia.tipo,
                bultos_por_tanda=bultos,
                porcentaje_produccion_pct=calcular_porcentaje_desde_bultos(
                    bultos, total_por_tanda
                ),
                peso_promedio_bulto_kg=referencia.peso_promedio_bulto_kg,
                rendimiento_fritura_pct=rendimiento,
                kg_crudos_por_tanda=kg_crudos,
                kg_fritos_por_tanda=kg_fritos,
                kg_crudos_planificados=(kg_crudos * orden.horas_produccion).quantize(
                    CENTAVOS
                ),
                kg_fritos_estimados=(kg_fritos * orden.horas_produccion).quantize(
                    CENTAVOS
                ),
            )
        )

    kg_promedio = Decimal("0")
    if total_por_tanda > 0:
        kg_promedio = (
            sum(
                (
                    fila.kg_fritos_por_tanda
                    for fila in filas
                ),
                Decimal("0"),
            )
            / Decimal(total_por_tanda)
        ).quantize(CUATRO_DECIMALES)

    diferencia = (total_fritos - orden.cantidad_programada).quantize(CENTAVOS)
    diferencia_pct = Decimal("0")
    if orden.cantidad_programada > 0:
        diferencia_pct = (
            diferencia / orden.cantidad_programada * CIEN
        ).quantize(CUATRO_DECIMALES)

    max_kg_por_bulto = max(
        (
            kg_fritos_por_bulto(
                referencia.peso_promedio_bulto_kg, referencia.rendimiento_fritura_pct
            )
            for referencia, _ in mezcla
            if referencia.rendimiento_fritura_pct is not None
        ),
        default=Decimal("0"),
    )
    capacidad_maxima_kg = (
        Decimal(capacidad * orden.horas_produccion) * max_kg_por_bulto
    )
    factible = capacidad_maxima_kg >= orden.cantidad_programada
    mensaje = None
    if not factible:
        mensaje = (
            "La capacidad máxima del horno no alcanza para la cantidad pedida con el "
            "rendimiento de estas referencias. Ajusta la mezcla o pide más horas."
        )
    else:
        avisos = _advertencias(
            total_kg_fritos=total_fritos,
            cantidad_programada=orden.cantidad_programada,
        )
        if avisos:
            mensaje = " ".join(avisos)

    return FormulaProyeccionSalida(
        origen=origen,
        capacidad_bultos_hora=orden.horno.capacidad_bultos_hora,
        capacidad_maxima_bultos=_capacidad_maxima(orden.horno, orden.horas_produccion),
        total_bultos_por_tanda=total_por_tanda,
        total_bultos_planificados=total_por_tanda * orden.horas_produccion,
        kg_fritos_por_bulto_promedio=kg_promedio,
        total_kg_crudos=total_crudos,
        total_kg_fritos_estimados=total_fritos,
        cantidad_programada=orden.cantidad_programada,
        diferencia_kg=diferencia,
        diferencia_pct=diferencia_pct,
        tandas_programadas=orden.horas_produccion,
        factible=factible,
        mensaje=mensaje,
        referencias=filas,
    )


# --- Bandeja restringida de Bodega -----------------------------------------


def _salida_bodega(
    db: Session,
    orden: OrdenProduccion,
    *,
    planificados: Decimal | int | None = None,
    producidos: Decimal | None = None,
    tandas: int | None = None,
) -> OrdenBodegaSalida:
    tiene_formula = bool(orden.referencias)
    if planificados is None and tiene_formula:
        planificados = sum(fila.bultos_planificados for fila in orden.referencias)
    if producidos is None and tiene_formula:
        producidos = sum(
            producido_por_referencia(db, orden.id).values(), Decimal("0")
        )
    if tandas is None:
        tandas = _tandas_registradas(db, orden.id)
    total_plan = int(planificados) if planificados is not None else None
    total_producido = producidos if tiene_formula else None
    avance = None
    if total_plan and total_producido is not None:
        avance = (total_producido / Decimal(total_plan) * CIEN).quantize(
            Decimal("0.01")
        )
    base = OrdenSalida.model_validate(orden).model_dump()
    return OrdenBodegaSalida(
        **base,
        formula_notas=orden.formula_notas,
        total_bultos_planificados=total_plan,
        total_bultos_producidos=total_producido,
        tandas_registradas=tandas,
        tandas_programadas=orden.horas_produccion if tiene_formula else None,
        avance_bultos_porcentaje=avance,
    )


def listar_ordenes_bodega(
    db: Session,
    *,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
    estado: str | None = None,
    producto_id: int | None = None,
    destino: str | None = None,
    solo_sin_formula: bool = False,
) -> list[OrdenBodegaSalida]:
    consulta = select(OrdenProduccion).where(OrdenProduccion.eliminado == False)
    if fecha_desde is not None:
        consulta = consulta.where(OrdenProduccion.fecha >= fecha_desde)
    if fecha_hasta is not None:
        consulta = consulta.where(OrdenProduccion.fecha <= fecha_hasta)
    if estado is not None:
        consulta = consulta.where(OrdenProduccion.estado == estado)
    if producto_id is not None:
        consulta = consulta.where(OrdenProduccion.producto_id == producto_id)
    if destino is not None:
        consulta = consulta.where(OrdenProduccion.destino == destino)
    if solo_sin_formula:
        consulta = consulta.where(
            OrdenProduccion.estado == EstadoOrden.PENDIENTE,
            OrdenProduccion.formula_obligatoria.is_(True),
            ~select(OrdenReferencia.id)
            .where(OrdenReferencia.orden_id == OrdenProduccion.id)
            .exists(),
        )
    consulta = consulta.order_by(
        OrdenProduccion.fecha.desc(), OrdenProduccion.id.desc()
    ).limit(500)
    ordenes = list(db.scalars(consulta).unique().all())
    if not ordenes:
        return []

    ids = [orden.id for orden in ordenes]
    planificados = {
        orden_id: total
        for orden_id, total in db.execute(
            select(
                OrdenReferencia.orden_id,
                func.coalesce(func.sum(OrdenReferencia.bultos_planificados), 0),
            )
            .where(OrdenReferencia.orden_id.in_(ids))
            .group_by(OrdenReferencia.orden_id)
        ).all()
    }
    producidos = {
        orden_id: total
        for orden_id, total in db.execute(
            select(
                RegistroHorno.orden_id,
                func.coalesce(func.sum(RegistroHornoReferencia.cantidad_bultos), 0),
            )
            .join(
                RegistroHornoReferencia,
                RegistroHornoReferencia.registro_horno_id == RegistroHorno.id,
            )
            .where(
                RegistroHorno.orden_id.in_(ids),
                RegistroHorno.eliminado == False,
            )
            .group_by(RegistroHorno.orden_id)
        ).all()
    }
    tandas = {
        orden_id: total
        for orden_id, total in db.execute(
            select(RegistroHorno.orden_id, func.count())
            .where(
                RegistroHorno.orden_id.in_(ids),
                RegistroHorno.eliminado == False,
            )
            .group_by(RegistroHorno.orden_id)
        ).all()
    }
    return [
        _salida_bodega(
            db,
            orden,
            planificados=planificados.get(orden.id),
            producidos=producidos.get(orden.id, Decimal("0")),
            tandas=int(tandas.get(orden.id, 0)),
        )
        for orden in ordenes
    ]


def detalle_bodega(db: Session, orden: OrdenProduccion) -> OrdenBodegaDetalle:
    return OrdenBodegaDetalle(
        orden=_salida_bodega(db, orden),
        formula=obtener(db, orden),
    )
