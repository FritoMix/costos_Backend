"""Actualización sobre un esquema anterior con datos existentes y rollback de DDL."""

import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

from app.db.migraciones import aplicar_migraciones_pendientes

ORIGEN = Path(__file__).resolve().parents[2] / "migraciones"


def manifiesto(carpeta):
    (carpeta / "checksums.json").write_text(
        json.dumps({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in carpeta.glob("V*.sql")})
    )


@pytest.fixture
def motor_vacio(engine_integracion):
    nombre = f"prueba_upgrade_{uuid4().hex}"
    with engine_integracion.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{nombre}"'))
    motor = create_engine(engine_integracion.url, connect_args={"options": f"-csearch_path={nombre},public"})
    try:
        yield motor
    finally:
        motor.dispose()
        with engine_integracion.begin() as c:
            c.execute(text(f'DROP SCHEMA "{nombre}" CASCADE'))


def test_actualizar_desde_v14_preserva_datos_y_detecta_cambio_historico(motor_vacio, tmp_path):
    for archivo in ORIGEN.glob("V*.sql"):
        if int(archivo.name.split("__")[0][1:]) <= 14:
            shutil.copy2(archivo, tmp_path / archivo.name)
    manifiesto(tmp_path)
    assert aplicar_migraciones_pendientes(motor_vacio, tmp_path) == 14
    with motor_vacio.begin() as c:
        c.execute(
            text(
                "INSERT INTO usuarios (nombre_completo, nombre_usuario, password_hash, rol_id) "
                "SELECT 'Persona histórica', 'historico', 'hash-ficticio', id FROM roles WHERE codigo='admin'"
            )
        )
        # Reproduce el historial del migrador anterior sin hashes.
        c.execute(text("ALTER TABLE esquema_migraciones DROP COLUMN checksum_sha256"))
    for archivo in ORIGEN.glob("V*.sql"):
        shutil.copy2(archivo, tmp_path / archivo.name)
    manifiesto(tmp_path)
    # Todas las migraciones posteriores a V14 (V15, V16 y las que vengan).
    posteriores = [a for a in ORIGEN.glob("V*.sql") if int(a.name.split("__")[0][1:]) > 14]
    assert aplicar_migraciones_pendientes(motor_vacio, tmp_path) == len(posteriores)
    with motor_vacio.connect() as c:
        assert c.scalar(text("SELECT count(*) FROM usuarios WHERE nombre_usuario='historico'")) == 1
        assert c.scalar(text("SELECT count(*) FROM esquema_migraciones WHERE checksum_sha256 IS NULL")) == 0
    primera = next(tmp_path.glob("V1__*.sql"))
    primera.write_text(primera.read_text() + "\n-- alteración posterior\n")
    manifiesto(tmp_path)  # Aunque cambien también el manifiesto, la base conserva el hash original.
    with pytest.raises(RuntimeError, match="histórica"):
        aplicar_migraciones_pendientes(motor_vacio, tmp_path)


def test_migracion_fallida_no_deja_tabla_ni_historial_parcial(motor_vacio, tmp_path):
    (tmp_path / "V1__correcta.sql").write_text("CREATE TABLE conservada (id INTEGER)")
    manifiesto(tmp_path)
    aplicar_migraciones_pendientes(motor_vacio, tmp_path)
    (tmp_path / "V2__falla.sql").write_text("CREATE TABLE parcial (id INTEGER); SELECT funcion_inexistente()")
    manifiesto(tmp_path)
    with pytest.raises(ProgrammingError):
        aplicar_migraciones_pendientes(motor_vacio, tmp_path)
    with motor_vacio.connect() as c:
        assert c.scalar(text("SELECT to_regclass('conservada')")) is not None
        assert c.scalar(text("SELECT to_regclass('parcial')")) is None
        assert c.scalar(text("SELECT count(*) FROM esquema_migraciones")) == 1


