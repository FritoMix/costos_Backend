"""
Logica de negocio de las ordenes de produccion.

Reglas que viven aqui (confirmadas con la planta, no inventadas):
  * El numero de orden es OP-AAAAMMDD-0001 y reinicia cada dia.
  * Una orden de exportacion solo puede ir a un horno apto para exportar.
  * Una orden nacional solo puede ir a un horno que produzca esa categoria.
  * El producto tiene que pertenecer a la categoria elegida.
  * Un horno NUNCA puede tener dos ordenes en produccion a la vez.
  * Si el pedido llego en canastillas, se convierte a kg con un peso
    ESTIMADO (del producto, o el general): el peso real de cada canastilla
    se sigue pesando en saborizado.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.borrado_suave import marcar_eliminado_por
from app.core.errores import ErrorDeValidacion, RecursoNoEncontrado
from app.core.tiempo import hoy_local
from app.modules.catalogos.models import Horno, Producto
from app.modules.catalogos.service import obtener_configuracion
from app.modules.identidad.models import RolCodigo, Usuario
from app.modules.notificaciones import service as notificaciones
from app.modules.produccion.models import (
    DestinoOrden,
    EstadoOrden,
    OrdenProduccion,
    RegistroHorno,
    RegistroSaborizado,
    SecuenciaOrden,
    UnidadSolicitada,
)
from app.modules.produccion.schemas import OrdenGuardar

logger = logging.getLogger("datacontrol")

# --- Consultas -------------------------------------------------------------


def obtener_orden(db: Session, orden_id: int) -> OrdenProduccion:
    orden = db.get(OrdenProduccion, orden_id)
    if orden is None or orden.eliminado:
        raise RecursoNoEncontrado("Esa orden no existe.")
    return orden


def listar_ordenes(
    db: Session,
    *,
    usuario: Usuario,
    estado: str | None = None,
    solo_propias: bool | None = None,
) -> list[OrdenProduccion]:
    """
    Lista de ordenes visibles.

    Un supervisor ve por defecto solo las suyas (es lo que gestiona);
    el administrador ve todas. Los operarios usan el filtro
    estado='en_produccion' para ver a que orden pueden registrarle datos.
    """
    consulta = select(OrdenProduccion).where(OrdenProduccion.eliminado == False)

    if estado is not None:
        consulta = consulta.where(OrdenProduccion.estado == estado)

    if solo_propias is None:
        solo_propias = usuario.rol.codigo == RolCodigo.SUPERVISOR
    if solo_propias:
        consulta = consulta.where(OrdenProduccion.supervisor_id == usuario.id)

    consulta = consulta.order_by(OrdenProduccion.fecha.desc(), OrdenProduccion.id.desc()).limit(500)
    return list(db.scalars(consulta).unique().all())


# --- Numeracion ------------------------------------------------------------


def generar_numero_orden(db: Session, fecha) -> str:
    """
    Siguiente numero del dia. Se usa una operacion atomica de PostgreSQL
    (INSERT ... ON CONFLICT DO UPDATE): si dos supervisores crean una orden
    en el mismo instante, cada uno recibe un numero distinto.
    """
    tabla = SecuenciaOrden.__table__
    sentencia = (
        insert(tabla)
        .values(fecha=fecha, ultimo_numero=1)
        .on_conflict_do_update(
            index_elements=[tabla.c.fecha],
            set_={"ultimo_numero": tabla.c.ultimo_numero + 1},
        )
        .returning(tabla.c.ultimo_numero)
    )
    consecutivo = db.execute(sentencia).scalar_one()
    return f"OP-{fecha:%Y%m%d}-{consecutivo:04d}"


# --- Validaciones compartidas ---------------------------------------------


def _validar_horas(datos: OrdenGuardar) -> None:
    """
    La orden se programa por HORAS COMPLETAS: en la planta no existen medias
    horas de produccion (una orden va 1, 2, 3... horas). El tipo entero del
    schema ya rechaza los decimales; aqui se cuida el minimo de una hora.
    El mismo limite esta en la base de datos (ck_orden_horas_minimo_una).
    """
    if datos.horas_produccion is None:
        raise ErrorDeValidacion("Debes indicar cuántas horas se va a mandar a producción.")
    if datos.horas_produccion < 1:
        raise ErrorDeValidacion("La producción debe programarse por al menos 1 hora completa.")


def _validar_catalogos(db: Session, datos: OrdenGuardar) -> tuple[Horno, Producto]:
    if datos.destino not in (DestinoOrden.NACIONAL, DestinoOrden.EXPORTACION):
        raise ErrorDeValidacion("El destino debe ser Nacional o Exportación.")
    if datos.unidad_solicitada not in (UnidadSolicitada.KG, UnidadSolicitada.CANASTILLAS):
        raise ErrorDeValidacion("La unidad solicitada debe ser Kg o Canastillas.")

    _validar_horas(datos)

    horno = db.get(Horno, datos.horno_id)
    if horno is None or not horno.activo:
        raise ErrorDeValidacion("El horno seleccionado no es válido.")

    if datos.destino == DestinoOrden.EXPORTACION:
        # Toda orden de exportacion se trabaja en un horno habilitado para
        # exportar, sin importar la categoria.
        if not horno.apto_exportacion:
            raise ErrorDeValidacion(
                f'El horno "{horno.nombre}" no está habilitado para órdenes de exportación.'
            )
    else:
        if datos.categoria_id not in {c.id for c in horno.categorias}:
            raise ErrorDeValidacion(f'El horno "{horno.nombre}" no puede producir esa categoría.')

    producto = db.get(Producto, datos.producto_id)
    if producto is None or not producto.activo:
        raise ErrorDeValidacion("El producto seleccionado no es válido.")
    if producto.categoria_id != datos.categoria_id:
        raise ErrorDeValidacion(
            f'El producto "{producto.nombre_comercial}" no pertenece a esa categoría.'
        )

    return horno, producto


def calcular_cantidad_programada(
    db: Session, datos: OrdenGuardar, producto: Producto
) -> tuple[Decimal, Decimal | None]:
    """
    Cuantos kg tiene la orden.

    Si al supervisor le pidieron canastillas, se convierten a kg con un
    peso ESTIMADO por canastilla: primero el del producto (cada referencia
    pesa distinto; cabello de angel pesa mas), y si no tiene, el valor
    general de Catalogos > Configuracion.

    Devuelve (cantidad_programada_kg, cantidad_canastillas_solicitadas).
    """
    if datos.unidad_solicitada == UnidadSolicitada.CANASTILLAS:
        if datos.cantidad_canastillas is None or datos.cantidad_canastillas <= 0:
            raise ErrorDeValidacion("Debes indicar cuántas canastillas se solicitaron.")

        peso_canastilla = producto.peso_estandar_canastilla_kg
        if peso_canastilla is None:
            peso_canastilla = obtener_configuracion(db).peso_estandar_canastilla_kg
        if peso_canastilla is None:
            raise ErrorDeValidacion(
                "Todavía no hay un peso estándar de canastilla configurado para este producto "
                "ni uno general. Pídele al Administrador que lo configure en Catálogos > "
                "Productos (o en Catálogos > Configuración como valor general)."
            )
        cantidad_kg = (datos.cantidad_canastillas * peso_canastilla).quantize(Decimal("0.01"))
        return cantidad_kg, datos.cantidad_canastillas

    if datos.cantidad_kg is None or datos.cantidad_kg <= 0:
        raise ErrorDeValidacion("La cantidad programada debe ser mayor a cero.")
    return datos.cantidad_kg, None


# --- Operaciones -----------------------------------------------------------


def crear_orden(db: Session, datos: OrdenGuardar, supervisor: Usuario) -> OrdenProduccion:
    _horno, producto = _validar_catalogos(db, datos)
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
    )
    db.add(orden)
    db.commit()
    db.refresh(orden)

    # Aviso a los operarios de que hay una orden nueva que trabajar. Si algo
    # falla al notificar, la orden YA quedo creada: se registra el problema
    # pero no se le devuelve un error al supervisor.
    try:
        notificaciones.avisar_orden_creada(db, orden)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo notificar la creación de la orden %s", orden.numero_orden)

    return orden


def editar_orden(db: Session, orden: OrdenProduccion, datos: OrdenGuardar) -> OrdenProduccion:
    """
    Corrige una orden ya creada, por si el supervisor se equivoco. Solo
    mientras sigue activa: una vez Finalizada o Cancelada no se toca.
    """
    if orden.estado not in EstadoOrden.ACTIVOS:
        raise ErrorDeValidacion(
            "Esta orden ya no se puede editar porque está Finalizada o Cancelada."
        )

    _horno, producto = _validar_catalogos(db, datos)

    if orden.estado == EstadoOrden.EN_PRODUCCION and datos.horno_id != orden.horno_id:
        # Cambiar de horno con la orden ya en produccion vuelve a chocar
        # con la regla de "un horno, una orden a la vez".
        ocupado = db.scalar(
            select(OrdenProduccion).where(
                OrdenProduccion.horno_id == datos.horno_id,
                OrdenProduccion.estado == EstadoOrden.EN_PRODUCCION,
                OrdenProduccion.id != orden.id,
            )
        )
        if ocupado is not None:
            raise ErrorDeValidacion(
                f"Ese horno ya tiene la orden {ocupado.numero_orden} en producción."
            )

    cantidad_kg, canastillas = calcular_cantidad_programada(db, datos, producto)

    orden.turno_id = datos.turno_id
    orden.horno_id = datos.horno_id
    orden.producto_id = datos.producto_id
    orden.categoria_id = datos.categoria_id
    orden.unidad_solicitada = datos.unidad_solicitada
    orden.cantidad_canastillas_solicitadas = canastillas
    orden.horas_produccion = datos.horas_produccion
    orden.cantidad_programada = cantidad_kg
    orden.destino = datos.destino

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ErrorDeValidacion(
            "Ese horno acaba de quedar ocupado por otra orden. Intenta de nuevo."
        ) from exc
    db.refresh(orden)
    return orden


def iniciar_orden(db: Session, orden: OrdenProduccion) -> OrdenProduccion:
    if orden.estado != EstadoOrden.PENDIENTE:
        raise ErrorDeValidacion("Solo se puede iniciar una orden que esté Pendiente.")

    ocupado = db.scalar(
        select(OrdenProduccion).where(
            OrdenProduccion.horno_id == orden.horno_id,
            OrdenProduccion.estado == EstadoOrden.EN_PRODUCCION,
        )
    )
    if ocupado is not None:
        raise ErrorDeValidacion(
            f'El horno "{orden.horno.nombre}" ya tiene la orden {ocupado.numero_orden} en '
            "producción. Debes finalizarla antes de iniciar otra."
        )

    orden.estado = EstadoOrden.EN_PRODUCCION
    orden.hora_inicio = datetime.now(UTC)
    try:
        db.commit()
    except IntegrityError as exc:
        # Segunda linea de defensa: si dos peticiones pasaron la validacion
        # casi al mismo tiempo, el indice unico de PostgreSQL rechaza la
        # segunda. Se convierte en un mensaje claro, no en un error tecnico.
        db.rollback()
        raise ErrorDeValidacion(
            "Ese horno acaba de quedar ocupado por otra orden. Intenta de nuevo."
        ) from exc
    db.refresh(orden)

    # Aqui empieza a correr el reloj de la produccion: se deja programado el
    # aviso de "faltan 15 minutos" para el final calculado.
    try:
        notificaciones.programar_aviso_fin_produccion(db, orden)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo programar el aviso de fin de %s", orden.numero_orden)

    return orden


def finalizar_orden(db: Session, orden: OrdenProduccion) -> OrdenProduccion:
    if orden.estado != EstadoOrden.EN_PRODUCCION:
        raise ErrorDeValidacion("Solo se puede finalizar una orden que esté En producción.")
    orden.estado = EstadoOrden.FINALIZADA
    orden.hora_fin = datetime.now(UTC)
    db.commit()
    db.refresh(orden)
    return orden


def cancelar_orden(db: Session, orden: OrdenProduccion) -> OrdenProduccion:
    if orden.estado not in EstadoOrden.ACTIVOS:
        raise ErrorDeValidacion("Esta orden ya no se puede cancelar.")
    orden.estado = EstadoOrden.CANCELADA
    db.commit()
    db.refresh(orden)
    return orden


def eliminar_orden(db: Session, orden: OrdenProduccion, usuario: Usuario) -> int:
    """
    Borrado suave CON CASCADA: si el administrador elimina una orden es
    porque vio algo raro y quiere borrarla completa de un solo clic. La
    orden y todos sus registros activos quedan marcados como eliminados:
    desaparecen de listas, Analisis y exportaciones, pero siguen en la base
    de datos para poder auditar.

    Devuelve cuantos registros de horno/saborizado se llevo consigo.
    """
    arrastrados = 0

    registros_horno = db.scalars(
        select(RegistroHorno).where(
            RegistroHorno.orden_id == orden.id, RegistroHorno.eliminado == False
        )
    ).unique().all()
    registros_saborizado = db.scalars(
        select(RegistroSaborizado).where(
            RegistroSaborizado.orden_id == orden.id, RegistroSaborizado.eliminado == False
        )
    ).unique().all()

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

    marcar_eliminado_por(db, orden, usuario)
    db.commit()
    return arrastrados
