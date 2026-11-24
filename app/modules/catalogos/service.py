"""
Logica del modulo Catalogos.

Regla general de borrado, igual para todos los catalogos: un elemento solo
se borra de verdad si NUNCA se ha usado. Si ya aparece en productos,
hornos, ordenes o registros, se rechaza con un mensaje claro y se propone
desactivarlo: asi ningun dato historico queda huerfano.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errores import ConflictoDeDatos, ErrorDeValidacion, RecursoNoEncontrado
from app.modules.catalogos.models import (
    CategoriaProducto,
    ConfiguracionPlanta,
    Horno,
    Linea,
    MuestraDensidadAceite,
    Producto,
    Sabor,
    TipoAceite,
    TipoDesperdicio,
    Turno,
    Variedad,
    horno_categoria,
)
from app.modules.catalogos.schemas import (
    CatalogoGuardar,
    CategoriaGuardar,
    ConfiguracionGuardar,
    HornoGuardar,
    MuestraDensidadCrear,
    ProductoGuardar,
    TipoAceiteGuardar,
    TurnoGuardar,
    VariedadGuardar,
)

# --- Utilidades comunes ----------------------------------------------------


def _obtener(db: Session, modelo, registro_id: int, que_es: str):
    registro = db.get(modelo, registro_id)
    if registro is None:
        raise RecursoNoEncontrado(f"{que_es} no existe.")
    return registro


def _nombre_libre(db: Session, modelo, columna, nombre: str, excepto_id: int | None) -> None:
    consulta = select(modelo).where(columna == nombre)
    if excepto_id is not None:
        consulta = consulta.where(modelo.id != excepto_id)
    if db.scalar(consulta) is not None:
        raise ConflictoDeDatos(f'Ya existe un registro con el nombre "{nombre}".')


def _existe(db: Session, consulta) -> bool:
    return db.scalar(consulta.limit(1)) is not None


# --- Categorias ------------------------------------------------------------


def listar_categorias(db: Session, solo_activas: bool = False) -> list[CategoriaProducto]:
    consulta = (
        select(CategoriaProducto)
        .options(selectinload(CategoriaProducto.sabores))
        .order_by(CategoriaProducto.nombre)
    )
    if solo_activas:
        consulta = consulta.where(CategoriaProducto.activo == True)
    return list(db.scalars(consulta).all())


def _aplicar_sabores(db: Session, categoria: CategoriaProducto, sabor_ids: list[int] | None) -> None:
    if sabor_ids is None:
        return
    sabores = []
    for sabor_id in dict.fromkeys(sabor_ids):
        sabor = db.get(Sabor, sabor_id)
        if sabor is None:
            raise ErrorDeValidacion("Uno de los sabores seleccionados no existe.")
        sabores.append(sabor)
    categoria.sabores = sabores


def crear_categoria(db: Session, datos: CategoriaGuardar) -> CategoriaProducto:
    nombre = datos.nombre.strip()
    _nombre_libre(db, CategoriaProducto, CategoriaProducto.nombre, nombre, None)
    categoria = CategoriaProducto(nombre=nombre, activo=datos.activo)
    _aplicar_sabores(db, categoria, datos.sabor_ids)
    db.add(categoria)
    db.commit()
    db.refresh(categoria)
    return categoria


def actualizar_categoria(db: Session, categoria_id: int, datos: CategoriaGuardar) -> CategoriaProducto:
    categoria = _obtener(db, CategoriaProducto, categoria_id, "Esa categoría")
    nombre = datos.nombre.strip()
    _nombre_libre(db, CategoriaProducto, CategoriaProducto.nombre, nombre, categoria_id)
    categoria.nombre = nombre
    categoria.activo = datos.activo
    _aplicar_sabores(db, categoria, datos.sabor_ids)
    db.commit()
    db.refresh(categoria)
    return categoria


def eliminar_categoria(db: Session, categoria_id: int) -> None:
    from app.modules.produccion.models import OrdenProduccion

    categoria = _obtener(db, CategoriaProducto, categoria_id, "Esa categoría")
    en_uso = (
        _existe(db, select(Producto.id).where(Producto.categoria_id == categoria_id))
        or _existe(db, select(OrdenProduccion.id).where(OrdenProduccion.categoria_id == categoria_id))
        or _existe(
            db,
            select(horno_categoria.c.horno_id).where(horno_categoria.c.categoria_id == categoria_id),
        )
    )
    if en_uso:
        raise ErrorDeValidacion(
            f'No se puede eliminar "{categoria.nombre}": ya está en uso (productos, hornos u '
            "órdenes). Puedes desactivarla en su lugar."
        )
    db.delete(categoria)
    db.commit()


# --- Sabores ---------------------------------------------------------------


def listar_sabores(
    db: Session, solo_activos: bool = False, categoria_id: int | None = None
) -> list[Sabor]:
    """Sabores; con categoria_id, solo los de esa categoria (si tiene asignados)."""
    consulta = select(Sabor).order_by(Sabor.nombre)
    if solo_activos:
        consulta = consulta.where(Sabor.activo == True)
    sabores = list(db.scalars(consulta).all())
    if categoria_id is not None:
        categoria = db.get(CategoriaProducto, categoria_id)
        permitidos = {s.id for s in categoria.sabores} if categoria else set()
        if permitidos:
            sabores = [s for s in sabores if s.id in permitidos]
    return sabores


def crear_sabor(db: Session, datos: CatalogoGuardar) -> Sabor:
    nombre = datos.nombre.strip()
    _nombre_libre(db, Sabor, Sabor.nombre, nombre, None)
    sabor = Sabor(nombre=nombre, activo=datos.activo)
    db.add(sabor)
    db.commit()
    db.refresh(sabor)
    return sabor


def actualizar_sabor(db: Session, sabor_id: int, datos: CatalogoGuardar) -> Sabor:
    sabor = _obtener(db, Sabor, sabor_id, "Ese sabor")
    nombre = datos.nombre.strip()
    _nombre_libre(db, Sabor, Sabor.nombre, nombre, sabor_id)
    sabor.nombre = nombre
    sabor.activo = datos.activo
    db.commit()
    db.refresh(sabor)
    return sabor


def eliminar_sabor(db: Session, sabor_id: int) -> None:
    from app.modules.produccion.models import RegistroSaborizado

    sabor = _obtener(db, Sabor, sabor_id, "Ese sabor")
    if _existe(db, select(RegistroSaborizado.id).where(RegistroSaborizado.sabor_id == sabor_id)):
        raise ErrorDeValidacion(
            f'No se puede eliminar "{sabor.nombre}": ya tiene recepciones registradas. '
            "Puedes desactivarlo en su lugar."
        )
    db.delete(sabor)
    db.commit()


# --- Tipos de desperdicio --------------------------------------------------


def listar_tipos_desperdicio(db: Session, solo_activos: bool = False) -> list[TipoDesperdicio]:
    consulta = select(TipoDesperdicio).order_by(TipoDesperdicio.nombre)
    if solo_activos:
        consulta = consulta.where(TipoDesperdicio.activo == True)
    return list(db.scalars(consulta).all())


def crear_tipo_desperdicio(db: Session, datos: CatalogoGuardar) -> TipoDesperdicio:
    nombre = datos.nombre.strip()
    _nombre_libre(db, TipoDesperdicio, TipoDesperdicio.nombre, nombre, None)
    tipo = TipoDesperdicio(nombre=nombre, activo=datos.activo)
    db.add(tipo)
    db.commit()
    db.refresh(tipo)
    return tipo


def actualizar_tipo_desperdicio(
    db: Session, tipo_id: int, datos: CatalogoGuardar
) -> TipoDesperdicio:
    tipo = _obtener(db, TipoDesperdicio, tipo_id, "Ese tipo de desperdicio")
    nombre = datos.nombre.strip()
    _nombre_libre(db, TipoDesperdicio, TipoDesperdicio.nombre, nombre, tipo_id)
    tipo.nombre = nombre
    tipo.activo = datos.activo
    db.commit()
    db.refresh(tipo)
    return tipo


def eliminar_tipo_desperdicio(db: Session, tipo_id: int) -> None:
    from app.modules.produccion.models import Desperdicio

    tipo = _obtener(db, TipoDesperdicio, tipo_id, "Ese tipo de desperdicio")
    if _existe(db, select(Desperdicio.id).where(Desperdicio.tipo_desperdicio_id == tipo_id)):
        raise ErrorDeValidacion(
            f'No se puede eliminar "{tipo.nombre}": ya se usó en registros de horno. '
            "Puedes desactivarlo en su lugar."
        )
    db.delete(tipo)
    db.commit()


# --- Turnos ----------------------------------------------------------------


def listar_turnos(db: Session, solo_activos: bool = False) -> list[Turno]:
    consulta = select(Turno).order_by(Turno.hora_inicio)
    if solo_activos:
        consulta = consulta.where(Turno.activo == True)
    return list(db.scalars(consulta).all())


def _aplicar_datos_turno(turno: Turno, datos: TurnoGuardar) -> None:
    if datos.hora_inicio == datos.hora_fin:
        raise ErrorDeValidacion("La hora de inicio y la de fin no pueden ser iguales.")
    turno.nombre = datos.nombre.strip()
    turno.hora_inicio = datos.hora_inicio
    turno.hora_fin = datos.hora_fin
    # El turno nocturno se detecta solo: no hay que preguntarselo a nadie.
    turno.cruza_medianoche = datos.hora_fin < datos.hora_inicio
    turno.activo = datos.activo


def crear_turno(db: Session, datos: TurnoGuardar) -> Turno:
    _nombre_libre(db, Turno, Turno.nombre, datos.nombre.strip(), None)
    turno = Turno()
    _aplicar_datos_turno(turno, datos)
    db.add(turno)
    db.commit()
    db.refresh(turno)
    return turno


def actualizar_turno(db: Session, turno_id: int, datos: TurnoGuardar) -> Turno:
    turno = _obtener(db, Turno, turno_id, "Ese turno")
    _nombre_libre(db, Turno, Turno.nombre, datos.nombre.strip(), turno_id)
    _aplicar_datos_turno(turno, datos)
    db.commit()
    db.refresh(turno)
    return turno


def eliminar_turno(db: Session, turno_id: int) -> None:
    from app.modules.produccion.models import OrdenProduccion, RegistroSaborizado

    turno = _obtener(db, Turno, turno_id, "Ese turno")
    en_uso = _existe(
        db, select(OrdenProduccion.id).where(OrdenProduccion.turno_id == turno_id)
    ) or _existe(db, select(RegistroSaborizado.id).where(RegistroSaborizado.turno_id == turno_id))
    if en_uso:
        raise ErrorDeValidacion(
            f'No se puede eliminar "{turno.nombre}": ya tiene órdenes o recepciones. '
            "Puedes desactivarlo en su lugar."
        )
    db.delete(turno)
    db.commit()


def detectar_turno_por_hora(db: Session, hora) -> Turno:
    """
    A que turno pertenece una hora del reloj. Se usa en saborizado para no
    tener que preguntarselo al operario.
    """
    for turno in listar_turnos(db, solo_activos=True):
        if turno.contiene(hora):
            return turno
    raise ErrorDeValidacion(
        "No hay ningún turno configurado que incluya esa hora. "
        "Pídele al Administrador que revise los turnos en Catálogos."
    )


# --- Hornos ----------------------------------------------------------------


def listar_hornos(db: Session, solo_activos: bool = False) -> list[Horno]:
    consulta = select(Horno).order_by(Horno.nombre)
    if solo_activos:
        consulta = consulta.where(Horno.activo == True)
    return list(db.scalars(consulta).unique().all())


def obtener_horno(db: Session, horno_id: int) -> Horno:
    return _obtener(db, Horno, horno_id, "Ese horno")


def _aplicar_datos_horno(db: Session, horno: Horno, datos: HornoGuardar) -> None:
    horno.nombre = datos.nombre.strip()
    horno.activo = datos.activo
    horno.tipo_aceite = (datos.tipo_aceite or "").strip() or None
    if "aceite_id" in datos.model_fields_set:
        if datos.aceite_id is not None:
            aceite = _obtener(db, TipoAceite, datos.aceite_id, "Ese aceite")
            if not aceite.activo and aceite.id != horno.aceite_id:
                raise ErrorDeValidacion(f'El aceite "{aceite.nombre}" está desactivado.')
        horno.aceite_id = datos.aceite_id
    horno.apto_exportacion = datos.apto_exportacion
    horno.tanque_diametro_cm = datos.tanque_diametro_cm
    horno.litros_por_cm_manual = datos.litros_por_cm_manual
    # En una actualizacion, un cliente viejo puede omitir el campo. En ese
    # caso se conserva la capacidad ya configurada; un NULL explicito la
    # borra (solo Administracion puede hacerlo desde la API).
    if "capacidad_bultos_hora" in datos.model_fields_set:
        horno.capacidad_bultos_hora = datos.capacidad_bultos_hora
    _aplicar_linea_horno(db, horno, datos.linea_id)

    categorias = []
    for categoria_id in datos.categoria_ids:
        categoria = db.get(CategoriaProducto, categoria_id)
        if categoria is None:
            raise ErrorDeValidacion("Una de las categorías seleccionadas no existe.")
        categorias.append(categoria)
    horno.categorias = categorias


def _aplicar_linea_horno(db: Session, horno: Horno, linea_id: int | None) -> None:
    """
    Linea del horno (V21). Sin linea_id: un horno nuevo queda de papa y uno
    existente conserva la suya. No se cambia la linea con una orden abierta.
    """
    if linea_id is None:
        if horno.linea_id is None:
            horno.linea_id = linea_por_codigo(db, "papa").id
        return
    linea = _obtener(db, Linea, linea_id, "Esa línea")
    if not linea.activo and linea.id != horno.linea_id:
        raise ErrorDeValidacion(f'La línea "{linea.nombre}" está desactivada.')
    if horno.id is not None and horno.linea_id != linea.id:
        from app.modules.produccion.models import EstadoOrden, OrdenProduccion

        abierta = _existe(
            db,
            select(OrdenProduccion.id).where(
                OrdenProduccion.horno_id == horno.id,
                OrdenProduccion.eliminado == False,  # noqa: E712
                OrdenProduccion.estado.in_([EstadoOrden.PENDIENTE, EstadoOrden.EN_PRODUCCION]),
            ),
        )
        if abierta:
            raise ErrorDeValidacion(
                f'"{horno.nombre}" tiene una orden abierta: ciérrala antes de cambiarle la línea.'
            )
    horno.linea_id = linea.id


def crear_horno(db: Session, datos: HornoGuardar) -> Horno:
    _nombre_libre(db, Horno, Horno.nombre, datos.nombre.strip(), None)
    horno = Horno()
    _aplicar_datos_horno(db, horno, datos)
    db.add(horno)
    db.commit()
    db.refresh(horno)
    return horno


def actualizar_horno(db: Session, horno_id: int, datos: HornoGuardar) -> Horno:
    horno = obtener_horno(db, horno_id)
    _nombre_libre(db, Horno, Horno.nombre, datos.nombre.strip(), horno_id)
    _aplicar_datos_horno(db, horno, datos)
    db.commit()
    db.refresh(horno)
    return horno


def actualizar_capacidad_horno(
    db: Session, horno_id: int, capacidad_bultos_hora: Decimal
) -> Horno:
    horno = obtener_horno(db, horno_id)
    horno.capacidad_bultos_hora = capacidad_bultos_hora
    db.commit()
    db.refresh(horno)
    return horno


def eliminar_horno(db: Session, horno_id: int) -> None:
    from app.modules.produccion.models import OrdenProduccion

    horno = obtener_horno(db, horno_id)
    en_uso = _existe(
        db, select(OrdenProduccion.id).where(OrdenProduccion.horno_id == horno_id)
    ) or _existe(
        db, select(MuestraDensidadAceite.id).where(MuestraDensidadAceite.horno_id == horno_id)
    )
    if en_uso:
        raise ErrorDeValidacion(
            f'No se puede eliminar "{horno.nombre}": ya tiene órdenes o muestras de densidad. '
            "Puedes desactivarlo en su lugar."
        )
    horno.categorias = []
    db.delete(horno)
    db.commit()


# --- Productos -------------------------------------------------------------


def listar_productos(db: Session, solo_activos: bool = False) -> list[Producto]:
    consulta = select(Producto).order_by(Producto.nombre_comercial)
    if solo_activos:
        consulta = consulta.where(Producto.activo == True)
    return list(db.scalars(consulta).all())


def crear_producto(db: Session, datos: ProductoGuardar) -> Producto:
    nombre = datos.nombre_comercial.strip()
    _nombre_libre(db, Producto, Producto.nombre_comercial, nombre, None)
    _obtener(db, CategoriaProducto, datos.categoria_id, "Esa categoría")
    producto = Producto(
        nombre_comercial=nombre,
        categoria_id=datos.categoria_id,
        activo=datos.activo,
        peso_estandar_canastilla_kg=datos.peso_estandar_canastilla_kg,
        destino=datos.destino,
        sabor_minimo_pct=datos.sabor_minimo_pct,
        sabor_maximo_pct=datos.sabor_maximo_pct,
    )
    db.add(producto)
    db.commit()
    db.refresh(producto)
    return producto


def actualizar_producto(db: Session, producto_id: int, datos: ProductoGuardar) -> Producto:
    producto = _obtener(db, Producto, producto_id, "Ese producto")
    nombre = datos.nombre_comercial.strip()
    _nombre_libre(db, Producto, Producto.nombre_comercial, nombre, producto_id)
    _obtener(db, CategoriaProducto, datos.categoria_id, "Esa categoría")
    producto.nombre_comercial = nombre
    producto.categoria_id = datos.categoria_id
    producto.activo = datos.activo
    producto.peso_estandar_canastilla_kg = datos.peso_estandar_canastilla_kg
    if "destino" in datos.model_fields_set:
        producto.destino = datos.destino
    # Un cliente viejo que no los envia conserva el rango de sabor.
    if "sabor_minimo_pct" in datos.model_fields_set or "sabor_maximo_pct" in datos.model_fields_set:
        producto.sabor_minimo_pct = datos.sabor_minimo_pct
        producto.sabor_maximo_pct = datos.sabor_maximo_pct
    db.commit()
    db.refresh(producto)
    return producto


def eliminar_producto(db: Session, producto_id: int) -> None:
    from app.modules.produccion.models import OrdenProduccion

    producto = _obtener(db, Producto, producto_id, "Ese producto")
    if _existe(db, select(OrdenProduccion.id).where(OrdenProduccion.producto_id == producto_id)):
        raise ErrorDeValidacion(
            f'No se puede eliminar "{producto.nombre_comercial}": ya tiene órdenes registradas. '
            "Puedes desactivarlo en su lugar."
        )
    db.delete(producto)
    db.commit()


# --- Configuracion de planta ----------------------------------------------


def obtener_configuracion(db: Session) -> ConfiguracionPlanta:
    """La fila unica de configuracion; se crea vacia si todavia no existe."""
    config = db.get(ConfiguracionPlanta, 1)
    if config is None:
        config = ConfiguracionPlanta(id=1)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def guardar_configuracion(db: Session, datos: ConfiguracionGuardar) -> ConfiguracionPlanta:
    config = obtener_configuracion(db)
    config.peso_estandar_bulto_kg = datos.peso_estandar_bulto_kg
    config.peso_estandar_canastilla_kg = datos.peso_estandar_canastilla_kg
    db.commit()
    db.refresh(config)
    return config


def obtener_peso_estandar_bulto(db: Session) -> Decimal:
    config = obtener_configuracion(db)
    if config.peso_estandar_bulto_kg is None:
        raise ErrorDeValidacion(
            "El Administrador todavía no configuró el peso estándar del bulto. "
            "Pídele que lo configure en Catálogos > Configuración."
        )
    return config.peso_estandar_bulto_kg


# --- Densidad del aceite ---------------------------------------------------


def listar_muestras_densidad(db: Session, horno_id: int | None = None) -> list[MuestraDensidadAceite]:
    consulta = select(MuestraDensidadAceite).order_by(
        MuestraDensidadAceite.fecha.desc(), MuestraDensidadAceite.id.desc()
    )
    if horno_id is not None:
        consulta = consulta.where(MuestraDensidadAceite.horno_id == horno_id)
    return list(db.scalars(consulta.limit(200)).unique().all())


def registrar_muestra_densidad(
    db: Session, datos: MuestraDensidadCrear, usuario_id: int
) -> MuestraDensidadAceite:
    obtener_horno(db, datos.horno_id)
    muestra = MuestraDensidadAceite(
        horno_id=datos.horno_id,
        fecha=datos.fecha,
        densidad_kg_por_litro=datos.densidad_kg_por_litro,
        usuario_id=usuario_id,
    )
    db.add(muestra)
    db.commit()
    db.refresh(muestra)
    return muestra


def obtener_densidad_vigente(db: Session, horno_id: int, fecha: date) -> Decimal | None:
    """
    Muestra de densidad mas reciente de ese horno con fecha igual o
    anterior a la del registro. Si no hay ninguna, la densidad del aceite
    del catalogo que tenga asignado el horno (V18). None si no hay ni una
    ni otra: no se calculan los kg de aceite, pero el registro se guarda.
    """
    muestra = db.scalar(
        select(MuestraDensidadAceite)
        .where(
            MuestraDensidadAceite.horno_id == horno_id,
            MuestraDensidadAceite.fecha <= fecha,
        )
        .order_by(MuestraDensidadAceite.fecha.desc(), MuestraDensidadAceite.id.desc())
        .limit(1)
    )
    if muestra is not None:
        return muestra.densidad_kg_por_litro
    horno = db.get(Horno, horno_id)
    if horno is not None and horno.aceite is not None:
        return horno.aceite.densidad_kg_por_litro
    return None


def obtener_densidades_vigentes_todos_hornos(
    db: Session, fecha: date
) -> list[dict]:
    """
    Obtiene en una sola consulta consolidada la ultima densidad vigente de cada horno.
    """
    hornos = listar_hornos(db)
    if not hornos:
        return []

    muestras = list(
        db.scalars(
            select(MuestraDensidadAceite)
            .where(MuestraDensidadAceite.fecha <= fecha)
            .order_by(
                MuestraDensidadAceite.horno_id,
                MuestraDensidadAceite.fecha.desc(),
                MuestraDensidadAceite.id.desc(),
            )
        ).all()
    )

    ultima_muestra: dict[int, MuestraDensidadAceite] = {}
    for m in muestras:
        if m.horno_id not in ultima_muestra:
            ultima_muestra[m.horno_id] = m

    resultado = []
    for horno in hornos:
        m = ultima_muestra.get(horno.id)
        resultado.append(
            {
                "horno_id": horno.id,
                "horno_nombre": horno.nombre,
                "fecha": m.fecha if m else None,
                "densidad_kg_por_litro": m.densidad_kg_por_litro if m else None,
            }
        )
    return resultado



# --- Tipos de aceite (V18) ---------------------------------------------------


def listar_aceites(db: Session, solo_activos: bool = False) -> list[TipoAceite]:
    consulta = select(TipoAceite).order_by(TipoAceite.nombre)
    if solo_activos:
        consulta = consulta.where(TipoAceite.activo == True)  # noqa: E712
    return list(db.scalars(consulta).all())


def crear_aceite(db: Session, datos: TipoAceiteGuardar) -> TipoAceite:
    nombre = datos.nombre.strip()
    _nombre_libre(db, TipoAceite, TipoAceite.nombre, nombre, None)
    aceite = TipoAceite(nombre=nombre)
    _aplicar_aceite(aceite, datos)
    db.add(aceite)
    db.commit()
    db.refresh(aceite)
    return aceite


def actualizar_aceite(db: Session, aceite_id: int, datos: TipoAceiteGuardar) -> TipoAceite:
    aceite = _obtener(db, TipoAceite, aceite_id, "Ese aceite")
    nombre = datos.nombre.strip()
    _nombre_libre(db, TipoAceite, TipoAceite.nombre, nombre, aceite_id)
    aceite.nombre = nombre
    _aplicar_aceite(aceite, datos)
    db.commit()
    db.refresh(aceite)
    return aceite


def eliminar_aceite(db: Session, aceite_id: int) -> None:
    from app.modules.produccion.models import RegistroHorno

    aceite = _obtener(db, TipoAceite, aceite_id, "Ese aceite")
    if _existe(db, select(Horno.id).where(Horno.aceite_id == aceite_id)) or _existe(
        db, select(RegistroHorno.id).where(RegistroHorno.aceite_id == aceite_id)
    ):
        raise ErrorDeValidacion(
            f'No se puede eliminar "{aceite.nombre}": un horno lo usa o ya hay tandas con él. '
            "Puedes desactivarlo en su lugar."
        )
    db.delete(aceite)
    db.commit()


def _aplicar_aceite(aceite: TipoAceite, datos: TipoAceiteGuardar) -> None:
    aceite.densidad_kg_por_litro = datos.densidad_kg_por_litro
    aceite.proveedor = (datos.proveedor or "").strip() or None
    aceite.activo = datos.activo


# --- Lineas de produccion y variedades (V21) --------------------------------


def listar_lineas(db: Session, solo_activas: bool = False) -> list[Linea]:
    consulta = select(Linea).order_by(Linea.orden, Linea.nombre)
    if solo_activas:
        consulta = consulta.where(Linea.activo == True)  # noqa: E712
    return list(db.scalars(consulta).all())


def linea_por_codigo(db: Session, codigo: str) -> Linea:
    linea = db.scalar(select(Linea).where(Linea.codigo == codigo))
    if linea is None:
        raise RecursoNoEncontrado("Esa línea no existe.")
    return linea


def listar_variedades(
    db: Session, linea_id: int | None = None, solo_activas: bool = False
) -> list[Variedad]:
    consulta = select(Variedad).order_by(Variedad.nombre)
    if linea_id is not None:
        consulta = consulta.where(Variedad.linea_id == linea_id)
    if solo_activas:
        consulta = consulta.where(Variedad.activo == True)  # noqa: E712
    return list(db.scalars(consulta).all())


def _variedad_libre(db: Session, linea_id: int, nombre: str, variedad_id: int | None) -> None:
    consulta = select(Variedad.id).where(
        Variedad.linea_id == linea_id, func.lower(Variedad.nombre) == nombre.lower()
    )
    if variedad_id is not None:
        consulta = consulta.where(Variedad.id != variedad_id)
    if db.scalar(consulta) is not None:
        raise ConflictoDeDatos(f'Ya existe la variedad "{nombre}" en esa línea.')


def crear_variedad(db: Session, datos: VariedadGuardar) -> Variedad:
    _obtener(db, Linea, datos.linea_id, "Esa línea")
    nombre = datos.nombre.strip()
    _variedad_libre(db, datos.linea_id, nombre, None)
    variedad = Variedad(linea_id=datos.linea_id, nombre=nombre, activo=datos.activo)
    db.add(variedad)
    db.commit()
    db.refresh(variedad)
    return variedad


def actualizar_variedad(db: Session, variedad_id: int, datos: VariedadGuardar) -> Variedad:
    """Cambia el nombre (para corregir errores de escritura) o la desactiva."""
    variedad = _obtener(db, Variedad, variedad_id, "Esa variedad")
    nombre = datos.nombre.strip()
    _variedad_libre(db, variedad.linea_id, nombre, variedad_id)
    variedad.nombre = nombre
    variedad.activo = datos.activo
    db.commit()
    db.refresh(variedad)
    return variedad


def eliminar_variedad(db: Session, variedad_id: int) -> None:
    from app.modules.produccion.models import OrdenProduccion

    variedad = _obtener(db, Variedad, variedad_id, "Esa variedad")
    if _existe(db, select(OrdenProduccion.id).where(OrdenProduccion.variedad_id == variedad_id)):
        raise ErrorDeValidacion(
            f'No se puede eliminar "{variedad.nombre}": ya se usó en órdenes. Puedes desactivarla.'
        )
    db.delete(variedad)
    db.commit()
