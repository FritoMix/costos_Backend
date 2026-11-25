"""Codigos de recuperacion del administrador (V25)."""

import re

import pytest
from sqlalchemy import select

from app.core.errores import CredencialesInvalidas, ErrorDeValidacion
from app.core.seguridad import hash_password, verificar_password
from app.modules.identidad import recuperacion
from app.modules.identidad.models import CodigoRecuperacion
from app.modules.identidad.sesiones import AccesoTemporalmenteLimitado

ACTUAL = "ClaveActual-2026"
NUEVA = "ClaveNueva-2026"
IP = "10.0.0.7"


@pytest.fixture
def admin(db, datos_base):
    usuario = datos_base.admin
    usuario.password_hash = hash_password(ACTUAL)
    db.flush()
    return usuario


def test_genera_ocho_codigos_unicos_y_los_guarda_cifrados(db, admin):
    with pytest.raises(ErrorDeValidacion, match="contraseña actual"):
        recuperacion.generar(db, admin, "otra")

    codigos = recuperacion.generar(db, admin, ACTUAL)
    assert len(codigos) == 8 and len(set(codigos)) == 8
    assert all(re.fullmatch(r"[2-9A-Z]{4}-[2-9A-Z]{4}-[2-9A-Z]{4}", c) for c in codigos)
    guardados = db.scalars(select(CodigoRecuperacion).where(CodigoRecuperacion.usuario_id == admin.id)).all()
    assert len(guardados) == 8
    # Nada del secreto queda en claro: solo el identificador y el hash.
    for codigo, fila in zip(sorted(codigos), sorted(guardados, key=lambda f: f.identificador), strict=True):
        assert codigo.replace("-", "")[4:] not in fila.codigo_hash
    assert recuperacion.estado(db, admin)["disponibles"] == 8


def test_solo_el_administrador_genera_codigos(db, datos_base):
    supervisor = datos_base.supervisor
    supervisor.password_hash = hash_password(ACTUAL)
    with pytest.raises(ErrorDeValidacion, match="Solo el administrador"):
        recuperacion.generar(db, supervisor, ACTUAL)


def test_un_codigo_cambia_la_contrasena_una_sola_vez(db, admin):
    codigos = recuperacion.generar(db, admin, ACTUAL)
    version = admin.token_version
    # Sin guiones y en minusculas tambien sirve: asi lo puede escribir cualquiera.
    quedan = recuperacion.recuperar(db, "ADMIN_PRUEBA ", codigos[0].replace("-", "").lower(), NUEVA, IP)
    assert quedan == 7
    assert verificar_password(NUEVA, admin.password_hash)
    assert admin.token_version == version + 1  # cierra las sesiones abiertas
    assert admin.debe_cambiar_password is False

    with pytest.raises(CredencialesInvalidas):
        recuperacion.recuperar(db, "admin_prueba", codigos[0], "OtraClave-2026", IP)


def test_codigo_falso_o_usuario_inexistente_dan_el_mismo_error(db, admin):
    codigos = recuperacion.generar(db, admin, ACTUAL)
    falso = "2222-2222-2222"
    for usuario, codigo in [("admin_prueba", falso), ("no_existe", codigos[0]), ("admin_prueba", "corto")]:
        with pytest.raises(CredencialesInvalidas, match="Usuario o código"):
            recuperacion.recuperar(db, usuario, codigo, NUEVA, IP)
    assert verificar_password(ACTUAL, admin.password_hash)


def test_bloquea_tras_varios_intentos_fallidos(db, admin):
    codigos = recuperacion.generar(db, admin, ACTUAL)
    for _ in range(5):
        with pytest.raises(CredencialesInvalidas):
            recuperacion.recuperar(db, "admin_prueba", "2222-2222-2222", NUEVA, IP)
    # Bloqueado: ni un codigo valido entra hasta que pase la espera.
    with pytest.raises(AccesoTemporalmenteLimitado):
        recuperacion.recuperar(db, "admin_prueba", codigos[1], NUEVA, "10.0.0.8")
    assert verificar_password(ACTUAL, admin.password_hash)


def test_generar_otra_vez_anula_los_anteriores(db, admin):
    viejos = recuperacion.generar(db, admin, ACTUAL)
    nuevos = recuperacion.generar(db, admin, ACTUAL)
    with pytest.raises(CredencialesInvalidas):
        recuperacion.recuperar(db, "admin_prueba", viejos[0], NUEVA, IP)
    assert recuperacion.recuperar(db, "admin_prueba", nuevos[0], NUEVA, IP) == 7
