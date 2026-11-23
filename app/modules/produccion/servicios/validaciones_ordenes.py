"""Reglas de programación y compatibilidad de catálogos para crear o editar órdenes.

Estas consultas y validaciones no escriben ni confirman transacciones.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion
from app.modules.catalogos.models import CategoriaProducto, Horno, Linea, Producto, Turno, Variedad
from app.modules.produccion.models import DestinoOrden, UnidadSolicitada
from app.modules.produccion.schemas import OrdenGuardar


def validar_horas(datos: OrdenGuardar) -> None:
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


def validar_catalogos(
    db: Session, datos: OrdenGuardar, *, turno_actual_id: int | None = None
) -> tuple[Horno, Producto]:
    if datos.destino not in (DestinoOrden.NACIONAL, DestinoOrden.EXPORTACION):
        raise ErrorDeValidacion("El destino debe ser Nacional o Exportación.")
    if datos.unidad_solicitada not in UnidadSolicitada.TODAS:
        raise ErrorDeValidacion("La unidad solicitada no es válida.")

    validar_horas(datos)

    horno = db.get(Horno, datos.horno_id)
    if horno is None or not horno.activo:
        raise ErrorDeValidacion("El horno seleccionado no es válido.")
    linea = horno.linea

    # Cada linea pide la orden en su unidad (V21). Sin linea: como papa.
    unidades = (
        linea.unidades_orden
        if linea is not None
        else [UnidadSolicitada.KG, UnidadSolicitada.CANASTILLAS]
    )
    if datos.unidad_solicitada not in unidades:
        nombre = linea.nombre if linea is not None else "Papa"
        raise ErrorDeValidacion(f"En la línea {nombre} la orden se pide en {' o '.join(unidades)}.")

    if datos.destino == DestinoOrden.EXPORTACION:
        # Toda orden de exportacion se trabaja en un horno habilitado para
        # exportar, sin importar la categoria.
        if not horno.apto_exportacion:
            raise ErrorDeValidacion(
                f'El horno "{horno.nombre}" no está habilitado para órdenes de exportación.'
            )
        # Aun asi, la categoria tiene que ser de la linea del horno: un
        # producto de platano no se frie en un horno de papa.
        if linea is not None:
            _validar_categoria_de_la_linea(db, horno, linea, datos.categoria_id)
    else:
        if datos.categoria_id not in {c.id for c in horno.categorias}:
            raise ErrorDeValidacion(f'El horno "{horno.nombre}" no puede producir esa categoría.')

    producto = db.get(Producto, datos.producto_id)
    if producto is None or not producto.activo:
        raise ErrorDeValidacion("El producto seleccionado no es válido.")
    if producto.categoria_id != datos.categoria_id:
        raise ErrorDeValidacion(f'El producto "{producto.nombre_comercial}" no pertenece a esa categoría.')
    if not producto.sirve_para(datos.destino):
        destino = "exportación" if datos.destino == DestinoOrden.EXPORTACION else "nacional"
        raise ErrorDeValidacion(
            f'El producto "{producto.nombre_comercial}" no está marcado para {destino}. '
            "Cámbialo en Catálogos > Productos si corresponde."
        )

    _validar_variedad(db, datos, linea)

    turno = db.get(Turno, datos.turno_id)
    if turno is None:
        raise ErrorDeValidacion("El turno seleccionado no existe.")
    if not turno.activo and datos.turno_id != turno_actual_id:
        raise ErrorDeValidacion("El turno seleccionado está inactivo. Elige un turno activo.")

    return horno, producto




def _validar_categoria_de_la_linea(db: Session, horno: Horno, linea: Linea, categoria_id: int) -> None:
    de_la_linea = db.scalar(
        select(Horno.id)
        .join(Horno.categorias)
        .where(Horno.linea_id == linea.id, CategoriaProducto.id == categoria_id)
        .limit(1)
    )
    if de_la_linea is None:
        raise ErrorDeValidacion(
            f'Esa categoría no es de la línea {linea.nombre} del horno "{horno.nombre}".'
        )


def _validar_variedad(db: Session, datos: OrdenGuardar, linea: Linea | None) -> None:
    """En platano el supervisor dice que variedad se va a fritar (Harton, FHIA 21)."""
    if linea is None or not linea.pide_variedad:
        if datos.variedad_id is not None and linea is not None:
            raise ErrorDeValidacion(f"La línea {linea.nombre} no lleva variedad en la orden.")
        return
    if datos.variedad_id is None:
        raise ErrorDeValidacion(f"Escoge qué tipo de {linea.nombre_materia_prima} se va a fritar.")
    variedad = db.get(Variedad, datos.variedad_id)
    if variedad is None or variedad.linea_id != linea.id or not variedad.activo:
        raise ErrorDeValidacion(f"Ese tipo de {linea.nombre_materia_prima} no es válido.")
