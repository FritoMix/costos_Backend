"""Reglas de programación y compatibilidad de catálogos para crear o editar órdenes.

Estas consultas y validaciones no escriben ni confirman transacciones.
"""

from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion
from app.modules.catalogos.models import Horno, Producto, Turno
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
    if datos.unidad_solicitada not in (UnidadSolicitada.KG, UnidadSolicitada.CANASTILLAS):
        raise ErrorDeValidacion("La unidad solicitada debe ser Kg o Canastillas.")

    validar_horas(datos)

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
        raise ErrorDeValidacion(f'El producto "{producto.nombre_comercial}" no pertenece a esa categoría.')

    turno = db.get(Turno, datos.turno_id)
    if turno is None:
        raise ErrorDeValidacion("El turno seleccionado no existe.")
    if not turno.activo and datos.turno_id != turno_actual_id:
        raise ErrorDeValidacion("El turno seleccionado está inactivo. Elige un turno activo.")

    return horno, producto


