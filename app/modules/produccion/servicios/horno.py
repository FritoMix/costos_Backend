"""
Logica de negocio del registro de horno (las tandas de fritura).

Lo que calcula la app sola, para que el operario no tenga que hacerlo:
  kg crudos      = bultos x peso estandar del bulto (copiado al registro)
  litros aceite  = diferencia de nivel en cm x litros por cm del tanque
  kg de aceite   = litros x densidad vigente de ese horno en esa fecha

Si falta la calibracion del tanque o la densidad, esas columnas quedan
vacias: el registro se guarda igual y no se inventa ningun valor.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.borrado_suave import marcar_eliminado_por
from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.core.tiempo import combinar_fecha_y_hora
from app.modules.catalogos.models import Horno, TipoDesperdicio
from app.modules.catalogos.service import obtener_densidad_vigente, obtener_peso_estandar_bulto
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.produccion.models import (
    Desperdicio,
    EstadoOrden,
    OrdenProduccion,
    RegistroHorno,
)
from app.modules.produccion.schemas import RegistroHornoGuardar


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


def _aplicar_datos(
    db: Session, registro: RegistroHorno, orden: OrdenProduccion, datos: RegistroHornoGuardar
) -> None:
    peso_bulto = obtener_peso_estandar_bulto(db)
    diferencia = datos.nivel_aceite_inicial_cm - datos.nivel_aceite_final_cm
    litros_por_cm, volumen, densidad, kg_aceite = calcular_aceite(
        db, orden.horno, orden.fecha, diferencia
    )
    inicio, fin = combinar_fecha_y_hora(orden.fecha, datos.hora_inicio, datos.hora_fin)

    registro.hora_inicio = inicio
    registro.hora_fin = fin
    registro.cantidad_bultos = datos.cantidad_bultos
    registro.peso_estandar_bulto_kg = peso_bulto
    registro.kg_crudos_calculados = (datos.cantidad_bultos * peso_bulto).quantize(Decimal("0.01"))
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
