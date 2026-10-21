"""Calculos puros de produccion.

Aqui viven las unicas formulas de kilos, rendimiento y distribucion. Tanto
el registro de horno como la proyeccion de Bodega llaman a estas funciones:
ningun router ni componente Angular replica la formula definitiva.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.core.errores import ErrorDeValidacion

CENTAVOS = Decimal("0.01")
CIEN = Decimal("100")
TOLERANCIA_PORCENTAJE = Decimal("0.01")


@dataclass(frozen=True)
class Participacion:
    """Porcentaje de una referencia dentro de la mezcla de produccion."""

    referencia_id: int
    porcentaje: Decimal


def _a_decimal(valor: Decimal | int | str) -> Decimal:
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def calcular_kg_crudos(
    cantidad_bultos: Decimal | int | str,
    peso_promedio_bulto_kg: Decimal | int | str,
) -> Decimal:
    """Formula 1: bultos x peso promedio del bulto, en kg con 2 decimales."""
    bultos = _a_decimal(cantidad_bultos)
    peso = _a_decimal(peso_promedio_bulto_kg)
    # El registro de horno exige bultos > 0 en su schema. La proyeccion si
    # admite 0 cuando una referencia recibe cero bultos por redondeo.
    if bultos < 0:
        raise ErrorDeValidacion("La cantidad de bultos no puede ser negativa.")
    if peso <= 0:
        raise ErrorDeValidacion("El peso promedio por bulto debe ser mayor a cero.")
    return (bultos * peso).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def calcular_kg_fritos_estimados(
    kg_crudos: Decimal | int | str,
    rendimiento_fritura_pct: Decimal | int | str,
) -> Decimal:
    """Formula 2: kg crudos x rendimiento / 100, en kg con 2 decimales."""
    crudos = _a_decimal(kg_crudos)
    rendimiento = _a_decimal(rendimiento_fritura_pct)
    if crudos < 0:
        raise ErrorDeValidacion("Los kg crudos no pueden ser negativos.")
    if rendimiento <= 0 or rendimiento > CIEN:
        raise ErrorDeValidacion(
            "El rendimiento de fritura debe ser mayor a 0 % y menor o igual a 100 %."
        )
    return (crudos * rendimiento / CIEN).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def calcular_bultos_estimados(
    capacidad_horno: Decimal | int | str,
    porcentaje_produccion_pct: Decimal | int | str,
) -> Decimal:
    """Formula 3: capacidad x participacion / 100, sin redondear a entero."""
    capacidad = _a_decimal(capacidad_horno)
    porcentaje = _a_decimal(porcentaje_produccion_pct)
    if capacidad <= 0:
        raise ErrorDeValidacion("La capacidad del horno debe ser mayor a cero.")
    if porcentaje < 0 or porcentaje > CIEN:
        raise ErrorDeValidacion("La participación debe estar entre 0 % y 100 %.")
    return (capacidad * porcentaje / CIEN).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def validar_participaciones(participaciones: Sequence[Participacion]) -> Decimal:
    """
    Valida que las referencias activas sumen 100 % (tolerancia 0,01 %).

    Se valida en el momento de usar la configuracion (proyeccion/distribucion),
    no al guardar cada referencia: Bodega edita una fila a la vez y una
    configuracion puede quedar temporalmente incompleta mientras se reemplaza
    una referencia. El sistema la marca incompleta y no permite proyectar
    hasta que vuelva a sumar 100 %.
    """
    if not participaciones:
        raise ErrorDeValidacion(
            "No hay referencias de papa activas para distribuir la producción."
        )

    ids = [p.referencia_id for p in participaciones]
    if len(ids) != len(set(ids)):
        raise ErrorDeValidacion("La configuración tiene referencias repetidas.")

    total = Decimal("0")
    for participacion in participaciones:
        porcentaje = _a_decimal(participacion.porcentaje)
        if porcentaje < 0 or porcentaje > CIEN:
            raise ErrorDeValidacion(
                "La participación de cada referencia debe estar entre 0 % y 100 %."
            )
        total += porcentaje

    if abs(total - CIEN) > TOLERANCIA_PORCENTAJE:
        raise ErrorDeValidacion(
            "El porcentaje total de distribución debe sumar 100 %. "
            f"Actualmente suma {total.quantize(Decimal('0.0001'))} %."
        )
    return total


def distribuir_bultos(
    capacidad: int,
    participaciones: Sequence[Participacion],
) -> dict[int, int]:
    """
    Reparte bultos enteros con el metodo de mayores restos.

    Garantiza que la suma de bultos asignados sea exactamente `capacidad`.
    Los empates se resuelven por mayor porcentaje y, si persisten, por el id
    menor (orden estable y reproducible).
    """
    if capacidad <= 0:
        raise ErrorDeValidacion("La capacidad del horno debe ser mayor a cero.")

    validar_participaciones(participaciones)
    exactos = [
        (Decimal(capacidad) * _a_decimal(p.porcentaje) / CIEN, p)
        for p in participaciones
    ]
    asignados = [
        int(exacto.to_integral_value(rounding=ROUND_FLOOR)) for exacto, _ in exactos
    ]
    restos = [
        exacto - Decimal(entero)
        for (exacto, _), entero in zip(exactos, asignados, strict=True)
    ]

    faltan = capacidad - sum(asignados)
    if faltan < 0:
        raise ErrorDeValidacion("La distribución calculada supera la capacidad del horno.")
    if faltan > len(asignados):
        raise ErrorDeValidacion("No se pudo distribuir la capacidad entre las referencias.")

    orden = sorted(
        range(len(exactos)),
        key=lambda indice: (
            restos[indice],
            _a_decimal(exactos[indice][1].porcentaje),
            -exactos[indice][1].referencia_id,
        ),
        reverse=True,
    )
    for indice in orden[:faltan]:
        asignados[indice] += 1

    return {
        exactos[indice][1].referencia_id: asignados[indice]
        for indice in range(len(exactos))
    }
