"""Exportación cifrada, restauración real y eliminación del destino temporal en CI."""

import shutil
import subprocess
from decimal import Decimal

import pytest
from sqlalchemy import text

from scripts import backup_postgres as backup


@pytest.mark.skipif(
    any(
        shutil.which(binario) is None
        for binario in ["pg_dump", "pg_restore", "createdb", "dropdb", "psql", "age", "age-keygen"]
    ),
    reason="Faltan herramientas PostgreSQL/age; CI las instala explícitamente.",
)
def test_backup_cifrado_y_restore_recuperan_registros(engine_integracion, tmp_path):
    identidad = tmp_path / "clave.identity"
    subprocess.run(["age-keygen", "-o", str(identidad)], check=True, capture_output=True)
    publico = subprocess.check_output(["age-keygen", "-y", str(identidad)], text=True).strip()
    # El fixture ya garantiza que esta base desechable termina en _test.
    url = engine_integracion.url.render_as_string(hide_password=False)
    env = {
        **__import__("os").environ,
        "DATABASE_URL": url,
        "RESTORE_DATABASE_URL": url,
        "APP_ENV": "testing",
        "BACKUP_DIR": str(tmp_path),
        "BACKUP_AGE_RECIPIENT": publico,
        "BACKUP_AGE_IDENTITY": str(identidad),
    }
    env.pop("BACKUP_REMOTE", None)
    with engine_integracion.begin() as c:
        usuario_id = c.scalar(
            text(
                "INSERT INTO usuarios (nombre_completo, nombre_usuario, password_hash, rol_id) "
                "SELECT 'Prueba respaldo', 'backup_probe', 'ficticio', id FROM roles "
                "WHERE codigo='admin' RETURNING id"
            )
        )
        producto_id = c.scalar(
            text(
                "INSERT INTO productos (nombre_comercial, categoria_id) "
                "SELECT 'Producto respaldo', id FROM categorias_producto LIMIT 1 RETURNING id"
            )
        )
        orden_id = c.scalar(
            text(
                "INSERT INTO ordenes_produccion (numero_orden, fecha, supervisor_id, turno_id, "
                "horno_id, producto_id, categoria_id, cantidad_programada, horas_produccion) "
                "SELECT 'OP-RESPALDO', CURRENT_DATE, :usuario, "
                "(SELECT min(id) FROM turnos), (SELECT min(id) FROM hornos), :producto, "
                "(SELECT categoria_id FROM productos WHERE id=:producto), 123.45, 2 RETURNING id"
            ),
            {"usuario": usuario_id, "producto": producto_id},
        )
        usuarios = c.scalar(text("SELECT count(*) FROM usuarios"))
        ordenes = c.scalar(text("SELECT count(*) FROM ordenes_produccion"))
    try:
        archivo = backup.respaldo(env)
        assert archivo.suffix == ".age"
        assert archivo.stat().st_mode & 0o777 == 0o600
        assert not list(tmp_path.glob("*.dump"))
        resultado = backup.restaurar_prueba(archivo, env)
        assert resultado["conteos"]["usuarios"] == usuarios
        assert resultado["conteos"]["ordenes"] == ordenes
        assert resultado["conteos"]["cantidad_programada_kg"] == "123.45"
        with engine_integracion.connect() as c:
            assert (
                c.scalar(
                    text("SELECT count(*) FROM pg_database WHERE datname LIKE 'datacontrol_restore_test_%'")
                )
                == 0
            )
            assert c.scalar(
                text("SELECT cantidad_programada FROM ordenes_produccion WHERE id=:id"), {"id": orden_id}
            ) == Decimal("123.45")

    finally:
        with engine_integracion.begin() as c:
            c.execute(text("DELETE FROM ordenes_produccion WHERE id=:id"), {"id": orden_id})
            c.execute(text("DELETE FROM productos WHERE id=:id"), {"id": producto_id})
            c.execute(text("DELETE FROM usuarios WHERE id=:id"), {"id": usuario_id})
