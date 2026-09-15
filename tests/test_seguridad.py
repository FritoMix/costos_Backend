"""
Pruebas de contrasenas y tokens de sesion.

No necesitan base de datos: son logica pura.
"""

import time

import pytest

from app.core.errores import CredencialesInvalidas
from app.core.seguridad import (
    crear_token_acceso,
    hash_password,
    leer_token_acceso,
    verificar_password,
)


def test_el_hash_no_es_la_contrasena_en_texto_plano():
    hash_generado = hash_password("clave-super-secreta")
    assert hash_generado != "clave-super-secreta"
    assert hash_generado.startswith("$2b$")


def test_verificar_password_acepta_la_correcta_y_rechaza_la_incorrecta():
    hash_generado = hash_password("clave-super-secreta")
    assert verificar_password("clave-super-secreta", hash_generado) is True
    assert verificar_password("otra-clave", hash_generado) is False


def test_dos_hashes_de_la_misma_clave_son_distintos():
    """Cada hash lleva su propia 'sal': dos usuarios con la misma clave no se delatan."""
    assert hash_password("misma-clave") != hash_password("misma-clave")


def test_un_hash_corrupto_no_revienta_la_app():
    assert verificar_password("clave", "esto-no-es-un-hash") is False


def test_el_token_guarda_el_usuario_y_su_rol():
    token, segundos = crear_token_acceso(usuario_id=7, rol="operario_horno")
    contenido = leer_token_acceso(token)

    assert contenido["sub"] == "7"
    assert contenido["rol"] == "operario_horno"
    assert segundos > 0


def test_un_token_alterado_se_rechaza():
    token, _ = crear_token_acceso(usuario_id=1, rol="admin")
    alterado = token[:-3] + "aaa"

    with pytest.raises(CredencialesInvalidas):
        leer_token_acceso(alterado)


def test_un_token_vencido_se_rechaza(monkeypatch):
    from app.core import seguridad

    monkeypatch.setattr(seguridad.settings, "access_token_expire_minutes", -1)
    token, _ = crear_token_acceso(usuario_id=1, rol="admin")
    time.sleep(0.01)

    with pytest.raises(CredencialesInvalidas):
        leer_token_acceso(token)
