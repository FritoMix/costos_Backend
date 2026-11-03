"""
Formulas de papa reutilizables por producto (catalogo de Bodega).

Flujo:
  * Bodega crea una formula con las referencias del catalogo de papa y la
    ACTIVA. Solo hay una activa por producto (indice unico parcial en la
    base); activar otra desactiva la anterior.
  * Al crear una orden, el supervisor ve la activa de ese producto y la
    orden nace con esa mezcla copiada a `orden_referencias` (los snapshots
    de peso y rendimiento se toman del catalogo en ese momento).
  * Si el producto no tiene activa, o la activa no cabe en el horno elegido,
    la orden queda pendiente y Bodega la define como hoy.

Las ordenes ya creadas nunca cambian si Bodega edita la plantilla: conservan
su copia congelada.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.modules.bodega.models import ReferenciaPapa
from app.modules.catalogos.models import Horno, Producto
from app.modules.identidad.models import Usuario
from app.modules.produccion.dominio.calculos import (
    CIEN,
    Participacion,
    calcular_kg_crudos,
    calcular_kg_fritos_estimados,
    calcular_porcentaje_desde_bultos,
    distribuir_bultos,
    validar_participaciones,
)
from app.modules.produccion.models import (
    FormulaPapa,
    FormulaPapaReferencia,
    OrdenProduccion,
)
from app.modules.produccion.schemas import (
    FormulaPapaGuardar,
    FormulaPapaReferenciaSalida,
    FormulaPapaSalida,
    UsuarioRef,
)
from app.modules.produccion.servicios.formula import (
    filas_de_mezcla,
    resolver_mezcla,
    validar_mezcla_en_horno,
    validar_referencia_formula,
)

logger = logging.getLogger("datacontrol")

CENTAVOS = Decimal("0.01")


# --- Lectura -----------------------------------------------------------------


def salida(formula: FormulaPapa, horas: int | None = None) -> FormulaPapaSalida:
    """Arma la salida con los kg calculados desde el catalogo actual."""
    filas: list[FormulaPapaReferenciaSalida] = []
    total_bultos = sum(fila.bultos_por_tanda for fila in formula.referencias)
    total_crudos = Decimal("0")
    total_fritos = Decimal("0")
    for fila in formula.referencias:
        referencia = fila.referencia_papa
        if referencia.rendimiento_fritura_pct is None:
            continue
        kg_crudos = calcular_kg_crudos(fila.bultos_por_tanda, referencia.peso_promedio_bulto_kg)
        kg_fritos = calcular_kg_fritos_estimados(kg_crudos, referencia.rendimiento_fritura_pct)
        total_crudos += kg_crudos
        total_fritos += kg_fritos
        filas.append(
            FormulaPapaReferenciaSalida(
                referencia_id=referencia.id,
                nombre=referencia.nombre,
                tipo=referencia.tipo,
                bultos_por_tanda=fila.bultos_por_tanda,
                porcentaje_produccion_pct=calcular_porcentaje_desde_bultos(
                    fila.bultos_por_tanda, total_bultos
                ),
                peso_promedio_bulto_kg=referencia.peso_promedio_bulto_kg,
                rendimiento_fritura_pct=referencia.rendimiento_fritura_pct,
                kg_crudos_por_tanda=kg_crudos,
                kg_fritos_por_tanda=kg_fritos,
            )
        )

    planificados_bultos = total_bultos * horas if horas else None
    return FormulaPapaSalida(
        id=formula.id,
        nombre=formula.nombre,
        producto=formula.producto,
        activa=formula.activa,
        notas=formula.notas,
        referencias=filas,
        total_bultos_por_tanda=total_bultos,
        total_kg_crudos=total_crudos.quantize(CENTAVOS),
        total_kg_fritos_estimados=total_fritos.quantize(CENTAVOS),
        horas=horas,
        total_bultos_planificados=planificados_bultos,
        total_kg_crudos_planificados=(
            (total_crudos * horas).quantize(CENTAVOS) if horas else None
        ),
        total_kg_fritos_planificados=(
            (total_fritos * horas).quantize(CENTAVOS) if horas else None
        ),
        creado_por=(
            UsuarioRef.model_validate(formula.creado_por) if formula.creado_por else None
        ),
        fecha_creacion=formula.fecha_creacion,
        fecha_actualizacion=formula.fecha_actualizacion,
    )


def listar(
    db: Session,
    *,
    producto_id: int | None = None,
    solo_activas: bool = False,
) -> list[FormulaPapaSalida]:
    consulta = select(FormulaPapa)
    if producto_id is not None:
        consulta = consulta.where(FormulaPapa.producto_id == producto_id)
    if solo_activas:
        consulta = consulta.where(FormulaPapa.activa.is_(True))
    consulta = consulta.order_by(
        FormulaPapa.producto_id, FormulaPapa.activa.desc(), FormulaPapa.nombre
    )
    return [salida(formula) for formula in db.scalars(consulta).unique().all()]


def obtener(db: Session, formula_id: int) -> FormulaPapa:
    formula = db.get(FormulaPapa, formula_id)
    if formula is None:
        raise RecursoNoEncontrado("Esa fórmula no existe.")
    return formula


def obtener_activa(db: Session, producto_id: int) -> FormulaPapa | None:
    return db.scalar(
        select(FormulaPapa).where(
            FormulaPapa.producto_id == producto_id,
            FormulaPapa.activa.is_(True),
        )
    )


# --- Escritura ---------------------------------------------------------------


def _validar_producto(db: Session, producto_id: int) -> Producto:
    producto = db.get(Producto, producto_id)
    if producto is None or not producto.activo:
        raise ErrorDeValidacion("El producto seleccionado no es válido.")
    return producto


def _validar_nombre_unico(
    db: Session, *, producto_id: int, nombre: str, excluir_id: int | None = None
) -> None:
    consulta = select(FormulaPapa.id).where(
        FormulaPapa.producto_id == producto_id,
        FormulaPapa.nombre == nombre,
    )
    if excluir_id is not None:
        consulta = consulta.where(FormulaPapa.id != excluir_id)
    if db.scalar(consulta.limit(1)) is not None:
        raise ErrorDeValidacion(
            "Ya existe una fórmula con ese nombre para el producto. Usa otro nombre."
        )


def _aplicar_datos(
    db: Session, formula: FormulaPapa, datos: FormulaPapaGuardar
) -> None:
    _validar_producto(db, datos.producto_id)
    nombre = datos.nombre.strip()
    if not nombre:
        raise ErrorDeValidacion("La fórmula necesita un nombre.")
    _validar_nombre_unico(
        db, producto_id=datos.producto_id, nombre=nombre, excluir_id=formula.id
    )
    mezcla = resolver_mezcla(db, datos.referencias)

    formula.nombre = nombre
    formula.producto_id = datos.producto_id
    formula.notas = (datos.notas or "").strip() or None
    formula.fecha_actualizacion = datetime.now(UTC)
    formula.referencias.clear()
    db.flush()
    for referencia, bultos in mezcla:
        formula.referencias.append(_fila_referencia(referencia, bultos))


def _fila_referencia(referencia, bultos: int) -> FormulaPapaReferencia:
    return FormulaPapaReferencia(
        referencia_papa_id=referencia.id,
        bultos_por_tanda=bultos,
    )


def crear(db: Session, datos: FormulaPapaGuardar, usuario: Usuario) -> FormulaPapaSalida:
    """Crea una plantilla INACTIVA; se activa con el endpoint de activación."""
    producto = _validar_producto(db, datos.producto_id)
    nombre = datos.nombre.strip()
    if not nombre:
        raise ErrorDeValidacion("La fórmula necesita un nombre.")
    _validar_nombre_unico(db, producto_id=producto.id, nombre=nombre)
    mezcla = resolver_mezcla(db, datos.referencias)

    formula = FormulaPapa(
        nombre=nombre,
        producto_id=producto.id,
        activa=False,
        notas=(datos.notas or "").strip() or None,
        creado_por_id=usuario.id,
    )
    for referencia, bultos in mezcla:
        formula.referencias.append(
            _fila_referencia(referencia, bultos)
        )
    db.add(formula)
    db.commit()
    db.refresh(formula)
    return salida(formula)


def detalle(db: Session, formula_id: int) -> FormulaPapaSalida:
    """Fórmula del catálogo lista para la API."""
    return salida(obtener(db, formula_id))


def actualizar(
    db: Session, formula: FormulaPapa, datos: FormulaPapaGuardar
) -> FormulaPapaSalida:
    """Reemplaza nombre, producto, notas y mezcla. Las ordenes ya creadas no cambian."""
    _aplicar_datos(db, formula, datos)
    db.commit()
    db.refresh(formula)
    return salida(formula)


def activar(db: Session, formula: FormulaPapa) -> FormulaPapaSalida:
    """Activa esta formula y desactiva la que estuviera activa del producto."""
    db.execute(
        update(FormulaPapa)
        .where(
            FormulaPapa.producto_id == formula.producto_id,
            FormulaPapa.activa.is_(True),
            FormulaPapa.id != formula.id,
        )
        .values(activa=False)
    )
    formula.activa = True
    formula.fecha_actualizacion = datetime.now(UTC)
    db.commit()
    db.refresh(formula)
    return salida(formula)


def desactivar(db: Session, formula: FormulaPapa) -> FormulaPapaSalida:
    formula.activa = False
    formula.fecha_actualizacion = datetime.now(UTC)
    db.commit()
    db.refresh(formula)
    return salida(formula)


def eliminar(db: Session, formula: FormulaPapa) -> None:
    if formula.activa:
        raise ErrorDeValidacion(
            "No puedes eliminar la fórmula activa. Desactívala o activa otra primero."
        )
    db.delete(formula)
    db.commit()


# --- Reparto de la capacidad ------------------------------------------------


def capacidad_de_hornos(db: Session) -> int:
    """
    Capacidad de referencia para repartir una mezcla: la mayor capacidad
    configurada entre los hornos activos. Las ordenes siguen validando contra
    el horno que elija el supervisor.
    """
    capacidad = db.scalar(
        select(func.max(Horno.capacidad_bultos_hora)).where(
            Horno.activo.is_(True),
            Horno.capacidad_bultos_hora.is_not(None),
        )
    )
    if capacidad is None:
        raise ErrorDeValidacion(
            "Ningún horno activo tiene configurada su capacidad de bultos por hora. "
            "Configúrala en Hornos para repartir la mezcla."
        )
    return int(capacidad)


def sugerir_mezcla(db: Session, referencia_ids: list[int]) -> tuple[int, list[tuple[int, int]]]:
    """
    Reparte la capacidad del horno entre las referencias elegidas usando su
    participación de Bodega. Si la participación no suma 100 %, reparte en
    partes iguales. Devuelve (capacidad, [(referencia_id, bultos)]).
    """
    if not referencia_ids:
        raise ErrorDeValidacion("Elige al menos una referencia para repartir la mezcla.")
    if len(referencia_ids) != len(set(referencia_ids)):
        raise ErrorDeValidacion("No puedes repetir una referencia en la misma fórmula.")

    referencias = list(
        db.scalars(
            select(ReferenciaPapa).where(ReferenciaPapa.id.in_(referencia_ids))
        ).all()
    )
    if len(referencias) != len(set(referencia_ids)):
        raise RecursoNoEncontrado("Alguna referencia de papa no existe.")
    for referencia in referencias:
        validar_referencia_formula(referencia)

    capacidad = capacidad_de_hornos(db)
    participaciones: list[Participacion] | None = None
    if all(referencia.porcentaje_produccion_pct is not None for referencia in referencias):
        candidatas = [
            Participacion(
                referencia_id=referencia.id,
                porcentaje=referencia.porcentaje_produccion_pct,
            )
            for referencia in referencias
        ]
        try:
            validar_participaciones(candidatas)
            participaciones = candidatas
        except ErrorDeValidacion:
            participaciones = None
    if participaciones is None:
        partes = CIEN / Decimal(len(referencias))
        participaciones = [
            Participacion(referencia_id=referencia.id, porcentaje=partes)
            for referencia in referencias
        ]

    distribucion = distribuir_bultos(capacidad, participaciones)
    return capacidad, [
        (referencia.id, distribucion[referencia.id])
        for referencia in referencias
        if distribucion[referencia.id] > 0
    ]


# --- Integracion con la orden ------------------------------------------------


def activa_para_orden(
    db: Session, *, producto_id: int, horas: int | None = None
) -> FormulaPapaSalida | None:
    """La plantilla activa del producto, con totales para las horas pedidas."""
    formula = obtener_activa(db, producto_id)
    return salida(formula, horas=horas) if formula else None


def aplicar_a_orden(db: Session, orden: OrdenProduccion) -> bool:
    """
    Copia la formula activa del producto a la orden recien creada.

    Devuelve False (sin tocar la orden) si no hay activa o si la mezcla no
    cabe en el horno o no alcanza la cantidad pedida: en ese caso Bodega la
    define a mano y recibe el aviso.
    """
    activa = obtener_activa(db, orden.producto_id)
    if activa is None:
        return False
    try:
        mezcla = resolver_mezcla(db, activa.referencias)
        validar_mezcla_en_horno(
            mezcla,
            horno=orden.horno,
            horas_produccion=orden.horas_produccion,
            cantidad_programada=orden.cantidad_programada,
        )
    except ErrorDeValidacion as exc:
        logger.warning(
            "Fórmula activa %s no aplicable a %s: %s",
            activa.id,
            orden.numero_orden,
            exc,
        )
        return False

    orden.referencias.clear()
    db.flush()
    orden.referencias.extend(filas_de_mezcla(orden, mezcla, activa.creado_por_id))
    orden.formula_notas = activa.notas
    orden.formula_actualizada_por_id = activa.creado_por_id
    orden.formula_fecha_actualizacion = datetime.now(UTC)
    orden.formula_papa_id = activa.id
    db.commit()
    db.refresh(orden)
    return True
