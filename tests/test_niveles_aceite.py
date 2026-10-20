"""
Pruebas de los niveles de aceite de una tanda.

Un consumo negativo (nivel final mayor que el inicial) sesga los indicadores
de la planta, asi que se rechaza en el schema y tambien en el servicio.
"""

from datetime import time
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.errores import ErrorDeValidacion
from app.modules.produccion.schemas import RegistroHornoGuardar
from app.modules.produccion.servicios.horno import _validar_niveles_aceite


def _registro(**cambios) -> RegistroHornoGuardar:
    base = dict(
        hora_inicio=time(6, 0),
        hora_fin=time(7, 0),
        cantidad_bultos=Decimal("10"),
        operarios_seleccion=2,
        operarios_horno=1,
        nivel_aceite_inicial_cm=Decimal("20"),
        nivel_aceite_final_cm=Decimal("18"),
        temperatura_aceite_c=Decimal("175"),
    )
    base.update(cambios)
    return RegistroHornoGuardar(**base)


def test_el_schema_rechaza_un_consumo_negativo():
    with pytest.raises(ValidationError, match="nivel final"):
        _registro(nivel_aceite_final_cm=Decimal("21"))


def test_el_servicio_rechaza_un_consumo_negativo():
    with pytest.raises(ErrorDeValidacion, match="nivel final"):
        _validar_niveles_aceite(Decimal("20"), Decimal("21"))


def test_niveles_normales_pasan():
    _validar_niveles_aceite(Decimal("20"), Decimal("18"))
    registro = _registro(nivel_aceite_final_cm=Decimal("20"))
    assert registro.nivel_aceite_final_cm == Decimal("20")
