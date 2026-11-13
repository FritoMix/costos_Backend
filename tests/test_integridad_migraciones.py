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


@pytest.mark.parametrize("peso", ["-1", "0", "0.005", "10000"])
def test_peso_de_canastilla_respeta_escala_y_positividad(peso):
    from pydantic import ValidationError

    from app.modules.produccion.schemas import RecepcionGuardar

    with pytest.raises(ValidationError):
        RecepcionGuardar(
            hora_inicio="06:00", hora_fin="07:00", sabor_id=1, cantidad_sabor_kg="1", pesos_canastillas=[peso]
        )


@pytest.mark.parametrize(
    "accion,origenes,destino",
    [
        ("iniciar", {"pendiente"}, "en_produccion"),
        ("finalizar", {"en_produccion"}, "finalizada"),
        ("cancelar", {"pendiente", "en_produccion"}, "cancelada"),
    ],
)
@pytest.mark.parametrize("estado", ["pendiente", "en_produccion", "finalizada", "cancelada"])
def test_matriz_completa_de_transiciones(accion, origenes, destino, estado):
    from app.core.errores import ErrorDeValidacion
    from app.modules.produccion.dominio.estados import requiere_transicion

    if estado == destino:
        assert requiere_transicion(estado, accion) is False
    elif estado in origenes:
        assert requiere_transicion(estado, accion) is True
    else:
        with pytest.raises(ErrorDeValidacion):
            requiere_transicion(estado, accion)
