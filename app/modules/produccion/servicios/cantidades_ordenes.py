"""Conversión de cantidades pedidas: kg o canastillas, con Decimal y redondeo explícito."""

from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from app.core.errores import ErrorDeValidacion
from app.modules.catalogos.models import Producto
from app.modules.catalogos.service import obtener_configuracion
from app.modules.produccion.models import UnidadSolicitada
from app.modules.produccion.schemas import OrdenGuardar


def calcular_cantidad_programada(
    db: Session, datos: OrdenGuardar, producto: Producto
) -> tuple[Decimal, Decimal | None]:
    """
    Cuantos kg tiene la orden.

    Si al supervisor le pidieron canastillas, se convierten a kg con un
    peso ESTIMADO por canastilla: primero el del producto (cada referencia
    pesa distinto; cabello de angel pesa mas), y si no tiene, el valor
    general de Catalogos > Configuracion.

    Mojes, baches y bultos (V21): se guarda cuantos se pidieron y la meta en
    kg queda en 0. La app captura lo real: no estima kg por unidad.

    Devuelve (cantidad_programada_kg, cantidad_solicitada_en_su_unidad).
    """
    if datos.unidad_solicitada in UnidadSolicitada.CONTEO:
        if datos.cantidad_unidades is None or datos.cantidad_unidades <= 0:
            raise ErrorDeValidacion(f"Indica cuántos {datos.unidad_solicitada} se pidieron.")
        return Decimal("0"), Decimal(datos.cantidad_unidades)
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
        cantidad_kg = (datos.cantidad_canastillas * peso_canastilla).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if not Decimal("0.01") <= cantidad_kg <= Decimal("99999999.99"):
            raise ErrorDeValidacion(
                "La conversión de canastillas debe resultar entre 0.01 y 99999999.99 kg. "
                "Revisa la cantidad y el peso de la canastilla."
            )
        return cantidad_kg, datos.cantidad_canastillas

    if datos.cantidad_kg is None or datos.cantidad_kg <= 0:
        raise ErrorDeValidacion("La cantidad programada debe ser mayor a cero.")
    return datos.cantidad_kg, None


