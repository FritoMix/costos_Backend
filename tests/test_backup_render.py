from pathlib import Path

import pytest

from scripts import backup_render as job


def test_archivo_secreto_obligatorio_antes_de_conectar(tmp_path, monkeypatch):
    llamadas = []
    monkeypatch.setattr(job, "respaldo", lambda env: llamadas.append(env))
    with pytest.raises(job.ErrorOperacion, match="archivo secreto"):
        job.ejecutar_job({"RCLONE_CONFIG_SOURCE": str(tmp_path / "ausente")})
    assert llamadas == []


@pytest.mark.parametrize("contenido", [b"", b" " , b"x" * (1024 * 1024 + 1)])
def test_secreto_vacio_o_excesivo_no_inicia_exportacion(contenido, tmp_path, monkeypatch):
    secreto = tmp_path / "rclone.conf"
    secreto.write_bytes(contenido)
    llamadas = []
    monkeypatch.setattr(job, "respaldo", lambda env: llamadas.append(env))
    with pytest.raises(job.ErrorOperacion):
        job.ejecutar_job({"RCLONE_CONFIG_SOURCE": str(secreto)})
    assert llamadas == []


@pytest.mark.parametrize("falla", [False, True])
def test_temporal_privado_se_limpia_incluso_si_falla_la_copia(falla, tmp_path, monkeypatch, capsys):
    secreto = tmp_path / "origen.conf"
    secreto.write_text("[gdrive]\ntoken=credencial-ficticia\n")
    creados = []

    def respaldar(env):
        config = Path(env["RCLONE_CONFIG"])
        creados.append(config.parent)
        assert config.read_text() == secreto.read_text()
        assert config.stat().st_mode & 0o777 == 0o600
        assert config.parent.stat().st_mode & 0o777 == 0o700
        assert env["BACKUP_DIR"] == str(config.parent / "copias")
        assert env["BACKUP_REMOTE"] == "gdrive:DataControl-respaldos"
        if falla:
            raise job.ErrorOperacion("fallo controlado")

    monkeypatch.setattr(job, "respaldo", respaldar)
    env = {"RCLONE_CONFIG_SOURCE": str(secreto), "BACKUP_REMOTE": "gdrive:DataControl-respaldos"}
    if falla:
        with pytest.raises(job.ErrorOperacion):
            job.ejecutar_job(env)
    else:
        job.ejecutar_job(env)
    assert all(not carpeta.exists() for carpeta in creados)
    assert secreto.exists()
    assert "RCLONE_CONFIG" not in env
    assert "credencial-ficticia" not in capsys.readouterr().out
