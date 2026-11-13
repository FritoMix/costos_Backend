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
    assert aplicar_migraciones_pendientes(motor_vacio, tmp_path) == 2
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
