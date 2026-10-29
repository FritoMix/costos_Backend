"""
Logica de negocio del registro de horno (las tandas de fritura).

Lo que calcula la app sola, para que el operario no tenga que hacerlo:
  kg crudos      = bultos x peso promedio de la referencia de papa
  kg fritos est. = kg crudos x rendimiento de fritura / 100
  litros aceite  = diferencia de nivel en cm x litros por cm del tanque
  kg de aceite   = litros x densidad vigente de ese horno en esa fecha

Una tanda puede mezclar varias referencias. Si la orden tiene formula
(la definio Bodega), el peso, el rendimiento y el porcentaje se toman del
snapshot CONGELADO de la formula, no del catalogo: si Bodega corrige una
referencia despues, las tandas no cambian. El detalle por referencia vive
en registro_horno_referencias y la cabecera guarda la suma de bultos y kg.

Las ordenes historicas (sin formula) siguen usando la referencia unica del
catalogo, como antes de la formula por orden.

Si falta la calibracion del tanque o la densidad, esas columnas quedan
vacias: el registro se guarda igual y no se inventa ningun valor.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.borrado_suave import marcar_eliminado_por
from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.core.tiempo import combinar_fecha_y_hora
from app.modules.bodega.service import obtener as obtener_referencia_papa
from app.modules.catalogos.models import Horno, TipoDesperdicio
from app.modules.catalogos.service import obtener_densidad_vigente
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.produccion.dominio.calculos import (
    calcular_kg_crudos,
    calcular_kg_fritos_estimados,
)
from app.modules.produccion.dominio.limites import (
    validar_conteo_tandas,
    validar_duracion_tanda,
    validar_ventana_registro,
)
from app.modules.produccion.models import (
    Desperdicio,
    EstadoOrden,
    OrdenProduccion,
    RegistroHorno,
    RegistroHornoReferencia,
)
from app.modules.produccion.schemas import RegistroHornoGuardar
from app.modules.produccion.servicios.registros import bloquear_orden
from app.modules.produccion.servicios.totales import producido_por_referencia

CENTAVOS = Decimal("0.01")


def calcular_aceite(
    db: Session, horno: Horno, fecha: date, diferencia_cm: Decimal
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal | None]:
    """
    Convierte cm -> litros -> kg.

    Devuelve (litros_por_cm_usado, volumen_litros, densidad_usada, kg).
    Los valores usados se guardan en el registro para que un cambio futuro
    de calibracion o densidad no altere el historico.
    """
    litros_por_cm = horno.litros_por_cm
    if litros_por_cm is None:
        return None, None, None, None

    volumen = (diferencia_cm * litros_por_cm).quantize(Decimal("0.01"))

    densidad = obtener_densidad_vigente(db, horno.id, fecha)
    if densidad is None:
        return litros_por_cm, volumen, None, None

    return litros_por_cm, volumen, densidad, (volumen * densidad).quantize(Decimal("0.01"))


def listar_registros(db: Session, orden_id: int) -> list[RegistroHorno]:
    return list(
        db.scalars(
            select(RegistroHorno)
            .where(RegistroHorno.orden_id == orden_id, RegistroHorno.eliminado == False)
            .order_by(RegistroHorno.hora_inicio)
        )
        .unique()
        .all()
    )


def obtener_registro(db: Session, registro_id: int) -> RegistroHorno:
    registro = db.get(RegistroHorno, registro_id)
    if registro is None or registro.eliminado:
        raise RecursoNoEncontrado("Ese registro de horno no existe.")
    return registro


def _validar_desperdicio(db: Session, datos: RegistroHornoGuardar) -> bool:
    """True si hay que guardar un desperdicio con estos datos."""
    hay_datos = datos.tipo_desperdicio_id is not None and (datos.cantidad_desperdicio_kg or 0) > 0
    if not hay_datos:
        return False
    if db.get(TipoDesperdicio, datos.tipo_desperdicio_id) is None:
        raise ErrorDeValidacion("El tipo de desperdicio seleccionado no es válido.")
    return True


def _validar_niveles_aceite(inicial: Decimal, final: Decimal) -> None:
    """
    El nivel final no puede superar al inicial: significaria un consumo
    negativo y sesgaria los indicadores de toda la planta. Si en la planta
    rellenaron el tanque durante la tanda, hay que corregir las medidas.
    """
    if final > inicial:
        raise ErrorDeValidacion(
            "El nivel final del aceite no puede ser mayor que el inicial. "
            "Si se rellenó el tanque durante la tanda, corrige las medidas antes de guardar."
        )


def _mezcla_solicitada(datos: RegistroHornoGuardar) -> list[tuple[int, Decimal]]:
    """
    Referencias y bultos de la tanda.

    El formato nuevo manda `referencias`; un cliente viejo manda
    `referencia_papa_id` + `cantidad_bultos` y se interpreta como una lista
    de una sola fila. Si vienen ambos, gana `referencias`.
    """
    if datos.referencias:
        return [(fila.referencia_papa_id, fila.cantidad_bultos) for fila in datos.referencias]
    return [(datos.referencia_papa_id, datos.cantidad_bultos)]


def _filas_desde_formula(
    db: Session,
    orden: OrdenProduccion,
    registro: RegistroHorno,
    mezcla: list[tuple[int, Decimal]],
) -> list[RegistroHornoReferencia]:
    """
    Arma el detalle de la tanda con el snapshot de la formula.

    Valida que cada referencia este en la formula y que los bultos no
    superen el restante planificado (el registro que se edita se excluye
    para no contar dos veces su version anterior).
    """
    formula_por_referencia = {
        fila.referencia_papa_id: fila for fila in orden.referencias
    }
    producido = producido_por_referencia(
        db, orden.id, excluir_registro_id=registro.id
    )
    filas: list[RegistroHornoReferencia] = []
    for referencia_id, bultos in mezcla:
        fila_formula = formula_por_referencia.get(referencia_id)
        if fila_formula is None:
            raise ErrorDeValidacion(
                "Esa referencia no está en la fórmula de la orden. Elige una de la "
                "mezcla definida por Bodega."
            )
        ya_producido = producido.get(referencia_id, Decimal("0"))
        restante = fila_formula.bultos_planificados - ya_producido
        if bultos > restante:
            raise ErrorDeValidacion(
                f'La fórmula de "{fila_formula.referencia_papa.nombre}" planificó '
                f"{fila_formula.bultos_planificados} bultos y ya se produjeron "
                f"{ya_producido}. Solo quedan {restante}; esta tanda pide {bultos}."
            )
        kg_crudos = calcular_kg_crudos(bultos, fila_formula.peso_promedio_bulto_kg)
        filas.append(
            RegistroHornoReferencia(
                referencia_papa_id=referencia_id,
                cantidad_bultos=bultos,
                peso_estandar_bulto_kg=fila_formula.peso_promedio_bulto_kg,
                rendimiento_fritura_pct=fila_formula.rendimiento_fritura_pct,
                porcentaje_produccion_pct=fila_formula.porcentaje_produccion_pct,
                kg_crudos_calculados=kg_crudos,
                kg_fritos_estimados=calcular_kg_fritos_estimados(
                    kg_crudos, fila_formula.rendimiento_fritura_pct
                ),
            )
        )
    return filas


def _filas_desde_catalogo(
    db: Session,
    registro: RegistroHorno,
    mezcla: list[tuple[int, Decimal]],
) -> list[RegistroHornoReferencia]:
    """
    Tandas de una orden HISTORICA (sin formula): una sola referencia del
    catalogo, con las reglas previas a la formula por orden.
    """
    if len(mezcla) > 1:
        raise ErrorDeValidacion(
            "Esta orden es histórica y solo admite una referencia por tanda."
        )
    referencia_id, bultos = mezcla[0]
    referencia = obtener_referencia_papa(db, referencia_id)
    if not referencia.activo and referencia.id != registro.referencia_papa_id:
        raise ErrorDeValidacion(
            "La referencia de papa seleccionada está inactiva. Elige otra."
        )
    parametros_incompletos = (
        referencia.rendimiento_fritura_pct is None
        or referencia.porcentaje_produccion_pct is None
    )
    # Las tandas NUEVAS exigen la referencia completa. Una tanda historica
    # (ya tiene id) puede corregirse aunque su referencia sea anterior a V9:
    # se conserva el rendimiento NULL y no se inventan kg fritos.
    if parametros_incompletos and registro.id is None:
        raise ErrorDeValidacion(
            f'La referencia "{referencia.nombre}" todavía no tiene configurados el '
            "rendimiento de fritura y la participación. Pídele a Bodega que complete "
            "sus parámetros antes de registrar la tanda."
        )

    kg_crudos = calcular_kg_crudos(bultos, referencia.peso_promedio_bulto_kg)
    if referencia.rendimiento_fritura_pct is None:
        kg_fritos = None
    else:
        kg_fritos = calcular_kg_fritos_estimados(
            kg_crudos, referencia.rendimiento_fritura_pct
        )
    return [
        RegistroHornoReferencia(
            referencia_papa_id=referencia.id,
            cantidad_bultos=bultos,
            peso_estandar_bulto_kg=referencia.peso_promedio_bulto_kg,
            rendimiento_fritura_pct=referencia.rendimiento_fritura_pct,
            porcentaje_produccion_pct=referencia.porcentaje_produccion_pct,
            kg_crudos_calculados=kg_crudos,
            kg_fritos_estimados=kg_fritos,
        )
    ]


def _validar_capacidad_tanda(orden: OrdenProduccion, total_bultos: Decimal) -> None:
    """La mezcla de una tanda no puede superar la capacidad del horno."""
    capacidad = orden.horno.capacidad_bultos_hora
    if capacidad is None:
        return
    if total_bultos > capacidad:
        raise ErrorDeValidacion(
            f"La tanda carga {total_bultos} bultos y el {orden.horno.nombre} admite "
            f"máximo {capacidad} por hora. Ajusta la mezcla antes de guardar."
        )


def _aplicar_datos(
    db: Session, registro: RegistroHorno, orden: OrdenProduccion, datos: RegistroHornoGuardar
) -> None:
    mezcla = _mezcla_solicitada(datos)
    total_bultos = sum((bultos for _, bultos in mezcla), Decimal("0"))

    if orden.referencias:
        filas = _filas_desde_formula(db, orden, registro, mezcla)
    else:
        if orden.formula_obligatoria:
            raise ErrorDeValidacion(
                "Bodega debe definir la fórmula antes de registrar tandas."
            )
        filas = _filas_desde_catalogo(db, registro, mezcla)
    _validar_capacidad_tanda(orden, total_bultos)

    _validar_niveles_aceite(datos.nivel_aceite_inicial_cm, datos.nivel_aceite_final_cm)
    diferencia = datos.nivel_aceite_inicial_cm - datos.nivel_aceite_final_cm
    litros_por_cm, volumen, densidad, kg_aceite = calcular_aceite(
        db, orden.horno, orden.fecha, diferencia
    )
    inicio, fin = combinar_fecha_y_hora(orden.fecha, datos.hora_inicio, datos.hora_fin)
    validar_duracion_tanda(inicio=inicio, fin=fin)
    validar_ventana_registro(
        horas_produccion=orden.horas_produccion,
        inicio=inicio,
        fin=fin,
        registros=listar_registros(db, orden.id),
        tipo_registro="tanda de horno",
        excluir_id=registro.id,
    )
    validar_conteo_tandas(
        horas_produccion=orden.horas_produccion,
        registros=listar_registros(db, orden.id),
        excluir_id=registro.id,
    )

    if registro.id is None:
        # Las tandas nuevas dejan la referencia del padre en NULL: el detalle
        # por referencia vive en registro_horno_referencias. Los registros
        # historicos conservan sus valores congelados.
        registro.referencia_papa_id = None
        registro.referencia_papa = None
        registro.peso_estandar_bulto_kg = None
        registro.rendimiento_fritura_pct = None
        registro.porcentaje_produccion_pct = None

    registro.hora_inicio = inicio
    registro.hora_fin = fin
    registro.cantidad_bultos = total_bultos.quantize(CENTAVOS)
    registro.kg_crudos_calculados = sum(
        (fila.kg_crudos_calculados for fila in filas), Decimal("0")
    ).quantize(CENTAVOS)
    if all(fila.kg_fritos_estimados is not None for fila in filas):
        registro.kg_fritos_estimados = sum(
            (fila.kg_fritos_estimados for fila in filas), Decimal("0")
        ).quantize(CENTAVOS)
    else:
        registro.kg_fritos_estimados = None
    registro.operarios_seleccion = datos.operarios_seleccion
    registro.operarios_horno = datos.operarios_horno
    registro.nivel_aceite_inicial_cm = datos.nivel_aceite_inicial_cm
    registro.nivel_aceite_final_cm = datos.nivel_aceite_final_cm
    registro.diferencia_aceite_cm = diferencia
    registro.temperatura_aceite_c = datos.temperatura_aceite_c
    registro.litros_por_cm_usado = litros_por_cm
    registro.volumen_aceite_litros = volumen
    registro.densidad_aceite_usada = densidad
    registro.kg_aceite_consumido = kg_aceite
    registro.observaciones = (datos.observaciones or "").strip() or None

    # El detalle por referencia se reemplaza completo (sirve para crear y
    # para corregir una tanda). Se elimina primero y se hace flush para no
    # chocar con el índice único (registro, referencia) al insertar la nueva.
    registro.referencias.clear()
    db.flush()
    registro.referencias.extend(filas)

    # El desperdicio se reemplaza completo: se borra el anterior (si habia)
    # y se crea uno nuevo con los datos del formulario.
    registro.desperdicios.clear()
    if _validar_desperdicio(db, datos):
        registro.desperdicios.append(
            Desperdicio(
                tipo_desperdicio_id=datos.tipo_desperdicio_id,
                cantidad_kg=datos.cantidad_desperdicio_kg,
                observacion=(datos.observacion_desperdicio or "").strip() or None,
            )
        )


def crear_registro(
    db: Session, orden: OrdenProduccion, datos: RegistroHornoGuardar, usuario: Usuario
) -> RegistroHorno:
    if orden.estado != EstadoOrden.EN_PRODUCCION:
        raise ErrorDeValidacion(
            "Solo se pueden registrar datos de horno para una orden que esté En producción."
        )

    bloquear_orden(db, orden.id)
    registro = RegistroHorno(orden_id=orden.id, usuario_id=usuario.id)
    registro.orden = orden
    _aplicar_datos(db, registro, orden, datos)
    db.add(registro)
    db.commit()
    db.refresh(registro)
    return registro


def editar_registro(
    db: Session, registro: RegistroHorno, datos: RegistroHornoGuardar, usuario: Usuario
) -> RegistroHorno:
    """
    Corrige un registro ya guardado. Solo mientras la orden sigue En
    produccion, y solo el operario que lo hizo (o el administrador).

    El aceite se vuelve a calcular con la calibracion y densidad vigentes
    ahora: si cuando se creo faltaba la densidad y ya se cargo, al editar
    esa parte queda completa. Es una correccion activa, no un recalculo
    silencioso del historial.
    """
    if registro.orden.estado != EstadoOrden.EN_PRODUCCION:
        raise ErrorDeValidacion(
            "Solo se puede editar un registro de horno mientras la orden esté En producción."
        )
    _verificar_autoria(registro, usuario)
    bloquear_orden(db, registro.orden_id)
    _aplicar_datos(db, registro, registro.orden, datos)
    db.commit()
    db.refresh(registro)
    return registro


def eliminar_registro(db: Session, registro: RegistroHorno, usuario: Usuario) -> None:
    """Borrado suave (solo Administrador; ver el router)."""
    marcar_eliminado_por(db, registro, usuario)
    db.commit()


def _verificar_autoria(registro: RegistroHorno, usuario: Usuario) -> None:
    if usuario.rol.codigo == RolCodigo.ADMIN:
        return
    if registro.usuario_id != usuario.id:
        raise ErrorDeValidacion("Solo puedes corregir los registros que tú mismo guardaste.")
