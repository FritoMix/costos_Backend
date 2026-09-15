"""
Calculo de los indicadores de produccion.

Formulas confirmadas explicitamente por la planta (no inventadas):

    Aceite por bulto      = kg de aceite consumido / cantidad de bultos
    % Rendimiento         = (kg de papa frita / kg crudos) x 100
    % Absorcion de aceite = (kg de aceite / kg de papa frita) x 100

Todos los totales se calculan sobre el conjunto de ordenes que cumple los
filtros elegidos. Si a un registro de horno le falta el calculo de aceite
(porque el horno todavia no tiene calibracion o densidad), esa parte
simplemente no se suma: no se inventa un valor.

Lo eliminado (borrado suave) nunca entra en estos numeros.
"""

from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.cache import TTL, cache_ttl
from app.modules.analitica.schemas import (
    Desglose,
    FilaBache,
    FiltrosAnalisis,
    IndicadoresCategoriaSalida,
    IndicadoresSalida,
)
from app.modules.catalogos.models import (
    CategoriaProducto,
    Horno,
    Producto,
    Sabor,
    TipoDesperdicio,
    Turno,
)
from app.modules.produccion.models import (
    Desperdicio,
    OrdenProduccion,
    RegistroHorno,
    RegistroSaborizado,
)

CERO = Decimal("0")


def consulta_ordenes_filtradas(filtros: FiltrosAnalisis) -> Select:
    """
    Ids de las ordenes que cumplen los filtros. Es la base de todo el
    modulo: los demas totales se calculan sobre este conjunto.
    """
    # Se compara con "is not None" y no con "if filtros.x", porque un id
    # podria ser 0 y "if 0" es False: ese filtro se ignoraria por error.
    consulta = select(OrdenProduccion.id).where(OrdenProduccion.eliminado == False)

    if filtros.fecha_desde is not None:
        consulta = consulta.where(OrdenProduccion.fecha >= filtros.fecha_desde)
    if filtros.fecha_hasta is not None:
        consulta = consulta.where(OrdenProduccion.fecha <= filtros.fecha_hasta)
    if filtros.turno_id is not None:
        consulta = consulta.where(OrdenProduccion.turno_id == filtros.turno_id)
    if filtros.horno_id is not None:
        consulta = consulta.where(OrdenProduccion.horno_id == filtros.horno_id)
    if filtros.producto_id is not None:
        consulta = consulta.where(OrdenProduccion.producto_id == filtros.producto_id)
    if filtros.categoria_id is not None:
        consulta = consulta.where(OrdenProduccion.categoria_id == filtros.categoria_id)
    if filtros.supervisor_id is not None:
        consulta = consulta.where(OrdenProduccion.supervisor_id == filtros.supervisor_id)
    if filtros.sabor_id is not None:
        # El sabor no es un campo de la orden: se registra en cada
        # recepcion. Una orden "tiene" ese sabor si alguna de sus
        # recepciones vivas lo uso.
        consulta = consulta.where(
            OrdenProduccion.id.in_(
                select(RegistroSaborizado.orden_id).where(
                    RegistroSaborizado.sabor_id == filtros.sabor_id,
                    RegistroSaborizado.eliminado == False,
                )
            )
        )
    return consulta


def _desglose(filas) -> list[Desglose]:
    return [Desglose(etiqueta=etiqueta, valor=valor) for etiqueta, valor in filas]


