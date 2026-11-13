import hashlib
import json

import pytest

from app.db.migraciones import aplicar_migraciones_pendientes


class NoConectar:
    def begin(self):
        raise AssertionError("Un artefacto inválido no debe conectar a PostgreSQL")


def test_rechaza_versiones_duplicadas_antes_de_conectar(tmp_path):
    (tmp_path / "V1__uno.sql").write_text("SELECT 1")
    (tmp_path / "V01__otro.sql").write_text("SELECT 2")
    with pytest.raises(RuntimeError, match="duplicada"):
        aplicar_migraciones_pendientes(NoConectar(), tmp_path)


def test_rechaza_sql_alterado_aunque_la_version_sea_igual(tmp_path):
    ruta = tmp_path / "V1__uno.sql"
    ruta.write_text("SELECT 1")
    (tmp_path / "checksums.json").write_text(
        json.dumps({ruta.name: hashlib.sha256(ruta.read_bytes()).hexdigest()})
    )
    ruta.write_text("SELECT 2")
    with pytest.raises(RuntimeError, match="Integridad"):
        aplicar_migraciones_pendientes(NoConectar(), tmp_path)


def test_no_ignora_carpeta_ausente(tmp_path):
    with pytest.raises(RuntimeError, match="No existe"):
        aplicar_migraciones_pendientes(NoConectar(), tmp_path / "ausente")
