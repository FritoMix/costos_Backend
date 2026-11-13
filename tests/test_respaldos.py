"""Seguridad de los respaldos sin acceso a ningún PostgreSQL real."""

import json

import pytest

from scripts import backup_postgres as backup


def preparar(tmp_path):
    archivo = tmp_path / "copia.dump.age"
    archivo.write_bytes(b"cifrado-de-prueba")
    archivo.with_suffix(".age.json").write_text(
        json.dumps(
            {
                "version": 1,
                "archivo": archivo.name,
                "sha256": backup.sha256(archivo),
            }
        )
    )
    return archivo, {
        "RESTORE_DATABASE_URL": "postgresql://test:clave-secreta@localhost/postgres",
        "BACKUP_AGE_IDENTITY": str(tmp_path / "identidad"),
    }


def test_no_admite_elegir_una_base_existente(tmp_path, monkeypatch):
    archivo, env = preparar(tmp_path)
    env["TEST_DB"] = "produccion"
    llamadas = []
    monkeypatch.setattr(backup, "ejecutar", lambda *a, **kw: llamadas.append(a))
    with pytest.raises(backup.ErrorOperacion, match="TEST_DB"):
        backup.restaurar_prueba(archivo, env)
    assert llamadas == []


def test_no_borra_si_createdb_falla_o_el_nombre_colisiona(tmp_path, monkeypatch):
    archivo, env = preparar(tmp_path)
    llamadas = []

    def ejecutar(args, *a, **kw):
        llamadas.append(args)
        raise backup.ErrorOperacion("No se creó la base")

    monkeypatch.setattr(backup, "ejecutar", ejecutar)
    with pytest.raises(backup.ErrorOperacion):
        backup.restaurar_prueba(archivo, env)
    assert [a[0] for a in llamadas] == ["createdb"]


def test_restaura_solo_en_base_generada_y_limpia_si_falla(tmp_path, monkeypatch):
    archivo, env = preparar(tmp_path)
    llamadas = []
    monkeypatch.setattr(backup, "ejecutar", lambda args, *a, **kw: llamadas.append(args))

    def fallar(*args, **kwargs):
        raise backup.ErrorOperacion("falló el descifrado")

    monkeypatch.setattr(backup, "tuberia", fallar)
    with pytest.raises(backup.ErrorOperacion):
        backup.restaurar_prueba(archivo, env)
    assert [a[0] for a in llamadas] == ["createdb", "dropdb"]
    assert llamadas[0][-1] == llamadas[1][-1]
    assert llamadas[0][-1].startswith("datacontrol_restore_test_")
    assert "clave-secreta" not in repr(llamadas)


def test_copia_alterada_se_rechaza_antes_de_crear_base(tmp_path, monkeypatch):
    archivo, env = preparar(tmp_path)
    archivo.write_bytes(b"alterado")
    llamadas = []
    monkeypatch.setattr(backup, "ejecutar", lambda *a, **kw: llamadas.append(a))
    with pytest.raises(backup.ErrorOperacion, match="integridad"):
        backup.restaurar_prueba(archivo, env)
    assert llamadas == []


def test_produccion_exige_cifrado_y_destino_externo(tmp_path):
    env = {"DATABASE_URL": "postgresql://test:secreto@localhost/planta", "BACKUP_DIR": str(tmp_path)}
    with pytest.raises(backup.ErrorOperacion, match="AGE_RECIPIENT"):
        backup.respaldo(env)
    env["BACKUP_AGE_RECIPIENT"] = "age1publica"
    with pytest.raises(backup.ErrorOperacion, match="BACKUP_REMOTE"):
        backup.respaldo(env)


def test_fallo_de_exportacion_no_publica_backup_ni_elimina_anteriores(tmp_path, monkeypatch):
    viejo = tmp_path / "copia-previa.dump.age"
    viejo.write_bytes(b"previo")
    env = {
        "DATABASE_URL": "postgresql://test:secreto@localhost/planta_test",
        "APP_ENV": "testing",
        "BACKUP_DIR": str(tmp_path),
        "BACKUP_AGE_RECIPIENT": "age1publica",
    }

    def fallar(*a, **kw):
        raise backup.ErrorOperacion("pg_dump falló")

    monkeypatch.setattr(backup, "tuberia", fallar)
    with pytest.raises(backup.ErrorOperacion):
        backup.respaldo(env)
    assert viejo.read_bytes() == b"previo"
    assert not list(tmp_path.glob("*.partial"))
    assert list(tmp_path.iterdir()) == [viejo]


def test_url_no_llega_a_los_argumentos_y_descodifica_credenciales():
    env = backup.configuracion(
        {"DATABASE_URL": "postgresql://usuario:p%40ss@servidor/planta?sslmode=require"}
    )
    assert env["PGPASSWORD"] == "p@ss"
    assert env["PGSSLMODE"] == "require"
    assert "DATABASE_URL" not in env