def _indicadores_cacheado(filtros: FiltrosAnalisis) -> IndicadoresSalida:
    """Version sin cache con su propia sesion, para no ensuciar la clave de
    cache con la sesion de cada request (que cambia siempre)."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        return _calcular_indicadores_interno(db, filtros)
    finally:
        db.close()


@cache_ttl(TTL.TREINTA_SEGUNDOS)
def _indicadores_cached_por_filtros(filtros: FiltrosAnalisis) -> dict:
    """Guarda el resultado cacheado como dict (pydantic son inmutables)."""
    resultado = _indicadores_cacheado(filtros)
    return resultado.model_dump()


def calcular_indicadores(db: Session, filtros: FiltrosAnalisis) -> IndicadoresSalida:
    """Punto de entrada publico: cachea 30s por filtros y usa la sesion que
    recibe solo cuando la cache esta fria."""
    resultado = _indicadores_cached_por_filtros(filtros)
    return IndicadoresSalida.model_validate(resultado)


def _calcular_indicadores_interno(db: Session, filtros: FiltrosAnalisis) -> IndicadoresSalida:
    ordenes = consulta_ordenes_filtradas(filtros).subquery()
    ids_ordenes = select(ordenes.c.id)

    numero_ordenes = db.scalar(select(func.count()).select_from(ordenes)) or 0

    # --- Totales de horno ---
    kg_crudos, bultos, kg_aceite = db.execute(
        select(
            func.coalesce(func.sum(RegistroHorno.kg_crudos_calculados), 0),
            func.coalesce(func.sum(RegistroHorno.cantidad_bultos), 0),
            func.coalesce(func.sum(RegistroHorno.kg_aceite_consumido), 0),
        ).where(RegistroHorno.orden_id.in_(ids_ordenes), RegistroHorno.eliminado == False)
    ).one()

    kg_desperdicio = db.scalar(
        select(func.coalesce(func.sum(Desperdicio.cantidad_kg), 0))
        .join(RegistroHorno, Desperdicio.registro_horno_id == RegistroHorno.id)
        .where(RegistroHorno.orden_id.in_(ids_ordenes), RegistroHorno.eliminado == False)
    ) or CERO

    # --- Totales de saborizado ---
    kg_papa_frita, kg_sabor = db.execute(
        select(
            func.coalesce(func.sum(RegistroSaborizado.kg_recibidos), 0),
            func.coalesce(func.sum(RegistroSaborizado.cantidad_sabor_kg), 0),
        ).where(
            RegistroSaborizado.orden_id.in_(ids_ordenes), RegistroSaborizado.eliminado == False
        )
    ).one()

    # --- Indicadores ---
    aceite_por_bulto = rendimiento = absorcion = None
    if bultos and bultos > 0:
        aceite_por_bulto = (kg_aceite / bultos).quantize(Decimal("0.01"))
    if kg_crudos and kg_crudos > 0:
        rendimiento = (kg_papa_frita / kg_crudos * 100).quantize(Decimal("0.01"))
    if kg_papa_frita and kg_papa_frita > 0:
        absorcion = (kg_aceite / kg_papa_frita * 100).quantize(Decimal("0.01"))

    # --- Desgloses para las graficas (produccion = kg de papa frita) ---
    def suma_papa_frita_por(columna, tabla, condicion_join, orden_por=None):
        consulta = (
            select(columna, func.coalesce(func.sum(RegistroSaborizado.kg_recibidos), 0))
            .select_from(RegistroSaborizado)
            .join(OrdenProduccion, RegistroSaborizado.orden_id == OrdenProduccion.id)
            .join(tabla, condicion_join)
            .where(
                RegistroSaborizado.orden_id.in_(ids_ordenes),
                RegistroSaborizado.eliminado == False,
            )
            .group_by(columna)
            .order_by(orden_por if orden_por is not None else columna)
        )
        return db.execute(consulta).all()

    por_horno = suma_papa_frita_por(Horno.nombre, Horno, OrdenProduccion.horno_id == Horno.id)
    por_turno = suma_papa_frita_por(Turno.nombre, Turno, OrdenProduccion.turno_id == Turno.id)
    por_producto = suma_papa_frita_por(
        Producto.nombre_comercial,
        Producto,
        OrdenProduccion.producto_id == Producto.id,
        orden_por=func.sum(RegistroSaborizado.kg_recibidos).desc(),
    )[:10]

    por_tipo_desperdicio = db.execute(
        select(TipoDesperdicio.nombre, func.coalesce(func.sum(Desperdicio.cantidad_kg), 0))
        .select_from(Desperdicio)
        .join(RegistroHorno, Desperdicio.registro_horno_id == RegistroHorno.id)
        .join(TipoDesperdicio, Desperdicio.tipo_desperdicio_id == TipoDesperdicio.id)
        .where(RegistroHorno.orden_id.in_(ids_ordenes), RegistroHorno.eliminado == False)
        .group_by(TipoDesperdicio.nombre)
        .order_by(func.sum(Desperdicio.cantidad_kg).desc())
    ).all()

    return IndicadoresSalida(
        numero_ordenes=numero_ordenes,
        kg_crudos=kg_crudos,
        cantidad_bultos=bultos,
        kg_papa_frita=kg_papa_frita,
        kg_sabor=kg_sabor,
        kg_desperdicio=kg_desperdicio,
        kg_aceite=kg_aceite,
        aceite_por_bulto=aceite_por_bulto,
        rendimiento_porcentaje=rendimiento,
        porcentaje_absorcion_aceite=absorcion,
        por_horno=_desglose(por_horno),
        por_producto=_desglose(por_producto),
        por_turno=_desglose(por_turno),
        por_tipo_desperdicio=_desglose(por_tipo_desperdicio),
    )


def calcular_indicadores_por_categoria(
    db: Session, filtros: FiltrosAnalisis
) -> list[IndicadoresCategoriaSalida]:
    """
    Un cuadro de indicadores por cada categoria presente en el resultado
    filtrado, en vez de todo mezclado en un solo total. Si ya se filtro por
    una categoria, sale un solo cuadro.

    Optimizacion: en vez de N queries (una por categoria), se ejecutan
    queries agregadas con GROUP BY que resuelven todo en ~4 consultas.
    """
    ordenes = consulta_ordenes_filtradas(filtros).subquery()
    ids_ordenes = select(ordenes.c.id)

    # 1) Totales de horno por categoria (una sola query).
    # Dict: categoria_id -> (kg_crudos, bultos, kg_aceite)
    horno_por_categoria: dict[int, tuple] = {}
    for cat_id, kg_crudos, bultos, kg_aceite in db.execute(
        select(
            OrdenProduccion.categoria_id,
            func.coalesce(func.sum(RegistroHorno.kg_crudos_calculados), 0),
            func.coalesce(func.sum(RegistroHorno.cantidad_bultos), 0),
            func.coalesce(func.sum(RegistroHorno.kg_aceite_consumido), 0),
        )
        .select_from(OrdenProduccion)
        .join(RegistroHorno, RegistroHorno.orden_id == OrdenProduccion.id)
        .where(
            OrdenProduccion.id.in_(ids_ordenes),
            RegistroHorno.eliminado == False,
        )
        .group_by(OrdenProduccion.categoria_id)
    ).all():
        horno_por_categoria[cat_id] = (kg_crudos, bultos, kg_aceite)

    # 2) Totales de desperdicio por categoria (una sola query)
    desperdicio_por_categoria = dict(
        db.execute(
            select(
                OrdenProduccion.categoria_id,
                func.coalesce(func.sum(Desperdicio.cantidad_kg), 0),
            )
            .select_from(OrdenProduccion)
            .join(RegistroHorno, RegistroHorno.orden_id == OrdenProduccion.id)
            .join(Desperdicio, Desperdicio.registro_horno_id == RegistroHorno.id)
            .where(
                OrdenProduccion.id.in_(ids_ordenes),
                RegistroHorno.eliminado == False,
            )
            .group_by(OrdenProduccion.categoria_id)
        ).all()
    )

    # 3) Totales de saborizado por categoria (una sola query).
    # Dict: categoria_id -> (kg_papa_frita, kg_sabor)
    saborizado_por_categoria: dict[int, tuple] = {}
    for cat_id, kg_papa_frita, kg_sabor in db.execute(
        select(
            OrdenProduccion.categoria_id,
            func.coalesce(func.sum(RegistroSaborizado.kg_recibidos), 0),
            func.coalesce(func.sum(RegistroSaborizado.cantidad_sabor_kg), 0),
        )
        .select_from(OrdenProduccion)
        .join(RegistroSaborizado, RegistroSaborizado.orden_id == OrdenProduccion.id)
        .where(
            OrdenProduccion.id.in_(ids_ordenes),
            RegistroSaborizado.eliminado == False,
        )
        .group_by(OrdenProduccion.categoria_id)
    ).all():
        saborizado_por_categoria[cat_id] = (kg_papa_frita, kg_sabor)

    # 4) Sabores por categoria (una sola query)
    sabores_por_categoria: dict[int, list] = {}
    for cat_id, sabor_nombre, kg in db.execute(
        select(
            OrdenProduccion.categoria_id,
            Sabor.nombre,
            func.coalesce(func.sum(RegistroSaborizado.kg_recibidos), 0),
        )
        .select_from(OrdenProduccion)
        .join(RegistroSaborizado, RegistroSaborizado.orden_id == OrdenProduccion.id)
        .join(Sabor, RegistroSaborizado.sabor_id == Sabor.id)
        .where(
            OrdenProduccion.id.in_(ids_ordenes),
            RegistroSaborizado.eliminado == False,
        )
        .group_by(OrdenProduccion.categoria_id, Sabor.nombre)
        .order_by(OrdenProduccion.categoria_id, func.sum(RegistroSaborizado.kg_recibidos).desc())
    ).all():
        sabores_por_categoria.setdefault(cat_id, []).append((sabor_nombre, kg))

    # 5) Conteo de ordenes por categoria
    conteo_por_categoria = dict(
        db.execute(
            select(OrdenProduccion.categoria_id, func.count())
            .where(OrdenProduccion.id.in_(ids_ordenes))
            .group_by(OrdenProduccion.categoria_id)
        ).all()
    )

    # Construir resultado
    categorias = db.execute(
        select(CategoriaProducto.id, CategoriaProducto.nombre)
        .join(OrdenProduccion, OrdenProduccion.categoria_id == CategoriaProducto.id)
        .where(OrdenProduccion.id.in_(ids_ordenes))
        .distinct()
        .order_by(CategoriaProducto.nombre)
    ).all()

    resultado: list[IndicadoresCategoriaSalida] = []
    for categoria_id, categoria_nombre in categorias:
        kg_crudos, bultos, kg_aceite = horno_por_categoria.get(categoria_id, (CERO, CERO, CERO))
        kg_desperdicio = desperdicio_por_categoria.get(categoria_id, CERO)
        kg_papa_frita, kg_sabor = saborizado_por_categoria.get(categoria_id, (CERO, CERO))
        numero_ordenes = conteo_por_categoria.get(categoria_id, 0)

        aceite_por_bulto = rendimiento = absorcion = None
        if bultos and bultos > 0:
            aceite_por_bulto = (kg_aceite / bultos).quantize(Decimal("0.01"))
        if kg_crudos and kg_crudos > 0:
            rendimiento = (kg_papa_frita / kg_crudos * 100).quantize(Decimal("0.01"))
        if kg_papa_frita and kg_papa_frita > 0:
            absorcion = (kg_aceite / kg_papa_frita * 100).quantize(Decimal("0.01"))

        sabores = sabores_por_categoria.get(categoria_id, [])

        resultado.append(
            IndicadoresCategoriaSalida(
                categoria_id=categoria_id,
                categoria_nombre=categoria_nombre,
                numero_ordenes=numero_ordenes,
                kg_crudos=kg_crudos,
                cantidad_bultos=bultos,
                kg_papa_frita=kg_papa_frita,
                kg_sabor=kg_sabor,
                kg_desperdicio=kg_desperdicio,
                kg_aceite=kg_aceite,
                aceite_por_bulto=aceite_por_bulto,
                rendimiento_porcentaje=rendimiento,
                porcentaje_absorcion_aceite=absorcion,
                sabores_usados=_desglose(sabores),
            )
        )
    return resultado


def obtener_detalle_baches(db: Session, filtros: FiltrosAnalisis) -> list[FilaBache]:
    """
    Una fila por cada tanda de horno.

    IMPORTANTE: los kg de papa frita se registran por ORDEN completa (en
    saborizado), no por cada tanda. Si una orden tuvo varias tandas, aqui
    se usa el total de papa frita de TODA la orden para calcular los
    porcentajes de esa fila: es la mejor aproximacion posible con los
    datos que existen, y en pantalla se avisa.
    """
    ordenes = consulta_ordenes_filtradas(filtros).subquery()

    registros = list(
        db.scalars(
            select(RegistroHorno)
            .where(
                RegistroHorno.orden_id.in_(select(ordenes.c.id)),
                RegistroHorno.eliminado == False,
            )
            .order_by(RegistroHorno.hora_inicio.desc())
            .limit(500)
        )
        .unique()
        .all()
    )
    if not registros:
        return []

    orden_ids = {r.orden_id for r in registros}
    papa_frita_por_orden = dict(
        db.execute(
            select(
                RegistroSaborizado.orden_id,
                func.coalesce(func.sum(RegistroSaborizado.kg_recibidos), 0),
            )
            .where(
                RegistroSaborizado.orden_id.in_(orden_ids),
                RegistroSaborizado.eliminado == False,
            )
            .group_by(RegistroSaborizado.orden_id)
        ).all()
    )

    filas: list[FilaBache] = []
    for registro in registros:
        orden = registro.orden
        kg_papa_frita = papa_frita_por_orden.get(registro.orden_id, CERO)

        aceite_por_bulto = rendimiento = absorcion = None
        if registro.kg_aceite_consumido is not None and registro.cantidad_bultos > 0:
            aceite_por_bulto = (registro.kg_aceite_consumido / registro.cantidad_bultos).quantize(
                Decimal("0.01")
            )
        if registro.kg_crudos_calculados > 0:
            rendimiento = (kg_papa_frita / registro.kg_crudos_calculados * 100).quantize(
                Decimal("0.01")
            )
        if kg_papa_frita > 0 and registro.kg_aceite_consumido is not None:
            absorcion = (registro.kg_aceite_consumido / kg_papa_frita * 100).quantize(
                Decimal("0.01")
            )

        kg_desperdicio = sum((d.cantidad_kg for d in registro.desperdicios), CERO)
        horas = Decimal(
            str(round((registro.hora_fin - registro.hora_inicio).total_seconds() / 3600, 2))
        )

        filas.append(
            FilaBache(
                registro_id=registro.id,
                numero_orden=orden.numero_orden,
                fecha=orden.fecha,
                hora_inicio=registro.hora_inicio,
                hora_fin=registro.hora_fin,
                duracion_horas=horas,
                horno=orden.horno.nombre,
                producto=orden.producto.nombre_comercial,
                categoria=orden.categoria.nombre,
                turno=orden.turno.nombre,
                supervisor=orden.supervisor.nombre_completo,
                operario=registro.usuario.nombre_completo,
                cantidad_bultos=registro.cantidad_bultos,
                kg_crudos=registro.kg_crudos_calculados,
                kg_papa_frita_orden=kg_papa_frita,
                kg_aceite=registro.kg_aceite_consumido,
                temperatura_aceite_c=registro.temperatura_aceite_c,
                kg_desperdicio=kg_desperdicio,
                aceite_por_bulto=aceite_por_bulto,
                rendimiento_porcentaje=rendimiento,
                porcentaje_absorcion_aceite=absorcion,
            )
        )
    return filas
