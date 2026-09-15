"""
Pruebas de la calibracion del tanque de aceite.

De aqui salen los litros consumidos en cada tanda, asi que un error en esta
formula se propaga a los indicadores de toda la planta.
"""

import math
from decimal import Decimal

from app.modules.catalogos.models import Horno


def _horno(diametro=None, manual=None) -> Horno:
    horno = Horno()
    horno.nombre = "Horno de prueba"
    horno.tanque_diametro_cm = diametro
    horno.litros_por_cm_manual = manual
    return horno


def test_sin_calibracion_no_se_inventa_un_valor():
    assert _horno().litros_por_cm is None


def test_con_diametro_se_calcula_como_cilindro():
    horno = _horno(diametro=Decimal("100.00"))

    # Area del circulo (pi * r^2) en cm2, pasada a litros (1 L = 1000 cm3).
    esperado = round(math.pi * 50**2 / 1000, 4)
    assert float(horno.litros_por_cm) == esperado


def test_la_calibracion_manual_manda_sobre_el_diametro():
    """
    Si la planta midio el tanque a mano, ese dato es mas confiable que
    suponer un cilindro perfecto.
    """
    horno = _horno(diametro=Decimal("100.00"), manual=Decimal("7.5000"))

    assert horno.litros_por_cm == Decimal("7.5000")


def test_la_calibracion_manual_funciona_sin_diametro():
    horno = _horno(manual=Decimal("6.2500"))

    assert horno.litros_por_cm == Decimal("6.2500")