def test_v27_revoca_solo_el_codigo_de_v26_aunque_cambie_el_nombre(motor_vacio, tmp_path):
    for archivo in ORIGEN.glob("V*.sql"):
        if int(archivo.name.split("__")[0][1:]) <= 25:
            shutil.copy2(archivo, tmp_path / archivo.name)
    manifiesto(tmp_path)
    aplicar_migraciones_pendientes(motor_vacio, tmp_path)
    with motor_vacio.begin() as c:
        c.execute(text(
            "INSERT INTO usuarios (nombre_completo, nombre_usuario, password_hash, rol_id) "
            "SELECT 'Administrador de prueba', 'admin', 'ficticio', id FROM roles WHERE codigo='admin'"
        ))

    shutil.copy2(next(ORIGEN.glob("V26__*")), tmp_path)
    manifiesto(tmp_path)
    assert aplicar_migraciones_pendientes(motor_vacio, tmp_path) == 1
    with motor_vacio.begin() as c:
        original = c.execute(text("SELECT id, usuario_id, identificador FROM codigos_recuperacion")).one()
        c.execute(text("UPDATE usuarios SET nombre_usuario='admin_renombrado' WHERE id=:id"),
                  {"id": original.usuario_id})
        personal = c.scalar(text(
            "INSERT INTO codigos_recuperacion (usuario_id, identificador, codigo_hash) "
            "VALUES (:usuario, :prefijo, 'hash-personal-de-prueba') RETURNING id"
        ), {"usuario": original.usuario_id, "prefijo": original.identificador})

    shutil.copy2(next(ORIGEN.glob("V27__*")), tmp_path)
    manifiesto(tmp_path)
    assert aplicar_migraciones_pendientes(motor_vacio, tmp_path) == 1
    assert aplicar_migraciones_pendientes(motor_vacio, tmp_path) == 0
    with motor_vacio.connect() as c:
        disponibles = c.scalars(text("SELECT id FROM codigos_recuperacion WHERE usado_en IS NULL")).all()
        assert disponibles == [personal]


@pytest.mark.parametrize("estado_codigo", ["disponible", "usado", "reemplazado"])
def test_v32_revoca_la_credencial_de_v30_y_preserva_el_acceso_personal(
    motor_vacio, tmp_path, estado_codigo
):
    for archivo in ORIGEN.glob("V*.sql"):
        if int(archivo.name.split("__")[0][1:]) <= 29:
            shutil.copy2(archivo, tmp_path)
    manifiesto(tmp_path)
    aplicar_migraciones_pendientes(motor_vacio, tmp_path)

    with motor_vacio.begin() as c:
        usuario_id = c.scalar(text(
            "INSERT INTO usuarios (nombre_completo, nombre_usuario, password_hash, rol_id) "
            "SELECT 'Responsable de prueba', 'admin', 'hash-personal', id FROM roles WHERE codigo='admin' "
            "RETURNING id"
        ))

    for version in (30, 31):
        shutil.copy2(next(ORIGEN.glob(f"V{version}__*.sql")), tmp_path)
    manifiesto(tmp_path)
    assert aplicar_migraciones_pendientes(motor_vacio, tmp_path) == 2

    with motor_vacio.begin() as c:
        original = c.execute(text("SELECT id, identificador FROM codigos_recuperacion")).one()
        personal = c.scalar(text(
            "INSERT INTO codigos_recuperacion (usuario_id, identificador, codigo_hash) "
            "VALUES (:usuario, :prefijo, 'otro-hash') RETURNING id"
        ), {"usuario": usuario_id, "prefijo": original.identificador})
        usado_en = None
        if estado_codigo == "usado":
            usado_en = c.scalar(text(
                "UPDATE codigos_recuperacion SET usado_en=now() WHERE id=:id RETURNING usado_en"
            ), {"id": original.id})
        elif estado_codigo == "reemplazado":
            c.execute(text("DELETE FROM codigos_recuperacion WHERE id=:id"), {"id": original.id})
        c.execute(text(
            "UPDATE usuarios SET nombre_usuario='admin_renombrado', correo='titular@example.test', "
            "correo_verificado_en=now() WHERE id=:id"
        ), {"id": usuario_id})
        cuenta = text(
            "SELECT password_hash, token_version, correo, correo_verificado_en FROM usuarios WHERE id=:id"
        )
        antes = c.execute(cuenta, {"id": usuario_id}).one()

    shutil.copy2(next(ORIGEN.glob("V32__*.sql")), tmp_path)
    manifiesto(tmp_path)
    assert aplicar_migraciones_pendientes(motor_vacio, tmp_path) == 1
    assert aplicar_migraciones_pendientes(motor_vacio, tmp_path) == 0

    with motor_vacio.connect() as c:
        filas = dict(c.execute(text("SELECT id, usado_en FROM codigos_recuperacion")).all())
        esperadas = {personal: None}
        if estado_codigo == "usado":
            esperadas[original.id] = usado_en
        assert filas == esperadas
        assert c.execute(cuenta, {"id": usuario_id}).one() == antes
